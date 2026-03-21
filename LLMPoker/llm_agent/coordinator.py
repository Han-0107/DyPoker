"""
Coordinator - 多 Agent 协调器
结合标准策略 Agent 和对手分析 Agent 的建议，给出最终决策。

工作流程:
  1. 标准策略 Agent (SFT/GRPO 训练) 给出基于游戏状态的标准决策
  2. 对手分析 Agent 分析对手历史行动并分类策略类型，给出反制建议
  3. Coordinator 综合两者的建议，做出最终决策
"""

from __future__ import annotations
import json
import logging
import re
import time
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class Coordinator:
    """
    Multi-Agent 协调器
    综合标准策略 Agent 和对手分析 Agent 的建议做出最终决策
    """

    COORDINATOR_SYSTEM_PROMPT = """You are an expert coordinator for a multi-agent Texas Hold'em poker decision system.
You will receive TWO pieces of advice:
1. **Standard Strategy Agent**: A decision from a well-trained poker agent (trained via SFT and GRPO), providing a solid, standard-play action based on the current game state.
2. **Opponent Analysis Agent**: An analysis of each opponent's historical playing style (classified into strategy types such as Tight-Passive, Loose-Passive, Weak-Tight, etc.) with specific counter-strategy recommendations.

Your task is to combine these two perspectives and produce the FINAL optimal action.

Guidelines:
- The Standard Strategy Agent provides a fundamentally sound baseline action. Respect it unless the Opponent Analysis provides a strong reason to deviate.
- If the Opponent Analysis identifies exploitable tendencies (e.g., opponent is Weak-Tight and folds under pressure), adjust the action accordingly (e.g., raise/bluff more).
- If opponent data is insufficient (low confidence or few observed hands), lean heavily toward the Standard Strategy Agent's recommendation.
- Consider the specific counter-strategy advice when deciding whether to upgrade (e.g., check → raise) or downgrade (e.g., raise → call/fold) the standard action.
- Always honor the valid_actions list; never invent actions not available.
- For raises, the amount must be at least min_raise + call_amount, but not exceeding your stack.

Output JSON schema (no prose):
{
  "reasoning": "1-3 bullet-style thoughts explaining how you combined the two agents' advice",
  "action": "fold" | "check" | "call" | "raise" | "all_in",
  "raise_amount": <number, required only for "raise">,
  "confidence": 0-1
}

Keep responses deterministic and well-formatted JSON only (no markdown, no extra text)."""

    def __init__(self):
        pass

    @staticmethod
    def build_coordinator_prompt(
        game_state: Dict[str, Any],
        player_name: str,
        standard_decision: Dict[str, Any],
        opponent_analysis: str,
    ) -> str:
        """
        构建 Coordinator 的用户 prompt，综合标准策略和对手分析。

        Args:
            game_state: 当前游戏状态
            player_name: 当前玩家名称
            standard_decision: 标准策略 Agent 的决策
                               {"action": str, "amount": int, "reasoning": str}
            opponent_analysis: 对手分析 Agent 的分析文本

        Returns:
            str: Coordinator 的完整 prompt
        """
        parts = []

        # ── 游戏概况 ──
        parts.append("=== Current Game Situation ===")
        parts.append(f"Phase: {game_state.get('phase', '?')}")
        parts.append(f"Pot: {game_state.get('pot', 0)} chips")
        parts.append(f"Your chips: {game_state.get('your_chips', 0)}")
        parts.append(f"Amount to call: {game_state.get('call_amount', 0)}")
        parts.append(f"Minimum raise: {game_state.get('min_raise', 10)}")

        hand_cards = game_state.get("your_hand", [])
        if hand_cards:
            parts.append(f"Your hand: {' '.join(hand_cards)}")

        community = game_state.get("community_cards", [])
        if community:
            parts.append(f"Community cards: {' '.join(community)}")

        valid_actions = game_state.get("valid_actions", [])
        parts.append(f"Valid actions: {', '.join(valid_actions)}")
        parts.append("")

        # ── 标准策略 Agent 的建议 ──
        parts.append("=== Standard Strategy Agent Recommendation ===")
        std_action = standard_decision.get("action", "?")
        std_amount = standard_decision.get("amount", 0)
        std_reasoning = standard_decision.get("reasoning", "")
        std_confidence = standard_decision.get("confidence", "N/A")

        parts.append(f"Recommended action: {std_action}"
                     + (f" (amount: {std_amount})" if std_action == "raise" else ""))
        if std_reasoning:
            parts.append(f"Reasoning: {std_reasoning}")
        if std_confidence != "N/A":
            parts.append(f"Confidence: {std_confidence}")
        parts.append("")

        # ── 对手分析 Agent 的建议 ──
        parts.append("=== Opponent Analysis Agent Report ===")
        parts.append(opponent_analysis)
        parts.append("")

        # ── 指示 ──
        parts.append("Based on BOTH the standard strategy recommendation and the opponent "
                     "analysis, decide on the FINAL optimal action. If the opponent analysis "
                     "suggests an exploitative adjustment to the standard action, make that "
                     "adjustment. Otherwise, follow the standard strategy.")
        parts.append("")
        parts.append("Your final coordinated decision (JSON only):")

        return "\n".join(parts)

    @staticmethod
    def parse_coordinator_response(
        raw: str,
        game_state: Dict[str, Any],
        fallback_decision: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        解析 Coordinator 的 LLM 响应。
        如果解析失败，返回 fallback_decision（即标准策略 Agent 的决策）。

        Args:
            raw: LLM 原始输出
            game_state: 当前游戏状态
            fallback_decision: 标准策略 Agent 的决策（用于回退）

        Returns:
            Dict with action, amount, reasoning
        """
        # 分离 thinking 内容
        thinking = ""
        answer = raw
        think_match = re.search(r'<think>(.*?)</think>', raw, re.DOTALL)
        if think_match:
            thinking = think_match.group(1).strip()
            answer = raw[think_match.end():].strip()

        action = None
        reasoning = ""
        amount = 0

        # 尝试提取 JSON
        json_match = re.search(r'\{[^{}]*\}', answer, re.DOTALL)
        if not json_match:
            json_match = re.search(r'\{[^{}]*\}', raw, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group())
                action = data.get("action", "").lower().strip()
                reasoning = data.get("reasoning", "")
                amount = data.get("raise_amount", 0)
            except json.JSONDecodeError:
                pass

        # 如果 JSON 解析失败，尝试文本提取
        if not action:
            text_lower = answer.lower() if answer else raw.lower()
            if re.search(r'\ball[\s_-]?in\b', text_lower):
                action = "all_in"
            elif re.search(r'\braise\b', text_lower):
                action = "raise"
                amt_match = re.search(r'raise\s*(?:to\s*)?(\d+(?:\.\d+)?)', text_lower)
                if amt_match:
                    amount = float(amt_match.group(1))
            elif re.search(r'\bcall\b', text_lower):
                action = "call"
            elif re.search(r'\bcheck\b', text_lower):
                action = "check"
            elif re.search(r'\bfold\b', text_lower):
                action = "fold"

        # 如果仍然无法解析，使用 fallback
        if not action:
            logger.warning("Coordinator: Failed to parse response, using standard agent decision")
            return fallback_decision

        # 验证动作合法性
        valid_actions = game_state.get("valid_actions", [])
        if action not in valid_actions:
            if action == "bet" and "raise" in valid_actions:
                action = "raise"
            elif action == "check" and "call" in valid_actions:
                action = "call"
            elif action == "call" and "check" in valid_actions:
                action = "check"
            elif action == "raise" and "all_in" in valid_actions and "raise" not in valid_actions:
                action = "all_in"
            elif action == "fold" and "check" in valid_actions:
                action = "check"
            elif "check" in valid_actions:
                action = "check"
            elif "call" in valid_actions:
                action = "call"
            else:
                action = "fold"

        # 处理 raise 金额
        if action == "raise":
            min_raise = game_state.get("min_raise", 10)
            call_amount = game_state.get("call_amount", 0)
            your_chips = game_state.get("your_chips", 0)
            min_total = call_amount + min_raise

            if isinstance(amount, str):
                try:
                    amount = float(amount)
                except ValueError:
                    amount = min_total

            if amount <= call_amount and call_amount > 0 and "call" in valid_actions:
                action = "call"
                amount = 0
            elif amount < min_total:
                amount = min_total

            if action == "raise" and amount >= your_chips:
                action = "all_in"
                amount = 0

        return {
            "action": action,
            "amount": int(amount) if action == "raise" else 0,
            "reasoning": reasoning,
            "thinking": thinking,
            "coordinator": True,  # 标记这是 coordinator 的决策
        }
