"""
Player - 玩家模型
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from .card import Card


@dataclass
class Player:
    """德州扑克玩家"""
    name: str
    chips: int = 1000
    hand: List[Card] = field(default_factory=list)
    is_active: bool = True       # 是否还在本局中（未fold）
    is_all_in: bool = False      # 是否已经all-in
    current_bet: int = 0         # 当前轮已下注金额
    total_bet: int = 0           # 本局总下注金额
    has_acted: bool = False      # 本轮是否已行动过
    is_human: bool = False       # 是否为人类玩家
    agent_type: str = "llm"      # 代理类型: "llm", "human", "random"

    def reset_for_new_hand(self):
        """新一手牌前重置状态"""
        self.hand = []
        self.is_active = True
        self.is_all_in = False
        self.current_bet = 0
        self.total_bet = 0
        self.has_acted = False

    def reset_current_bet(self):
        """新一轮下注前重置当前下注"""
        self.current_bet = 0
        self.has_acted = False

    def place_bet(self, amount: int) -> int:
        """
        下注
        返回实际下注金额（可能因筹码不足而少于请求金额）
        """
        actual = min(amount, self.chips)
        self.chips -= actual
        self.current_bet += actual
        self.total_bet += actual
        if self.chips == 0:
            self.is_all_in = True
        return actual

    def fold(self):
        """弃牌"""
        self.is_active = False

    def receive_cards(self, cards: List[Card]):
        """接收手牌"""
        self.hand.extend(cards)

    def to_dict(self, hide_hand: bool = False) -> dict:
        """
        序列化为字典
        hide_hand: 是否隐藏手牌（用于向其他玩家展示状态时）
        """
        d = {
            "name": self.name,
            "chips": self.chips,
            "is_active": self.is_active,
            "is_all_in": self.is_all_in,
            "current_bet": self.current_bet,
            "total_bet": self.total_bet,
        }
        if not hide_hand:
            d["hand"] = [str(c) for c in self.hand]
        else:
            d["hand"] = ["??"] * len(self.hand)
        return d

    def __str__(self) -> str:
        hand_str = " ".join(str(c) for c in self.hand) if self.hand else "no cards"
        status = "ACTIVE" if self.is_active else "FOLDED"
        return f"{self.name} [{status}] chips={self.chips} bet={self.current_bet} hand=[{hand_str}]"
