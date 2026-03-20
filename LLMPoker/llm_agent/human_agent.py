"""
HumanAgent - 人类玩家交互代理

通过终端输入与用户交互，展示游戏状态并获取决策。
接口与 LLMAgent 保持一致 (make_decision)。
"""

from __future__ import annotations
import sys
from typing import Dict, Any, List


# ── 牌面花色 Unicode 美化 ──
_SUIT_SYMBOL = {"♠": "♠", "♥": "♥", "♦": "♦", "♣": "♣"}
_SUIT_COLOR = {"♠": "\033[37m", "♥": "\033[91m", "♦": "\033[91m", "♣": "\033[37m"}
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
WHITE = "\033[97m"


def _colorize_card(card_str: str) -> str:
    """给牌面上色（红心/方块红色，黑桃/梅花白色）"""
    if not card_str or card_str == "??":
        return f"{DIM}[??]{RESET}"
    suit = card_str[-1] if card_str else ""
    color = _SUIT_COLOR.get(suit, WHITE)
    return f"{color}{BOLD}{card_str}{RESET}"


def _colorize_cards(cards: List[str]) -> str:
    """给一组牌上色"""
    return " ".join(_colorize_card(c) for c in cards)


class HumanAgent:
    """
    人类玩家代理 - 通过终端交互获取决策

    与 LLMAgent 具有相同的 make_decision(game_state) 接口，
    可以无缝替换到游戏循环中。
    """

    def __init__(self, player_name: str, **kwargs):
        self.player_name = player_name
        self.decision_history: list = []

    # =========================================================
    #  状态展示
    # =========================================================

    def _display_game_state(self, state: Dict[str, Any]):
        """美化展示当前游戏状态"""
        phase = state.get("phase", "?")
        pot = state.get("pot", 0)
        community = state.get("community_cards", [])
        your_hand = state.get("your_hand", [])
        your_chips = state.get("your_chips", 0)
        call_amount = state.get("call_amount", 0)
        current_bet = state.get("current_bet", 0)
        min_raise = state.get("min_raise", 0)
        players = state.get("players", [])

        phase_name = {
            "PREFLOP": "翻牌前 (Pre-Flop)",
            "FLOP": "翻牌 (Flop)",
            "TURN": "转牌 (Turn)",
            "RIVER": "河牌 (River)",
        }.get(phase, phase)

        print()
        print(f"  {CYAN}{'═' * 52}{RESET}")
        print(f"  {CYAN}║{RESET}  {MAGENTA}{BOLD}🎮 轮到你行动 — {self.player_name}{RESET}")
        print(f"  {CYAN}{'═' * 52}{RESET}")

        # 阶段 & 底池
        print(f"  {CYAN}║{RESET}  📍 阶段: {YELLOW}{phase_name}{RESET}")
        print(f"  {CYAN}║{RESET}  💰 底池: {GREEN}{BOLD}{pot}{RESET}   "
              f"当前注: {current_bet}   最小加注: {min_raise}")

        # 公共牌
        if community:
            print(f"  {CYAN}║{RESET}  🃏 公共牌: {_colorize_cards(community)}")
        else:
            print(f"  {CYAN}║{RESET}  🃏 公共牌: {DIM}(尚未发牌){RESET}")

        # 你的手牌
        print(f"  {CYAN}║{RESET}  🂡 你的手牌: {_colorize_cards(your_hand)}")
        print(f"  {CYAN}║{RESET}  💵 你的筹码: {GREEN}{your_chips}{RESET}"
              f"   需跟注: {RED}{call_amount}{RESET}")

        # 其他玩家
        print(f"  {CYAN}║{RESET}")
        print(f"  {CYAN}║{RESET}  {DIM}{'─' * 46}{RESET}")
        print(f"  {CYAN}║{RESET}  👥 玩家状态:")
        for p in players:
            name = p["name"]
            chips = p["chips"]
            bet = p.get("current_bet", 0)
            is_active = p.get("is_active", True)
            is_all_in = p.get("is_all_in", False)

            if name == self.player_name:
                marker = f"{MAGENTA}★{RESET} "
            else:
                marker = "  "

            if not is_active:
                status = f"{DIM}[已弃牌]{RESET}"
            elif is_all_in:
                status = f"{RED}{BOLD}[ALL-IN]{RESET}"
            else:
                status = f"{GREEN}[活跃]{RESET}"

            hand_str = ""
            hand_cards = p.get("hand", [])
            if hand_cards and hand_cards != ["??", "??"]:
                hand_str = f" 手牌: {_colorize_cards(hand_cards)}"
            elif name != self.player_name:
                hand_str = f" {DIM}[??]{RESET}"

            print(f"  {CYAN}║{RESET}  {marker}{name:<15} "
                  f"筹码:{chips:<6} 本轮下注:{bet:<5} {status}{hand_str}")

        print(f"  {CYAN}{'═' * 52}{RESET}")

    def _display_valid_actions(self, valid_actions: List[str], state: Dict[str, Any]):
        """展示可用动作"""
        call_amount = state.get("call_amount", 0)
        min_raise = state.get("min_raise", 0)
        your_chips = state.get("your_chips", 0)

        action_desc = {
            "fold":   f"🚫 fold   — 弃牌",
            "check":  f"✋ check  — 过牌（不加注）",
            "call":   f"📞 call   — 跟注 ({call_amount} 筹码)",
            "raise":  f"💰 raise  — 加注 (最少 {call_amount + min_raise}，输入总额)",
            "all_in": f"🔥 all_in — 全下 ({your_chips} 筹码)",
        }

        print(f"\n  {YELLOW}{BOLD}可选操作:{RESET}")
        for i, act in enumerate(valid_actions, 1):
            desc = action_desc.get(act, act)
            print(f"    {BOLD}[{i}]{RESET} {desc}")

    # =========================================================
    #  决策接口
    # =========================================================

    def make_decision(self, game_state: Dict[str, Any]) -> Dict[str, Any]:
        """
        通过终端交互获取人类玩家的决策。
        接口与 LLMAgent.make_decision 保持一致。

        返回: {"action": str, "amount": int, "reasoning": str}
        """
        self._display_game_state(game_state)

        valid_actions = game_state.get("valid_actions", [])
        if not valid_actions:
            return {"action": "fold", "amount": 0, "reasoning": "No valid actions"}

        self._display_valid_actions(valid_actions, game_state)

        while True:
            try:
                print()
                user_input = input(f"  {GREEN}👉 请输入你的操作 (名称或编号): {RESET}").strip().lower()

                if not user_input:
                    continue

                # 支持通过编号选择
                action = None
                if user_input.isdigit():
                    idx = int(user_input) - 1
                    if 0 <= idx < len(valid_actions):
                        action = valid_actions[idx]
                    else:
                        print(f"  {RED}❌ 无效编号，请输入 1~{len(valid_actions)}{RESET}")
                        continue
                else:
                    # 支持名称匹配 (大小写不敏感, 支持部分匹配)
                    user_input = user_input.replace("-", "_").replace(" ", "_")
                    for va in valid_actions:
                        if va == user_input or va.startswith(user_input):
                            action = va
                            break

                if action is None:
                    print(f"  {RED}❌ 无效操作: '{user_input}'。"
                          f"可选: {', '.join(valid_actions)}{RESET}")
                    continue

                # 处理 raise 金额
                amount = 0
                if action == "raise":
                    call_amount = game_state.get("call_amount", 0)
                    min_raise = game_state.get("min_raise", 0)
                    your_chips = game_state.get("your_chips", 0)
                    min_total = call_amount + min_raise

                    while True:
                        try:
                            amt_input = input(
                                f"  {GREEN}💰 输入加注总额 "
                                f"(最少 {min_total}, 最多 {your_chips}, "
                                f"输入 'all' 全下): {RESET}"
                            ).strip().lower()

                            if amt_input in ("all", "allin", "all_in", "全下"):
                                action = "all_in"
                                amount = 0
                                break

                            amount = int(amt_input)
                            if amount >= your_chips:
                                # 超过筹码 → all_in
                                print(f"  {YELLOW}⚠️ 金额 >= 你的筹码，自动转为 ALL-IN{RESET}")
                                action = "all_in"
                                amount = 0
                                break
                            elif amount < min_total:
                                print(f"  {RED}❌ 加注总额至少为 {min_total}{RESET}")
                                continue
                            else:
                                break
                        except ValueError:
                            print(f"  {RED}❌ 请输入一个有效数字{RESET}")

                # 确认
                amount_str = f" → {amount}" if amount else ""
                print(f"\n  {GREEN}✅ 你选择了: {BOLD}{action}{amount_str}{RESET}")

                decision = {
                    "action": action,
                    "amount": amount,
                    "reasoning": "Human player decision",
                }
                self.decision_history.append(decision)
                return decision

            except (EOFError, KeyboardInterrupt):
                print(f"\n  {YELLOW}⚠️ 检测到中断，自动弃牌 (fold){RESET}")
                return {"action": "fold", "amount": 0, "reasoning": "User interrupted"}
