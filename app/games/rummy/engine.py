from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from math import inf

SUITS = ("clubs", "diamonds", "hearts", "spades")
RANK_LABELS = {
    1: "A",
    11: "J",
    12: "Q",
    13: "K",
}


@dataclass(frozen=True)
class Card:
    card_id: str
    rank: int | None
    suit: str | None
    printed_joker: bool = False

    def is_wild(self, wild_rank: int) -> bool:
        return self.printed_joker or self.rank == wild_rank

    def value(self, wild_rank: int) -> int:
        if self.is_wild(wild_rank) or self.rank is None:
            return 0
        if self.rank == 1 or self.rank >= 10:
            return 10
        return self.rank

    def to_dict(self, wild_rank: int) -> dict[str, str | int | bool | None]:
        return {
            "id": self.card_id,
            "rank": self.rank,
            "rank_label": RANK_LABELS.get(self.rank, str(self.rank)) if self.rank else "Joker",
            "suit": self.suit,
            "printed_joker": self.printed_joker,
            "wild": self.is_wild(wild_rank),
        }


def create_deck(deck_count: int) -> list[Card]:
    deck = []
    for deck_number in range(deck_count):
        for suit in SUITS:
            for rank in range(1, 14):
                deck.append(Card(f"d{deck_number}-{suit}-{rank}", rank, suit))
        deck.append(Card(f"d{deck_number}-joker-1", None, None, True))
        deck.append(Card(f"d{deck_number}-joker-2", None, None, True))
    return deck


def _is_pure_sequence(cards: tuple[Card, ...], wild_rank: int) -> bool:
    if len(cards) < 3 or any(card.is_wild(wild_rank) for card in cards):
        return False
    suits = {card.suit for card in cards}
    ranks = [card.rank for card in cards]
    if len(suits) != 1 or len(set(ranks)) != len(ranks):
        return False

    candidates = []
    for ace_value in (1, 14):
        values = [ace_value if rank == 1 else rank for rank in ranks]
        values.sort()
        if values[-1] - values[0] + 1 == len(values):
            candidates.append(values)
    return bool(candidates)


def _is_sequence(cards: tuple[Card, ...], wild_rank: int) -> bool:
    if len(cards) < 3:
        return False
    wildcards = [card for card in cards if card.is_wild(wild_rank)]
    natural = [card for card in cards if not card.is_wild(wild_rank)]
    if not natural or len({card.suit for card in natural}) != 1:
        return False
    ranks = [card.rank for card in natural]
    if len(set(ranks)) != len(ranks):
        return False

    for start in range(1, 16 - len(cards)):
        positions = set(range(start, start + len(cards)))
        if all(
            ({1, 14} & positions if card.rank == 1 else {card.rank}) & positions
            for card in natural
        ):
            return True
    return False


def _is_set(cards: tuple[Card, ...], wild_rank: int) -> bool:
    if not 3 <= len(cards) <= 4:
        return False
    natural = [card for card in cards if not card.is_wild(wild_rank)]
    if len(natural) < 2:
        return False
    return (
        len({card.rank for card in natural}) == 1
        and len({card.suit for card in natural}) == len(natural)
    )


def _meld_type(cards: tuple[Card, ...], wild_rank: int) -> str | None:
    if _is_pure_sequence(cards, wild_rank):
        return "pure_sequence"
    if _is_sequence(cards, wild_rank):
        return "sequence"
    if _is_set(cards, wild_rank):
        return "set"
    return None


def _meld_candidates(cards: tuple[Card, ...], wild_rank: int):
    by_first = [[] for _ in cards]
    for size in range(3, len(cards) + 1):
        for indices in combinations(range(len(cards)), size):
            group = tuple(cards[index] for index in indices)
            kind = _meld_type(group, wild_rank)
            if kind:
                mask = sum(1 << index for index in indices)
                by_first[indices[0]].append((mask, kind))
    return by_first


def find_valid_partition(cards: list[Card], wild_rank: int) -> list[list[Card]] | None:
    if len(cards) != 13 or len({card.card_id for card in cards}) != 13:
        return None
    card_tuple = tuple(cards)
    candidates = _meld_candidates(card_tuple, wild_rank)

    @lru_cache(maxsize=None)
    def search(remaining: int, has_pure: bool, sequence_count: int):
        if remaining == 0:
            return () if has_pure and sequence_count >= 2 else None
        first = (remaining & -remaining).bit_length() - 1
        for mask, kind in candidates[first]:
            if mask & remaining != mask:
                continue
            result = search(
                remaining ^ mask,
                has_pure or kind == "pure_sequence",
                min(2, sequence_count + (kind in {"pure_sequence", "sequence"})),
            )
            if result is not None:
                return (mask,) + result
        return None

    masks = search((1 << len(card_tuple)) - 1, False, 0)
    if masks is None:
        return None
    return [
        [card_tuple[index] for index in range(len(card_tuple)) if mask & (1 << index)]
        for mask in masks
    ]


def is_valid_declaration(cards: list[Card], wild_rank: int) -> bool:
    return find_valid_partition(cards, wild_rank) is not None


def hand_points(cards: list[Card], wild_rank: int) -> int:
    if len(cards) != 13:
        return min(80, sum(card.value(wild_rank) for card in cards))
    card_tuple = tuple(cards)
    candidates = _meld_candidates(card_tuple, wild_rank)
    points = [card.value(wild_rank) for card in card_tuple]

    @lru_cache(maxsize=None)
    def best_penalty(remaining: int, has_pure: bool, sequence_count: int) -> float:
        if remaining == 0:
            return 0 if has_pure and sequence_count >= 2 else inf
        first = (remaining & -remaining).bit_length() - 1
        bit = 1 << first
        best = points[first] + best_penalty(remaining ^ bit, has_pure, sequence_count)
        for mask, kind in candidates[first]:
            if mask & remaining != mask:
                continue
            best = min(
                best,
                best_penalty(
                    remaining ^ mask,
                    has_pure or kind == "pure_sequence",
                    min(2, sequence_count + (kind in {"pure_sequence", "sequence"})),
                ),
            )
        return best

    result = best_penalty((1 << len(card_tuple)) - 1, False, 0)
    if result != inf:
        return min(80, int(result))

    pure_sequences = [
        mask
        for mask, kind in candidates[0]
        if kind == "pure_sequence"
    ]
    for first_index in range(1, len(card_tuple)):
        pure_sequences.extend(
            mask for mask, kind in candidates[first_index] if kind == "pure_sequence"
        )
    if not pure_sequences:
        return 80
    return min(
        80,
        min(
            sum(points[index] for index in range(len(card_tuple)) if not mask & (1 << index))
            for mask in pure_sequences
        ),
    )
