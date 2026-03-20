#!/usr/bin/env python3
"""
main.py - 使用本地 vLLM 模型进行多人德州扑克对局

用法:
    python main.py                              # 默认6人，100手牌
    python main.py --players 4 --hands 10       # 4人，10手牌
    python main.py --tp 4                       # 使用4张GPU
    CUDA_VISIBLE_DEVICES=2,3 python main.py     # 指定GPU
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime
from typing import Optional

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from config import LLMConfig
from poker_engine.game import PokerGame, Action, ActionType
from poker_engine.player import Player
from llm_agent.agent import LLMAgent
from llm_agent.human_agent import HumanAgent
from utils.gpu_utils import setup_cuda_devices
from utils.markdown_logger import MarkdownLogger
from utils.console_display import (
    print_banner,
    print_hand_header,
    print_phase_change,
    print_action,
    print_results,
    print_final_standings,
)

# ─────────────────────────────────────────────────────────
#  常量
# ─────────────────────────────────────────────────────────

DEFAULT_MODEL_PATH = "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-14B"

PLAYER_NAMES = [
    "Alice 🂡", "Bob 🂢", "Charlie 🂣",
    "Diana 🂤", "Eve 🂥", "Frank 🂦",
    "Grace ��", "Hank 🂨", "Ivy 🂩", "Jack 🂪",
]

ACTION_MAP = {
    "fold": ActionType.FOLD,
    "check": ActionType.CHECK,
    "call": ActionType.CALL,
    "raise": ActionType.RAISE,
    "all_in": ActionType.ALL_IN,
}


# ─────────────────────────────────────────────────────────
#  游戏运行
# ─────────────────────────────────────────────────────────

def run_game(
    n_players: int = 6,
    n_hands: int = 5,
    chips: int = 1000,
    small_blind: int = 5,
    big_blind: int = 10,
    model_path: str = DEFAULT_MODEL_PATH,
    tensor_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
    seed: int = 42,
    log_level: str = "WARNING",
    output_md: str = "",
    lora_paths: Optional[list[str]] = None,
    human: bool = False,
    human_name: str = "You 🧑",
):
    """运行德州扑克对局"""

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(n_players, n_hands, model_path, tensor_parallel_size)
    if human:
        print(f"  🎮 人机对战模式 — 你是: {human_name}")
        print()

    # ── Markdown 日志 ──
    if not output_md:
        output_md = os.path.join(
            PROJECT_DIR, f"game_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        )
    md = MarkdownLogger(output_md)
    md.write_banner(n_players, n_hands, model_path, tensor_parallel_size)

    # ── 自动选择空闲GPU ──
    setup_cuda_devices(num_gpus=tensor_parallel_size)
    print()

    # ── 创建玩家和Agent ──
    players = []
    agents = {}
    initial_chips = {}

    ai_name_idx = 0
    for i in range(n_players):
        if human and i == 0:
            # 第一个座位为人类玩家
            player = Player(
                name=human_name, chips=chips,
                is_human=True, agent_type="human",
            )
            players.append(player)
            initial_chips[human_name] = chips
            agents[human_name] = HumanAgent(player_name=human_name)
        else:
            name = PLAYER_NAMES[ai_name_idx] if ai_name_idx < len(PLAYER_NAMES) else f"Player_{ai_name_idx + 1}"
            ai_name_idx += 1
            player = Player(name=name, chips=chips, agent_type="llm")
            players.append(player)
            initial_chips[name] = chips

            agents[name] = LLMAgent(
                player_name=name,
                llm_model=model_path,
                temperature=0.7,
                max_retries=3,
                vllm_tensor_parallel_size=tensor_parallel_size,
                vllm_gpu_memory_utilization=gpu_memory_utilization,
                vllm_max_model_len=max_model_len,
                lora_paths=lora_paths,
            )

    # ── 创建游戏 ──
    game = PokerGame(
        players=players,
        small_blind=small_blind,
        big_blind=big_blind,
        seed=seed,
    )

    print("  🚀 正在加载模型（首次推理时自动加载）...")
    print()

    start_time = time.time()
    prev_phase = None

    # ── 主循环 ──
    try:
      for hand_num in range(1, n_hands + 1):
        active_count = len([p for p in game.players if p.chips > 0])
        if active_count < 2:
            print("\n  ⚠️ 活跃玩家不足2人，游戏结束!")
            md._add("> ⚠️ 活跃玩家不足2人，游戏结束!")
            md._add("")
            break

        # 人机模式下检查人类筹码
        if human:
            human_player = game.get_player_by_name(human_name)
            if human_player and human_player.chips <= 0:
                print(f"\n  😢 你的筹码已耗尽，游戏结束!")
                md._add(f"> 😢 {human_name} 筹码耗尽，游戏结束!")
                md._add("")
                break

        game.start_new_hand()
        print_hand_header(hand_num, n_hands, game)
        md.write_hand_header(hand_num, n_hands, game)
        prev_phase = game.phase.name

        hand_start = time.time()

        while not game.is_hand_over():
            current = game.get_current_player()
            if current is None:
                break

            # 检查阶段变化（动作执行前）
            if game.phase.name != prev_phase:
                print_phase_change(game.phase.name, [str(c) for c in game.community_cards])
                md.write_phase_change(game.phase.name, [str(c) for c in game.community_cards])
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

            # 非人类玩家才打印动作（人类已在 HumanAgent 内展示）
            if not getattr(current, "is_human", False):
                print_action(current.name, decision)
            md.write_action(current.name, decision)

            # 执行动作
            action = Action(
                player_name=current.name,
                action_type=ACTION_MAP[decision["action"]],
                amount=decision.get("amount", 0),
            )
            result = game.execute_action(action)

            if not result.get("success"):
                print(f"      ❌ 错误: {result.get('error')}")
                md.write_action_error(result.get('error', ''))
                fold_action = Action(current.name, ActionType.FOLD)
                game.execute_action(fold_action)

            # 检查阶段变化（动作执行后）
            if game.phase.name != prev_phase:
                print_phase_change(game.phase.name, [str(c) for c in game.community_cards])
                md.write_phase_change(game.phase.name, [str(c) for c in game.community_cards])
                prev_phase = game.phase.name

        # 手牌结果
        hand_time = time.time() - hand_start
        if game.hand_results:
            print_results(game, game.hand_results[-1])
            md.write_hand_result(game, game.hand_results[-1])
        print(f"\n  ⏱️ 本手耗时: {hand_time:.1f}s")
        md.write_hand_time(hand_time)

        # 当前筹码
        print("  💰 当前筹码:")
        for p in sorted(game.players, key=lambda x: x.chips, reverse=True):
            bar = "▓" * (p.chips // 100)
            marker = " ★" if getattr(p, "is_human", False) else ""
            print(f"     {p.name:<15} {p.chips:>6}  {bar}{marker}")
        md.write_chips_summary(game.players)

        # 每手结束后刷新文件
        md.flush()

        # 人机模式下每手结束后询问是否继续
        if human and hand_num < n_hands:
            try:
                cont = input(
                    f"\n  按 Enter 继续下一手 (或输入 'q' 退出)... "
                ).strip().lower()
                if cont in ("q", "quit", "exit", "退出"):
                    print("\n  👋 你选择了退出游戏!")
                    md._add("> 👋 玩家主动退出游戏")
                    md._add("")
                    break
            except (EOFError, KeyboardInterrupt):
                print("\n  👋 游戏中断!")
                break

    except (EOFError, KeyboardInterrupt):
        print("\n\n  👋 游戏被中断!")

    # ── 最终结果 ──
    total_time = time.time() - start_time
    print_final_standings(game, initial_chips, total_time)
    md.write_final_standings(game, initial_chips, total_time)
    md.flush()
    print(f"\n  📝 游戏记录已保存至: {output_md}")

    # ── 清理 ──
    try:
        from llm_agent.vllm_provider import shutdown_vllm
        shutdown_vllm()
    except Exception:
        pass

    return game


# ─────────────────────────────────────────────────────────
#  CLI 入口
# ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="🃏 LLM 德州扑克对局",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py                             # 默认6人 (纯AI对局)
  python main.py --players 4 --hands 10      # 4人10手
  python main.py --tp 4 --gpu-util 0.85      # 4卡并行

  🎮 人机对战模式:
  python main.py --human                     # 1个人类 + 5个AI (共6人)
  python main.py --human --players 4         # 1个人类 + 3个AI (共4人)
  python main.py --human --name "玩家1"      # 自定义名称
        """,
    )

    # 人机对战
    parser.add_argument("--human", action="store_true",
                        help="🎮 加入一个人类玩家 (替换第一个AI)")
    parser.add_argument("--name", type=str, default="You 🧑",
                        help="人类玩家的显示名称 (默认 'You 🧑')")

    # 通用参数
    parser.add_argument("--players", type=int, default=6, help="玩家总数 (2-10, 默认6)")
    parser.add_argument("--hands", type=int, default=5, help="总手数")
    parser.add_argument("--chips", type=int, default=1000, help="初始筹码 (默认1000)")
    parser.add_argument("--small-blind", type=int, default=5, help="小盲注 (默认5)")
    parser.add_argument("--big-blind", type=int, default=10, help="大盲注 (默认10)")
    parser.add_argument("--model", default="./checkpoints/pokerbench-qwen2.5-7b",
                        help="模型路径")
    parser.add_argument("--tp", type=int, default=1,
                        help="Tensor parallel GPU数 (默认1)")
    parser.add_argument("--gpu-util", type=float, default=0.9,
                        help="GPU显存利用率 (默认0.9)")
    parser.add_argument("--max-model-len", type=int, default=10000,
                        help="最大序列长度 (默认10000)")
    parser.add_argument("--seed", type=int, default=40, help="随机种子 (默认40)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认INFO)")
    parser.add_argument("--output", default="",
                        help="输出Markdown文件路径 (默认自动生成)")
    parser.add_argument("--lora", action="append", default=None,
                        help="可选 LoRA 适配器路径（可重复指定多个）")

    args = parser.parse_args()

    if args.players < 2 or args.players > 10:
        parser.error("玩家数量必须在2-10之间")

    output = args.output if args.output else "./result/game.md"

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
        output_md=output,
        lora_paths=args.lora,
        human=args.human,
        human_name=args.name,
    )


if __name__ == "__main__":
    main()
