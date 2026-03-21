#!/usr/bin/env python3
"""Validate the 5 fixes to GRPO training data format.

Run from DyPoker/LLMPoker/:
    conda run -n Poker python training/validate_fixes.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from training.phh_parser import collect_phh_files, extract_winner_training_samples

# ── Load a small sample ───────────────────────────────────────────────
data_root = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..", "phh-dataset", "data",
)
if not os.path.isdir(data_root):
    data_root = "../phh-dataset/data"
print(f"Data root: {os.path.abspath(data_root)}")
phh_files = collect_phh_files(data_root, max_files=50)
samples = extract_winner_training_samples(phh_files, max_samples=500)
print(f"Total samples from 50 files: {len(samples)}")

if not samples:
    print("ERROR: No samples loaded.")
    sys.exit(1)

# ── Counters ──────────────────────────────────────────────────────────
total = len(samples)
raises = 0
raise_cumulative_suspect = 0  # raise_amount > player stack (likely cumulative)
postflop_prompts = 0
postflop_with_street_actions = 0
check_count = 0
call_count = 0
reasoning_set = set()
blinds_in_history = 0

for s in samples:
    prompt = s["prompt"]
    completion = s["completion"]

    # ── Fix 1: check raise amounts ──────────────────────────────
    try:
        comp_data = json.loads(completion)
    except json.JSONDecodeError:
        continue

    act = comp_data.get("action", "")
    amt = comp_data.get("raise_amount", 0)
    reasoning = comp_data.get("reasoning", "")

    if act == "raise" and amt:
        raises += 1
        # In the prompt, look for starting chips
        # Incremental raises should generally be << starting stack
        # Cumulative raises tend to be very large

    # ── Fix 2: check postflop action history ────────────────────
    if "On the flop" in prompt or "On the turn" in prompt or "On the river" in prompt:
        postflop_prompts += 1
    # Also count if prompt mentions community cards but has no street markers
    if "Community cards:" in prompt:
        has_community = True
        cards_line = ""
        for line in prompt.split("\n"):
            if "Community cards:" in line:
                cards_line = line
                break
        if cards_line and cards_line.strip() != "Community cards: (none yet)":
            # This is a postflop situation
            if "On the flop" in prompt or "On the turn" in prompt or "On the river" in prompt:
                postflop_with_street_actions += 1

    # ── Fix 3: check/call labels ────────────────────────────────
    if act == "check":
        check_count += 1
    elif act == "call":
        call_count += 1

    # ── Fix 4: reasoning variety ────────────────────────────────
    reasoning_set.add(reasoning)

    # ── Fix 5: blinds in action history ─────────────────────────
    if "posts blind" in prompt.lower() or "blind" in prompt.lower():
        # Old format would show blinds as RAISE in action history
        pass
    if "Action: blind" in prompt:
        blinds_in_history += 1

# ── Report ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("GRPO Training Data Format Validation Report")
print("=" * 60)

print(f"\n🔴 Fix 1: Raise Amount (cumulative → incremental)")
print(f"  Total raise samples: {raises}")
print(f"  (Manual inspection recommended for amount plausibility)")

print(f"\n🔴 Fix 2: Postflop Action History")
print(f"  Prompts mentioning flop/turn/river streets: {postflop_prompts}")
# Count postflop situations
postflop_situations = 0
for s in samples:
    prompt = s["prompt"]
    for line in prompt.split("\n"):
        if "Community cards:" in line and "(none yet)" not in line and line.strip() != "Community cards:":
            postflop_situations += 1
            break
print(f"  Total postflop situations: {postflop_situations}")
if postflop_situations > 0:
    pct = postflop_with_street_actions / postflop_situations * 100
    print(f"  Postflop with street action markers: {postflop_with_street_actions} ({pct:.1f}%)")
else:
    print(f"  No postflop situations found in sample")

print(f"\n🟡 Fix 3: Check/Call Labels")
print(f"  check: {check_count}, call: {call_count}")

print(f"\n🟡 Fix 4: Reasoning Variety")
print(f"  Unique reasoning strings: {len(reasoning_set)}")
if len(reasoning_set) <= 10:
    for r in sorted(reasoning_set):
        print(f"    - {r[:80]}")
else:
    for r in sorted(reasoning_set)[:5]:
        print(f"    - {r[:80]}")
    print(f"    ... and {len(reasoning_set) - 5} more")

print(f"\n🟡 Fix 5: Blinds in Action History")
print(f"  'Action: blind' in prompts: {blinds_in_history}")
print(f"  (Should be 0; blinds now use ActionType.BLIND filtered from history)")

# ── Show sample prompt/completion ─────────────────────────────────────
print("\n" + "=" * 60)
print("SAMPLE PROMPT + COMPLETION (first postflop if available):")
print("=" * 60)
for s in samples:
    prompt = s["prompt"]
    if "On the flop" in prompt or "On the turn" in prompt:
        print(prompt[:1500])
        print("---COMPLETION---")
        print(s["completion"])
        break
else:
    # fallback to first sample
    print(samples[0]["prompt"][:1500])
    print("---COMPLETION---")
    print(samples[0]["completion"])

print("\n✅ Validation complete.")
