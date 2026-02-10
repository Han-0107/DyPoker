"""
HandEvaluator - 德州扑克牌力评估器
判断最佳5张牌组合以及比较大小
"""

from __future__ import annotations
from collections import Counter
from enum import IntEnum
from itertools import combinations
from typing import List, Tuple

from .card import Card, Rank


class HandRank(IntEnum):
    """牌型等级（从低到高）"""
    HIGH_CARD = 0       # 高牌
    ONE_PAIR = 1        # 一对
    TWO_PAIR = 2        # 两对
    THREE_OF_A_KIND = 3 # 三条
    STRAIGHT = 4        # 顺子
    FLUSH = 5           # 同花
    FULL_HOUSE = 6      # 葫芦
    FOUR_OF_A_KIND = 7  # 四条
    STRAIGHT_FLUSH = 8  # 同花顺
    ROYAL_FLUSH = 9     # 皇家同花顺

    def __str__(self) -> str:
        names = {
            0: "高牌 (High Card)",
            1: "一对 (One Pair)",
            2: "两对 (Two Pair)",
            3: "三条 (Three of a Kind)",
            4: "顺子 (Straight)",
            5: "同花 (Flush)",
            6: "葫芦 (Full House)",
            7: "四条 (Four of a Kind)",
            8: "同花顺 (Straight Flush)",
            9: "皇家同花顺 (Royal Flush)",
        }
        return names[self.value]


class HandEvaluator:
    """
    牌力评估器
    返回 (HandRank, tiebreakers) 元组用于比较大小
    tiebreakers 是一个元组，按优先级排列的点数值
    """

    @staticmethod
    def evaluate(cards: List[Card]) -> Tuple[HandRank, Tuple[int, ...]]:
        """
        评估最佳5张牌组合
        cards: 5~7张牌（2张手牌 + 3~5张公共牌）
        返回: (HandRank, tiebreakers)
        """
        if len(cards) < 5:
            raise ValueError(f"Need at least 5 cards, got {len(cards)}")

        best = None
        for combo in combinations(cards, 5):
            result = HandEvaluator._evaluate_five(list(combo))
            if best is None or result > best:
                best = result
        return best

    @staticmethod
    def _evaluate_five(cards: List[Card]) -> Tuple[HandRank, Tuple[int, ...]]:
        """评估恰好5张牌"""
        ranks = sorted([c.rank for c in cards], reverse=True)
        suits = [c.suit for c in cards]
        rank_counts = Counter(ranks)

        is_flush = len(set(suits)) == 1
        is_straight, straight_high = HandEvaluator._check_straight(ranks)

        # 按出现频次分组
        count_groups = sorted(rank_counts.items(), key=lambda x: (x[1], x[0]), reverse=True)
        counts = [c for _, c in count_groups]
        group_ranks = [r for r, _ in count_groups]

        # 皇家同花顺
        if is_flush and is_straight and straight_high == Rank.ACE:
            return (HandRank.ROYAL_FLUSH, (int(Rank.ACE),))

        # 同花顺
        if is_flush and is_straight:
            return (HandRank.STRAIGHT_FLUSH, (straight_high,))

        # 四条
        if counts[0] == 4:
            return (HandRank.FOUR_OF_A_KIND, (int(group_ranks[0]), int(group_ranks[1])))

        # 葫芦
        if counts[0] == 3 and counts[1] == 2:
            return (HandRank.FULL_HOUSE, (int(group_ranks[0]), int(group_ranks[1])))

        # 同花
        if is_flush:
            return (HandRank.FLUSH, tuple(int(r) for r in ranks))

        # 顺子
        if is_straight:
            return (HandRank.STRAIGHT, (straight_high,))

        # 三条
        if counts[0] == 3:
            kickers = sorted([r for r in ranks if r != group_ranks[0]], reverse=True)
            return (HandRank.THREE_OF_A_KIND,
                    (int(group_ranks[0]),) + tuple(int(k) for k in kickers))

        # 两对
        if counts[0] == 2 and counts[1] == 2:
            pair_ranks = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r in ranks if rank_counts[r] == 1][0]
            return (HandRank.TWO_PAIR,
                    (int(pair_ranks[0]), int(pair_ranks[1]), int(kicker)))

        # 一对
        if counts[0] == 2:
            pair_rank = group_ranks[0]
            kickers = sorted([r for r in ranks if r != pair_rank], reverse=True)
            return (HandRank.ONE_PAIR,
                    (int(pair_rank),) + tuple(int(k) for k in kickers))

        # 高牌
        return (HandRank.HIGH_CARD, tuple(int(r) for r in ranks))

    @staticmethod
    def _check_straight(ranks: List[Rank]) -> Tuple[bool, int]:
        """
        检查是否为顺子
        返回: (is_straight, highest_card_value)
        特殊处理 A-2-3-4-5 (wheel)
        """
        unique_ranks = sorted(set(ranks), reverse=True)
        if len(unique_ranks) < 5:
            return False, 0

        # 常规顺子
        if unique_ranks[0] - unique_ranks[4] == 4:
            return True, int(unique_ranks[0])

        # A-2-3-4-5 (Wheel)
        if set(int(r) for r in unique_ranks) == {14, 2, 3, 4, 5}:
            return True, 5  # 5作为最高牌

        return False, 0

    @staticmethod
    def compare_hands(hand1: List[Card], hand2: List[Card]) -> int:
        """
        比较两手牌
        返回: 1 (hand1赢), -1 (hand2赢), 0 (平局)
        """
        eval1 = HandEvaluator.evaluate(hand1)
        eval2 = HandEvaluator.evaluate(hand2)
        if eval1 > eval2:
            return 1
        elif eval1 < eval2:
            return -1
        return 0

    @staticmethod
    def hand_description(cards: List[Card]) -> str:
        """返回牌型的文字描述"""
        hand_rank, _ = HandEvaluator.evaluate(cards)
        return str(hand_rank)
