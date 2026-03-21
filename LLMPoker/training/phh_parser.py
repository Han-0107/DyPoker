"""
phh_parser - PHH (Poker Hand History) 格式解析器

解析 phh-dataset 中的 .phh 文件（TOML 子集），提取扑克对局信息，
用于构建 GRPO 训练样本。
"""

from __future__ import annotations

import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from glob import glob
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_agent.prompt_builder import PromptBuilder
from utils.pokerbench_utils import build_action_json

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
#  Card notation helpers
# ─────────────────────────────────────────────────────────

_RANK_FULL = {
    "2": "Two", "3": "Three", "4": "Four", "5": "Five",
    "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine",
    "T": "Ten", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace",
}
_SUIT_FULL = {
    "c": "Club", "d": "Diamond", "h": "Heart", "s": "Spade",
}

_POSITION_NAMES_6MAX = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]
_POSITION_NAMES_HEADS_UP = ["SB", "BB"]


def _card_to_full_name(card_str: str) -> str:
    """e.g. 'Kd' -> 'King of Diamond'"""
    if len(card_str) < 2:
        return card_str
    rank = card_str[:-1]
    suit = card_str[-1].lower()
    return f"{_RANK_FULL.get(rank, rank)} of {_SUIT_FULL.get(suit, suit)}"


def _card_to_titled(card_str: str) -> str:
    """e.g. 'Kd' -> 'King Of Diamond'"""
    if len(card_str) < 2:
        return card_str
    rank = card_str[:-1]
    suit = card_str[-1].lower()
    return f"{_RANK_FULL.get(rank, rank)} Of {_SUIT_FULL.get(suit, suit)}"


# ─────────────────────────────────────────────────────────
#  PHH TOML Parsing
# ─────────────────────────────────────────────────────────

def _parse_phh_toml(filepath: str) -> Optional[Dict[str, Any]]:
    """Parse a .phh file (TOML subset) into a dict.

    We use a lightweight parser instead of requiring tomllib/toml for
    broader compatibility.
    """
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    # Try tomllib first (Python 3.11+), then tomli, then fallback
    try:
        import tomllib
        return tomllib.loads(text)
    except ImportError:
        pass
    try:
        import tomli
        return tomli.loads(text)
    except ImportError:
        pass

    # Minimal fallback parser for the fields we need
    result: Dict[str, Any] = {}
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if "#" in stripped and "'" not in stripped and '"' not in stripped:
            stripped = stripped[:stripped.index("#")].strip()
        if stripped:
            lines.append(stripped)

    full_text = "\n".join(lines)

    m = re.search(r'''variant\s*=\s*['"](.*?)['"]''', full_text)
    if m:
        result["variant"] = m.group(1)

    m = re.search(r'''players\s*=\s*\[(.*?)\]''', full_text, re.DOTALL)
    if m:
        result["players"] = re.findall(r'''['"]([^'"]+)['"]''', m.group(1))

    for key in ["antes", "blinds_or_straddles", "starting_stacks", "finishing_stacks"]:
        m = re.search(rf'''{key}\s*=\s*\[(.*?)\]''', full_text, re.DOTALL)
        if m:
            nums = re.findall(r'[\d.]+', m.group(1))
            result[key] = [float(x) if '.' in x else int(x) for x in nums]

    m = re.search(r'''min_bet\s*=\s*([\d.]+)''', full_text)
    if m:
        result["min_bet"] = int(float(m.group(1)))

    m = re.search(r'''actions\s*=\s*\[(.*?)\]''', full_text, re.DOTALL)
    if m:
        result["actions"] = re.findall(r'''['"]([^'"]+)['"]''', m.group(1))

    return result if "actions" in result else None


# ─────────────────────────────────────────────────────────
#  Data Structures
# ─────────────────────────────────────────────────────────

@dataclass
class ParsedHand:
    """Parsed poker hand from PHH format."""
    variant: str
    players: List[str]
    starting_stacks: List[float]
    finishing_stacks: List[float]
    blinds: List[float]
    antes: List[float]
    min_bet: int
    hole_cards: Dict[int, str]        # player_idx -> cards string
    community_cards: List[str]        # list of card strings
    actions: List[Dict[str, Any]]     # parsed player actions
    raw_actions: List[str]


# ─────────────────────────────────────────────────────────
#  Hand Parsing
# ─────────────────────────────────────────────────────────

def parse_phh_hand(filepath: str) -> Optional[ParsedHand]:
    """Parse a single .phh file into a structured hand object."""
    data = _parse_phh_toml(filepath)
    if data is None:
        return None

    variant = data.get("variant", "")
    if variant != "NT":  # Only No-Limit Texas Hold'em
        return None

    players = data.get("players", [])
    starting_stacks = data.get("starting_stacks", [])
    finishing_stacks = data.get("finishing_stacks", [])
    blinds = data.get("blinds_or_straddles", [])
    antes = data.get("antes", [0] * len(players))
    min_bet = data.get("min_bet", 0)
    raw_actions = data.get("actions", [])

    if not players or not starting_stacks or not raw_actions:
        return None
    if not finishing_stacks:
        return None
    if len(players) < 2 or len(players) > 10:
        return None

    # Parse actions
    hole_cards: Dict[int, str] = {}
    community_cards: List[str] = []
    parsed_actions: List[Dict[str, Any]] = []

    for action_str in raw_actions:
        parts = action_str.strip().split()
        if len(parts) < 2:
            continue

        actor = parts[0]
        action_type = parts[1]

        if actor == "d":
            if action_type == "dh" and len(parts) >= 3:
                player_id = parts[2]
                cards = parts[3] if len(parts) > 3 else "????"
                m = re.match(r'p(\d+)', player_id)
                if m:
                    p_idx = int(m.group(1)) - 1
                    if "?" not in cards:
                        hole_cards[p_idx] = cards
            elif action_type == "db" and len(parts) >= 3:
                board_str = parts[2]
                for i in range(0, len(board_str), 2):
                    if i + 2 <= len(board_str):
                        community_cards.append(board_str[i:i + 2])
                parsed_actions.append({
                    "_street_reset": True, "player_idx": -1,
                    "action": "_board", "amount": 0,
                })
        else:
            m = re.match(r'p(\d+)', actor)
            if not m:
                continue
            p_idx = int(m.group(1)) - 1

            if action_type == "f":
                parsed_actions.append({
                    "player_idx": p_idx, "action": "fold", "amount": 0,
                })
            elif action_type == "cc":
                # 确定当前street上的最大下注
                max_bet_current_street = 0.0
                street_has_board = False

                # 扫描所有之前的action, 找到最后一次street reset
                last_reset = -1
                for ai, prev_a in enumerate(parsed_actions):
                    if prev_a.get("_street_reset"):
                        last_reset = ai
                        street_has_board = True

                if not street_has_board:
                    # Preflop: 盲注是初始的max bet
                    for bi, blind_val in enumerate(blinds):
                        if blind_val > max_bet_current_street:
                            max_bet_current_street = blind_val

                # 在当前street内, 找最大的raise(cbr)
                for prev_a in parsed_actions[last_reset + 1:]:
                    if prev_a.get("_street_reset"):
                        continue
                    if prev_a["action"] == "raise" and prev_a["amount"] > max_bet_current_street:
                        max_bet_current_street = prev_a["amount"]

                # 判断是 check 还是 call
                if street_has_board:
                    # Postflop: 如果没有任何raise, 就是check
                    is_check = (max_bet_current_street == 0)
                else:
                    # Preflop: BB check (自己的blind >= max bet), 否则是 call
                    player_blind = blinds[p_idx] if p_idx < len(blinds) else 0
                    is_check = (player_blind >= max_bet_current_street)

                parsed_actions.append({
                    "player_idx": p_idx,
                    "action": "check" if is_check else "call",
                    "amount": 0,
                })
            elif action_type == "cbr":
                amount = float(parts[2]) if len(parts) > 2 else 0
                parsed_actions.append({
                    "player_idx": p_idx, "action": "raise", "amount": amount,
                })
            elif action_type == "sm":
                pass

    parsed_actions = [a for a in parsed_actions if not a.get("_street_reset")]

    return ParsedHand(
        variant=variant,
        players=players,
        starting_stacks=starting_stacks,
        finishing_stacks=finishing_stacks,
        blinds=blinds,
        antes=antes,
        min_bet=min_bet,
        hole_cards=hole_cards,
        community_cards=community_cards,
        actions=parsed_actions,
        raw_actions=raw_actions,
    )


# ─────────────────────────────────────────────────────────
#  Position & Winner Helpers
# ─────────────────────────────────────────────────────────

def get_position_name(player_idx: int, num_players: int, dealer_idx: int) -> str:
    """Get position name for a player given the table configuration."""
    if num_players == 2:
        positions = ["SB", "BB"]
        return positions[player_idx % 2]

    if num_players <= 6:
        pos_names = _POSITION_NAMES_6MAX[-num_players:]
        mapping = {}
        mapping[0] = "SB"
        mapping[1] = "BB"
        remaining = [p for p in pos_names if p not in ("SB", "BB", "BTN")]
        mapping[num_players - 1] = "BTN"
        for i, pos in enumerate(remaining):
            mapping[2 + i] = pos
        return mapping.get(player_idx, f"Seat{player_idx + 1}")

    return f"Seat{player_idx + 1}"


def identify_winners(hand: ParsedHand) -> List[int]:
    """Identify winners = players whose finishing_stacks > starting_stacks."""
    winners = []
    for i in range(len(hand.players)):
        if i < len(hand.finishing_stacks) and i < len(hand.starting_stacks):
            if hand.finishing_stacks[i] > hand.starting_stacks[i]:
                winners.append(i)
    return winners


# ─────────────────────────────────────────────────────────
#  Game State Reconstruction
# ─────────────────────────────────────────────────────────

def build_game_state_at_action(
    hand: ParsedHand,
    action_idx: int,
    player_idx: int,
) -> Optional[Dict[str, Any]]:
    """Reconstruct the game state as seen by a player right before their action."""
    num_players = len(hand.players)
    actions_before = hand.actions[:action_idx]

    # ── 从 raw_actions 中提取公共牌和街道边界 ──
    board_cards_seen: List[str] = []
    # 记录每个 parsed action 之前是否有 street reset (db)
    # street_reset_before_action[i] = True 如果在第i个action之前有新的board
    street_reset_before_action: Dict[int, bool] = {}
    parsed_action_count = 0
    pending_reset = False

    for raw_act in hand.raw_actions:
        parts = raw_act.strip().split()
        if len(parts) < 2:
            continue
        actor, act_type = parts[0], parts[1]

        if actor == "d" and act_type == "db" and len(parts) >= 3:
            board_str = parts[2]
            for i in range(0, len(board_str), 2):
                if i + 2 <= len(board_str):
                    board_cards_seen.append(board_str[i:i + 2])
            pending_reset = True
        elif actor != "d" and act_type in ("f", "cc", "cbr"):
            if pending_reset:
                street_reset_before_action[parsed_action_count] = True
                pending_reset = False
            parsed_action_count += 1
            if parsed_action_count > action_idx:
                break

    n_board = len(board_cards_seen)
    if n_board == 0:
        phase = "PREFLOP"
    elif n_board <= 3:
        phase = "FLOP"
    elif n_board == 4:
        phase = "TURN"
    elif n_board >= 5:
        phase = "RIVER"
    else:
        phase = "PREFLOP"

    if player_idx not in hand.hole_cards:
        return None

    cards_str = hand.hole_cards[player_idx]
    hole_cards = [cards_str[i:i + 2] for i in range(0, len(cards_str), 2)]

    pot = sum(hand.antes)
    player_bets = {i: 0.0 for i in range(num_players)}
    folded = set()
    current_max_bet = 0.0

    for i, blind in enumerate(hand.blinds):
        if blind > 0:
            player_bets[i] += blind
            pot += blind
            if blind > current_max_bet:
                current_max_bet = blind

    phase_actions_desc = []
    for ai, a in enumerate(actions_before):
        pidx = a["player_idx"]
        act = a["action"]
        amt = a["amount"]

        # 如果在这个action之前有新的street, 插入 phase 标记并重置 bets
        if street_reset_before_action.get(ai, False):
            phase_actions_desc.append({
                "player": "_dealer", "action": "phase", "amount": 0,
            })
            # 新street: 重置每个玩家的当前下注
            for k in player_bets:
                player_bets[k] = 0.0
            current_max_bet = 0.0

        if act == "fold":
            folded.add(pidx)
            phase_actions_desc.append({
                "player": hand.players[pidx], "action": "fold", "amount": 0,
            })
        elif act == "call":
            call_amt = current_max_bet - player_bets[pidx]
            player_bets[pidx] = current_max_bet
            pot += max(call_amt, 0)
            phase_actions_desc.append({
                "player": hand.players[pidx], "action": "call", "amount": call_amt,
            })
        elif act == "check":
            phase_actions_desc.append({
                "player": hand.players[pidx], "action": "check", "amount": 0,
            })
        elif act == "raise":
            if amt > 0:
                # PHH amount 是累计总额, 转换为增量 (额外投入的筹码)
                incremental = amt - player_bets[pidx]
                player_bets[pidx] = amt
                pot += max(incremental, 0)
                current_max_bet = max(current_max_bet, amt)
            else:
                incremental = 0
            phase_actions_desc.append({
                "player": hand.players[pidx], "action": "raise",
                "amount": max(incremental, 0),  # 增量金额
            })

    call_amount = max(current_max_bet - player_bets[player_idx], 0)
    your_chips = hand.starting_stacks[player_idx] - player_bets[player_idx]
    min_raise = hand.min_bet if hand.min_bet > 0 else (
        hand.blinds[1] if len(hand.blinds) > 1 else 100
    )

    valid_actions = ["fold"]
    if call_amount == 0:
        valid_actions.append("check")
    else:
        valid_actions.append("call")
    if your_chips > call_amount + min_raise:
        valid_actions.append("raise")
    if your_chips > 0:
        valid_actions.append("all_in")

    players_info = []
    for i in range(num_players):
        p_chips = hand.starting_stacks[i] - player_bets[i]
        players_info.append({
            "name": hand.players[i],
            "chips": p_chips,
            "is_active": i not in folded,
            "current_bet": player_bets[i],
        })

    sb = hand.blinds[0] if len(hand.blinds) > 0 else 0
    bb = hand.blinds[1] if len(hand.blinds) > 1 else 0

    return {
        "phase": phase,
        "pot": pot,
        "community_cards": board_cards_seen,
        "your_hand": hole_cards,
        "your_chips": your_chips,
        "call_amount": call_amount,
        "min_raise": min_raise,
        "current_bet": current_max_bet,
        "valid_actions": valid_actions,
        "players": players_info,
        "action_history": phase_actions_desc,
        "small_blind": sb,
        "big_blind": bb,
        "dealer": hand.players[-1],
    }


def action_to_label(action: Dict[str, Any]) -> str:
    """Convert a parsed action to a label string."""
    act = action["action"]
    amt = action["amount"]
    if act == "fold":
        return "fold"
    elif act == "call":
        return "call"
    elif act == "raise":
        if amt > 0:
            return f"raise {int(amt)}"
        return "raise"
    return "check"


def build_prompt_for_decision(
    hand: ParsedHand,
    action_idx: int,
    player_idx: int,
) -> Optional[str]:
    """Build a PokerBench-style natural language prompt for a decision point."""
    game_state = build_game_state_at_action(hand, action_idx, player_idx)
    if game_state is None:
        return None
    player_name = hand.players[player_idx]
    return PromptBuilder.build_decision_prompt(game_state, player_name)


# ─────────────────────────────────────────────────────────
#  Dataset Collection
# ─────────────────────────────────────────────────────────

def _generate_reasoning(
    act: str,
    amt: Optional[float],
    action: Dict[str, Any],
    hand: ParsedHand,
    action_idx: int,
    player_idx: int,
) -> str:
    """Generate a brief reasoning string based on the action context.

    Produces varied, contextual reasoning instead of a static placeholder.
    """
    pos = get_position_name(player_idx, len(hand.players), len(hand.players) - 1)

    # 计算已发的公共牌数量来判断街道
    board_count = 0
    pa_count = 0
    for raw in hand.raw_actions:
        parts = raw.strip().split()
        if len(parts) < 2:
            continue
        if parts[0] == "d" and parts[1] == "db":
            board_str = parts[2] if len(parts) > 2 else ""
            board_count += len(board_str) // 2
        elif parts[0] != "d" and parts[1] in ("f", "cc", "cbr"):
            pa_count += 1
            if pa_count > action_idx:
                break

    if board_count == 0:
        street = "preflop"
    elif board_count <= 3:
        street = "on the flop"
    elif board_count == 4:
        street = "on the turn"
    else:
        street = "on the river"

    if act == "fold":
        return f"Fold {street} from {pos}; hand not strong enough to continue."
    elif act == "check":
        return f"Check {street} from {pos}; pot control or trapping."
    elif act == "call":
        return f"Call {street} from {pos}; pot odds justify continuing."
    elif act == "raise":
        if amt and amt > 0:
            return f"Raise {street} from {pos}; value bet or semi-bluff, sizing {int(amt)} chips."
        return f"Raise {street} from {pos}; applying pressure."
    elif act == "all_in":
        return f"All-in {street} from {pos}; maximum pressure or value."
    return "Expert play."


def collect_phh_files(data_dir: str, max_files: int = 0) -> List[str]:
    """Recursively collect all .phh files from data_dir."""
    patterns = [os.path.join(data_dir, "**", "*.phh")]
    files = []
    for pattern in patterns:
        files.extend(glob(pattern, recursive=True))
    files = sorted(set(files))

    if max_files > 0 and len(files) > max_files:
        random.shuffle(files)
        files = files[:max_files]

    logger.info(f"Found {len(files)} .phh files under {data_dir}")
    return files


def extract_winner_training_samples(
    phh_files: List[str],
    max_samples: int = 50000,
) -> List[Dict[str, str]]:
    """Extract (prompt, completion) pairs from winner's actions in phh hands."""
    samples = []
    n_hands_processed = 0
    n_hands_skipped = 0

    for fp in phh_files:
        if max_samples > 0 and len(samples) >= max_samples:
            break

        hand = parse_phh_hand(fp)
        if hand is None:
            n_hands_skipped += 1
            continue

        winners = identify_winners(hand)
        if not winners:
            n_hands_skipped += 1
            continue

        n_hands_processed += 1

        for action_idx, action in enumerate(hand.actions):
            if action["player_idx"] not in winners:
                continue
            if action["action"] == "fold":
                if random.random() > 0.15:
                    continue

            player_idx = action["player_idx"]
            prompt = build_prompt_for_decision(hand, action_idx, player_idx)
            if prompt is None:
                continue

            act = action["action"]
            if act == "raise" and action["amount"] > 0:
                # PHH amount 是累计总额, 需要转为增量
                # 重建当时的 game_state 来获取玩家当时的已下注额
                gs = build_game_state_at_action(hand, action_idx, player_idx)
                if gs is not None:
                    # 从 game_state 中获取当时玩家需要的增量
                    # call_amount = current_max_bet - player_current_bet
                    # raise 的增量 = PHH_cumulative - player_current_bet
                    # 但 gs 已经帮我们算好了 call_amount 和 your_chips
                    # 更直接的方法: 从 players_info 获取 current_bet
                    player_current_bet = 0.0
                    for p_info in gs["players"]:
                        if p_info["name"] == hand.players[player_idx]:
                            player_current_bet = p_info["current_bet"]
                            break
                    incremental_amount = action["amount"] - player_current_bet
                    amt = max(incremental_amount, 0)
                else:
                    amt = action["amount"]
            else:
                amt = None

            # 生成有信息量的 reasoning
            reasoning = _generate_reasoning(act, amt, action, hand, action_idx, player_idx)
            completion = build_action_json(act, amt, reasoning=reasoning)

            samples.append({"prompt": prompt, "completion": completion})

            if max_samples > 0 and len(samples) >= max_samples:
                break

    logger.info(
        f"Extracted {len(samples)} training samples from {n_hands_processed} hands "
        f"({n_hands_skipped} skipped)"
    )
    return samples
