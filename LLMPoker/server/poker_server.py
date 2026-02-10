"""
Poker Game Server - FastAPI 游戏服务器
提供REST API供LLM Agent和人类玩家交互
职责：管理游戏生命周期，提供游戏状态查询和动作提交接口
"""

from __future__ import annotations
import logging
import asyncio
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from poker_engine.card import Card
from poker_engine.player import Player
from poker_engine.game import PokerGame, GamePhase, Action, ActionType

logger = logging.getLogger(__name__)


# =========================================================
#  请求/响应模型
# =========================================================

class CreateGameRequest(BaseModel):
    """创建游戏请求"""
    players: List[Dict[str, Any]]  # [{"name": "LLM_1", "chips": 1000}, ...]
    small_blind: int = 5
    big_blind: int = 10
    seed: Optional[int] = None

class ActionRequest(BaseModel):
    """玩家动作请求"""
    player_name: str
    action: str  # fold, check, call, raise, all_in
    amount: int = 0

class StartHandRequest(BaseModel):
    """开始新一手牌"""
    pass

class GameResponse(BaseModel):
    """通用响应"""
    success: bool
    message: str = ""
    data: Optional[Dict[str, Any]] = None


# =========================================================
#  游戏管理器
# =========================================================

class GameManager:
    """管理多个游戏实例"""

    def __init__(self):
        self.games: Dict[str, PokerGame] = {}
        self.default_game: Optional[PokerGame] = None
        self._lock = asyncio.Lock()

    def create_game(
        self,
        game_id: str,
        players: List[Player],
        small_blind: int = 5,
        big_blind: int = 10,
        seed: Optional[int] = None,
    ) -> PokerGame:
        game = PokerGame(
            players=players,
            small_blind=small_blind,
            big_blind=big_blind,
            seed=seed,
        )
        self.games[game_id] = game
        if self.default_game is None:
            self.default_game = game
        return game

    def get_game(self, game_id: Optional[str] = None) -> PokerGame:
        if game_id and game_id in self.games:
            return self.games[game_id]
        if self.default_game:
            return self.default_game
        raise HTTPException(status_code=404, detail="No active game found")


game_manager = GameManager()


# =========================================================
#  FastAPI 应用
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Poker Game Server starting...")
    yield
    logger.info("Poker Game Server shutting down...")

app = FastAPI(
    title="Texas Hold'em Poker Server",
    description="德州扑克游戏服务器 - 提供REST API供LLM Agent和人类玩家交互",
    version="1.0.0",
    lifespan=lifespan,
)


# =========================================================
#  API 端点
# =========================================================

@app.get("/")
async def root():
    return {"message": "Texas Hold'em Poker Server", "status": "running"}


@app.post("/game/create", response_model=GameResponse)
async def create_game(req: CreateGameRequest):
    """创建新游戏"""
    try:
        players = []
        for p_info in req.players:
            player = Player(
                name=p_info["name"],
                chips=p_info.get("chips", 1000),
                agent_type=p_info.get("agent_type", "llm"),
            )
            players.append(player)

        game_id = f"game_{len(game_manager.games) + 1}"
        game = game_manager.create_game(
            game_id=game_id,
            players=players,
            small_blind=req.small_blind,
            big_blind=req.big_blind,
            seed=req.seed,
        )

        return GameResponse(
            success=True,
            message=f"Game '{game_id}' created with {len(players)} players",
            data={
                "game_id": game_id,
                "players": [p.name for p in players],
                "small_blind": req.small_blind,
                "big_blind": req.big_blind,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/game/start", response_model=GameResponse)
async def start_hand(game_id: Optional[str] = None):
    """开始新一手牌"""
    try:
        game = game_manager.get_game(game_id)
        game.start_new_hand()
        return GameResponse(
            success=True,
            message=f"Hand #{game.hand_number} started",
            data=game.get_game_state(),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/game/state")
async def get_game_state(
    player_name: Optional[str] = None,
    game_id: Optional[str] = None,
):
    """获取当前游戏状态"""
    try:
        game = game_manager.get_game(game_id)
        return game.get_game_state(player_name=player_name)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/game/action", response_model=GameResponse)
async def submit_action(req: ActionRequest, game_id: Optional[str] = None):
    """提交玩家动作"""
    try:
        game = game_manager.get_game(game_id)

        # 解析动作类型
        action_map = {
            "fold": ActionType.FOLD,
            "check": ActionType.CHECK,
            "call": ActionType.CALL,
            "raise": ActionType.RAISE,
            "all_in": ActionType.ALL_IN,
        }

        action_type = action_map.get(req.action.lower())
        if action_type is None:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid action: {req.action}. Valid: {list(action_map.keys())}",
            )

        action = Action(
            player_name=req.player_name,
            action_type=action_type,
            amount=req.amount,
        )

        result = game.execute_action(action)

        if not result.get("success", False):
            raise HTTPException(status_code=400, detail=result.get("error", "Unknown error"))

        return GameResponse(
            success=True,
            message=f"{req.player_name}: {req.action}",
            data=result,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/game/summary")
async def get_summary(game_id: Optional[str] = None):
    """获取游戏摘要"""
    try:
        game = game_manager.get_game(game_id)
        return {"summary": game.summary()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/game/history")
async def get_history(game_id: Optional[str] = None):
    """获取手牌历史"""
    try:
        game = game_manager.get_game(game_id)
        return {
            "hand_results": game.hand_results,
            "total_hands": game.hand_number,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/game/players")
async def get_players(game_id: Optional[str] = None):
    """获取所有玩家信息"""
    try:
        game = game_manager.get_game(game_id)
        return {
            "players": [
                {
                    "name": p.name,
                    "chips": p.chips,
                    "is_active": p.is_active,
                    "agent_type": p.agent_type,
                }
                for p in game.players
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# =========================================================
#  启动
# =========================================================

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    uvicorn.run(app, host="0.0.0.0", port=8000)
