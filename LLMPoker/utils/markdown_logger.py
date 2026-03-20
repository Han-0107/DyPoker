"""
MarkdownLogger - 将扑克游戏过程输出到 Markdown 文件

用于记录每一手牌的详细过程，包括玩家动作、LLM 推理和最终结果。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from poker_engine.game import PokerGame


class MarkdownLogger:
    """将扑克游戏过程输出到 Markdown 文件"""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.lines: list[str] = []

    def _add(self, text: str = ""):
        self.lines.append(text)

    def flush(self):
        """将内容写入文件"""
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))

    # ── 各种写入方法 ──

    def write_banner(self, n_players: int, n_hands: int, model_path: str, tp: int):
        self._add("# 🃏 Qwen3 德州扑克对局记录")
        self._add("")
        self._add("| 项目 | 值 |")
        self._add("|------|------|")
        self._add(f"| 模型 | `{os.path.basename(model_path)}` |")
        self._add(f"| 玩家数 | {n_players} |")
        self._add(f"| 总手数 | {n_hands} |")
        self._add(f"| GPU 并行 | {tp} 卡 |")
        self._add(f"| 时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
        self._add("")
        self._add("---")
        self._add("")

    def write_hand_header(self, hand_num: int, total: int, game: "PokerGame"):
        self._add(f"## 🎴 第 {hand_num}/{total} 手牌")
        self._add("")
        self._add(f"**庄家:** {game.players[game.dealer_idx].name}")
        self._add("")
        self._add("| 玩家 | 筹码 | 状态 |")
        self._add("|------|------|------|")
        for p in game.players:
            status = "✅ 活跃" if p.chips > 0 else "❌ 出局"
            self._add(f"| {p.name} | {p.chips} | {status} |")
        self._add("")

    def write_phase_change(self, phase: str, community_cards: list):
        phase_names = {
            "PREFLOP": "🔮 翻牌前 (Preflop)",
            "FLOP": "🃏 翻牌 (Flop)",
            "TURN": "🃏 转牌 (Turn)",
            "RIVER": "🃏 河牌 (River)",
            "SHOWDOWN": "🏆 摊牌 (Showdown)",
        }
        name = phase_names.get(phase, None)
        if name is None:
            return
        cc = " ".join(f"`{c}`" for c in community_cards) if community_cards else "_(无)_"
        self._add(f"### {name}")
        self._add("")
        self._add(f"**公共牌:** {cc}")
        self._add("")

    def write_action(self, player_name: str, decision: dict):
        action = decision["action"]
        amount = decision.get("amount", 0)
        reasoning = decision.get("reasoning", "")
        raw_response = decision.get("raw_response", "")
        input_prompt = decision.get("input_prompt", "")

        action_emoji = {
            "fold": "🚫 弃牌", "check": "✋ 过牌", "call": "📞 跟注",
            "raise": "💰 加注", "all_in": "🔥 全下",
        }
        action_str = action_emoji.get(action, action)
        amount_str = f" → **{amount}**" if amount else ""

        self._add(f"- **{player_name}**: {action_str}{amount_str}")
        if reasoning:
            self._add(f"  > 💭 {reasoning}")
        self._add("")

        # LLM 输入 prompt（折叠）
        if input_prompt:
            self._add("  <details>")
            self._add("  <summary>📥 LLM 输入 (点击展开)</summary>")
            self._add("")
            self._add("  ```")
            for line in input_prompt.splitlines():
                self._add(f"  {line}")
            self._add("  ```")
            self._add("")
            self._add("  </details>")
            self._add("")

        # LLM 完整输出（折叠）
        if raw_response:
            self._add("  <details>")
            self._add("  <summary>🤖 LLM 完整输出 (点击展开)</summary>")
            self._add("")
            self._add("  ```")
            for line in raw_response.splitlines():
                self._add(f"  {line}")
            self._add("  ```")
            self._add("")
            self._add("  </details>")
            self._add("")

    def write_action_error(self, error_msg: str):
        self._add(f"  - ❌ 错误: {error_msg}")
        self._add("")

    def write_hand_result(self, game: "PokerGame", last_result: dict):
        self._add("### 📋 本手结果")
        self._add("")
        cc = last_result.get("community_cards", [])
        if cc:
            self._add(f"**公共牌:** {' '.join(f'`{c}`' for c in cc)}")
            self._add("")
        for r in last_result.get("results", []):
            hand = r.get("hand", "N/A")
            cards = " ".join(f"`{c}`" for c in r.get("cards", []))
            self._add(f"- 🏆 **{r['player']}**: 赢得 **{r['won']}** 筹码 — _{hand}_ [{cards}]")
        self._add("")

    def write_hand_time(self, hand_time: float):
        self._add(f"⏱️ 本手耗时: **{hand_time:.1f}s**")
        self._add("")

    def write_chips_summary(self, players):
        self._add("**💰 当前筹码:**")
        self._add("")
        self._add("| 排名 | 玩家 | 筹码 |")
        self._add("|------|------|------|")
        for i, p in enumerate(sorted(players, key=lambda x: x.chips, reverse=True), 1):
            self._add(f"| {i} | {p.name} | {p.chips} |")
        self._add("")
        self._add("---")
        self._add("")

    def write_final_standings(self, game: "PokerGame", initial_chips: dict, total_time: float):
        self._add("## 🏆 最终排名")
        self._add("")
        medals = ["🥇", "🥈", "🥉"]
        sorted_players = sorted(game.players, key=lambda p: p.chips, reverse=True)
        self._add("| 排名 | 玩家 | 最终筹码 | 盈亏 |")
        self._add("|------|------|----------|------|")
        for i, p in enumerate(sorted_players):
            initial = initial_chips.get(p.name, 1000)
            diff = p.chips - initial
            sign = "+" if diff >= 0 else ""
            medal = medals[i] if i < len(medals) else f"{i+1}"
            self._add(f"| {medal} | {p.name} | {p.chips} | {sign}{diff} |")
        self._add("")
        winner = sorted_players[0]
        self._add(f"**🎉 冠军: {winner.name}** ({winner.chips} 筹码)")
        self._add("")
        self._add(f"- ⏱️ 总耗时: {total_time:.1f} 秒")
        self._add(f"- 📊 平均每手: {total_time / max(game.hand_number, 1):.1f} 秒")
        self._add("")
