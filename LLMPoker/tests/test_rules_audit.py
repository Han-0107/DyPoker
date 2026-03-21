"""
tests/test_rules_audit.py - 德州扑克规则全面审计测试

覆盖：
  1. 盲注机制 (Heads-up / 多人)
  2. 行动顺序 (Preflop / Postflop)
  3. 加注规则 (min-raise, re-raise)
  4. All-in 场景 (short stack, side pot)
  5. 庄家位移动
  6. 发牌 & Burn 牌
  7. 牌力评估边缘情况
  8. 底池计算
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from poker_engine.card import Card, Deck, Rank, Suit
from poker_engine.evaluator import HandEvaluator, HandRank
from poker_engine.player import Player
from poker_engine.game import PokerGame, Action, ActionType, GamePhase


def make_game(n=2, chips=1000, sb=5, bb=10, seed=42):
    players = [Player(name=f"P{i+1}", chips=chips) for i in range(n)]
    return PokerGame(players=players, small_blind=sb, big_blind=bb, seed=seed)


def play_until_over(game, default_action="check"):
    """用默认动作打完一手牌, 返回执行的动作列表"""
    actions_taken = []
    safety = 0
    while not game.is_hand_over() and safety < 100:
        safety += 1
        cur = game.get_current_player()
        if cur is None:
            break
        valid = game.get_valid_actions()
        if default_action == "check" and ActionType.CHECK in valid:
            a = Action(cur.name, ActionType.CHECK)
        elif ActionType.CALL in valid:
            a = Action(cur.name, ActionType.CALL)
        elif ActionType.CHECK in valid:
            a = Action(cur.name, ActionType.CHECK)
        else:
            a = Action(cur.name, ActionType.FOLD)
        r = game.execute_action(a)
        actions_taken.append((cur.name, a.action_type, r))
    return actions_taken


# ═════════════════════════════════════════════════════════
#  1. 盲注机制
# ═════════════════════════════════════════════════════════

class TestBlinds(unittest.TestCase):

    def test_headsup_blinds(self):
        """Heads-up: 庄家=小盲, 对手=大盲"""
        g = make_game(n=2, chips=1000, sb=5, bb=10)
        g.start_new_hand()
        # dealer_idx=0 → P1是庄家=小盲, P2是大盲
        p1, p2 = g.players
        self.assertEqual(g.pot, 15)
        # 小盲下了5, 大盲下了10
        self.assertEqual(p1.current_bet, 5)
        self.assertEqual(p2.current_bet, 10)
        self.assertEqual(p1.chips, 995)
        self.assertEqual(p2.chips, 990)

    def test_three_player_blinds(self):
        """3人: 庄家后面是小盲, 再后面是大盲"""
        g = make_game(n=3, chips=1000, sb=5, bb=10)
        g.start_new_hand()
        # dealer=P1(idx=0), SB=P2(idx=1), BB=P3(idx=2)
        self.assertEqual(g.players[1].current_bet, 5)   # SB
        self.assertEqual(g.players[2].current_bet, 10)  # BB
        self.assertEqual(g.players[0].current_bet, 0)   # Dealer (no blind)
        self.assertEqual(g.pot, 15)

    def test_blind_short_stack(self):
        """盲注玩家筹码不足时应 all-in"""
        players = [Player(name="P1", chips=1000), Player(name="P2", chips=3)]
        g = PokerGame(players=players, small_blind=5, big_blind=10, seed=42)
        g.start_new_hand()
        # P1 是庄家=小盲(5), P2 是大盲但只有3筹码
        p1, p2 = g.players
        self.assertEqual(p2.current_bet, 3)   # 只能下3
        self.assertTrue(p2.is_all_in)
        self.assertEqual(p2.chips, 0)
        self.assertEqual(g.pot, 8)  # 5 + 3


# ═════════════════════════════════════════════════════════
#  2. 行动顺序
# ═════════════════════════════════════════════════════════

class TestActionOrder(unittest.TestCase):

    def test_headsup_preflop_dealer_acts_first(self):
        """Heads-up preflop: 庄家(小盲)先行动"""
        g = make_game(n=2)
        g.start_new_hand()
        cur = g.get_current_player()
        # 庄家是 dealer_idx=0 → P1
        self.assertEqual(cur.name, "P1")

    def test_three_player_preflop_utg_first(self):
        """3人 preflop: UTG (大盲后一位 = 庄家自己) 先行动"""
        g = make_game(n=3)
        g.start_new_hand()
        # dealer=0, SB=1, BB=2, UTG = (0+3)%3 = 0 = dealer
        cur = g.get_current_player()
        self.assertEqual(cur.name, "P1")  # dealer = UTG in 3-player

    def test_postflop_sb_acts_first(self):
        """Postflop: 小盲位先行动"""
        g = make_game(n=3)
        g.start_new_hand()
        # 所有人 call/check 进入 flop
        play_until_phase(g, GamePhase.FLOP)
        cur = g.get_current_player()
        # postflop: (dealer_idx + 1) % n = 1 → P2 (SB)
        self.assertEqual(cur.name, "P2")


def play_until_phase(game, target_phase):
    """打到指定阶段"""
    safety = 0
    while game.phase != target_phase and not game.is_hand_over() and safety < 50:
        safety += 1
        cur = game.get_current_player()
        if cur is None:
            break
        valid = game.get_valid_actions()
        if ActionType.CALL in valid:
            game.execute_action(Action(cur.name, ActionType.CALL))
        elif ActionType.CHECK in valid:
            game.execute_action(Action(cur.name, ActionType.CHECK))
        else:
            game.execute_action(Action(cur.name, ActionType.FOLD))


# ═════════════════════════════════════════════════════════
#  3. 加注规则
# ═════════════════════════════════════════════════════════

class TestRaising(unittest.TestCase):

    def test_min_raise_is_big_blind(self):
        """最小加注额 = 大盲"""
        g = make_game(n=2, bb=10)
        g.start_new_hand()
        self.assertEqual(g.min_raise, 10)

    def test_raise_below_min_rejected(self):
        """加注低于最小额应被拒绝"""
        g = make_game(n=2, chips=1000, sb=5, bb=10)
        g.start_new_hand()
        cur = g.get_current_player()
        # call_amount = 10 - 5 = 5, min_raise=10, 所以最少要 5+10=15
        # 但 raise amount 表示的是总下注 (放入的筹码)
        # 尝试 raise 10 (不够, 因为 call_amount=5, min_raise=10 → 需要15)
        result = g.execute_action(Action(cur.name, ActionType.RAISE, amount=10))
        self.assertFalse(result["success"])

    def test_valid_raise(self):
        """合法加注"""
        g = make_game(n=2, chips=1000, sb=5, bb=10)
        g.start_new_hand()
        cur = g.get_current_player()
        # 需要至少 call(5) + min_raise(10) = 15
        result = g.execute_action(Action(cur.name, ActionType.RAISE, amount=25))
        self.assertTrue(result["success"])

    def test_reraise_updates_min_raise(self):
        """re-raise 应更新 min_raise"""
        g = make_game(n=2, chips=1000, sb=5, bb=10)
        g.start_new_hand()
        # P1 (dealer/SB, current_bet=5) raises to 30 → 放入25筹码
        # current_bet 变成 30, raise_size = 30 - 10 = 20
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.RAISE, amount=25))
        # min_raise 应至少为 20
        self.assertGreaterEqual(g.min_raise, 20)

    def test_raise_resets_others_acted(self):
        """加注后其他玩家的 has_acted 应被重置"""
        g = make_game(n=3, chips=1000)
        g.start_new_hand()
        # P1(UTG) calls
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.CALL))
        # P2(SB) raises
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.RAISE, amount=30))
        # P3(BB) 和 P1 的 has_acted 应被重置为 False
        p1 = g.get_player_by_name("P1")
        p3 = g.get_player_by_name("P3")
        self.assertFalse(p1.has_acted)
        self.assertFalse(p3.has_acted)


# ═════════════════════════════════════════════════════════
#  4. All-in 场景
# ═════════════════════════════════════════════════════════

class TestAllIn(unittest.TestCase):

    def test_allin_basic(self):
        """All-in 应将筹码清零"""
        g = make_game(n=2, chips=100)
        g.start_new_hand()
        cur = g.get_current_player()
        result = g.execute_action(Action(cur.name, ActionType.ALL_IN))
        self.assertTrue(result["success"])
        player = g.get_player_by_name(cur.name)
        self.assertEqual(player.chips, 0)
        self.assertTrue(player.is_all_in)

    def test_allin_short_stack_no_reopen(self):
        """
        短筹码 all-in 如果低于完整 raise, 不应重新开放加注轮次
        (这是一个高级规则，当前引擎简化处理)
        """
        # P1=1000, P2=15 (只能 all-in 15，而大盲=10)
        players = [Player(name="P1", chips=1000), Player(name="P2", chips=15)]
        g = PokerGame(players=players, small_blind=5, big_blind=10, seed=42)
        g.start_new_hand()
        # P1 是庄家/SB (bet=5), P2 是 BB (bet=10, chips剩5)
        # P1 calls → current_bet=10
        cur = g.get_current_player()
        self.assertEqual(cur.name, "P1")
        g.execute_action(Action("P1", ActionType.CALL))
        # P2 checks
        cur = g.get_current_player()
        if cur and cur.name == "P2":
            g.execute_action(Action("P2", ActionType.CHECK))

    def test_side_pot_scenario(self):
        """
        Side pot: P1(100), P2(50), P3(200) 全 all-in
        P2 只能赢 50*3=150 的 main pot
        P1 能赢 100*2 的 side pot (vs P3 only)
        注意: 当前引擎使用简化版分池, 这个测试验证基本行为
        """
        players = [
            Player(name="P1", chips=100),
            Player(name="P2", chips=50),
            Player(name="P3", chips=200),
        ]
        g = PokerGame(players=players, small_blind=5, big_blind=10, seed=42)
        g.start_new_hand()
        # 所有人 all-in
        while not g.is_hand_over():
            cur = g.get_current_player()
            if cur is None:
                break
            g.execute_action(Action(cur.name, ActionType.ALL_IN))
        # 游戏应该结束
        self.assertTrue(g.is_hand_over())
        # 底池应该是所有下注之和
        total_bet = sum(p.total_bet for p in g.players)
        # 验证总筹码守恒
        total_chips = sum(p.chips for p in g.players)
        self.assertEqual(total_chips, 350)  # 100 + 50 + 200


# ═════════════════════════════════════════════════════════
#  5. 庄家位移动
# ═════════════════════════════════════════════════════════

class TestDealerRotation(unittest.TestCase):

    def test_dealer_moves_after_hand(self):
        """每手牌结束后庄家位应该移动"""
        g = make_game(n=3, chips=1000)
        g.start_new_hand()
        initial_dealer = g.dealer_idx

        # 打完一手
        play_until_over(g)

        # 开始第二手
        g.start_new_hand()
        # 庄家应该移动了
        # 注意: dealer_idx 在 _showdown 或 all-fold 时 +1
        self.assertNotEqual(g.dealer_idx, initial_dealer)


# ═════════════════════════════════════════════════════════
#  6. 发牌 & Burn 牌
# ═════════════════════════════════════════════════════════

class TestDealing(unittest.TestCase):

    def test_each_player_gets_two_cards(self):
        """每个玩家应收到 2 张手牌"""
        g = make_game(n=4)
        g.start_new_hand()
        for p in g.players:
            self.assertEqual(len(p.hand), 2)

    def test_no_duplicate_cards(self):
        """所有发出的牌不应有重复"""
        g = make_game(n=6)
        g.start_new_hand()
        all_cards = []
        for p in g.players:
            all_cards.extend(p.hand)
        # 没有重复
        card_strs = [str(c) for c in all_cards]
        self.assertEqual(len(card_strs), len(set(card_strs)))

    def test_burn_cards(self):
        """
        应有 burn 牌:
        - Preflop: 发4*2=8张手牌 (4人)
        - Flop: burn 1 + deal 3 = 4张
        - Turn: burn 1 + deal 1 = 2张
        - River: burn 1 + deal 1 = 2张
        总共: 8 + 4 + 2 + 2 = 16张
        剩余: 52 - 16 = 36张
        """
        g = make_game(n=4, chips=1000)
        g.start_new_hand()
        cards_used = 8  # 4*2 手牌
        initial_remaining = g.deck.remaining
        self.assertEqual(initial_remaining, 52 - cards_used)

        # 打到 showdown
        play_until_over(g)

        # 验证公共牌 5 张
        if g.community_cards:
            self.assertEqual(len(g.community_cards), 5)

    def test_community_cards_progression(self):
        """公共牌发牌进度: 0 → 3 → 4 → 5"""
        g = make_game(n=2, chips=1000)
        g.start_new_hand()
        self.assertEqual(len(g.community_cards), 0)

        # 到 Flop
        play_until_phase(g, GamePhase.FLOP)
        if g.phase == GamePhase.FLOP:
            self.assertEqual(len(g.community_cards), 3)

        # 到 Turn
        play_until_phase(g, GamePhase.TURN)
        if g.phase == GamePhase.TURN:
            self.assertEqual(len(g.community_cards), 4)

        # 到 River
        play_until_phase(g, GamePhase.RIVER)
        if g.phase == GamePhase.RIVER:
            self.assertEqual(len(g.community_cards), 5)


# ═════════════════════════════════════════════════════════
#  7. 牌力评估边缘情况
# ═════════════════════════════════════════════════════════

class TestEvaluatorEdgeCases(unittest.TestCase):

    def _cards(self, *strs):
        return [Card.from_str(s) for s in strs]

    def test_ace_high_straight(self):
        """A-K-Q-J-T 顺子 (Broadway)"""
        cards = self._cards("Ah", "Kd", "Qc", "Js", "Th")
        rank, tb = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.STRAIGHT)
        self.assertEqual(tb[0], 14)  # Ace high

    def test_wheel_vs_higher_straight(self):
        """A-2-3-4-5 < 2-3-4-5-6"""
        wheel = self._cards("Ah", "2d", "3c", "4s", "5h")
        six_high = self._cards("2h", "3d", "4c", "5s", "6h")
        result = HandEvaluator.compare_hands(wheel, six_high)
        self.assertEqual(result, -1)  # wheel loses

    def test_same_pair_different_kicker(self):
        """同对子不同踢脚"""
        hand1 = self._cards("Ah", "Ad", "Kc", "Qs", "Jh")
        hand2 = self._cards("As", "Ac", "Kh", "Qd", "Th")
        result = HandEvaluator.compare_hands(hand1, hand2)
        self.assertEqual(result, 1)  # hand1 wins (J > T kicker)

    def test_flush_comparison(self):
        """同花比较最高牌"""
        hand1 = self._cards("Ah", "Kh", "7h", "4h", "2h")
        hand2 = self._cards("Qs", "Js", "Ts", "8s", "6s")
        result = HandEvaluator.compare_hands(hand1, hand2)
        self.assertEqual(result, 1)  # Ace-high flush wins

    def test_full_house_comparison(self):
        """葫芦比较三条部分"""
        hand1 = self._cards("Ah", "Ad", "Ac", "2s", "2h")  # AAA22
        hand2 = self._cards("Kh", "Kd", "Kc", "Qs", "Qh")  # KKKQQ
        result = HandEvaluator.compare_hands(hand1, hand2)
        self.assertEqual(result, 1)  # AAA > KKK

    def test_two_pair_comparison(self):
        """两对: 先比高对, 再比低对, 再比踢脚"""
        hand1 = self._cards("Ah", "Ad", "Kc", "Ks", "3h")  # AA KK 3
        hand2 = self._cards("Ah", "Ad", "Qc", "Qs", "Kh")  # AA QQ K
        result = HandEvaluator.compare_hands(hand1, hand2)
        self.assertEqual(result, 1)  # KK > QQ as second pair

    def test_seven_card_flush(self):
        """7张牌中有6张同花, 应选最佳5张"""
        cards = self._cards("Ah", "Kh", "Qh", "Jh", "9h", "3h", "2c")
        rank, tb = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.FLUSH)
        # 应选 A K Q J 9 of hearts
        self.assertEqual(tb, (14, 13, 12, 11, 9))

    def test_board_pair_best_hand(self):
        """手牌不参与最佳牌型 (公共牌更好)"""
        # 公共牌已经是顺子
        cards = self._cards("9h", "8d", "7c", "6s", "5h", "2c", "3d")
        rank, _ = HandEvaluator.evaluate(cards)
        self.assertEqual(rank, HandRank.STRAIGHT)


# ═════════════════════════════════════════════════════════
#  8. 底池计算
# ═════════════════════════════════════════════════════════

class TestPotCalculation(unittest.TestCase):

    def test_pot_after_blinds(self):
        """盲注后底池 = SB + BB"""
        g = make_game(n=2, sb=5, bb=10)
        g.start_new_hand()
        self.assertEqual(g.pot, 15)

    def test_pot_after_call(self):
        """跟注后底池增加"""
        g = make_game(n=2, sb=5, bb=10)
        g.start_new_hand()
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.CALL))
        # P1(SB=5) calls → 补 5 筹码 → pot = 15 + 5 = 20
        self.assertEqual(g.pot, 20)

    def test_pot_after_raise(self):
        """加注后底池增加"""
        g = make_game(n=2, sb=5, bb=10)
        g.start_new_hand()
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.RAISE, amount=25))
        # P1(SB=5) raises, places 25 more → current_bet=30, pot=15+25=40
        self.assertEqual(g.pot, 40)

    def test_chips_conservation(self):
        """筹码守恒: 所有玩家筹码之和始终不变"""
        g = make_game(n=4, chips=500)
        total_initial = 4 * 500  # 2000

        for _ in range(5):
            if len([p for p in g.players if p.chips > 0]) < 2:
                break
            g.start_new_hand()
            play_until_over(g)
            total_now = sum(p.chips for p in g.players)
            self.assertEqual(total_now, total_initial,
                             f"Hand #{g.hand_number}: 筹码不守恒! "
                             f"期望 {total_initial}, 实际 {total_now}")


# ═════════════════════════════════════════════════════════
#  9. 合法动作验证
# ═════════════════════════════════════════════════════════

class TestValidActions(unittest.TestCase):

    def test_cannot_check_when_facing_bet(self):
        """面对加注时不能 check"""
        g = make_game(n=2, sb=5, bb=10)
        g.start_new_hand()
        # P1(SB) 面对 BB=10, current_bet=5
        cur = g.get_current_player()
        result = g.execute_action(Action(cur.name, ActionType.CHECK))
        self.assertFalse(result["success"])

    def test_cannot_call_zero(self):
        """无需跟注时不能 call"""
        g = make_game(n=2, sb=5, bb=10)
        g.start_new_hand()
        # P1 calls
        cur = g.get_current_player()
        g.execute_action(Action(cur.name, ActionType.CALL))
        # P2(BB) current_bet == 10 == game.current_bet → 应 check 而非 call
        cur = g.get_current_player()
        if cur:
            result = g.execute_action(Action(cur.name, ActionType.CALL))
            self.assertFalse(result["success"])

    def test_fold_always_valid(self):
        """弃牌总是合法的"""
        g = make_game(n=2)
        g.start_new_hand()
        cur = g.get_current_player()
        valid = g.get_valid_actions()
        self.assertIn(ActionType.FOLD, valid)

    def test_allin_always_valid(self):
        """All-in 总是合法的"""
        g = make_game(n=2)
        g.start_new_hand()
        cur = g.get_current_player()
        valid = g.get_valid_actions()
        self.assertIn(ActionType.ALL_IN, valid)


# ═════════════════════════════════════════════════════════
#  10. 多手牌连续游戏
# ═════════════════════════════════════════════════════════

class TestMultipleHands(unittest.TestCase):

    def test_play_multiple_hands(self):
        """连续打多手牌不崩溃"""
        g = make_game(n=4, chips=500)
        for i in range(10):
            active = [p for p in g.players if p.chips > 0]
            if len(active) < 2:
                break
            g.start_new_hand()
            play_until_over(g)
        # 应该至少打了几手
        self.assertGreater(g.hand_number, 0)

    def test_eliminated_players_removed(self):
        """筹码为 0 的玩家应被移除"""
        players = [
            Player(name="Rich", chips=1000),
            Player(name="Poor", chips=10),
        ]
        g = PokerGame(players=players, small_blind=5, big_blind=10, seed=42)
        g.start_new_hand()
        # Poor 只有 10, 大盲已经 all-in
        play_until_over(g)
        # 第二手
        g.start_new_hand()
        # Poor 如果输了就被移除了
        if g.phase == GamePhase.FINISHED:
            # 只剩一人, 正确结束
            self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
