import unittest

from app.games.rummy.engine import Card, create_deck, find_valid_partition, hand_points, is_valid_declaration


class RummyRuleTests(unittest.TestCase):
    def setUp(self):
        self.valid_hand = [
            Card("ha", 1, "hearts"),
            Card("h2", 2, "hearts"),
            Card("h3", 3, "hearts"),
            Card("c4", 4, "clubs"),
            Card("c5", 5, "clubs"),
            Card("c6", 6, "clubs"),
            Card("c8", 8, "clubs"),
            Card("d8", 8, "diamonds"),
            Card("h8", 8, "hearts"),
            Card("c9", 9, "clubs"),
            Card("d9", 9, "diamonds"),
            Card("h9", 9, "hearts"),
            Card("s9", 9, "spades"),
        ]

    def test_deck_has_unique_cards_and_two_printed_jokers_per_deck(self):
        deck = create_deck(3)
        self.assertEqual(len(deck), 162)
        self.assertEqual(len({card.card_id for card in deck}), len(deck))
        self.assertEqual(sum(card.printed_joker for card in deck), 6)

    def test_valid_hand_has_pure_sequence_and_second_sequence(self):
        groups = find_valid_partition(self.valid_hand, wild_rank=13)
        self.assertIsNotNone(groups)
        self.assertEqual(sum(len(group) for group in groups), 13)
        self.assertTrue(is_valid_declaration(self.valid_hand, wild_rank=13))

    def test_ace_high_sequence_is_allowed_but_wraparound_is_not(self):
        ace_high = (
            Card("sq", 12, "spades"),
            Card("sk", 13, "spades"),
            Card("sa", 1, "spades"),
        )
        wraparound = (
            Card("sk2", 13, "spades"),
            Card("sa2", 1, "spades"),
            Card("s2", 2, "spades"),
        )
        self.assertTrue(is_valid_declaration(self.valid_hand, wild_rank=13))
        from app.games.rummy.engine import _is_pure_sequence

        self.assertTrue(_is_pure_sequence(ace_high, wild_rank=9))
        self.assertFalse(_is_pure_sequence(wraparound, wild_rank=9))

    def test_joker_can_complete_an_impure_sequence(self):
        from app.games.rummy.engine import _is_sequence

        cards = (
            Card("h2", 2, "hearts"),
            Card("h4", 4, "hearts"),
            Card("joker", None, None, printed_joker=True),
        )
        self.assertTrue(_is_sequence(cards, wild_rank=13))

    def test_selected_wild_rank_cannot_be_part_of_a_pure_sequence(self):
        no_pure_hand = [
            Card("h2", 2, "hearts"),
            Card("h3", 3, "hearts"),
            Card("h4", 4, "hearts"),
            Card("c4", 4, "clubs"),
            Card("c5", 5, "clubs"),
            Card("c6", 6, "clubs"),
            Card("c8", 8, "clubs"),
            Card("d8", 8, "diamonds"),
            Card("h8", 8, "hearts"),
            Card("c9", 9, "clubs"),
            Card("d9", 9, "diamonds"),
            Card("h9", 9, "hearts"),
            Card("s9", 9, "spades"),
        ]
        self.assertFalse(is_valid_declaration(no_pure_hand, wild_rank=4))

    def test_points_have_an_eighty_point_cap_and_wildcards_score_zero(self):
        self.assertEqual(hand_points(self.valid_hand, wild_rank=13), 0)
        hand = [
            Card(f"card-{index}", 10 if index % 2 else 13, "clubs")
            for index in range(13)
        ]
        self.assertEqual(hand_points(hand, wild_rank=13), 80)


if __name__ == "__main__":
    unittest.main()
