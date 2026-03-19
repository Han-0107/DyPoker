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
from typing import Optional

# 项目路径
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from config import GameConfig, LLMConfig, PlayerConfig
from poker_engine.game import PokerGame, Action, ActionType, GamePhase
from poker_engine.player import Player
from llm_agent.agent import LLMAgent
from gpu_utils import setup_cuda_devices


# ─────────────────────────────────────────────────────
#  Markdown 日志记录器
# ─────────────────────────────────────────────────────

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
        self._add(f"| 项目 | 值 |")
        self._add(f"|------|------|")
        self._add(f"| 模型 | `{os.path.basename(model_path)}` |")
        self._add(f"| 玩家数 | {n_players} |")
        self._add(f"| 总手数 | {n_hands} |")
        self._add(f"| GPU 并行 | {tp} 卡 |")
        self._add(f"| 时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |")
        self._add("")
        self._add("---")
        self._add("")

    def write_hand_header(self, hand_num: int, total: int, game: PokerGame):
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
        thinking = decision.get("thinking", "")
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
            self._add(f"  <details>")
            self._add(f"  <summary>📥 LLM 输入 (点击展开)</summary>")
            self._add(f"")
            self._add(f"  ```")
            for line in input_prompt.splitlines():
                self._add(f"  {line}")
            self._add(f"  ```")
            self._add(f"")
            self._add(f"  </details>")
            self._add("")
        # LLM 完整输出（折叠）
        if raw_response:
            self._add(f"  <details>")
            self._add(f"  <summary>� LLM 完整输出 (点击展开)</summary>")
            self._add(f"")
            self._add(f"  ```")
            for line in raw_response.splitlines():
                self._add(f"  {line}")
            self._add(f"  ```")
            self._add(f"")
            self._add(f"  </details>")
            self._add("")

    def write_action_error(self, error_msg: str):
        self._add(f"  - ❌ 错误: {error_msg}")
        self._add("")

    def write_hand_result(self, game: PokerGame, last_result: dict):
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

    def write_final_standings(self, game: PokerGame, initial_chips: dict, total_time: float):
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
        "FLOP": "🃏 翻牌 (Flop)",
        "TURN": "🃏 转牌 (Turn)",
        "RIVER": "🃏 河牌 (River)",
        "SHOWDOWN": "🏆 摊牌 (Showdown)",
    }
    name = phase_names.get(phase, None)
    if name is None:
        return  # 不打印 FINISHED 等无关阶段
    cc = " ".join(community_cards) if community_cards else "(无)"
    print(f"\n  {'─'*40}")
    print(f"  {name}  |  公共牌: {cc}")
    print(f"  {'─'*40}")


def print_action(player_name: str, decision: dict):
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
    tensor_parallel_size: int = 1,
    gpu_memory_utilization: float = 0.9,
    max_model_len: int = 4096,
    seed: int = 42,
    log_level: str = "WARNING",
    output_md: str = "",
    lora_paths: Optional[list[str]] = None,
):
    """运行Qwen3-32B德州扑克对局"""

    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print_banner(n_players, n_hands, model_path, tensor_parallel_size)

    # ── Markdown 日志 ──
    if not output_md:
        output_md = os.path.join(
            PROJECT_DIR,
            f"game_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md",
        )
    md = MarkdownLogger(output_md)
    md.write_banner(n_players, n_hands, model_path, tensor_parallel_size)

    # ── 自动选择空闲GPU ──
    setup_cuda_devices(num_gpus=tensor_parallel_size)
    print()

    # ── 创建LLM配置 ──
    llm_config = LLMConfig(
        model=model_path,
        temperature=0.7,
        max_retries=3,
        tensor_parallel_size=tensor_parallel_size,
        gpu_memory_utilization=gpu_memory_utilization,
        max_model_len=max_model_len,
        lora_paths=lora_paths,
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

    print("  🚀 正在加载Qwen3-32B模型（首次推理时自动加载）...")
    print()

    start_time = time.time()
    prev_phase = None

    # ── 主循环 ──
    for hand_num in range(1, n_hands + 1):
        active_count = len([p for p in game.players if p.chips > 0])
        if active_count < 2:
            print("\n  ⚠️ 活跃玩家不足2人，游戏结束!")
            md._add("> ⚠️ 活跃玩家不足2人，游戏结束!")
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

            # 检查阶段变化（动作执行后，用于显示新发的公共牌）
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
        print(f"  💰 当前筹码:")
        for p in sorted(game.players, key=lambda x: x.chips, reverse=True):
            bar = "▓" * (p.chips // 100)
            print(f"     {p.name:<15} {p.chips:>6}  {bar}")
        md.write_chips_summary(game.players)

        # 每手结束后刷新文件，防止中途崩溃丢失记录
        md.flush()

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
    parser.add_argument("--model", default="./checkpoints/pokerbench-qwen2.5-7b-soft", help="模型路径")
    parser.add_argument("--tp", type=int, default=1, help="Tensor parallel GPU数 (默认1；BitsAndBytes量化模型建议保持1)")
    parser.add_argument("--gpu-util", type=float, default=0.9, help="GPU显存利用率 (默认0.9)")
    parser.add_argument("--max-model-len", type=int, default=10000, help="最大序列长度 (默认10000)")
    parser.add_argument("--seed", type=int, default=40, help="随机种子 (默认42)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="日志级别 (默认INFO)")
    parser.add_argument("--output", default="./result/game.md", help="输出Markdown文件路径")
    parser.add_argument(
        "--lora",
        action="append",
        default=None,
        help="可选 LoRA 适配器路径（可重复指定多个）",
    )

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
        output_md=args.output,
        lora_paths=args.lora,
    )


if __name__ == "__main__":
    main()
