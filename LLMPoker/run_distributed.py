"""
run_distributed.py - 分离部署启动脚本
启动服务器后，自动创建游戏并启动多个LLM Agent
"""

import argparse
import logging
import subprocess
import sys
import os
import time
import requests
import signal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import LLMConfig

logger = logging.getLogger(__name__)


def wait_for_server(url: str, timeout: int = 30) -> bool:
    """等待服务器启动"""
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = requests.get(f"{url}/", timeout=2)
            if resp.status_code == 200:
                return True
        except requests.exceptions.ConnectionError:
            pass
        time.sleep(1)
    return False


def create_game_on_server(server_url: str, players: list, small_blind: int, big_blind: int):
    """在服务器上创建游戏"""
    resp = requests.post(f"{server_url}/game/create", json={
        "players": players,
        "small_blind": small_blind,
        "big_blind": big_blind,
    })
    resp.raise_for_status()
    data = resp.json()
    print(f"  ✅ 游戏创建成功: {data}")
    return data


def start_hand_on_server(server_url: str):
    """在服务器上开始新一手牌"""
    resp = requests.post(f"{server_url}/game/start")
    resp.raise_for_status()
    return resp.json()


def main():
    parser = argparse.ArgumentParser(description="分离部署 - 启动服务器和Agent")
    parser.add_argument("--server-port", type=int, default=8000)
    parser.add_argument("--num-players", type=int, default=2)
    parser.add_argument("--num-hands", type=int, default=10)
    parser.add_argument("--provider", default="ollama")
    parser.add_argument("--model", default="llama3.1:8b")
    parser.add_argument("--api-url", default=None)
    parser.add_argument("--api-key", default=None)
    parser.add_argument("--chips", type=int, default=1000)
    parser.add_argument("--small-blind", type=int, default=5)
    parser.add_argument("--big-blind", type=int, default=10)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    server_url = f"http://localhost:{args.server_port}"
    project_dir = os.path.dirname(os.path.abspath(__file__))
    processes = []

    def cleanup(signum=None, frame=None):
        print("\n🛑 正在关闭所有进程...")
        for p in processes:
            try:
                p.terminate()
                p.wait(timeout=5)
            except Exception:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # 1. 启动服务器
        print("=" * 60)
        print("  🚀 Step 1: 启动游戏服务器")
        print("=" * 60)
        server_proc = subprocess.Popen(
            [sys.executable, "main.py", "server", "--port", str(args.server_port)],
            cwd=project_dir,
        )
        processes.append(server_proc)

        print(f"  等待服务器启动 ({server_url})...")
        if not wait_for_server(server_url):
            print("  ❌ 服务器启动超时!")
            cleanup()
            return
        print("  ✅ 服务器已启动!")

        # 2. 创建游戏
        print(f"\n{'='*60}")
        print("  🎴 Step 2: 创建游戏")
        print("=" * 60)

        player_names = [f"LLM_Player_{i+1}" for i in range(args.num_players)]
        players = [{"name": name, "chips": args.chips, "agent_type": "llm"}
                   for name in player_names]
        create_game_on_server(server_url, players, args.small_blind, args.big_blind)

        # 3. 启动Agent进程
        print(f"\n{'='*60}")
        print(f"  🤖 Step 3: 启动 {args.num_players} 个LLM Agent")
        print("=" * 60)

        agent_cmd_base = [
            sys.executable, "main.py", "agent",
            "--server", server_url,
            "--provider", args.provider,
            "--model", args.model,
        ]
        if args.api_url:
            agent_cmd_base.extend(["--api-url", args.api_url])
        if args.api_key:
            agent_cmd_base.extend(["--api-key", args.api_key])

        for name in player_names:
            cmd = agent_cmd_base + ["--name", name]
            proc = subprocess.Popen(cmd, cwd=project_dir)
            processes.append(proc)
            print(f"  ✅ Agent '{name}' 已启动 (PID: {proc.pid})")
            time.sleep(0.5)

        # 4. 逐手开始游戏
        print(f"\n{'='*60}")
        print(f"  🎮 Step 4: 开始 {args.num_hands} 手牌")
        print("=" * 60)

        for hand in range(args.num_hands):
            print(f"\n  --- 开始第 {hand+1}/{args.num_hands} 手牌 ---")
            result = start_hand_on_server(server_url)

            # 等待本手牌结束
            while True:
                time.sleep(2)
                try:
                    state = requests.get(f"{server_url}/game/state").json()
                    if state.get("phase") in ("FINISHED",):
                        break
                except Exception:
                    break

            # 获取结果
            try:
                history = requests.get(f"{server_url}/game/history").json()
                if history.get("hand_results"):
                    last = history["hand_results"][-1]
                    for r in last.get("results", []):
                        print(f"    {r['player']}: 赢得 {r['won']} ({r.get('hand', '')})")
            except Exception:
                pass

            # 获取筹码
            try:
                players_info = requests.get(f"{server_url}/game/players").json()
                print("  筹码:")
                all_eliminated = True
                for p in players_info.get("players", []):
                    print(f"    {p['name']}: {p['chips']}")
                    if p["chips"] > 0:
                        all_eliminated = False
                if all_eliminated or sum(1 for p in players_info.get("players", []) if p["chips"] > 0) < 2:
                    print("\n  🏆 游戏结束!")
                    break
            except Exception:
                pass

        print(f"\n{'='*60}")
        print("  🏁 所有手牌已完成!")
        print("=" * 60)

    finally:
        cleanup()


if __name__ == "__main__":
    main()
