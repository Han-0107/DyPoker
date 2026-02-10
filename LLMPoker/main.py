"""
main.py - 主入口，支持多种运行模式
模式1: 启动游戏服务器 + 独立LLM Agent客户端（分离部署）
模式2: 本地一体化运行（方便测试）
"""

import argparse
import logging
import subprocess
import sys
import time
import os
import json
import signal

# 将项目根目录加入path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import GameConfig, LLMConfig, PlayerConfig, ServerConfig


def setup_logging(level: str = "INFO"):
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def run_server(config: GameConfig):
    """启动游戏服务器（独立进程）"""
    print("=" * 60)
    print("  启动德州扑克游戏服务器")
    print(f"  地址: http://{config.server.host}:{config.server.port}")
    print("=" * 60)

    import uvicorn
    from server.poker_server import app

    uvicorn.run(app, host=config.server.host, port=config.server.port)


def run_agent(player_name: str, server_url: str, llm_config: LLMConfig):
    """启动LLM Agent客户端（独立进程）"""
    from llm_agent.agent import LLMAgent

    print(f"\n{'─'*40}")
    print(f"  启动LLM Agent: {player_name}")
    print(f"  游戏服务器: {server_url}")
    print(f"  LLM模型: {llm_config.provider}/{llm_config.model}")
    print(f"{'─'*40}")

    agent = LLMAgent(
        player_name=player_name,
        game_server_url=server_url,
        llm_api_url=llm_config.api_url,
        llm_model=llm_config.model,
        llm_api_key=llm_config.api_key,
        llm_provider=llm_config.provider,
        temperature=llm_config.temperature,
        max_retries=llm_config.max_retries,
    )

    agent.run_loop()


def run_local(config: GameConfig):
    """
    本地一体化运行（不通过HTTP，直接调用）
    方便测试和调试
    """
    from poker_engine.game import PokerGame, Action, ActionType
    from poker_engine.player import Player
    from llm_agent.agent import LLMAgent, RandomAgent
    from llm_agent.prompt_builder import PromptBuilder

    print("=" * 60)
    print("  德州扑克 - LLM 本地对局模式")
    print("=" * 60)

    # 创建玩家
    players = []
    agents = {}
    for pc in config.players:
        player = Player(name=pc.name, chips=pc.chips, agent_type=pc.agent_type)
        players.append(player)

        if pc.agent_type == "random":
            agents[pc.name] = RandomAgent(pc.name)
        elif pc.agent_type == "llm" and pc.llm_config:
            agents[pc.name] = LLMAgent(
                player_name=pc.name,
                game_server_url="",  # 本地模式不用
                llm_api_url=pc.llm_config.api_url,
                llm_model=pc.llm_config.model,
                llm_api_key=pc.llm_config.api_key,
                llm_provider=pc.llm_config.provider,
                temperature=pc.llm_config.temperature,
                vllm_tensor_parallel_size=getattr(pc.llm_config, 'tensor_parallel_size', 1),
                vllm_gpu_memory_utilization=getattr(pc.llm_config, 'gpu_memory_utilization', 0.9),
                vllm_max_model_len=getattr(pc.llm_config, 'max_model_len', 4096),
            )

    # 创建游戏
    game = PokerGame(
        players=players,
        small_blind=config.small_blind,
        big_blind=config.big_blind,
        seed=config.seed,
    )

    action_map = {
        "fold": ActionType.FOLD,
        "check": ActionType.CHECK,
        "call": ActionType.CALL,
        "raise": ActionType.RAISE,
        "all_in": ActionType.ALL_IN,
    }

    # 主循环
    for hand_num in range(config.num_hands):
        if len([p for p in game.players if p.chips > 0]) < 2:
            print("\n🏆 游戏结束 - 玩家不足")
            break

        game.start_new_hand()
        print(f"\n{'='*50}")
        print(f"  第 {game.hand_number} 手牌")
        print(f"{'='*50}")

        while not game.is_hand_over():
            current = game.get_current_player()
            if current is None:
                break

            # 获取游戏状态
            state = game.get_game_state(player_name=current.name)

            # 获取代理的决策
            agent = agents.get(current.name)
            if agent is None:
                # 没有代理，默认check/fold
                valid = state.get("valid_actions", [])
                if "check" in valid:
                    decision = {"action": "check", "amount": 0}
                else:
                    decision = {"action": "fold", "amount": 0}
            else:
                decision = agent.make_decision(state)

            print(f"  {current.name}: {decision['action']}"
                  f"{' ' + str(decision.get('amount', '')) if decision.get('amount') else ''}"
                  f"  [{decision.get('reasoning', '')}]")

            # 执行动作
            action = Action(
                player_name=current.name,
                action_type=action_map[decision["action"]],
                amount=decision.get("amount", 0),
            )
            result = game.execute_action(action)

            if not result.get("success"):
                print(f"    ❌ Error: {result.get('error')}")
                # 出错时默认fold
                fold_action = Action(current.name, ActionType.FOLD)
                game.execute_action(fold_action)

        # 打印手牌结果
        if game.hand_results:
            last_result = game.hand_results[-1]
            print(f"\n  📋 结果:")
            for r in last_result.get("results", []):
                print(f"    {r['player']}: 赢得 {r['won']} 筹码"
                      f" ({r.get('hand', 'N/A')})")

        # 打印当前筹码
        print(f"\n  💰 筹码:")
        for p in game.players:
            print(f"    {p.name}: {p.chips}")

    # 最终统计
    print(f"\n{'='*60}")
    print("  🏆 最终结果")
    print(f"{'='*60}")
    sorted_players = sorted(game.players, key=lambda p: p.chips, reverse=True)
    for i, p in enumerate(sorted_players):
        initial = next(pc.chips for pc in config.players if pc.name == p.name)
        diff = p.chips - initial
        sign = "+" if diff >= 0 else ""
        print(f"  #{i+1} {p.name}: {p.chips} ({sign}{diff})")


def main():
    parser = argparse.ArgumentParser(description="LLM Texas Hold'em Poker")
    subparsers = parser.add_subparsers(dest="command", help="运行模式")

    # 模式1: 启动服务器
    server_parser = subparsers.add_parser("server", help="启动游戏服务器")
    server_parser.add_argument("--host", default="0.0.0.0")
    server_parser.add_argument("--port", type=int, default=8000)

    # 模式2: 启动Agent
    agent_parser = subparsers.add_parser("agent", help="启动LLM Agent")
    agent_parser.add_argument("--name", required=True, help="玩家名称")
    agent_parser.add_argument("--server", default="http://localhost:8000", help="游戏服务器地址")
    agent_parser.add_argument("--provider", default="ollama", help="LLM提供商")
    agent_parser.add_argument("--model", default="llama3.1:8b", help="LLM模型")
    agent_parser.add_argument("--api-url", default=None, help="LLM API地址")
    agent_parser.add_argument("--api-key", default=None, help="LLM API密钥")

    # 模式3: 本地运行
    local_parser = subparsers.add_parser("local", help="本地一体化运行")
    local_parser.add_argument("--preset", default="2player",
                              choices=["2player", "llm_vs_random", "multi", "qwen3"],
                              help="预设配置")
    local_parser.add_argument("--players", type=int, default=None, help="玩家数（覆盖预设）")
    local_parser.add_argument("--hands", type=int, default=10, help="总手数")
    local_parser.add_argument("--provider", default="ollama", help="LLM提供商")
    local_parser.add_argument("--model", default="llama3.1:8b", help="LLM模型名称或路径")
    local_parser.add_argument("--api-url", default=None, help="LLM API地址")
    local_parser.add_argument("--api-key", default=None, help="LLM API密钥")
    local_parser.add_argument("--seed", type=int, default=42, help="随机种子")
    local_parser.add_argument("--tp", type=int, default=2, help="vLLM tensor parallel size")
    local_parser.add_argument("--gpu-util", type=float, default=0.9, help="vLLM GPU显存利用率")
    local_parser.add_argument("--max-model-len", type=int, default=4096, help="vLLM最大序列长度")

    args = parser.parse_args()

    setup_logging()

    if args.command == "server":
        config = GameConfig(server=ServerConfig(host=args.host, port=args.port))
        run_server(config)

    elif args.command == "agent":
        api_url = args.api_url
        if api_url is None:
            if args.provider == "ollama":
                api_url = "http://localhost:11434/api/chat"
            elif args.provider == "openai":
                api_url = "https://api.openai.com/v1/chat/completions"

        llm_config = LLMConfig(
            provider=args.provider,
            model=args.model,
            api_url=api_url,
            api_key=args.api_key,
        )
        run_agent(args.name, args.server, llm_config)

    elif args.command == "local":
        # 构建LLM配置
        api_url = args.api_url
        if api_url is None:
            if args.provider == "ollama":
                api_url = "http://localhost:11434/api/chat"
            elif args.provider == "openai":
                api_url = "https://api.openai.com/v1/chat/completions"
            elif args.provider == "vllm":
                api_url = ""  # vllm本地调用不需要URL

        llm_cfg = LLMConfig(
            provider=args.provider,
            model=args.model,
            api_url=api_url or "",
            api_key=args.api_key,
            tensor_parallel_size=args.tp,
            gpu_memory_utilization=args.gpu_util,
            max_model_len=args.max_model_len,
        )

        if args.preset == "qwen3":
            n_players = args.players if args.players else 6
            config = GameConfig.qwen3_32b_game(
                n=n_players,
                num_hands=args.hands,
                tensor_parallel_size=args.tp,
                model_path=args.model if args.provider == "vllm" else
                    "/research/d7/gds/yhhan25/.cache/modelscope/hub/models/Qwen/Qwen3-32B",
            )
        elif args.preset == "2player":
            config = GameConfig.default_2player()
        elif args.preset == "llm_vs_random":
            config = GameConfig.llm_vs_random()
        else:
            n_players = args.players if args.players else 4
            config = GameConfig.multi_player(n=n_players)

        # 覆盖配置
        config.num_hands = args.hands
        config.seed = args.seed
        if args.players and args.preset != "qwen3":
            # 动态调整玩家数
            player_names = ["Alice", "Bob", "Charlie", "Diana", "Eve", "Frank",
                            "Grace", "Hank", "Ivy", "Jack"]
            config.players = [
                PlayerConfig(
                    name=player_names[i] if i < len(player_names) else f"Player_{i+1}",
                    chips=1000,
                    agent_type="llm",
                    llm_config=llm_cfg,
                )
                for i in range(args.players)
            ]
        else:
            for pc in config.players:
                if pc.agent_type == "llm":
                    pc.llm_config = llm_cfg

        run_local(config)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
