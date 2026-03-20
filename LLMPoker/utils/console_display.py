"""
console_display - 控制台美化输出

将游戏进行过程通过 emoji 和格式化文本输出到终端。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from poker_engine.game import PokerGame


def print_banner(n_players: int, n_hands: int, model_path: str, tp: int):
    """打印游戏开始横幅"""
    print("\n" + "🃏" * 30)
    print("  ♠♥♦♣  Qwen3-32B 德州扑克对局  ♣♦♥♠")
    print("🃏" * 30)
    print(f"  模型: {os.path.basename(model_path)}")
    print(f"  玩家: {n_players} 人")
    print(f"  手数: {n_hands}")
    print(f"  GPU:  {tp} 卡 tensor parallel")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🃏" * 30 + "\n")


def print_hand_header(hand_num: int, total: int, game: "PokerGame"):
    """打印每手牌的标题"""
    print(f"\n{'━' * 60}")
    print(f"  🎴 第 {hand_num}/{total} 手牌  |  庄家: {game.players[game.dealer_idx].name}")
    print(f"{'━' * 60}")
    for p in game.players:
        status = "✅" if p.chips > 0 else "❌"
        print(f"  {status} {p.name}: {p.chips} 筹码")
    print()


def print_phase_change(phase: str, community_cards: list):
    """打印阶段变化"""
    phase_names = {
        "PREFLOP": "🔮 翻牌前",
        "FLOP": "🃏 翻牌 (Flop)",
        "TURN": "🃏 转牌 (Turn)",
        "RIVER": "🃏 河牌 (River)",
        "SHOWDOWN": "🏆 摊牌 (Showdown)",
    }
    name = phase_names.get(phase, None)
    if name is None:
        return
    cc = " ".join(community_cards) if community_cards else "(无)"
    print(f"\n  {'─' * 40}")
    print(f"  {name}  |  公共牌: {cc}")
    print(f"  {'─' * 40}")


def print_action(player_name: str, decision: dict):
    """打印玩家动作"""
    action = decision["action"]
    amount = decision.get("amount", 0)
    reasoning = decision.get("reasoning", "")
    thinking = decision.get("thinking", "")

    action_emoji = {
        "fold": "🚫", "check": "✋", "call": "📞",
        "raise": "💰", "all_in": "🔥",
    }
    emoji = action_emoji.get(action, "❓")
    amount_str = f" → {amount}" if amount else ""
    reasoning_short = reasoning[:200] + "..." if len(reasoning) > 200 else reasoning
    thinking_short = thinking[:300] + "..." if len(thinking) > 300 else thinking

    print(f"    {emoji} {player_name}: {action}{amount_str}")
    if thinking_short:
        print(f"       🧠 {thinking_short}")
    if reasoning_short:
        print(f"       💭 {reasoning_short}")


def print_results(game: "PokerGame", last_result: dict):
    """打印手牌结果"""
    print("\n  📋 本手结果:")
    cc = last_result.get("community_cards", [])
    if cc:
        print(f"     公共牌: {' '.join(cc)}")

    for r in last_result.get("results", []):
        hand = r.get("hand", "N/A")
        cards = " ".join(r.get("cards", []))
        print(f"     🏆 {r['player']}: 赢得 {r['won']} 筹码  ({hand})  [{cards}]")


def print_final_standings(game: "PokerGame", initial_chips: dict, total_time: float):
    """打印最终排名"""
    print(f"\n{'🏆' * 25}")
    print("  最终排名")
    print(f"{'🏆' * 25}")

    sorted_players = sorted(game.players, key=lambda p: p.chips, reverse=True)
    medals = ["🥇", "🥈", "🥉", "  4", "  5", "  6", "  7", "  8", "  9", " 10"]

    for i, p in enumerate(sorted_players):
        initial = initial_chips.get(p.name, 1000)
        diff = p.chips - initial
        sign = "+" if diff >= 0 else ""
        medal = medals[i] if i < len(medals) else f" {i + 1}"
        bar = "█" * max(0, p.chips // 50)
        print(f"  {medal} {p.name:<15} {p.chips:>6} ({sign}{diff:>5})  {bar}")

    winner = sorted_players[0]
    print(f"\n  🎉 冠军: {winner.name} ({winner.chips} 筹码)")
    print(f"  ⏱️  总耗时: {total_time:.1f} 秒")
    print(f"  📊 平均每手: {total_time / max(game.hand_number, 1):.1f} 秒")
