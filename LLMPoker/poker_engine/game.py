"""
PokerGame - 德州扑克游戏主逻辑
管理整个游戏流程：发牌、下注轮次、摊牌、分配底池
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional, Dict, Tuple, Any

from .card import Card, Deck
from .evaluator import HandEvaluator, HandRank
from .player import Player

logger = logging.getLogger(__name__)


class GamePhase(Enum):
    """游戏阶段"""
    WAITING = auto()    # 等待开始
    PREFLOP = auto()    # 翻牌前
    FLOP = auto()       # 翻牌
    TURN = auto()       # 转牌
    RIVER = auto()      # 河牌
    SHOWDOWN = auto()   # 摊牌
    FINISHED = auto()   # 结束


class ActionType(Enum):
    """动作类型"""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"


@dataclass
class Action:
    """玩家动作"""
    player_name: str
    action_type: ActionType
    amount: int = 0

    def to_dict(self) -> dict:
        return {
            "player": self.player_name,
            "action": self.action_type.value,
            "amount": self.amount,
        }

    def __str__(self) -> str:
        if self.action_type in (ActionType.RAISE, ActionType.ALL_IN):
            return f"{self.player_name}: {self.action_type.value} {self.amount}"
        return f"{self.player_name}: {self.action_type.value}"


class PokerGame:
    """
    无限注德州扑克游戏引擎 (No-Limit Texas Hold'em)
    """

    def __init__(
        self,
        players: List[Player],
        small_blind: int = 5,
        big_blind: int = 10,
        seed: Optional[int] = None,
    ):
        if len(players) < 2:
            raise ValueError("Need at least 2 players")
        if len(players) > 10:
            raise ValueError("Maximum 10 players")

        self.players = players
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.seed = seed

        self.deck = Deck()
        self.community_cards: List[Card] = []
        self.pot: int = 0
        self.side_pots: List[Dict] = []  # [{amount, eligible_players}]
        self.phase: GamePhase = GamePhase.WAITING
        self.current_bet: int = 0
        self.min_raise: int = big_blind
        self.dealer_idx: int = 0
        self.current_player_idx: int = 0
        self.action_history: List[Action] = []
        self.hand_number: int = 0
        self.hand_results: List[Dict] = []

    # =========================================================
    #  游戏流程控制
    # =========================================================

    def start_new_hand(self):
        """开始新一手牌"""
        self.hand_number += 1
        logger.info(f"\n{'='*60}")
        logger.info(f"Hand #{self.hand_number}")
        logger.info(f"{'='*60}")

        # 移除没有筹码的玩家
        self.players = [p for p in self.players if p.chips > 0]
        if len(self.players) < 2:
            logger.info("Not enough players to continue.")
            self.phase = GamePhase.FINISHED
            return

        # 重置状态
        self.deck = Deck()
        self.deck.shuffle(self.seed)
        if self.seed is not None:
            self.seed += 1  # 每手使用不同种子

        self.community_cards = []
        self.pot = 0
        self.side_pots = []
        self.current_bet = 0
        self.min_raise = self.big_blind
        self.action_history = []

        for p in self.players:
            p.reset_for_new_hand()

        # 移动庄家位
        self.dealer_idx = self.dealer_idx % len(self.players)

        # 发手牌
        self._deal_hole_cards()

        # 收盲注
        self._post_blinds()

        # 进入翻牌前
        self.phase = GamePhase.PREFLOP
        self._set_first_actor_preflop()

        logger.info(f"Dealer: {self.players[self.dealer_idx].name}")
        logger.info(f"Community: (none yet)")
        for p in self.players:
            logger.info(f"  {p}")

    def _deal_hole_cards(self):
        """给每个玩家发2张手牌"""
        for _ in range(2):
            for p in self.players:
                p.receive_cards(self.deck.deal(1))

    def _post_blinds(self):
        """收取大小盲注"""
        n = len(self.players)
        if n == 2:
            # Heads-up: 庄家是小盲
            sb_idx = self.dealer_idx
            bb_idx = (self.dealer_idx + 1) % n
        else:
            sb_idx = (self.dealer_idx + 1) % n
            bb_idx = (self.dealer_idx + 2) % n

        sb_player = self.players[sb_idx]
        bb_player = self.players[bb_idx]

        sb_actual = sb_player.place_bet(self.small_blind)
        bb_actual = bb_player.place_bet(self.big_blind)

        self.pot += sb_actual + bb_actual
        self.current_bet = self.big_blind

        logger.info(f"{sb_player.name} posts small blind: {sb_actual}")
        logger.info(f"{bb_player.name} posts big blind: {bb_actual}")

        self.action_history.append(
            Action(sb_player.name, ActionType.RAISE, sb_actual))
        self.action_history.append(
            Action(bb_player.name, ActionType.RAISE, bb_actual))

    def _set_first_actor_preflop(self):
        """设置翻牌前第一个行动的玩家（大盲后面）"""
        n = len(self.players)
        if n == 2:
            # Heads-up: 庄家（小盲）先行动
            self.current_player_idx = self.dealer_idx
        else:
            self.current_player_idx = (self.dealer_idx + 3) % n
        # 跳过非活跃玩家
        self._skip_inactive()

    def _set_first_actor_postflop(self):
        """设置翻牌后第一个行动的玩家（庄家后面，即小盲位）"""
        n = len(self.players)
        idx = (self.dealer_idx + 1) % n
        self.current_player_idx = idx
        self._skip_inactive()

    def _skip_inactive(self):
        """跳过已弃牌或已all-in的玩家"""
        n = len(self.players)
        for _ in range(n):
            p = self.players[self.current_player_idx]
            if p.is_active and not p.is_all_in:
                return
            self.current_player_idx = (self.current_player_idx + 1) % n

    # =========================================================
    #  获取游戏状态（供外部/API调用）
    # =========================================================

    def get_current_player(self) -> Optional[Player]:
        """获取当前应该行动的玩家"""
        if self.phase in (GamePhase.WAITING, GamePhase.SHOWDOWN, GamePhase.FINISHED):
            return None
        return self.players[self.current_player_idx]

    def get_valid_actions(self) -> List[ActionType]:
        """获取当前玩家可执行的合法动作"""
        player = self.get_current_player()
        if player is None:
            return []

        actions = [ActionType.FOLD]
        call_amount = self.current_bet - player.current_bet

        if call_amount <= 0:
            actions.append(ActionType.CHECK)
        else:
            actions.append(ActionType.CALL)

        if player.chips > call_amount:
            actions.append(ActionType.RAISE)

        actions.append(ActionType.ALL_IN)
        return actions

    def get_game_state(self, player_name: Optional[str] = None) -> Dict[str, Any]:
        """
        获取当前游戏状态
        player_name: 如果指定，则只显示该玩家的手牌
        """
        players_info = []
        for p in self.players:
            hide = (player_name is not None and p.name != player_name)
            players_info.append(p.to_dict(hide_hand=hide))

        current_player = self.get_current_player()

        state = {
            "hand_number": self.hand_number,
            "phase": self.phase.name,
            "community_cards": [str(c) for c in self.community_cards],
            "pot": self.pot,
            "current_bet": self.current_bet,
            "min_raise": self.min_raise,
            "players": players_info,
            "current_player": current_player.name if current_player else None,
            "valid_actions": [a.value for a in self.get_valid_actions()],
            "dealer": self.players[self.dealer_idx].name,
            "action_history": [a.to_dict() for a in self.action_history],
        }

        # 如果请求特定玩家的视角，添加额外信息
        if player_name and current_player and current_player.name == player_name:
            call_amount = self.current_bet - current_player.current_bet
            state["call_amount"] = max(0, call_amount)
            state["your_chips"] = current_player.chips
            state["your_hand"] = [str(c) for c in current_player.hand]

        return state

    # =========================================================
    #  执行动作
    # =========================================================

    def execute_action(self, action: Action) -> Dict[str, Any]:
        """
        执行玩家动作
        返回动作结果
        """
        player = self.get_current_player()
        if player is None:
            return {"error": "No active player", "success": False}

        if player.name != action.player_name:
            return {"error": f"Not {action.player_name}'s turn, expected {player.name}",
                    "success": False}

        result = {"success": True, "action": action.to_dict()}

        if action.action_type == ActionType.FOLD:
            player.fold()
            logger.info(f"  {player.name} folds")

        elif action.action_type == ActionType.CHECK:
            if self.current_bet > player.current_bet:
                return {"error": "Cannot check, must call or raise", "success": False}
            logger.info(f"  {player.name} checks")

        elif action.action_type == ActionType.CALL:
            call_amount = self.current_bet - player.current_bet
            if call_amount <= 0:
                return {"error": "Nothing to call, use check", "success": False}
            actual = player.place_bet(call_amount)
            self.pot += actual
            result["amount"] = actual
            logger.info(f"  {player.name} calls {actual}")

        elif action.action_type == ActionType.RAISE:
            call_amount = self.current_bet - player.current_bet
            total_amount = action.amount
            if total_amount < call_amount + self.min_raise and total_amount < player.chips:
                # 允许小于min_raise的all-in
                return {"error": f"Raise must be at least {call_amount + self.min_raise}",
                        "success": False}
            actual = player.place_bet(total_amount)
            self.pot += actual
            raise_size = player.current_bet - self.current_bet
            if raise_size > 0:
                self.min_raise = max(self.min_raise, raise_size)
            self.current_bet = player.current_bet
            result["amount"] = actual
            logger.info(f"  {player.name} raises to {self.current_bet} (bet {actual})")

        elif action.action_type == ActionType.ALL_IN:
            actual = player.place_bet(player.chips)
            self.pot += actual
            if player.current_bet > self.current_bet:
                raise_size = player.current_bet - self.current_bet
                self.min_raise = max(self.min_raise, raise_size)
                self.current_bet = player.current_bet
            result["amount"] = actual
            logger.info(f"  {player.name} goes all-in with {actual}")

        self.action_history.append(action)

        # 检查是否本轮结束
        advance_result = self._advance_game()
        result.update(advance_result)
        return result

    def _advance_game(self) -> Dict[str, Any]:
        """推进游戏：移至下一个玩家或下一阶段"""
        result = {}

        # 检查是否只剩一个活跃玩家
        active_players = [p for p in self.players if p.is_active]
        if len(active_players) == 1:
            winner = active_players[0]
            winner.chips += self.pot
            result["winner"] = winner.name
            result["pot_won"] = self.pot
            self.phase = GamePhase.FINISHED
            logger.info(f"\n  {winner.name} wins {self.pot} (all others folded)")
            self._record_result([{"player": winner.name, "won": self.pot}])
            self.dealer_idx = (self.dealer_idx + 1) % len(self.players)
            return result

        # 移至下一个可行动的玩家
        self._move_to_next_player()

        # 检查本轮是否结束
        if self._is_betting_round_complete():
            result.update(self._advance_phase())

        return result

    def _move_to_next_player(self):
        """移动到下一个可行动的玩家"""
        n = len(self.players)
        for _ in range(n):
            self.current_player_idx = (self.current_player_idx + 1) % n
            p = self.players[self.current_player_idx]
            if p.is_active and not p.is_all_in:
                return
        # 所有人都all-in或弃牌

    def _is_betting_round_complete(self) -> bool:
        """检查当前下注轮是否完成"""
        active_can_act = [
            p for p in self.players
            if p.is_active and not p.is_all_in
        ]

        if not active_can_act:
            return True

        # 所有可行动的玩家下注金额相同
        return all(p.current_bet == self.current_bet for p in active_can_act)

    def _advance_phase(self) -> Dict[str, Any]:
        """推进到下一个阶段"""
        result = {}

        # 重置每轮下注
        for p in self.players:
            p.reset_current_bet()
        self.current_bet = 0
        self.min_raise = self.big_blind

        active_players = [p for p in self.players if p.is_active]
        active_can_act = [p for p in active_players if not p.is_all_in]

        if self.phase == GamePhase.PREFLOP:
            self.phase = GamePhase.FLOP
            # Burn one, deal three
            self.deck.deal(1)  # burn
            self.community_cards.extend(self.deck.deal(3))
            logger.info(f"\n--- FLOP: {' '.join(str(c) for c in self.community_cards)} ---")
            result["new_cards"] = [str(c) for c in self.community_cards[:3]]

        elif self.phase == GamePhase.FLOP:
            self.phase = GamePhase.TURN
            self.deck.deal(1)  # burn
            turn_card = self.deck.deal_one()
            self.community_cards.append(turn_card)
            logger.info(f"\n--- TURN: {' '.join(str(c) for c in self.community_cards)} ---")
            result["new_cards"] = [str(turn_card)]

        elif self.phase == GamePhase.TURN:
            self.phase = GamePhase.RIVER
            self.deck.deal(1)  # burn
            river_card = self.deck.deal_one()
            self.community_cards.append(river_card)
            logger.info(f"\n--- RIVER: {' '.join(str(c) for c in self.community_cards)} ---")
            result["new_cards"] = [str(river_card)]

        elif self.phase == GamePhase.RIVER:
            self.phase = GamePhase.SHOWDOWN
            result.update(self._showdown())
            return result

        # 如果只有一个人能行动（其他都all-in），直接快进
        if len(active_can_act) <= 1:
            result.update(self._advance_phase())
            return result

        self._set_first_actor_postflop()
        result["phase"] = self.phase.name
        return result

    # =========================================================
    #  摊牌与分池
    # =========================================================

    def _showdown(self) -> Dict[str, Any]:
        """摊牌，计算赢家并分配底池"""
        active_players = [p for p in self.players if p.is_active]

        logger.info(f"\n{'='*40}")
        logger.info("SHOWDOWN")
        logger.info(f"Community: {' '.join(str(c) for c in self.community_cards)}")

        # 计算每个玩家的最佳牌力
        evaluations = []
        for p in active_players:
            all_cards = p.hand + self.community_cards
            hand_rank, tiebreakers = HandEvaluator.evaluate(all_cards)
            evaluations.append({
                "player": p,
                "hand_rank": hand_rank,
                "tiebreakers": tiebreakers,
                "eval_tuple": (hand_rank, tiebreakers),
            })
            logger.info(f"  {p.name}: {' '.join(str(c) for c in p.hand)} -> {hand_rank}")

        # 按牌力排序（从高到低）
        evaluations.sort(key=lambda x: x["eval_tuple"], reverse=True)

        # 简单分池（不考虑复杂的side pot情况）
        winners = self._determine_winners(evaluations)
        results = self._distribute_pot(winners, evaluations)

        self.phase = GamePhase.FINISHED
        self._record_result(results)
        self.dealer_idx = (self.dealer_idx + 1) % len(self.players)

        return {
            "showdown": True,
            "results": results,
            "community_cards": [str(c) for c in self.community_cards],
        }

    def _determine_winners(self, evaluations: List[Dict]) -> List[Dict]:
        """确定赢家（可能有多个平局）"""
        if not evaluations:
            return []

        best_eval = evaluations[0]["eval_tuple"]
        winners = [e for e in evaluations if e["eval_tuple"] == best_eval]
        return winners

    def _distribute_pot(self, winners: List[Dict], all_evals: List[Dict]) -> List[Dict]:
        """分配底池"""
        results = []

        if not winners:
            return results

        # 简化版：均分给所有赢家
        share = self.pot // len(winners)
        remainder = self.pot % len(winners)

        for i, w in enumerate(winners):
            won_amount = share + (1 if i < remainder else 0)
            w["player"].chips += won_amount
            results.append({
                "player": w["player"].name,
                "won": won_amount,
                "hand": str(w["hand_rank"]),
                "cards": [str(c) for c in w["player"].hand],
            })
            logger.info(f"  {w['player'].name} wins {won_amount} with {w['hand_rank']}")

        return results

    def _record_result(self, results: List[Dict]):
        """记录手牌结果"""
        self.hand_results.append({
            "hand_number": self.hand_number,
            "results": results,
            "community_cards": [str(c) for c in self.community_cards],
        })

    # =========================================================
    #  工具方法
    # =========================================================

    def is_hand_over(self) -> bool:
        """当前手牌是否结束"""
        return self.phase in (GamePhase.FINISHED, GamePhase.SHOWDOWN)

    def get_active_player_count(self) -> int:
        """获取活跃玩家数量"""
        return sum(1 for p in self.players if p.is_active)

    def get_player_by_name(self, name: str) -> Optional[Player]:
        """根据名字获取玩家"""
        for p in self.players:
            if p.name == name:
                return p
        return None

    def summary(self) -> str:
        """获取当前局面的文字摘要"""
        lines = [
            f"=== Hand #{self.hand_number} | Phase: {self.phase.name} | Pot: {self.pot} ===",
            f"Community: {' '.join(str(c) for c in self.community_cards) if self.community_cards else '(none)'}",
            f"Current bet: {self.current_bet}",
            "Players:",
        ]
        for p in self.players:
            lines.append(f"  {p}")
        current = self.get_current_player()
        if current:
            lines.append(f"Waiting for: {current.name}")
            lines.append(f"Valid actions: {[a.value for a in self.get_valid_actions()]}")
        return "\n".join(lines)
