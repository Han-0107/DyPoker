"""
PromptBuilder - 构建发送给LLM的提示词
将游戏状态转化为LLM可理解的自然语言描述
支持两种格式：
  - pokerbench: 与 PokerBench 训练数据一致的自然语言叙述风格
  - structured: 结构化键值对风格（作为后备）
"""

from __future__ import annotations
from typing import Dict, Any, List, Optional
import re


# ── 牌面符号 → 英文全称映射 ──
_RANK_FULL = {
    "2": "Two", "3": "Three", "4": "Four", "5": "Five",
    "6": "Six", "7": "Seven", "8": "Eight", "9": "Nine",
    "T": "Ten", "J": "Jack", "Q": "Queen", "K": "King", "A": "Ace",
}
_SUIT_FULL = {
    "♣": "Club", "♦": "Diamond", "♥": "Heart", "♠": "Spade",
    "c": "Club", "d": "Diamond", "h": "Heart", "s": "Spade",
    "C": "Club", "D": "Diamond", "H": "Heart", "S": "Spade",
}


def _card_to_full_name(card_str: str) -> str:
    """
    将简短牌面字符串转换为 PokerBench 风格全称。
    例: 'K♦' -> 'King of Diamond', 'A♠' -> 'Ace of Spade'
    """
    card_str = card_str.strip()
    if len(card_str) < 2:
        return card_str
    rank_char = card_str[:-1]
    suit_char = card_str[-1]
    rank_name = _RANK_FULL.get(rank_char, rank_char)
    suit_name = _SUIT_FULL.get(suit_char, suit_char)
    return f"{rank_name} of {suit_name}"


def _card_to_titled(card_str: str) -> str:
    """
    将简短牌面字符串转换为 PokerBench 社区牌风格。
    例: 'K♦' -> 'King Of Diamond'
    """
    card_str = card_str.strip()
    if len(card_str) < 2:
        return card_str
    rank_char = card_str[:-1]
    suit_char = card_str[-1]
    rank_name = _RANK_FULL.get(rank_char, rank_char)
    suit_name = _SUIT_FULL.get(suit_char, suit_char)
    return f"{rank_name} Of {suit_name}"


# ── 6-max 位置映射 ──
_POSITION_NAMES_6MAX = ["UTG", "HJ", "CO", "BTN", "SB", "BB"]


class PromptBuilder:
    """构建德州扑克决策所需的Prompt"""

    SYSTEM_PROMPT = """You are an expert 6-max No-Limit Texas Hold'em decision maker. Given the game state, output ONLY JSON with the action you would take.

Output JSON schema (no prose):
{
  "reasoning": "1-3 short bullet-style thoughts",
  "action": "fold" | "check" | "call" | "raise" | "all_in",
  "raise_amount": <number, required only for "raise", means "raise to" this total bet amount>,
  "confidence": 0-1  // optional, omit if unsure
}

Rules:
- Honor the provided valid_actions list; never invent other actions.
- For raises, raise_amount uses "raise to" semantics: it is the TOTAL bet level you want to reach (not the extra chips you put in). For example, if current_bet is 20 and you want to raise, raise_amount must be at least min_raise_to (e.g., 40). If raise_amount >= your current_bet + your_chips → use "all_in".
- After someone raises or goes all-in, you must call (not check) to stay in the hand.
- The minimum raise must be at least the size of the previous raise increment above the current bet. For example, if someone bets 30, a raise must be to at least 60 (30 + 30).
- If call_amount is 0, prefer check over raise with weak/medium hands; avoid folding preflop unless hand is very weak and pressured.
- Use pot odds, position, board texture, and action history to justify the move concisely.
- Keep responses deterministic and well-formatted JSON only (no markdown, no extra text)."""

    @staticmethod
    def _get_positions(players: List[Dict], dealer_name: Optional[str] = None) -> Dict[str, str]:
        """
        根据玩家列表和庄家确定每个玩家的位置名称。
        返回 {player_name: position_name}
        """
        n = len(players)
        positions = {}

        # 找到庄家索引
        dealer_idx = 0
        if dealer_name:
            for i, p in enumerate(players):
                if p["name"] == dealer_name:
                    dealer_idx = i
                    break

        if n <= 6:
            # 使用 6-max 位置名
            pos_names = _POSITION_NAMES_6MAX[-n:]  # 取最后 n 个位置
            for i in range(n):
                player_idx = (dealer_idx + 1 + i) % n
                # BTN 是 dealer 的下一个在 pos_names 的最后之前
                positions[players[player_idx]["name"]] = pos_names[i]
            # 修正：BTN 就是 dealer
            positions[players[dealer_idx]["name"]] = "BTN"
            # SB 是 dealer+1, BB 是 dealer+2
            sb_idx = (dealer_idx + 1) % n
            bb_idx = (dealer_idx + 2) % n
            positions[players[sb_idx]["name"]] = "SB"
            positions[players[bb_idx]["name"]] = "BB"
            # 其余按顺序分配 UTG, HJ, CO
            remaining_positions = []
            if n == 6:
                remaining_positions = ["UTG", "HJ", "CO"]
            elif n == 5:
                remaining_positions = ["UTG", "CO"]
            elif n == 4:
                remaining_positions = ["CO"]
            elif n == 3:
                remaining_positions = []
            elif n == 2:
                # heads-up: BTN=SB
                positions[players[dealer_idx]["name"]] = "SB"
                positions[players[(dealer_idx + 1) % n]["name"]] = "BB"
                return positions

            pos_i = 0
            for i in range(n):
                idx = (dealer_idx + 3 + i) % n  # 从BB之后开始
                name = players[idx]["name"]
                if name not in [players[dealer_idx]["name"],
                                players[sb_idx]["name"],
                                players[bb_idx]["name"]]:
                    if pos_i < len(remaining_positions):
                        positions[name] = remaining_positions[pos_i]
                        pos_i += 1
        else:
            # > 6 players，用数字位置
            for i in range(n):
                positions[players[i]["name"]] = f"Seat{i+1}"

        return positions

    @staticmethod
    def build_decision_prompt(game_state: Dict[str, Any], player_name: str) -> str:
        """
        根据游戏状态构建决策prompt。
        使用与 PokerBench 训练数据一致的自然语言叙述风格，
        确保微调模型能正确理解和响应。
        """
        parts = []
        players = game_state.get("players", [])
        phase = game_state.get("phase", "PREFLOP")
        pot = game_state.get("pot", 0)
        community_cards = game_state.get("community_cards", [])
        hand_cards = game_state.get("your_hand", [])
        call_amount = game_state.get("call_amount", 0)
        your_chips = game_state.get("your_chips", 0)
        min_raise = game_state.get("min_raise", 10)
        valid_actions = game_state.get("valid_actions", [])
        current_bet = game_state.get("current_bet", 0)
        action_history = game_state.get("action_history", [])
        dealer_name = game_state.get("dealer", None)

        # ── 获取位置映射 ──
        positions = PromptBuilder._get_positions(players, dealer_name)
        my_position = positions.get(player_name, "?")

        # ── PokerBench 风格的自然语言叙述 ──
        parts.append("You are a specialist in playing 6-handed No Limit Texas Holdem. "
                      "The following will be a game scenario and you need to make the optimal decision.")
        parts.append("")
        parts.append("Here is a game summary:")
        parts.append("")

        # 盲注和筹码信息
        sb = game_state.get("small_blind", 5)
        bb = game_state.get("big_blind", 10)
        # 从 action_history 推断盲注大小
        if not sb and action_history:
            for h in action_history[:2]:
                if h.get("amount"):
                    if sb == 0:
                        sb = h["amount"]
                    else:
                        bb = h["amount"]
                        break

        # 找到初始筹码（使用当前筹码近似）
        max_chips = max((p["chips"] for p in players), default=1000)
        # 大致估算初始筹码（四舍五入到常见值）
        initial_chips = max_chips

        parts.append(f"The small blind is {sb} chips and the big blind is {bb} chips. "
                      f"Everyone started with {initial_chips} chips.")

        # 位置列表
        active_positions = []
        for p in players:
            pos = positions.get(p["name"], "?")
            active_positions.append(pos)
        parts.append(f"The player positions involved in this game are {', '.join(active_positions)}.")

        # 你的位置和手牌
        if hand_cards:
            hand_str = " and ".join(_card_to_full_name(c) for c in hand_cards)
            parts.append(f"In this hand, your position is {my_position}, "
                          f"and your holding is [{hand_str}].")
        else:
            parts.append(f"In this hand, your position is {my_position}.")

        # ── 行动历史（按阶段描述）──
        if action_history:
            # 将行动按阶段分组 (用 "phase" 标记分隔)
            streets: List[List[Dict]] = [[]]  # 第一组 = preflop
            for h in action_history:
                if h.get("action") == "phase":
                    streets.append([])
                    continue
                streets[-1].append(h)

            street_names = ["preflop", "flop", "turn", "river"]

            for si, street_actions in enumerate(streets):
                if not street_actions:
                    continue

                # 过滤掉盲注 (blind)
                game_actions = [a for a in street_actions
                                if a.get("action") != "blind"]
                if not game_actions:
                    continue

                # 构造每个行动的描述文本
                descs = []
                for h in game_actions:
                    action_str = h.get("action", "fold")
                    amount = h.get("amount", 0)
                    p_name = h.get("player", "")
                    p_pos = positions.get(p_name, p_name)

                    if action_str == "fold":
                        descs.append(f"{p_pos} fold")
                    elif action_str == "check":
                        descs.append(f"{p_pos} check")
                    elif action_str == "call":
                        descs.append(f"{p_pos} call")
                    elif action_str == "raise":
                        descs.append(f"{p_pos} raise {amount} chips")
                    elif action_str == "all_in":
                        descs.append(f"{p_pos} all-in {amount} chips")

                if descs:
                    sname = street_names[si] if si < len(street_names) else f"street{si}"
                    if sname == "preflop":
                        action_desc = ", and ".join(descs)
                        parts.append(f"Before the flop, {action_desc}.")
                        parts.append("Assume that all other players that is not mentioned folded.")
                    elif sname == "flop":
                        action_desc = ", and ".join(descs)
                        parts.append(f"On the flop, {action_desc}.")
                    elif sname == "turn":
                        action_desc = ", and ".join(descs)
                        parts.append(f"On the turn, {action_desc}.")
                    elif sname == "river":
                        action_desc = ", and ".join(descs)
                        parts.append(f"On the river, {action_desc}.")

        # ── 公共牌描述 ──
        if community_cards:
            if len(community_cards) >= 3:
                flop = community_cards[:3]
                flop_str = ", and ".join(_card_to_titled(c) for c in flop)
                # 收集flop阶段之后的action
                parts.append(f"The flop comes {flop_str}.")
            if len(community_cards) >= 4:
                turn = community_cards[3]
                parts.append(f"The turn comes {_card_to_titled(turn)}.")
            if len(community_cards) >= 5:
                river = community_cards[4]
                parts.append(f"The river comes {_card_to_titled(river)}.")

        parts.append("")
        parts.append("")

        # ── 决策提示 ──
        parts.append("Now it is your turn to make a move.")
        if hand_cards:
            hand_str = " and ".join(_card_to_full_name(c) for c in hand_cards)
            parts.append(f"To remind you, the current pot size is {pot} chips, "
                          f"and your holding is [{hand_str}].")
        else:
            parts.append(f"To remind you, the current pot size is {pot} chips.")

        # 额外上下文（不在 PokerBench 中但对实时游戏很重要）
        min_raise_to = game_state.get("min_raise_to", current_bet + min_raise)
        parts.append(f"Your chips: {your_chips}. Amount to call: {call_amount}. "
                      f"Current bet: {current_bet}. "
                      f"Minimum raise to: {min_raise_to} (raise_amount uses 'raise to' semantics, "
                      f"i.e., the total bet level you want to reach).")
        parts.append(f"Valid actions: {', '.join(valid_actions)}.")
        parts.append("")
        parts.append("Decide on an action based on the strength of your hand on this board, "
                      "your position, and actions before you. Do not explain your answer.")
        parts.append("Your optimal action is:")

        return "\n".join(parts)

    @staticmethod
    def build_decision_prompt_structured(game_state: Dict[str, Any], player_name: str) -> str:
        """
        结构化键值对风格的决策prompt（作为后备格式）
        """
        parts = []

        # 基本信息
        parts.append(f"=== Texas Hold'em - Hand #{game_state.get('hand_number', '?')} ===")
        parts.append(f"Phase: {game_state['phase']}")
        parts.append(f"Pot: {game_state['pot']} chips")
        parts.append(f"Current bet to match: {game_state['current_bet']} chips")

        # 你的手牌
        if "your_hand" in game_state:
            parts.append(f"\nYour hand: {' '.join(game_state['your_hand'])}")

        # 公共牌
        cc = game_state.get("community_cards", [])
        if cc:
            parts.append(f"Community cards: {' '.join(cc)}")
        else:
            parts.append("Community cards: (none yet - preflop)")

        # 你的筹码和需要跟注的金额
        if "your_chips" in game_state:
            parts.append(f"\nYour chips: {game_state['your_chips']}")
        if "call_amount" in game_state:
            parts.append(f"Amount to call: {game_state['call_amount']}")
        parts.append(f"Minimum raise: {game_state.get('min_raise', '?')}")

        # 对手信息
        parts.append("\n--- Players ---")
        for p in game_state.get("players", []):
            status = "ACTIVE" if p["is_active"] else "FOLDED"
            all_in = " (ALL-IN)" if p.get("is_all_in") else ""
            marker = " <<< YOU" if p["name"] == player_name else ""
            hand_str = f" Hand: {' '.join(p['hand'])}" if p['hand'][0] != '??' else ""
            parts.append(
                f"  {p['name']}: {p['chips']} chips | bet: {p['current_bet']} | "
                f"{status}{all_in}{hand_str}{marker}"
            )

        # 行动历史
        history = game_state.get("action_history", [])
        if history:
            parts.append("\n--- Action History (this hand) ---")
            for h in history[-15:]:  # 只显示最近15个动作
                amt = f" {h['amount']}" if h.get("amount") else ""
                parts.append(f"  {h['player']}: {h['action']}{amt}")

        # 可选动作
        parts.append(f"\n--- Your Valid Actions ---")
        parts.append(f"  {', '.join(game_state.get('valid_actions', []))}")

        # 最终指示
        parts.append(f"\nWhat is your action? Respond in JSON format only.")

        return "\n".join(parts)

    OPPONENT_ANALYSIS_SYSTEM_PROMPT = """You are an expert poker opponent profiler. You specialize in analyzing opponents' historical actions to classify their playing style.

Based on the statistical data and action patterns provided, classify each opponent into ONE of the following strategy types:

1. ABC Player / Balanced (13% population): Evenly distributed actions pre/post-flop; no distinct strategic preference.
2. Selective Value Aggressor (3%): Calls/raises post-flop mainly in high-value situations; seeks value selectively.
3. Tight-Passive / Rock (21%): Conservative pre-flop selection; predominantly passive post-flop, preferring checks/calls.
4. Positional Grinder (15%): Favors small late-position pre-flop raises; exploits position for incremental gains.
5. Weak-Tight / Passive Recreational (33%): Most common type; mostly checks post-flop; passive and folds under pressure.
6. Loose-Passive / Calling Station (10%): Frequently calls pre/post-flop; rarely raises; often calls down with weak hands.
7. Early-Position Aggressor (5%): Frequently makes small early-position pre-flop raises; aims to establish pre-flop dominance.

For each opponent, provide:
- The classified strategy type
- A confidence level (0-1)
- Specific counter-strategy advice for the current situation

Output JSON schema (no prose):
{
  "opponents": [
    {
      "name": "opponent_name",
      "strategy_type": "type_name",
      "confidence": 0-1,
      "counter_strategy": "specific advice for current hand"
    }
  ],
  "overall_table_advice": "general advice considering all opponents"
}

Keep responses deterministic and well-formatted JSON only (no markdown, no extra text)."""

    @staticmethod
    def build_opponent_analysis_prompt(
        game_state: Dict[str, Any],
        player_name: str,
        opponent_analysis_text: str,
    ) -> str:
        """
        构建对手分析 Agent 的 prompt。
        将统计数据和当前游戏情况提供给 LLM 进行对手策略分析。

        Args:
            game_state: 当前游戏状态
            player_name: 当前玩家名称
            opponent_analysis_text: OpponentAnalyzer 生成的统计分析文本

        Returns:
            str: 对手分析 prompt
        """
        parts = []
        parts.append("You are analyzing the opponents at a 6-max No-Limit Texas Hold'em table.")
        parts.append("")
        parts.append("=== Current Game Context ===")
        parts.append(f"Phase: {game_state.get('phase', '?')}")
        parts.append(f"Pot: {game_state.get('pot', 0)} chips")

        hand_cards = game_state.get("your_hand", [])
        if hand_cards:
            parts.append(f"Your hand: {' '.join(hand_cards)}")

        community = game_state.get("community_cards", [])
        if community:
            parts.append(f"Community cards: {' '.join(community)}")
        parts.append("")

        # 当前对手信息
        parts.append("=== Active Opponents at Table ===")
        players = game_state.get("players", [])
        for p in players:
            if p["name"] != player_name and p.get("is_active", True):
                status = "ACTIVE"
                if p.get("is_all_in"):
                    status = "ALL-IN"
                parts.append(f"  {p['name']}: {p['chips']} chips | Status: {status}")
        parts.append("")

        # 对手统计数据
        parts.append(opponent_analysis_text)
        parts.append("")

        parts.append("Based on the above statistical data and behavioral patterns, "
                     "classify each opponent's strategy type and provide specific "
                     "counter-strategy advice for the CURRENT hand situation.")
        parts.append("")
        parts.append("Your analysis (JSON only):")

        return "\n".join(parts)

    @staticmethod
    def build_reflection_prompt(
        game_state: Dict[str, Any],
        hand_result: Dict[str, Any],
        player_name: str,
    ) -> str:
        """
        构建手牌复盘prompt（可选功能，让LLM分析自己的表现）
        """
        parts = [
            "=== Hand Review ===",
            f"Hand #{hand_result.get('hand_number', '?')}",
            f"Community cards: {' '.join(hand_result.get('community_cards', []))}",
            "\nResults:",
        ]

        for r in hand_result.get("results", []):
            marker = " (YOU)" if r["player"] == player_name else ""
            parts.append(
                f"  {r['player']}{marker}: won {r['won']} chips "
                f"with {r.get('hand', 'N/A')} [{', '.join(r.get('cards', []))}]"
            )

        parts.append("\nBriefly review: What did you do well? What could you improve?")
        return "\n".join(parts)
