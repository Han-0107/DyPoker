"""
tests/test_poker_engine.py - 扑克引擎单元测试
测试发牌、牌力评估、游戏流程等核心逻辑
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from poker_engine.card import Card, Deck, Rank, Suit
from poker_engine.evaluator import HandEvaluator, HandRank
from poker_engine.player import Player
from poker_engine.game import PokerGame, Action, ActionType, GamePhase


class TestCard(unittest.TestCase):
    """测试Card类"""

    def test_create_card(self):
        card = Card(Rank.ACE, Suit.SPADES)
        self.assertEqual(card.rank, Rank.ACE)
        self.assertEqual(card.suit, Suit.SPADES)
        self.assertEqual(str(card), "A♠")

    def test_from_str(self):
        card = Card.from_str("Ah")
        self.assertEqual(card.rank, Rank.ACE)
        self.assertEqual(card.suit, Suit.HEARTS)

        card2 = Card.from_str("Td")
        self.assertEqual(card2.rank, Rank.TEN)
        self.assertEqual(card2.suit, Suit.DIAMONDS)

    def test_card_equality(self):
        c1 = Card(Rank.KING, Suit.HEARTS)
        c2 = Card(Rank.KING, Suit.HEARTS)
        self.assertEqual(c1, c2)

    def test_to_dict_from_dict(self):
        card = Card(Rank.QUEEN, Suit.CLUBS)
        d = card.to_dict()
        card2 = Card.from_dict(d)
        self.assertEqual(card, card2)


class TestDeck(unittest.TestCase):
    """测试Deck类"""

    def test_deck_52_cards(self):
        deck = Deck()
        self.assertEqual(len(deck), 52)

    def test_deal(self):
        deck = Deck()
        deck.shuffle(seed=42)
        cards = deck.deal(5)
        self.assertEqual(len(cards), 5)
        self.assertEqual(deck.remaining, 47)

    def test_shuffle_reproducible(self):
        d1 = Deck()
        d1.shuffle(seed=123)
        c1 = d1.deal(5)

        d2 = Deck()
        d2.shuffle(seed=123)
        c2 = d2.deal(5)

        self.assertEqual(c1, c2)

    def test_deal_too_many(self):
        deck = Deck()
        with self.assertRaises(ValueError):
            deck.deal(53)


class TestHandEvaluator(unittest.TestCase):
    """测试牌力评估器"""

    def _cards(self, *strs):
        return [Card.from_str(s) for s in strs]

    def test_royal_flush(self):
        cards = self._cards("Ah", "Kh", "Qh", "Jh", "Th")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.ROYAL_FLUSH)

    def test_straight_flush(self):
        cards = self._cards("9d", "8d", "7d", "6d", "5d")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.STRAIGHT_FLUSH)

    def test_four_of_a_kind(self):
        cards = self._cards("Ks", "Kh", "Kd", "Kc", "3h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.FOUR_OF_A_KIND)

    def test_full_house(self):
        cards = self._cards("Qs", "Qh", "Qd", "7c", "7h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.FULL_HOUSE)

    def test_flush(self):
        cards = self._cards("As", "Ts", "7s", "4s", "2s")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.FLUSH)

    def test_straight(self):
        cards = self._cards("9h", "8d", "7c", "6s", "5h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.STRAIGHT)

    def test_straight_wheel(self):
        """A-2-3-4-5 小顺子"""
        cards = self._cards("Ah", "2d", "3c", "4s", "5h")
        rank, tb = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.STRAIGHT)
        self.assertEqual(tb[0], 5)  # 5作为最高牌

    def test_three_of_a_kind(self):
        cards = self._cards("Jh", "Jd", "Jc", "8s", "3h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.THREE_OF_A_KIND)

    def test_two_pair(self):
        cards = self._cards("Ah", "Ad", "Kc", "Ks", "3h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.TWO_PAIR)

    def test_one_pair(self):
        cards = self._cards("Th", "Td", "8c", "5s", "2h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.ONE_PAIR)

    def test_high_card(self):
        cards = self._cards("Ah", "Kd", "9c", "5s", "2h")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.HIGH_CARD)

    def test_seven_cards_best_five(self):
        """7张牌中选最佳5张"""
        cards = self._cards("Ah", "Kh", "Qh", "Jh", "Th", "2c", "3d")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.ROYAL_FLUSH)

    def test_compare_hands(self):
        hand1 = self._cards("Ah", "Kh", "Qh", "Jh", "Th")  # Royal flush
        hand2 = self._cards("Ks", "Kh", "Kd", "Kc", "3h")  # Four of a kind
        self.assertEqual(HandEvaluator.compare_hands(hand1, hand2), 1)

    def test_compare_same_rank(self):
        """相同牌型比较踢脚牌"""
        hand1 = self._cards("Ah", "Ad", "Kc", "Qs", "Jh")  # Pair of aces, K kicker
        hand2 = self._cards("Ah", "Ad", "Tc", "9s", "8h")   # Pair of aces, T kicker
        self.assertEqual(HandEvaluator.compare_hands(hand1, hand2), 1)


class TestPlayer(unittest.TestCase):
    """测试Player类"""

    def test_place_bet(self):
        player = Player(name="Test", chips=100)
        actual = player.place_bet(30)
        self.assertEqual(actual, 30)
        self.assertEqual(player.chips, 70)
        self.assertEqual(player.current_bet, 30)

    def test_place_bet_all_in(self):
        player = Player(name="Test", chips=50)
        actual = player.place_bet(100)
        self.assertEqual(actual, 50)
        self.assertEqual(player.chips, 0)
        self.assertTrue(player.is_all_in)

    def test_fold(self):
        player = Player(name="Test")
        player.fold()
        self.assertFalse(player.is_active)

    def test_reset(self):
        player = Player(name="Test", chips=100)
        player.place_bet(50)
        player.fold()
        player.reset_for_new_hand()
        self.assertTrue(player.is_active)
        self.assertEqual(player.current_bet, 0)
        self.assertEqual(player.hand, [])


class TestPokerGame(unittest.TestCase):
    """测试游戏引擎"""

    def _create_game(self, n_players=2, chips=1000):
        players = [
            Player(name=f"Player_{i+1}", chips=chips)
            for i in range(n_players)
        ]
        return PokerGame(
            players=players,
            small_blind=5,
            big_blind=10,
            seed=42,
        )

    def test_create_game(self):
        game = self._create_game()
        self.assertEqual(len(game.players), 2)
        self.assertEqual(game.phase, GamePhase.WAITING)

    def test_start_hand(self):
        game = self._create_game()
        game.start_new_hand()
        self.assertEqual(game.phase, GamePhase.PREFLOP)
        self.assertEqual(game.hand_number, 1)
        # 每人应有2张手牌
        for p in game.players:
            self.assertEqual(len(p.hand), 2)
        # 底池应有盲注
        self.assertEqual(game.pot, 15)  # 5 + 10

    def test_simple_hand_fold(self):
        """一人弃牌，另一人赢"""
        game = self._create_game()
        game.start_new_hand()

        current = game.get_current_player()
        self.assertIsNotNone(current)

        # 当前玩家弃牌
        action = Action(current.name, ActionType.FOLD)
        result = game.execute_action(action)
        self.assertTrue(result["success"])
        self.assertIn("winner", result)

    def test_check_check_through(self):
        """双方都check到底"""
        game = self._create_game()
        game.start_new_hand()

        # Preflop: call + check
        current = game.get_current_player()
        game.execute_action(Action(current.name, ActionType.CALL))
        current = game.get_current_player()
        if current:
            game.execute_action(Action(current.name, ActionType.CHECK))

        # 后续轮次都check
        max_actions = 20  # 防止无限循环
        actions = 0
        while not game.is_hand_over() and actions < max_actions:
            current = game.get_current_player()
            if current is None:
                break
            valid = game.get_valid_actions()
            if ActionType.CHECK in valid:
                game.execute_action(Action(current.name, ActionType.CHECK))
            else:
                game.execute_action(Action(current.name, ActionType.CALL))
            actions += 1

        self.assertTrue(game.is_hand_over())

    def test_game_state(self):
        game = self._create_game()
        game.start_new_hand()
        state = game.get_game_state(player_name="Player_1")
        self.assertIn("phase", state)
        self.assertIn("pot", state)
        self.assertIn("players", state)
        self.assertIn("valid_actions", state)

    def test_raise_action(self):
        game = self._create_game()
        game.start_new_hand()

        current = game.get_current_player()
        action = Action(current.name, ActionType.RAISE, amount=30)
        result = game.execute_action(action)
        self.assertTrue(result["success"])

    def test_three_player_game(self):
        game = self._create_game(n_players=3)
        game.start_new_hand()
        self.assertEqual(len(game.players), 3)
        self.assertEqual(game.phase, GamePhase.PREFLOP)


if __name__ == "__main__":
    unittest.main()
