"""
grpo_trainer - GRPO (Group Relative Policy Optimization) 训练核心逻辑

包含奖励计算、响应生成、GRPO 步骤等训练循环所需的函数。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import torch
import torch.nn.functional as F
from torch.utils.data import Dataset

from llm_agent.prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
#  Reward Function
# ─────────────────────────────────────────────────────────

def compute_reward(
    generated_text: str,
    reference_action: str,
    reference_amount: Optional[float] = None,
) -> float:
    """Compute reward for a generated action vs the expert's action.

    Rewards:
      +1.0  exact match (same action, and close raise amount if applicable)
      +0.5  semantically similar (e.g., call vs check when no bet)
      +0.3  aggressive action matching direction (raise vs raise)
      -0.3  wrong action type but valid JSON
      -1.0  invalid response / can't parse
    """
    try:
        gen = json.loads(generated_text.strip())
        gen_action = gen.get("action", "").lower().strip()
        gen_amount = gen.get("raise_amount", None)
    except (json.JSONDecodeError, AttributeError):
        m = re.search(r'"action"\s*:\s*"(\w+)"', generated_text)
        if m:
            gen_action = m.group(1).lower()
            m2 = re.search(r'"raise_amount"\s*:\s*([\d.]+)', generated_text)
            gen_amount = float(m2.group(1)) if m2 else None
        else:
            return -1.0

    ref_action = reference_action.lower().strip()

    if gen_action == ref_action:
        if ref_action == "raise" and reference_amount is not None and gen_amount is not None:
            ratio = gen_amount / max(reference_amount, 1)
            if 0.7 <= ratio <= 1.3:
                return 1.0
            elif 0.5 <= ratio <= 2.0:
                return 0.7
            else:
                return 0.4
        return 1.0

    passive_actions = {"check", "call"}
    aggressive_actions = {"raise", "all_in"}

    if gen_action in passive_actions and ref_action in passive_actions:
        return 0.5
    if gen_action in aggressive_actions and ref_action in aggressive_actions:
        return 0.5

    if gen_action in ("fold", "check", "call", "raise", "all_in"):
        return -0.3

    return -1.0


# ─────────────────────────────────────────────────────────
#  Dataset
# ─────────────────────────────────────────────────────────

class PokerGRPODataset(Dataset):
    """Dataset that yields poker decision prompts for GRPO training."""

    def __init__(self, samples: List[Dict[str, str]], tokenizer, max_len: int = 1024):
        self.samples = samples
        self.tokenizer = tokenizer
        self.max_len = max_len

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, idx):
        sample = self.samples[idx]
        return {"prompt": sample["prompt"], "completion": sample["completion"]}


def collate_fn_grpo(batch):
    """Collate prompts and completions as raw strings."""
    return {
        "prompts": [b["prompt"] for b in batch],
        "completions": [b["completion"] for b in batch],
    }


# ─────────────────────────────────────────────────────────
#  Generation & Log-Prob Computation
# ─────────────────────────────────────────────────────────

@torch.no_grad()
def generate_group_responses(
    model,
    tokenizer,
    prompts: List[str],
    group_size: int = 4,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
    top_p: float = 0.95,
) -> List[List[str]]:
    """Generate `group_size` responses for each prompt.

    Uses batch generation: for each prompt, duplicate it `group_size` times
    and generate all responses in a single forward pass.

    Returns: list of lists, shape [batch_size, group_size]
    """
    all_responses = []

    for prompt in prompts:
        messages = [
            {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]
        chat_text = tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True,
        )

        # Batch: duplicate the same prompt group_size times for parallel generation
        batch_texts = [chat_text] * group_size
        inputs = tokenizer(
            batch_texts, return_tensors="pt", truncation=True,
            max_length=1024, padding=True,
        ).to(model.device)

        with torch.no_grad():
            outputs = model.generate(
                **inputs,
                max_new_tokens=max_new_tokens,
                temperature=temperature,
                top_p=top_p,
                do_sample=True,
                pad_token_id=tokenizer.pad_token_id,
            )

        prompt_len = inputs["input_ids"].shape[1]
        responses = []
        for i in range(group_size):
            gen_ids = outputs[i][prompt_len:]
            resp = tokenizer.decode(gen_ids, skip_special_tokens=True).strip()
            responses.append(resp)

        all_responses.append(responses)

    return all_responses


def compute_log_probs(
    model,
    tokenizer,
    prompt_text: str,
    response_text: str,
    max_length: int = 1280,
) -> torch.Tensor:
    """Compute log-probabilities of the response tokens given the prompt.

    Returns: scalar tensor of mean log-prob over response tokens.
    """
    messages = [
        {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
        {"role": "assistant", "content": response_text},
    ]
    full_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False,
    )

    encoding = tokenizer(
        full_text, return_tensors="pt", truncation=True, max_length=max_length,
    ).to(model.device)
    input_ids = encoding["input_ids"]

    prompt_messages = [
        {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    prompt_text_only = tokenizer.apply_chat_template(
        prompt_messages, tokenize=False, add_generation_prompt=True,
    )
    prompt_ids = tokenizer(
        prompt_text_only, return_tensors="pt", truncation=True, max_length=max_length,
    )["input_ids"]
    prompt_len = prompt_ids.shape[1]

    outputs = model(input_ids=input_ids, attention_mask=encoding.get("attention_mask"))
    logits = outputs.logits

    shift_logits = logits[:, prompt_len - 1:-1, :]
    shift_labels = input_ids[:, prompt_len:]

    if shift_labels.shape[1] == 0:
        return torch.tensor(0.0, device=model.device, requires_grad=True)

    log_probs = F.log_softmax(shift_logits, dim=-1)
    token_log_probs = log_probs.gather(2, shift_labels.unsqueeze(-1)).squeeze(-1)

    return token_log_probs.mean()


def compute_log_probs_batch(
    model,
    tokenizer,
    prompt_text: str,
    response_texts: List[str],
    max_length: int = 1280,
) -> List[torch.Tensor]:
    """Compute log-probabilities for multiple responses of the same prompt in one batch.

    This is much faster than calling compute_log_probs() in a loop because it
    batches all responses into a single forward pass through the model.

    Returns: list of scalar tensors (one per response).
    """
    if not response_texts:
        return []

    # Build prompt prefix (shared across all responses)
    prompt_messages = [
        {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    prompt_text_only = tokenizer.apply_chat_template(
        prompt_messages, tokenize=False, add_generation_prompt=True,
    )
    prompt_ids = tokenizer(
        prompt_text_only, return_tensors="pt", truncation=True, max_length=max_length,
    )["input_ids"]
    prompt_len = prompt_ids.shape[1]

    # Build full texts for all responses
    full_texts = []
    for resp in response_texts:
        messages = [
            {"role": "system", "content": PromptBuilder.SYSTEM_PROMPT},
            {"role": "user", "content": prompt_text},
            {"role": "assistant", "content": resp},
        ]
        full_texts.append(tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=False,
        ))

    # Tokenize as a batch with padding
    encoding = tokenizer(
        full_texts, return_tensors="pt", truncation=True,
        max_length=max_length, padding=True,
    ).to(model.device)

    input_ids = encoding["input_ids"]
    attention_mask = encoding["attention_mask"]

    outputs = model(input_ids=input_ids, attention_mask=attention_mask)
    logits = outputs.logits

    results = []
    for i in range(len(response_texts)):
        shift_logits_i = logits[i:i+1, prompt_len - 1:-1, :]
        shift_labels_i = input_ids[i:i+1, prompt_len:]

        # Mask out padding tokens
        mask_i = attention_mask[i:i+1, prompt_len:]

        if shift_labels_i.shape[1] == 0 or mask_i.sum() == 0:
            results.append(torch.tensor(0.0, device=model.device, requires_grad=True))
            continue

        log_probs_i = F.log_softmax(shift_logits_i, dim=-1)
        token_log_probs_i = log_probs_i.gather(2, shift_labels_i.unsqueeze(-1)).squeeze(-1)

        # Apply mask: only count non-padding tokens
        masked_log_probs = token_log_probs_i * mask_i
        mean_log_prob = masked_log_probs.sum() / mask_i.sum().clamp(min=1)
        results.append(mean_log_prob)

    return results

    shift_logits = logits[:, prompt_len - 1:-1, :]
    shift_labels = input_ids[:, prompt_len:]

    if shift_labels.shape[1] == 0:
        return torch.tensor(0.0, device=model.device, requires_grad=True)

    log_probs = F.log_softmax(shift_logits, dim=-1)
    token_log_probs = log_probs.gather(2, shift_labels.unsqueeze(-1)).squeeze(-1)

    return token_log_probs.mean()


# ─────────────────────────────────────────────────────────
#  GRPO Step
# ─────────────────────────────────────────────────────────

def grpo_step(
    model,
    ref_model,
    tokenizer,
    prompts: List[str],
    completions: List[str],
    group_size: int = 4,
    kl_coeff: float = 0.1,
    max_new_tokens: int = 256,
    temperature: float = 0.7,
) -> Tuple[torch.Tensor, Dict[str, float]]:
    """Perform one GRPO step.

    For each prompt:
      1. Generate `group_size` responses (batch)
      2. Compute rewards for each response (vs expert action)
      3. Compute group-relative advantages
      4. Update policy to maximize advantage-weighted log-probs with KL penalty

    Uses batched log-prob computation for efficiency.

    Returns: (loss, metrics_dict)
    """
    batch_size = len(prompts)

    model.eval()
    all_responses = generate_group_responses(
        model, tokenizer, prompts,
        group_size=group_size,
        max_new_tokens=max_new_tokens,
        temperature=temperature,
    )
    model.train()

    total_loss = torch.tensor(0.0, device=next(model.parameters()).device, requires_grad=True)
    total_reward = 0.0
    total_kl = 0.0
    n_valid = 0

    for b_idx in range(batch_size):
        prompt = prompts[b_idx]
        expert_completion = completions[b_idx]

        try:
            expert_data = json.loads(expert_completion)
            expert_action = expert_data.get("action", "check")
            expert_amount = expert_data.get("raise_amount", None)
        except json.JSONDecodeError:
            continue

        responses = all_responses[b_idx]
        rewards = [compute_reward(resp, expert_action, expert_amount) for resp in responses]
        rewards_tensor = torch.tensor(rewards, dtype=torch.float32)

        if rewards_tensor.std() > 1e-8:
            advantages = (rewards_tensor - rewards_tensor.mean()) / (rewards_tensor.std() + 1e-8)
        else:
            advantages = rewards_tensor - rewards_tensor.mean()

        # Filter to responses with non-zero advantage
        valid_indices = [i for i in range(group_size) if abs(advantages[i].item()) >= 1e-8]
        if not valid_indices:
            continue

        valid_responses = [responses[i] for i in valid_indices]
        valid_advantages = [advantages[i] for i in valid_indices]
        valid_rewards = [rewards[i] for i in valid_indices]

        # Batch compute log-probs for policy model
        policy_log_probs = compute_log_probs_batch(
            model, tokenizer, prompt, valid_responses,
        )

        # Batch compute log-probs for reference model (no grad)
        with torch.no_grad():
            ref_log_probs = compute_log_probs_batch(
                ref_model, tokenizer, prompt, valid_responses,
            )

        for i in range(len(valid_indices)):
            adv = valid_advantages[i].to(next(model.parameters()).device)
            log_prob = policy_log_probs[i]
            ref_log_prob = ref_log_probs[i]

            kl = log_prob - ref_log_prob
            sample_loss = -(adv * log_prob) + kl_coeff * kl

            total_loss = total_loss + sample_loss
            total_reward += valid_rewards[i]
            total_kl += kl.detach().item()
            n_valid += 1

    if n_valid > 0:
        total_loss = total_loss / n_valid

    metrics = {
        "loss": total_loss.detach().item(),
        "mean_reward": total_reward / max(n_valid, 1),
        "mean_kl": total_kl / max(n_valid, 1),
        "n_valid_samples": n_valid,
    }

    return total_loss, metrics
