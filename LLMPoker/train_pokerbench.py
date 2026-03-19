#!/usr/bin/env python
"""Supervised fine-tuning on PokerBench.

This script trains (or LoRA-fine-tunes) a chat model so it can make poker
decisions consistent with the PokerBench optimal actions.

Example:
    python train_pokerbench.py \
        --model Qwen/Qwen2.5-7B-Instruct \
        --output-dir ./checkpoints/pokerbench-qwen2.5-7b \
        --max-train-samples 20000 \
        --epochs 1 \
        --batch-size 2 \
        --grad-accum-steps 8
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Optional

from datasets import load_dataset
from peft import LoraConfig
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    BitsAndBytesConfig,
    TrainingArguments,
)
from trl import SFTTrainer

from llm_agent.prompt_builder import PromptBuilder
from pokerbench_utils import build_action_json, parse_pokerbench_label


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tune a chat model on PokerBench")
    parser.add_argument("--model", required=True, help="Base chat model name or path")
    parser.add_argument("--output-dir", required=True, help="Where to save checkpoints")
    parser.add_argument("--split", default="train", help="Dataset split to use (default train)")
    parser.add_argument("--max-train-samples", type=int, default=20000,
                        help="Limit training samples for quick runs (None = all)")
    parser.add_argument("--max-eval-samples", type=int, default=1000,
                        help="Eval subset size")
    parser.add_argument("--max-seq-len", type=int, default=1024,
                        help="Max sequence length after chat templating")
    parser.add_argument("--epochs", type=float, default=1.0, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=1, help="Per-device batch size")
    parser.add_argument("--grad-accum-steps", type=int, default=8, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--save-steps", type=int, default=500, help="Save checkpoint every N steps")
    parser.add_argument("--logging-steps", type=int, default=20, help="Logging steps")
    parser.add_argument("--lora-r", type=int, default=16, help="LoRA rank")
    parser.add_argument("--lora-alpha", type=float, default=32.0, help="LoRA alpha")
    parser.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout")
    parser.add_argument("--use-4bit", action="store_true", help="Enable QLoRA 4-bit loading")
    parser.add_argument("--merge-lora", action="store_true", help="Merge LoRA into base weights after training")
    parser.add_argument("--bf16", action="store_true", help="Force bf16 training (if supported)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    return parser.parse_args()


def build_chat_sample(tokenizer, instruction: str, label: str) -> str:
    action, amount = parse_pokerbench_label(label)
    assistant_json = build_action_json(action, amount)
    messages = [
        {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
        {"role": "assistant", "content": assistant_json},
    ]
    return tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=False,
    )


def main():
    args = parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # 1) Load dataset
    raw_ds = load_dataset("RZ412/PokerBench", split=args.split)
    # 记录一个示例，用于训练结束后生成 sanity prompt（避免列被 map 删除）
    sample_example = raw_ds[0]
    if args.max_train_samples:
        raw_ds = raw_ds.shuffle(seed=args.seed).select(range(args.max_train_samples))

    # train/val split
    dataset = raw_ds.train_test_split(test_size=min(0.02, max(50 / len(raw_ds), 0.01)), seed=args.seed)
    train_ds = dataset["train"]
    eval_ds = dataset["test"]
    if args.max_eval_samples:
        eval_ds = eval_ds.select(range(min(args.max_eval_samples, len(eval_ds))))

    # 2) Tokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # 3) Model (optionally 4-bit)
    bnb_config = None
    if args.use_4bit:
        try:
            import bitsandbytes  # type: ignore  # noqa: F401

            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_use_double_quant=True,
                bnb_4bit_quant_type="nf4",
            )
        except Exception as exc:  # pragma: no cover
            print(
                "[warn] bitsandbytes not available; falling back to full precision. "
                "Install bitsandbytes>=0.43.0 to enable --use-4bit."
            )
            bnb_config = None
            args.use_4bit = False

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        trust_remote_code=True,
        device_map="auto",
        quantization_config=bnb_config,
    )

    # 4) LoRA config
    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    )

    # 5) Pre-tokenize to text field (avoid TRL older formatting_func quirks)
    def to_text_batch(examples):
        texts = [build_chat_sample(tokenizer, ins, out) for ins, out in zip(examples["instruction"], examples["output"])]
        return {"text": texts}

    train_ds = train_ds.map(to_text_batch, batched=True, remove_columns=train_ds.column_names)
    eval_ds = eval_ds.map(to_text_batch, batched=True, remove_columns=eval_ds.column_names)

    # 6) Training args
    training_args_kwargs = dict(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum_steps,
        learning_rate=args.lr,
        logging_steps=args.logging_steps,
        save_steps=args.save_steps,
        evaluation_strategy="steps",
        eval_steps=args.save_steps,
        bf16=args.bf16,
        lr_scheduler_type="cosine",
        warmup_ratio=0.03,
        save_total_limit=2,
        report_to=["none"],
        seed=args.seed,
    )

    try:
        training_args = TrainingArguments(**training_args_kwargs)
    except TypeError:
        # 兼容旧版 transformers，去掉 evaluation 相关参数
        training_args_kwargs.pop("evaluation_strategy", None)
        training_args_kwargs.pop("eval_steps", None)
        training_args = TrainingArguments(**training_args_kwargs)

    trainer_tokenizer = tokenizer
    try:
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=eval_ds,
            tokenizer=tokenizer,
            peft_config=lora_config,
            dataset_text_field="text",
            max_seq_length=args.max_seq_len,
            packing=True,
        )
    except TypeError:
        # 兼容更旧版 TRL：去掉 tokenizer / max_seq_length / packing
        try:
            trainer = SFTTrainer(
                model=model,
                args=training_args,
                train_dataset=train_ds,
                eval_dataset=eval_ds,
                peft_config=lora_config,
                dataset_text_field="text",
            )
        except TypeError:
            # 最后退：仅保留必要参数
            trainer = SFTTrainer(
                model=model,
                args=training_args,
                train_dataset=train_ds,
                peft_config=lora_config,
            )

    trainer.train()

    # 7) Save
    trainer.save_state()
    # Trainer.tokenizer 已弃用，优先使用 processing_class；保底用原 tokenizer
    tokenizer_to_save = getattr(trainer, "processing_class", None) or getattr(trainer, "tokenizer", None) or tokenizer
    try:
        tokenizer_to_save.save_pretrained(args.output_dir)
    except Exception:
        tokenizer.save_pretrained(args.output_dir)

    if args.merge_lora:
        try:
            merged = trainer.model.merge_and_unload()
            merged.save_pretrained(args.output_dir)
            print("Merged LoRA weights into base model.")
        except Exception as exc:  # pragma: no cover - best-effort
            print(f"[warn] merge_and_unload failed: {exc}. Saving adapter instead.")
            trainer.model.save_pretrained(args.output_dir)
    else:
        trainer.model.save_pretrained(args.output_dir)

    with open(os.path.join(args.output_dir, "system_prompt.txt"), "w", encoding="utf-8") as f:
        f.write(PromptBuilder.SYSTEM_PROMPT)

    # Dump a tiny example for sanity
    try:
        if all(k in sample_example for k in ["instruction", "output"]):
            sample = build_chat_sample(tokenizer, sample_example["instruction"], sample_example["output"])
            with open(os.path.join(args.output_dir, "sample_prompt.txt"), "w", encoding="utf-8") as f:
                f.write(sample)
    except Exception as exc:  # best-effort
        print(f"[warn] failed to write sample_prompt.txt: {exc}")

    print("Training complete. Saved to", args.output_dir)


if __name__ == "__main__":
    main()
