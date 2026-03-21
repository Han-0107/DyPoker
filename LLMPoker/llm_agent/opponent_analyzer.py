"""
OpponentAnalyzer - 对手策略分析 Agent
通过分析对手的历史行动来分类其策略类型，并给出针对性建议。

支持的策略类型:
  1. ABC Player / Balanced (13%)
  2. Selective Value Aggressor (3%)
  3. Tight-Passive / Rock (21%)
  4. Positional Grinder (15%)
  5. Weak-Tight / Passive Recreational (33%)
  6. Loose-Passive / Calling Station (10%)
  7. Early-Position Aggressor (5%)
"""

from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
from enum import Enum

logger = logging.getLogger(__name__)


class StrategyType(Enum):
    """对手策略类型"""
    ABC_BALANCED = "ABC Player / Balanced"
    SELECTIVE_VALUE_AGGRESSOR = "Selective Value Aggressor"
    TIGHT_PASSIVE = "Tight-Passive / Rock"
    POSITIONAL_GRINDER = "Positional Grinder"
    WEAK_TIGHT = "Weak-Tight / Passive Recreational"
    LOOSE_PASSIVE = "Loose-Passive / Calling Station"
    EARLY_POSITION_AGGRESSOR = "Early-Position Aggressor"
    UNKNOWN = "Unknown"


# 针对每种对手策略的反制建议
COUNTER_STRATEGY = {
    StrategyType.ABC_BALANCED: (
        "This opponent plays a balanced, standard strategy with evenly distributed "
        "actions. Counter by mixing in more bluffs in polarized spots and making "
        "thin value bets, since they rarely deviate from standard play."
    ),
    StrategyType.SELECTIVE_VALUE_AGGRESSOR: (
        "This opponent only calls/raises post-flop in high-value situations. "
        "Counter by folding marginal hands to their post-flop aggression, "
        "but bluff more on boards that are unlikely to hit their value range."
    ),
    StrategyType.TIGHT_PASSIVE: (
        "This opponent is very conservative pre-flop and passive post-flop, "
        "preferring checks and calls. Counter by stealing their blinds aggressively, "
        "betting for value with medium-strength hands, and applying pressure on "
        "scary boards since they often fold under pressure."
    ),
    StrategyType.POSITIONAL_GRINDER: (
        "This opponent favors small late-position raises and exploits position. "
        "Counter by 3-betting their late-position opens more frequently, "
        "defending your blinds wider, and check-raising them post-flop to "
        "deny their positional advantage."
    ),
    StrategyType.WEAK_TIGHT: (
        "This opponent mostly checks post-flop and folds under pressure. "
        "Counter by betting aggressively on most boards with any reasonable hand, "
        "including many bluffs. Apply pressure with continuation bets and "
        "multi-barrel bluffs. Steal their blinds frequently."
    ),
    StrategyType.LOOSE_PASSIVE: (
        "This opponent calls frequently but rarely raises, often calling down "
        "with weak hands. Counter by value betting thinner and more frequently, "
        "avoiding bluffs since they call too much. Size your bets larger for "
        "value and never slow-play strong hands."
    ),
    StrategyType.EARLY_POSITION_AGGRESSOR: (
        "This opponent frequently raises from early position to establish "
        "pre-flop dominance. Counter by flatting with strong hands to trap them, "
        "3-betting with premium hands, and playing cautiously against their "
        "early-position raises with marginal holdings."
    ),
    StrategyType.UNKNOWN: (
        "Not enough data to classify this opponent. Play a solid, balanced "
        "strategy and focus on gathering more information about their tendencies."
    ),
}


@dataclass
class OpponentStats:
    """记录单个对手的行为统计"""
    # 总手数
    total_hands: int = 0

    # Pre-flop 统计
    preflop_fold: int = 0
    preflop_call: int = 0
    preflop_raise: int = 0
    preflop_all_in: int = 0

    # Post-flop 统计 (flop + turn + river)
    postflop_fold: int = 0
    postflop_check: int = 0
    postflop_call: int = 0
    postflop_raise: int = 0
    postflop_all_in: int = 0

    # 位置相关
    early_position_raises: int = 0   # UTG/HJ 位置的 raise
    late_position_raises: int = 0    # CO/BTN 位置的 raise
    early_position_actions: int = 0  # 从早期位置的总行动数
    late_position_actions: int = 0   # 从晚期位置的总行动数

    # raise 尺度
    small_raises: int = 0    # raise < 3x BB
    medium_raises: int = 0   # 3x BB <= raise < 6x BB
    large_raises: int = 0    # raise >= 6x BB

    @property
    def preflop_total(self) -> int:
        return self.preflop_fold + self.preflop_call + self.preflop_raise + self.preflop_all_in

    @property
    def postflop_total(self) -> int:
        return (self.postflop_fold + self.postflop_check +
                self.postflop_call + self.postflop_raise + self.postflop_all_in)

    @property
    def vpip(self) -> float:
        """Voluntarily Put In Pot - 自愿投入筹码的比例 (排除fold)"""
        if self.preflop_total == 0:
            return 0.0
        return (self.preflop_call + self.preflop_raise + self.preflop_all_in) / self.preflop_total

    @property
    def pfr(self) -> float:
        """Pre-Flop Raise - 翻前加注比例"""
        if self.preflop_total == 0:
            return 0.0
        return (self.preflop_raise + self.preflop_all_in) / self.preflop_total

    @property
    def postflop_aggression(self) -> float:
        """翻后激进度 = (raise + all_in) / (check + call + raise + all_in)"""
        denom = self.postflop_check + self.postflop_call + self.postflop_raise + self.postflop_all_in
        if denom == 0:
            return 0.0
        return (self.postflop_raise + self.postflop_all_in) / denom

    @property
    def postflop_passivity(self) -> float:
        """翻后被动度 = (check + call) / total postflop actions"""
        if self.postflop_total == 0:
            return 0.0
        return (self.postflop_check + self.postflop_call) / self.postflop_total

    @property
    def postflop_check_ratio(self) -> float:
        """翻后 check 比例"""
        if self.postflop_total == 0:
            return 0.0
        return self.postflop_check / self.postflop_total

    @property
    def early_position_raise_rate(self) -> float:
        """早期位置加注率"""
        if self.early_position_actions == 0:
            return 0.0
        return self.early_position_raises / self.early_position_actions

    @property
    def late_position_raise_rate(self) -> float:
        """晚期位置加注率"""
        if self.late_position_actions == 0:
            return 0.0
        return self.late_position_raises / self.late_position_actions

    @property
    def small_raise_ratio(self) -> float:
        """小额加注的比例"""
        total_raises = self.small_raises + self.medium_raises + self.large_raises
        if total_raises == 0:
            return 0.0
        return self.small_raises / total_raises


class OpponentAnalyzer:
    """
    对手策略分析器。
    在游戏过程中持续收集对手的行为统计，并用 LLM 分析对手策略类型。
    """

    # 早期位置和晚期位置定义
    EARLY_POSITIONS = {"UTG", "HJ"}
    LATE_POSITIONS = {"CO", "BTN"}

    def __init__(self, my_name: str):
        self.my_name = my_name
        # opponent_name -> OpponentStats
        self.opponent_stats: Dict[str, OpponentStats] = {}
        # 缓存对手策略分类结果 {opponent_name: (StrategyType, confidence)}
        self._strategy_cache: Dict[str, tuple] = {}
        # 标记是否需要重新分析
        self._dirty: Dict[str, bool] = {}

    def _ensure_stats(self, player_name: str) -> OpponentStats:
        """确保对手统计对象存在"""
        if player_name not in self.opponent_stats:
            self.opponent_stats[player_name] = OpponentStats()
            self._dirty[player_name] = True
        return self.opponent_stats[player_name]

    def record_hand_actions(
        self,
        action_history: List[Dict[str, Any]],
        positions: Dict[str, str],
        big_blind: int = 10,
    ):
        """
        记录一手牌中所有对手的行动。
        应在每手结束后调用。

        Args:
            action_history: 该手牌的行动历史列表 [{player, action, amount}, ...]
            positions: 玩家位置映射 {player_name: position_name}
            big_blind: 大盲注额度
        """
        # 跟踪当前街
        current_street = "preflop"

        # 记录参与这手牌的对手
        participants = set()
        for h in action_history:
            p_name = h.get("player", "")
            if p_name and p_name != self.my_name:
                participants.add(p_name)

        # 为参与的对手增加手数计数
        for p_name in participants:
            stats = self._ensure_stats(p_name)
            stats.total_hands += 1
            self._dirty[p_name] = True

        for h in action_history:
            action = h.get("action", "")
            p_name = h.get("player", "")
            amount = h.get("amount", 0)

            # 跳过非对手的行为
            if not p_name or p_name == self.my_name:
                continue

            # 阶段标记
            if action == "phase":
                phase_name = h.get("phase", "").lower()
                if phase_name in ("flop", "turn", "river"):
                    current_street = phase_name
                continue

            # 跳过盲注
            if action == "blind":
                continue

            stats = self._ensure_stats(p_name)
            position = positions.get(p_name, "")

            # 位置统计
            if position in self.EARLY_POSITIONS:
                stats.early_position_actions += 1
            elif position in self.LATE_POSITIONS:
                stats.late_position_actions += 1

            if current_street == "preflop":
                if action == "fold":
                    stats.preflop_fold += 1
                elif action == "call":
                    stats.preflop_call += 1
                elif action == "raise":
                    stats.preflop_raise += 1
                    # 位置加注统计
                    if position in self.EARLY_POSITIONS:
                        stats.early_position_raises += 1
                    elif position in self.LATE_POSITIONS:
                        stats.late_position_raises += 1
                    # 加注尺度
                    if amount > 0 and big_blind > 0:
                        ratio = amount / big_blind
                        if ratio < 3:
                            stats.small_raises += 1
                        elif ratio < 6:
                            stats.medium_raises += 1
                        else:
                            stats.large_raises += 1
                elif action == "all_in":
                    stats.preflop_all_in += 1
            else:
                # post-flop
                if action == "fold":
                    stats.postflop_fold += 1
                elif action == "check":
                    stats.postflop_check += 1
                elif action == "call":
                    stats.postflop_call += 1
                elif action == "raise":
                    stats.postflop_raise += 1
                elif action == "all_in":
                    stats.postflop_all_in += 1

    def classify_opponent(self, opponent_name: str) -> tuple:
        """
        基于统计数据对对手进行规则分类。
        返回: (StrategyType, confidence: float)
        """
        stats = self.opponent_stats.get(opponent_name)
        if stats is None or stats.total_hands < 3:
            return (StrategyType.UNKNOWN, 0.0)

        # 使用缓存（如果数据未更新）
        if not self._dirty.get(opponent_name, True) and opponent_name in self._strategy_cache:
            return self._strategy_cache[opponent_name]

        # ── 计算关键指标 ──
        vpip = stats.vpip
        pfr = stats.pfr
        post_agg = stats.postflop_aggression
        post_check_ratio = stats.postflop_check_ratio
        post_passivity = stats.postflop_passivity
        ep_raise_rate = stats.early_position_raise_rate
        lp_raise_rate = stats.late_position_raise_rate
        small_raise_ratio = stats.small_raise_ratio

        scores: Dict[StrategyType, float] = {st: 0.0 for st in StrategyType if st != StrategyType.UNKNOWN}

        # ── 规则打分 ──

        # 1. Weak-Tight / Passive Recreational (最常见 33%)
        #    特征: 翻后大量 check, 被动, 受压就 fold
        if post_check_ratio > 0.6:
            scores[StrategyType.WEAK_TIGHT] += 3.0
        elif post_check_ratio > 0.4:
            scores[StrategyType.WEAK_TIGHT] += 1.5
        if post_passivity > 0.8:
            scores[StrategyType.WEAK_TIGHT] += 2.0
        if vpip < 0.35:
            scores[StrategyType.WEAK_TIGHT] += 1.0
        if pfr < 0.1:
            scores[StrategyType.WEAK_TIGHT] += 1.0

        # 2. Tight-Passive / Rock (21%)
        #    特征: 翻前保守 (低 VPIP), 翻后被动 (偏好 check/call)
        if vpip < 0.25:
            scores[StrategyType.TIGHT_PASSIVE] += 3.0
        elif vpip < 0.35:
            scores[StrategyType.TIGHT_PASSIVE] += 1.5
        if pfr < 0.1:
            scores[StrategyType.TIGHT_PASSIVE] += 2.0
        elif pfr < 0.2:
            scores[StrategyType.TIGHT_PASSIVE] += 1.0
        if post_passivity > 0.7:
            scores[StrategyType.TIGHT_PASSIVE] += 1.5

        # 3. Positional Grinder (15%)
        #    特征: 偏好晚位小加注, 利用位置获取增量收益
        if lp_raise_rate > 0.4 and small_raise_ratio > 0.5:
            scores[StrategyType.POSITIONAL_GRINDER] += 3.0
        elif lp_raise_rate > 0.3:
            scores[StrategyType.POSITIONAL_GRINDER] += 1.5
        if lp_raise_rate > ep_raise_rate * 1.5:
            scores[StrategyType.POSITIONAL_GRINDER] += 2.0
        if small_raise_ratio > 0.6:
            scores[StrategyType.POSITIONAL_GRINDER] += 1.0

        # 4. ABC Player / Balanced (13%)
        #    特征: 行动分布均匀, 没有明显偏好
        if 0.3 <= vpip <= 0.5 and 0.15 <= pfr <= 0.35:
            scores[StrategyType.ABC_BALANCED] += 2.0
        if 0.2 <= post_agg <= 0.5:
            scores[StrategyType.ABC_BALANCED] += 1.5
        # 如果没有极端指标，加分
        if (0.25 <= vpip <= 0.55 and 0.1 <= pfr <= 0.4
                and 0.15 <= post_agg <= 0.55):
            scores[StrategyType.ABC_BALANCED] += 1.5

        # 5. Loose-Passive / Calling Station (10%)
        #    特征: 频繁 call, 很少 raise, 经常用弱牌跟到底
        if vpip > 0.5:
            scores[StrategyType.LOOSE_PASSIVE] += 2.0
        elif vpip > 0.4:
            scores[StrategyType.LOOSE_PASSIVE] += 1.0
        if pfr < 0.15 and vpip > 0.35:
            scores[StrategyType.LOOSE_PASSIVE] += 2.0
        postflop_call_ratio = 0.0
        if stats.postflop_total > 0:
            postflop_call_ratio = stats.postflop_call / stats.postflop_total
        if postflop_call_ratio > 0.5:
            scores[StrategyType.LOOSE_PASSIVE] += 2.5
        elif postflop_call_ratio > 0.35:
            scores[StrategyType.LOOSE_PASSIVE] += 1.0

        # 6. Early-Position Aggressor (5%)
        #    特征: 频繁从早位 raise, 试图建立翻前优势
        if ep_raise_rate > 0.4:
            scores[StrategyType.EARLY_POSITION_AGGRESSOR] += 3.0
        elif ep_raise_rate > 0.25:
            scores[StrategyType.EARLY_POSITION_AGGRESSOR] += 1.5
        if ep_raise_rate > lp_raise_rate:
            scores[StrategyType.EARLY_POSITION_AGGRESSOR] += 2.0
        if pfr > 0.3 and ep_raise_rate > 0.3:
            scores[StrategyType.EARLY_POSITION_AGGRESSOR] += 1.0

        # 7. Selective Value Aggressor (3%)
        #    特征: 翻后仅在高价值情况下 call/raise
        if post_agg > 0.4 and vpip < 0.4:
            scores[StrategyType.SELECTIVE_VALUE_AGGRESSOR] += 2.0
        if stats.postflop_total > 0:
            postflop_engage = (stats.postflop_call + stats.postflop_raise + stats.postflop_all_in)
            postflop_engage_ratio = postflop_engage / stats.postflop_total
            if postflop_engage_ratio < 0.5 and post_agg > 0.3:
                scores[StrategyType.SELECTIVE_VALUE_AGGRESSOR] += 2.0
        if pfr > 0.15 and post_agg > 0.35:
            scores[StrategyType.SELECTIVE_VALUE_AGGRESSOR] += 1.0

        # ── 选择得分最高的类型 ──
        best_type = max(scores, key=scores.get)
        best_score = scores[best_type]

        # 置信度: 基于总手数和得分
        hand_factor = min(1.0, stats.total_hands / 15)  # 15手牌后置信度达到最大
        confidence = min(1.0, (best_score / 8.0) * hand_factor)

        result = (best_type, confidence)
        self._strategy_cache[opponent_name] = result
        self._dirty[opponent_name] = False
        return result

    def get_opponent_analysis_text(
        self,
        opponents: List[str],
        game_state: Dict[str, Any],
    ) -> str:
        """
        为所有对手生成策略分析文本，用于构建 prompt。

        Args:
            opponents: 当前活跃的对手名称列表
            game_state: 当前游戏状态

        Returns:
            str: 对手分析的自然语言描述
        """
        if not opponents:
            return "No opponent data available yet."

        parts = []
        parts.append("=== Opponent Strategy Analysis ===\n")

        for opp_name in opponents:
            strategy_type, confidence = self.classify_opponent(opp_name)
            stats = self.opponent_stats.get(opp_name)

            if stats is None or stats.total_hands < 3:
                parts.append(f"• {opp_name}: Insufficient data "
                             f"({stats.total_hands if stats else 0} hands observed). "
                             f"Play a default balanced strategy against them.")
                continue

            parts.append(f"• {opp_name} (observed {stats.total_hands} hands):")
            parts.append(f"  - Classified as: {strategy_type.value} "
                         f"(confidence: {confidence:.0%})")
            parts.append(f"  - Key stats: VPIP={stats.vpip:.0%}, PFR={stats.pfr:.0%}, "
                         f"Post-flop aggression={stats.postflop_aggression:.0%}")
            parts.append(f"  - Counter strategy: {COUNTER_STRATEGY[strategy_type]}")
            parts.append("")

        return "\n".join(parts)

    def get_stats_summary(self, opponent_name: str) -> Dict[str, Any]:
        """获取对手统计摘要（用于日志/调试）"""
        stats = self.opponent_stats.get(opponent_name)
        if stats is None:
            return {"name": opponent_name, "hands": 0, "type": "Unknown"}

        strategy_type, confidence = self.classify_opponent(opponent_name)
        return {
            "name": opponent_name,
            "hands": stats.total_hands,
            "type": strategy_type.value,
            "confidence": f"{confidence:.0%}",
            "vpip": f"{stats.vpip:.0%}",
            "pfr": f"{stats.pfr:.0%}",
            "postflop_aggression": f"{stats.postflop_aggression:.0%}",
            "postflop_check_ratio": f"{stats.postflop_check_ratio:.0%}",
        }
