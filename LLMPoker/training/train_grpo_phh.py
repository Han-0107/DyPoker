#!/usr/bin/env python
"""GRPO (Group Relative Policy Optimization) training on phh-dataset.

This script fine-tunes an SFT-trained poker LLM using GRPO to learn
winning human expert strategies from the phh-dataset (Pluribus, WSOP,
HandHQ, etc.).

Example:
    python -m training.train_grpo_phh \
        --sft-model Qwen/Qwen2.5-7B-Instruct \
        --sft-adapter ./checkpoints/pokerbench-qwen2.5-7b-soft \
        --output-dir ./checkpoints/grpo-qwen2.5-7b-phh \
        --phh-data-dir ../phh-dataset/data \
        --epochs 2 \
        --bf16
"""

from __future__ import annotations

import argparse
import json
import os
import random
import logging
import sys

import numpy as np
import torch
from torch.utils.data import DataLoader

from peft import LoraConfig, PeftModel, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    get_cosine_schedule_with_warmup,
)

# 确保项目根目录在 sys.path 中
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from llm_agent.prompt_builder import PromptBuilder
from training.phh_parser import collect_phh_files, extract_winner_training_samples
from training.grpo_trainer import (
    PokerGRPODataset,
    collate_fn_grpo,
    generate_group_responses,
    compute_reward,
    grpo_step,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="GRPO training on phh-dataset")
    # Model
    parser.add_argument("--sft-model", required=True,
                        help="Base model name/path (e.g., Qwen/Qwen2.5-7B-Instruct)")
    parser.add_argument("--sft-adapter", default=None,
                        help="Path to SFT LoRA adapter (if separate from base model)")
    parser.add_argument("--output-dir", required=True,
                        help="Where to save GRPO checkpoints")
    # Data
    parser.add_argument("--phh-data-dir", required=True,
                        help="Path to phh-dataset/data directory")
    parser.add_argument("--max-phh-files", type=int, default=0,
                        help="Max number of .phh files to use (0=all)")
    parser.add_argument("--max-train-samples", type=int, default=30000,
                        help="Max training samples to extract from winner actions")
    parser.add_argument("--max-eval-samples", type=int, default=500,
                        help="Eval subset size")
    # GRPO hyperparams
    parser.add_argument("--group-size", type=int, default=4,
                        help="Number of responses per prompt for GRPO")
    parser.add_argument("--kl-coeff", type=float, default=0.1,
                        help="KL divergence penalty coefficient (β)")
    parser.add_argument("--temperature", type=float, default=0.7,
                        help="Sampling temperature for generation")
    parser.add_argument("--max-new-tokens", type=int, default=256,
                        help="Max new tokens per generation")
    # Training
    parser.add_argument("--epochs", type=int, default=2, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=2,
                        help="Per-device batch size (number of prompts)")
    parser.add_argument("--grad-accum-steps", type=int, default=8,
                        help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=5e-6,
                        help="Learning rate (conservative for GRPO)")
    parser.add_argument("--max-grad-norm", type=float, default=0.5,
                        help="Max gradient norm for clipping")
    parser.add_argument("--warmup-ratio", type=float, default=0.1,
                        help="Warmup ratio of total steps")
    parser.add_argument("--max-seq-len", type=int, default=1024,
                        help="Max sequence length")
    # LoRA
    parser.add_argument("--lora-r", type=int, default=8, help="LoRA rank")
    parser.add_argument("--lora-alpha", type=float, default=16.0, help="LoRA alpha")
    parser.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout")
    # Misc
    parser.add_argument("--use-4bit", action="store_true", help="Enable QLoRA 4-bit")
    parser.add_argument("--bf16", action="store_true", help="Use bf16")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--logging-steps", type=int, default=10, help="Log every N steps")
    parser.add_argument("--save-steps", type=int, default=200, help="Save every N steps")
    parser.add_argument("--merge-lora", action="store_true",
                        help="Merge LoRA into base weights after training")
    parser.add_argument("--fast", action="store_true",
                        help="Fast training mode: group_size=2, 1 epoch, "
                             "max 8000 samples, grad_accum=4, save every 100 steps")
    parser.add_argument("--resume-from", type=int, default=0,
                        help="Resume training from this global step (skip that many steps)")
    return parser.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # ── Fast mode overrides ──
    if args.fast:
        args.group_size = min(args.group_size, 2)
        args.epochs = 1
        args.max_train_samples = min(args.max_train_samples, 8000)
        args.grad_accum_steps = min(args.grad_accum_steps, 4)
        args.save_steps = min(args.save_steps, 100)
        args.max_new_tokens = min(args.max_new_tokens, 128)
        logger.info("⚡ Fast mode enabled: group_size=%d, epochs=%d, "
                     "max_samples=%d, grad_accum=%d, max_new_tokens=%d",
                     args.group_size, args.epochs, args.max_train_samples,
                     args.grad_accum_steps, args.max_new_tokens)

    # Set seeds
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    logger.info("=" * 60)
    logger.info("GRPO Training on phh-dataset (Winner Expert Strategy)")
    logger.info("=" * 60)
    logger.info(f"Base model:     {args.sft_model}")
    logger.info(f"SFT adapter:    {args.sft_adapter}")
    logger.info(f"Output:         {args.output_dir}")
    logger.info(f"Data dir:       {args.phh_data_dir}")
    logger.info(f"Group size:     {args.group_size}")
    logger.info(f"KL coeff (β):   {args.kl_coeff}")
    logger.info(f"Learning rate:  {args.lr}")
    logger.info(f"LoRA r/α:       {args.lora_r}/{args.lora_alpha}")
    logger.info(f"Grad clip:      {args.max_grad_norm}")
    logger.info("=" * 60)

    # ── 1. Collect and parse PHH data ──
    logger.info("Collecting PHH files...")
    phh_files = collect_phh_files(args.phh_data_dir, max_files=args.max_phh_files)

    logger.info("Extracting winner training samples...")
    all_samples = extract_winner_training_samples(phh_files, max_samples=args.max_train_samples)

    if len(all_samples) < 10:
        logger.error("Too few training samples extracted! Check your data directory.")
        sys.exit(1)

    random.shuffle(all_samples)
    n_eval = min(args.max_eval_samples, max(int(len(all_samples) * 0.02), 20))
    eval_samples = all_samples[:n_eval]
    train_samples = all_samples[n_eval:]
    logger.info(f"Train: {len(train_samples)} samples | Eval: {len(eval_samples)} samples")

    with open(os.path.join(args.output_dir, "data_stats.json"), "w") as f:
        json.dump({
            "total_phh_files": len(phh_files),
            "total_samples": len(all_samples),
            "train_samples": len(train_samples),
            "eval_samples": len(eval_samples),
        }, f, indent=2)

    # ── 2. Load tokenizer ──
    logger.info("Loading tokenizer...")
    tokenizer = AutoTokenizer.from_pretrained(args.sft_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── 3. Load model ──
    logger.info("Loading model...")
    bnb_config = None
    if args.use_4bit:
        try:
            import bitsandbytes  # noqa: F401
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True, bnb_4bit_use_double_quant=True, bnb_4bit_quant_type="nf4",
            )
        except ImportError:
            logger.warning("bitsandbytes not available, falling back to full precision")

    model_dtype = torch.bfloat16 if args.bf16 else torch.float32
    model = AutoModelForCausalLM.from_pretrained(
        args.sft_model, trust_remote_code=True, device_map="auto",
        quantization_config=bnb_config, torch_dtype=model_dtype,
    )

    if args.sft_adapter and os.path.isdir(args.sft_adapter):
        logger.info(f"Loading SFT LoRA adapter from {args.sft_adapter}")
        model = PeftModel.from_pretrained(model, args.sft_adapter)
        model = model.merge_and_unload()
        logger.info("SFT adapter merged into base model.")

    # ── 4. Create GRPO LoRA ──
    grpo_lora_config = LoraConfig(
        r=args.lora_r, lora_alpha=args.lora_alpha, lora_dropout=args.lora_dropout,
        bias="none", task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
    )
    model = get_peft_model(model, grpo_lora_config)
    model.print_trainable_parameters()

    # ── 5. Frozen reference model ──
    logger.info("Loading reference model (frozen)...")
    ref_model = AutoModelForCausalLM.from_pretrained(
        args.sft_model, trust_remote_code=True, device_map="auto",
        quantization_config=bnb_config, torch_dtype=model_dtype,
    )
    if args.sft_adapter and os.path.isdir(args.sft_adapter):
        ref_model = PeftModel.from_pretrained(ref_model, args.sft_adapter)
        ref_model = ref_model.merge_and_unload()
    ref_model.eval()
    for param in ref_model.parameters():
        param.requires_grad = False

    # ── 6. Optimizer & Scheduler ──
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr, weight_decay=0.01, betas=(0.9, 0.95),
    )

    total_steps = (len(train_samples) // args.batch_size // args.grad_accum_steps) * args.epochs
    warmup_steps = int(total_steps * args.warmup_ratio)
    scheduler = get_cosine_schedule_with_warmup(
        optimizer, num_warmup_steps=warmup_steps, num_training_steps=total_steps,
    )
    logger.info(f"Total steps: {total_steps} | Warmup: {warmup_steps}")

    # ── 7. Data loader ──
    train_dataset = PokerGRPODataset(train_samples, tokenizer, max_len=args.max_seq_len)
    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True,
        collate_fn=collate_fn_grpo, drop_last=True,
    )

    # ── 8. Training loop ──
    logger.info("Starting GRPO training...")
    model.train()
    global_step = 0
    best_reward = -float("inf")
    train_log = []
    skip_steps = args.resume_from  # skip this many optimizer steps if resuming

    for epoch in range(args.epochs):
        logger.info(f"\n{'=' * 40} Epoch {epoch + 1}/{args.epochs} {'=' * 40}")
        epoch_losses = []
        epoch_rewards = []
        optimizer.zero_grad()

        for batch_idx, batch in enumerate(train_loader):
            prompts = batch["prompts"]
            completions = batch["completions"]

            # Skip batches if resuming
            if skip_steps > 0 and (batch_idx + 1) % args.grad_accum_steps == 0:
                skip_steps -= 1
                global_step += 1
                scheduler.step()
                if global_step % 50 == 0:
                    logger.info(f"  Skipping step {global_step} (resuming)...")
                continue

            loss, metrics = grpo_step(
                model=model, ref_model=ref_model, tokenizer=tokenizer,
                prompts=prompts, completions=completions,
                group_size=args.group_size, kl_coeff=args.kl_coeff,
                max_new_tokens=args.max_new_tokens, temperature=args.temperature,
            )

            scaled_loss = loss / args.grad_accum_steps
            scaled_loss.backward()
            epoch_losses.append(metrics["loss"])
            epoch_rewards.append(metrics["mean_reward"])

            if (batch_idx + 1) % args.grad_accum_steps == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for p in model.parameters() if p.requires_grad],
                    args.max_grad_norm,
                )
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()
                global_step += 1

                if global_step % args.logging_steps == 0:
                    avg_loss = np.mean(epoch_losses[-args.grad_accum_steps * args.logging_steps:])
                    avg_reward = np.mean(epoch_rewards[-args.grad_accum_steps * args.logging_steps:])
                    current_lr = scheduler.get_last_lr()[0]
                    log_entry = {
                        "step": global_step, "epoch": epoch + 1,
                        "loss": float(avg_loss), "mean_reward": float(avg_reward),
                        "mean_kl": metrics["mean_kl"], "lr": current_lr,
                    }
                    train_log.append(log_entry)
                    logger.info(
                        f"Step {global_step:>5d} | Loss: {avg_loss:.4f} | "
                        f"Reward: {avg_reward:.3f} | KL: {metrics['mean_kl']:.4f} | "
                        f"LR: {current_lr:.2e}"
                    )

                if global_step % args.save_steps == 0:
                    ckpt_dir = os.path.join(args.output_dir, f"checkpoint-{global_step}")
                    model.save_pretrained(ckpt_dir)
                    tokenizer.save_pretrained(ckpt_dir)
                    logger.info(f"Saved checkpoint: {ckpt_dir}")

        # End of epoch eval
        logger.info(f"\nEpoch {epoch + 1} complete. Running evaluation...")
        eval_rewards = []
        model.eval()
        for sample in eval_samples[:100]:
            prompt = sample["prompt"]
            expert_completion = sample["completion"]
            try:
                expert_data = json.loads(expert_completion)
                expert_action = expert_data.get("action", "check")
                expert_amount = expert_data.get("raise_amount", None)
            except json.JSONDecodeError:
                continue

            responses = generate_group_responses(
                model, tokenizer, [prompt],
                group_size=1, max_new_tokens=args.max_new_tokens, temperature=0.1,
            )
            if responses and responses[0]:
                r = compute_reward(responses[0][0], expert_action, expert_amount)
                eval_rewards.append(r)

        model.train()
        mean_eval_reward = np.mean(eval_rewards) if eval_rewards else 0.0
        logger.info(f"Eval mean reward: {mean_eval_reward:.4f} ({len(eval_rewards)} samples)")

        if mean_eval_reward > best_reward:
            best_reward = mean_eval_reward
            best_dir = os.path.join(args.output_dir, "best")
            model.save_pretrained(best_dir)
            tokenizer.save_pretrained(best_dir)
            logger.info(f"New best model saved! Reward: {best_reward:.4f}")

    # ── 9. Final save ──
    logger.info("\nTraining complete. Saving final model...")
    model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)

    with open(os.path.join(args.output_dir, "training_log.json"), "w") as f:
        json.dump(train_log, f, indent=2)

    with open(os.path.join(args.output_dir, "system_prompt.txt"), "w") as f:
        f.write(PromptBuilder.SYSTEM_PROMPT)

    config_info = {
        "sft_model": args.sft_model, "sft_adapter": args.sft_adapter,
        "group_size": args.group_size, "kl_coeff": args.kl_coeff,
        "lr": args.lr, "lora_r": args.lora_r, "lora_alpha": args.lora_alpha,
        "max_grad_norm": args.max_grad_norm, "epochs": args.epochs,
        "total_steps": global_step, "best_eval_reward": best_reward,
    }
    with open(os.path.join(args.output_dir, "grpo_config.json"), "w") as f:
        json.dump(config_info, f, indent=2)

    if args.merge_lora:
        try:
            merged = model.merge_and_unload()
            merged_dir = os.path.join(args.output_dir, "merged")
            os.makedirs(merged_dir, exist_ok=True)
            merged.save_pretrained(merged_dir)
            tokenizer.save_pretrained(merged_dir)
            logger.info(f"Merged LoRA weights saved to {merged_dir}")
        except Exception as exc:
            logger.warning(f"merge_and_unload failed: {exc}")

    if train_samples:
        sample = train_samples[0]
        messages = [
            {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
            {"role": "user", "content": sample["prompt"]},
            {"role": "assistant", "content": sample["completion"]},
        ]
        sample_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False,
        )
        with open(os.path.join(args.output_dir, "sample_prompt.txt"), "w") as f:
            f.write(sample_text)

    logger.info(f"All done! Best eval reward: {best_reward:.4f}")
    logger.info(f"Model saved to: {args.output_dir}")


if __name__ == "__main__":
    main()
