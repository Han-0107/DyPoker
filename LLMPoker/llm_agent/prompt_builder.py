"""
PromptBuilder - 构建发送给LLM的提示词
将游戏状态转化为LLM可理解的自然语言描述
"""

from __future__ import annotations
from typing import Dict, Any, List


class PromptBuilder:
    """构建德州扑克决策所需的Prompt"""

    SYSTEM_PROMPT = """You are an expert Texas Hold'em poker player. You will be given the current game state and must decide on the best action.

Your response MUST be in the following JSON format (and NOTHING else):
{
    "reasoning": "Brief explanation of your thought process",
    "action": "fold" | "check" | "call" | "raise" | "all_in",
    "raise_amount": <number, only required if action is "raise">
}

Key poker concepts to consider:
1. Hand strength: Evaluate your hole cards and how they connect with community cards
2. Position: Being last to act is an advantage
3. Pot odds: Compare the bet you need to call with the potential winnings
4. Opponent behavior: Consider what their actions reveal about their hand
5. Bluffing: Sometimes bet with weak hands to win pots
6. Stack sizes: Consider your and opponents' remaining chips

If your hand isn't too bad, try not to fold before the flop. Avoid overly aggressive strategies and use checks more often. Only be aggressive with strong hands and selective with marginal ones. Adapt to opponent tendencies."""

    @staticmethod
    def build_decision_prompt(game_state: Dict[str, Any], player_name: str) -> str:
        """
        根据游戏状态构建决策prompt
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
