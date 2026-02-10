#!/usr/bin/env python3
"""
run_qwen3_poker.py - 使用本地Qwen3-32B模型进行6人德州扑克对局

用法:
    python run_qwen3_poker.py                          # 默认6人，5手牌
    python run_qwen3_poker.py --players 4 --hands 10   # 4人，10手牌
    python run_qwen3_poker.py --tp 4                   # 使用4张GPU
    CUDA_VISIBLE_DEVICES=2,3 python run_qwen3_poker.py # 指定GPU
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from config import GameConfig, LLMConfig, PlayerConfig
from poker_engine.game import PokerGame, Action, ActionType, GamePhase
from poker_engine.player import Player
from llm_agent.agent import LLMAgent, RandomAgent


# ─────────────────────────────────────────────────────
#  配置
# ─────────────────────────────────────────────────────

QWEN3_32B_PATH = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-14B"

PLAYER_NAMES = [
    "Alice 🂡", "Bob 🂢", "Charlie 🂣",
    "Diana 🂤", "Eve 🂥", "Frank 🂦",
    "Grace 🂧", "Hank 🂨", "Ivy 🂩", "Jack 🂪",
]

ACTION_MAP = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
}


def print_banner(n_players: int, n_hands: int, model_path: str, tp: int):
    print("\n" + "🃏" * 30)
    print("  ♠♥♦♣  Qwen3-32B 德州扑克对局  ♣♦♥♠")
    print("🃏" * 30)
    print(f"  模型: {os.path.basename(model_path)}")
    print(f"  玩家: {n_players} 人")
    print(f"  手数: {n_hands}")
    print(f"  GPU:  {tp} 卡 tensor parallel")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🃏" * 30 + "\n")


def print_hand_header(hand_num: int, total: int, game: PokerGame):
    print(f"\n{'━'*60}")
    print(f"  🎴 第 {hand_num}/{total} 手牌  |  庄家: {game.players[game.dealer_idx].name}")
    print(f"{'━'*60}")
    for p in game.players:
        status = "✅" if p.chips > 0 else "❌"
        print(f"  {status} {p.name}: {p.chips} 筹码")
    print()


def print_phase_change(phase: str, community_cards: list):
    phase_names = {
        "PREFLOP": "🔮 翻牌前",
        "FLOP": "🃏 翻牌",
        "TURN": "🃏 转牌",
        "RIVER": "🃏 河牌",
    }
    name = phase_names.get(phase, phase)
    cc = " ".join(community_cards) if community_cards else "(无)"
    print(f"\n  {'─'*40}")
    print(f"  {name}  |  公共牌: {cc}")
    print(f"  {'─'*40}")


def print_action(player_name: str, decision: dict):
    action = decision["action"]
    amount = decision.get("amount", 0)
    reasoning = decision.get("reasoning", "")

    action_emoji = {
        "fold": "🚫", "check": "✋", "call": "📞",
        "raise": "💰", "all_in": "🔥",
    }
    emoji = action_emoji.get(action, "❓")
    amount_str = f" → {amount}" if amount else ""
    reasoning_short = reasoning[:80] + "..." if len(reasoning) > 80 else reasoning

    print(f"    {emoji} {player_name}: {action}{amount_str}")
    if reasoning_short:
        print(f"       💭 {reasoning_short}")


def print_results(game: PokerGame, last_result: dict):
    print(f"\n  📋 本手结果:")
    cc = last_result.get("community_cards", [])
    if cc:
        print(f"     公共牌: {' '.join(cc)}")

    for r in last_result.get("results", []):
        hand = r.get("hand", "N/A")
        cards = " ".join(r.get("cards", []))
        print(f"     🏆 {r['player']}: 赢得 {r['won']} 筹码  ({hand})  [{cards}]")


def print_final_standings(game: PokerGame, initial_chips: dict, total_time: float):
    print(f"\n{'🏆'*25}")
    print(f"  最终排名")
    print(f"{'🏆'*25}")

    sorted_players = sorted(game.players, key=lambda p: p.chips, reverse=True)
    medals = ["🥇", "🥈", "🥉", "  4", "  5", "  6", "  7", "  8", "  9", " 10"]

    for i, p in enumerate(sorted_players):
        initial = initial_chips.get(p.name, 1000)
        diff = p.chips - initial
        sign = "+" if diff >= 0 else ""
        medal = medals[i] if i < len(medals) else f" {i+1}"
        bar = "█" * max(0, p.chips // 50)
        print(f"  {medal} {p.name:<15} {p.chips:>6} ({sign}{diff:>5})  {bar}")

    winner = sorted_players[0]
    print(f"\n  🎉 冠军: {winner.name} ({winner.chips} 筹码)")
    print(f"  ⏱️  总耗时: {total_time:.1f} 秒")
    print(f"  📊 平均每手: {total_time/max(game.hand_number,1):.1f} 秒")


def run_game(
    n_players: int = 6,
    n_hands: int = 5,
    chips: int = 1000,
    small_blind: int = 5,
    big_blind: int = 10,
    model_path: str = QWEN3_32B_PATH,
    tensor_parallel_size: int = 2,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
    seed: int = 42,
    log_level: str = "WARNING",
):
    """运行Qwen3-32B德州扑克对局"""

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(n_players, n_hands, model_path, tensor_parallel_size)

    # ── 创建LLM配置 ──
    llm_config = LLMConfig(
        provider="vllm",
        model=model_path,
        api_url="",
        temperature=0.7,
        max_retries=3,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
    )

    # ── 创建玩家和Agent ──
    players = []
    agents = {}
    initial_chips = {}

    for i in range(n_players):
        name = PLAYER_NAMES[i] if i < len(PLAYER_NAMES) else f"Player_{i+1}"
        player = Player(name=name, chips=chips, agent_type="llm")
        players.append(player)
        initial_chips[name] = chips

        agents[name] = LLMAgent(
            player_name=name,
            game_server_url="",
            llm_api_url="",
            llm_model=model_path,
            llm_provider="vllm",
            temperature=0.7,
            max_retries=3,
            vllm_tensor_parallel_size=tensor_parallel_size,
            vllm_gpu_memory_utilization=gpu_memory_utilization,
            vllm_max_model_len=max_model_len,
        )

    # ── 创建游戏 ──
    game = PokerGame(
        players=players,
        small_blind=small_blind,
        big_blind=big_blind,
        seed=seed,
    )

    print("  🚀 正在加载Qwen3-32B模型（首次推理时自动加载）...")
    print()

    start_time = time.time()
    prev_phase = None

    # ── 主循环 ──
    for hand_num in range(1, n_hands + 1):
        active_count = len([p for p in game.players if p.chips > 0])
        if active_count < 2:
            print("\n  ⚠️ 活跃玩家不足2人，游戏结束!")
            break

        game.start_new_hand()
        print_hand_header(hand_num, n_hands, game)
        prev_phase = game.phase.name

        hand_start = time.time()

        while not game.is_hand_over():
            current = game.get_current_player()
            if current is None:
                break

            # 检查阶段变化
            if game.phase.name != prev_phase:
                print_phase_change(game.phase.name, [str(c) for c in game.community_cards])
                prev_phase = game.phase.name

            # 获取状态
            state = game.get_game_state(player_name=current.name)

            # LLM决策
            agent = agents.get(current.name)
            if agent is None:
                valid = state.get("valid_actions", [])
                decision = {"action": "check" if "check" in valid else "fold", "amount": 0}
            else:
                decision = agent.make_decision(state)

            print_action(current.name, decision)

            # 执行动作
            action = Action(
                player_name=current.name,
                action_type=ACTION_MAP[decision["action"]],
                amount=decision.get("amount", 0),
            )
            result = game.execute_action(action)

            if not result.get("success"):
                print(f"      ❌ 错误: {result.get('error')}")
                fold_action = Action(current.name, ActionType.FOLD)
                game.execute_action(fold_action)

        # 手牌结果
        hand_time = time.time() - hand_start
        if game.hand_results:
            print_results(game, game.hand_results[-1])
        print(f"\n  ⏱️ 本手耗时: {hand_time:.1f}s")

        # 当前筹码
        print(f"  💰 当前筹码:")
        for p in sorted(game.players, key=lambda x: x.chips, reverse=True):
            bar = "▓" * (p.chips // 100)
            print(f"     {p.name:<15} {p.chips:>6}  {bar}")

    # ── 最终结果 ──
    total_time = time.time() - start_time
    print_final_standings(game, initial_chips, total_time)

    # ── 清理 ──
    try:
        from llm_agent.vllm_provider import shutdown_vllm
        shutdown_vllm()
    except Exception:
        pass

    return game


def main():
    parser = argparse.ArgumentParser(
        description="🃏 Qwen3-32B 德州扑克对局",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python run_qwen3_poker.py                             # 默认6人5手
  python run_qwen3_poker.py --players 4 --hands 10      # 4人10手
  python run_qwen3_poker.py --tp 4 --gpu-util 0.85      # 4卡并行
  CUDA_VISIBLE_DEVICES=2,3 python run_qwen3_poker.py    # 指定GPU 2,3
        """,
    )

    parser.add_argument("--players", type=int, default=6, help="玩家数量 (2-10, 默认6)")
    parser.add_argument("--hands", type=int, default=5, help="总手数 (默认5)")
    parser.add_argument("--chips", type=int, default=1000, help="初始筹码 (默认1000)")
    parser.add_argument("--small-blind", type=int, default=5, help="小盲注 (默认5)")
    parser.add_argument("--big-blind", type=int, default=10, help="大盲注 (默认10)")
    parser.add_argument("--model", default=QWEN3_32B_PATH, help="模型路径")
    parser.add_argument("--tp", type=int, default=2, help="Tensor parallel GPU数 (默认2)")
    parser.add_argument("--gpu-util", type=float, default=0.9, help="GPU显存利用率 (默认0.9)")
    parser.add_argument("--max-model-len", type=int, default=4096, help="最大序列长度 (默认4096)")
    parser.add_argument("--seed", type=int, default=42, help="随机种子 (默认42)")
    parser.add_argument("--log-level", default="WARNING",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认WARNING)")

    args = parser.parse_args()

    if args.players < 2 or args.players > 10:
        parser.error("玩家数量必须在2-10之间")

    run_game(
        n_players=args.players,
        n_hands=args.hands,
        chips=args.chips,
        small_blind=args.small_blind,
        big_blind=args.big_blind,
        model_path=args.model,
        tensor_parallel_size=args.tp,
        gpu_memory_utilization=args.gpu_util,
        max_model_len=args.max_model_len,
        seed=args.seed,
        log_level=args.log_level,
    )


if __name__ == "__main__":
    main()
