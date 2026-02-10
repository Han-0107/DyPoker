"""
Card 和 Deck - 扑克牌和牌组
"""

from __future__ import annotations
import random
from dataclasses import dataclass
from enum import IntEnum
from typing import List


class Suit(IntEnum):
    """花色"""
    CLUBS = 0       # ♣ 梅花
    DIAMONDS = 1    # ♦ 方块
    HEARTS = 2      # ♥ 红心
    SPADES = 3      # ♠ 黑桃


class Rank(IntEnum):
    """点数"""
    TWO = 2
    THREE = 3
    FOUR = 4
    FIVE = 5
    SIX = 6
    SEVEN = 7
    EIGHT = 8
    NINE = 9
    TEN = 10
    JACK = 11
    QUEEN = 12
    KING = 13
    ACE = 14


# 显示用的映射
SUIT_SYMBOLS = {
    Suit.CLUBS: "♣",
    Suit.DIAMONDS: "♦",
    Suit.HEARTS: "♥",
    Suit.SPADES: "♠",
}

RANK_SYMBOLS = {
    Rank.TWO: "2", Rank.THREE: "3", Rank.FOUR: "4", Rank.FIVE: "5",
    Rank.SIX: "6", Rank.SEVEN: "7", Rank.EIGHT: "8", Rank.NINE: "9",
    Rank.TEN: "T", Rank.JACK: "J", Rank.QUEEN: "Q", Rank.KING: "K",
    Rank.ACE: "A",
}

# 从字符串解析
RANK_FROM_CHAR = {v: k for k, v in RANK_SYMBOLS.items()}
RANK_FROM_CHAR["10"] = Rank.TEN

SUIT_FROM_CHAR = {
    "c": Suit.CLUBS, "C": Suit.CLUBS, "♣": Suit.CLUBS,
    "d": Suit.DIAMONDS, "D": Suit.DIAMONDS, "♦": Suit.DIAMONDS,
    "h": Suit.HEARTS, "H": Suit.HEARTS, "♥": Suit.HEARTS,
    "s": Suit.SPADES, "S": Suit.SPADES, "♠": Suit.SPADES,
}


@dataclass(frozen=True)
class Card:
    """一张扑克牌"""
    rank: Rank
    suit: Suit

    def __str__(self) -> str:
        return f"{RANK_SYMBOLS[self.rank]}{SUIT_SYMBOLS[self.suit]}"

    def __repr__(self) -> str:
        return f"Card({self})"

    def to_short_str(self) -> str:
        """返回简短表示，如 'Ah' 代表红心A"""
        suit_chars = {Suit.CLUBS: "c", Suit.DIAMONDS: "d",
                      Suit.HEARTS: "h", Suit.SPADES: "s"}
        return f"{RANK_SYMBOLS[self.rank]}{suit_chars[self.suit]}"

    @classmethod
    def from_str(cls, s: str) -> "Card":
        """
        从字符串创建牌，支持格式：'Ah', 'Td', '2c', 'Ks' 等
        """
        s = s.strip()
        if len(s) < 2:
            raise ValueError(f"Invalid card string: {s}")
        rank_char = s[:-1]
        suit_char = s[-1]
        if rank_char not in RANK_FROM_CHAR:
            raise ValueError(f"Invalid rank: {rank_char}")
        if suit_char not in SUIT_FROM_CHAR:
            raise ValueError(f"Invalid suit: {suit_char}")
        return cls(rank=RANK_FROM_CHAR[rank_char], suit=SUIT_FROM_CHAR[suit_char])

    def to_dict(self) -> dict:
        """序列化为字典"""
        return {"rank": int(self.rank), "suit": int(self.suit), "str": str(self)}

    @classmethod
    def from_dict(cls, d: dict) -> "Card":
        """从字典反序列化"""
        return cls(rank=Rank(d["rank"]), suit=Suit(d["suit"]))


class Deck:
    """一副52张扑克牌"""

    def __init__(self):
        self._cards: List[Card] = []
        self.reset()

    def reset(self):
        """重置牌组"""
        self._cards = [
            Card(rank=rank, suit=suit)
            for suit in Suit
            for rank in Rank
        ]

    def shuffle(self, seed: int | None = None):
        """洗牌"""
        if seed is not None:
            rng = random.Random(seed)
            rng.shuffle(self._cards)
        else:
            random.shuffle(self._cards)

    def deal(self, n: int = 1) -> List[Card]:
        """发牌"""
        if n > len(self._cards):
            raise ValueError(f"Not enough cards: need {n}, have {len(self._cards)}")
        dealt = self._cards[:n]
        self._cards = self._cards[n:]
        return dealt

    def deal_one(self) -> Card:
        """发一张牌"""
        return self.deal(1)[0]

    @property
    def remaining(self) -> int:
        """剩余牌数"""
        return len(self._cards)

    def __len__(self) -> int:
        return len(self._cards)
