import asyncio
import re
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.games.rummy.engine import create_deck, find_valid_partition, hand_points

app = FastAPI(title="R Games")
INDEX_FILE = Path(__file__).resolve().parent.parent / "static" / "index.html"
SESSION_TIMEOUT_SECONDS = 90
ROOM_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SUPPORTED_GAMES = {
    "rummy": {
        "name": "Rummy",
        "category": "Card game · Multiplayer",
        "description": "Create a table, invite friends, and get ready to play.",
        "min_players": 2,
        "max_players": 6,
        "available": True,
    },
    "ludo": {
        "name": "Ludo",
        "category": "Board game · Multiplayer",
        "description": "Race your tokens around the board with friends.",
        "min_players": 2,
        "max_players": 4,
        "available": False,
    },
    "solitaire": {
        "name": "Solitaire",
        "category": "Card game · Single player",
        "description": "A relaxing solo card game.",
        "min_players": 1,
        "max_players": 1,
        "available": False,
    },
}

sessions: dict[str, dict[str, Any]] = {}
usernames: dict[str, str] = {}
rooms: dict[str, dict[str, Any]] = {}
lobby_connections: dict[WebSocket, str] = {}
state_lock = asyncio.Lock()
MAX_SAFE_JSON_INTEGER = 2**53 - 1


class ClaimSession(BaseModel):
    username: str = Field(min_length=1, max_length=24)


class CreateRoom(BaseModel):
    game_id: str = "rummy"
    room_name: str = Field(default="Rummy room", min_length=1, max_length=40)
    visibility: str = "public"
    min_players: int = 2
    max_players: int = 6
    game_options: dict[str, Any] = Field(default_factory=dict)


class UpdateDisplayName(BaseModel):
    display_name: str = Field(min_length=1, max_length=24)


class DrawCard(BaseModel):
    source: str


class DiscardCard(BaseModel):
    card_id: str


class DeclareHand(BaseModel):
    card_ids: list[str] = Field(min_length=13, max_length=13)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def _remove_player_from_game(room: dict[str, Any], token: str) -> None:
    game = room.get("game")
    if not game or token not in game["participants"]:
        return
    game["participants"].remove(token)
    game["active_tokens"] = [player for player in game["active_tokens"] if player != token]
    game["hands"].pop(token, None)
    game["scores"].pop(token, None)
    if game["status"] == "playing" and game["turn_token"] == token:
        if game["active_tokens"]:
            game["turn_token"] = game["active_tokens"][0]
            game["phase"] = "draw"
    if game["status"] in {"playing", "round_over"} and len(game["active_tokens"]) < 2:
        game["status"] = "complete"
        game["winner_tokens"] = list(game["active_tokens"])
        game["complete_message"] = "The game ended because fewer than two players remained."
        room["status"] = "complete"


def _remove_player_from_room(token: str) -> None:
    session = sessions.get(token)
    if not session:
        return
    room = rooms.get(session.get("room_code"))
    if not room:
        session["room_code"] = None
        return
    if token in room["players"]:
        room["players"].remove(token)
    _remove_player_from_game(room, token)
    if not room["players"]:
        rooms.pop(room["code"], None)
    elif room["host_token"] == token:
        room["host_token"] = room["players"][0]
    session["room_code"] = None


def _release_session(token: str) -> None:
    session = sessions.get(token)
    if not session:
        return
    _remove_player_from_room(token)
    session = sessions.pop(token, None)
    if session:
        usernames.pop(session["username"].casefold(), None)


def _expire_sessions(now: float) -> bool:
    expired = [
        token
        for token, session in sessions.items()
        if now - session["last_seen"] > SESSION_TIMEOUT_SECONDS
    ]
    for token in expired:
        _release_session(token)
    return bool(expired)


async def _broadcast_lobby() -> None:
    disconnected = []
    for websocket in tuple(lobby_connections):
        try:
            await websocket.send_json({"type": "state_changed"})
        except (WebSocketDisconnect, RuntimeError):
            disconnected.append(websocket)
    for websocket in disconnected:
        lobby_connections.pop(websocket, None)


async def _expire_and_notify() -> None:
    if _expire_sessions(time.monotonic()):
        await _broadcast_lobby()


def _current_session(token: str | None) -> dict[str, Any]:
    if not token or token not in sessions:
        raise HTTPException(status_code=401, detail="Claim a username to continue.")
    session = sessions[token]
    session["last_seen"] = time.monotonic()
    return session


def _room_code() -> str:
    while True:
        code = "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(6))
        if code not in rooms:
            return code


def _new_game(room: dict[str, Any]) -> dict[str, Any]:
    participants = list(room["players"])
    minimum_decks = max(1, (len(participants) * 13 + 54) // 54)
    maximum_decks = room["game_options"]["max_decks"]
    if minimum_decks > maximum_decks:
        raise HTTPException(
            status_code=409,
            detail=f"{len(participants)} players need at least {minimum_decks} decks, "
            f"but this room allows at most {maximum_decks}.",
        )
    deck_count = minimum_decks
    stock = create_deck(deck_count)
    secrets.SystemRandom().shuffle(stock)
    wild_rank = secrets.randbelow(13) + 1
    hands = {token: [stock.pop() for _ in range(13)] for token in participants}
    initial_discard = stock.pop()
    return {
        "status": "playing",
        "participants": participants,
        "active_tokens": participants.copy(),
        "hands": hands,
        "stock": stock,
        "discard_pile": [initial_discard],
        "last_discarder": None,
        "turn_token": participants[0],
        "phase": "draw",
        "round_number": 1,
        "deck_count": deck_count,
        "wild_rank": wild_rank,
        "scores": {token: 0 for token in participants},
        "round_scores": {},
        "round_winner": None,
        "winner_tokens": [],
        "eliminated": [],
        "complete_message": "",
    }


def _start_next_round(room: dict[str, Any], game: dict[str, Any]) -> None:
    participants = [
        token for token in game["active_tokens"]
        if token in room["players"] and token not in game["eliminated"]
    ]
    if len(participants) < 2:
        game["status"] = "complete"
        game["winner_tokens"] = participants
        room["status"] = "complete"
        return
    previous_round = game["round_number"]
    next_game = _new_game_for_players(room, participants)
    next_game["round_number"] = previous_round + 1
    next_game["scores"] = game["scores"]
    next_game["eliminated"] = game["eliminated"]
    room["game"] = next_game


def _new_game_for_players(room: dict[str, Any], participants: list[str]) -> dict[str, Any]:
    previous_players = room["players"]
    room["players"] = participants
    try:
        game = _new_game(room)
    finally:
        room["players"] = previous_players
    return game


def _finish_round(room: dict[str, Any], winner_token: str) -> None:
    game = room["game"]
    participants = list(game["participants"])
    options = room["game_options"]
    mode = options["scoring_mode"]
    round_scores = {
        token: 0 if token == winner_token else hand_points(game["hands"][token], game["wild_rank"])
        for token in participants
        if token in game["hands"]
    }
    for token, score in round_scores.items():
        game["scores"][token] = game["scores"].get(token, 0) + score
    game["round_scores"] = round_scores
    game["round_winner"] = winner_token
    game["status"] = "round_over"
    game["phase"] = "finished"
    room["status"] = "in_progress"

    if mode == "points":
        game["status"] = "complete"
        game["winner_tokens"] = [winner_token]
        room["status"] = "complete"
    elif mode == "deals" and game["round_number"] >= options["deal_count"]:
        lowest_score = min(game["scores"][token] for token in participants)
        game["winner_tokens"] = [
            token for token in participants if game["scores"][token] == lowest_score
        ]
        game["status"] = "complete"
        room["status"] = "complete"
    elif mode == "pool":
        limit = options["pool_limit"]
        for token, score in round_scores.items():
            if token != winner_token and game["scores"][token] >= limit:
                game["eliminated"].append(token)
                game["active_tokens"].remove(token)
        if len(game["active_tokens"]) <= 1:
            game["winner_tokens"] = game["active_tokens"].copy()
            game["status"] = "complete"
            room["status"] = "complete"


def _game_summary(room: dict[str, Any], viewer_token: str) -> dict[str, Any] | None:
    game = room.get("game")
    if not game:
        return None
    mode = room["game_options"]["scoring_mode"]
    winner_tokens = game["winner_tokens"]
    return {
        "status": game["status"],
        "phase": game["phase"],
        "round_number": game["round_number"],
        "scoring_mode": mode,
        "deal_count": room["game_options"]["deal_count"],
        "pool_limit": _json_safe_integer(room["game_options"]["pool_limit"]),
        "deck_count": game["deck_count"],
        "wild_rank": game["wild_rank"],
        "turn_name": sessions.get(game["turn_token"], {}).get("display_name", ""),
        "is_your_turn": game["turn_token"] == viewer_token,
        "is_host": viewer_token == room["host_token"],
        "own_hand": [
            card.to_dict(game["wild_rank"])
            for card in game["hands"].get(viewer_token, [])
        ],
        "stock_count": len(game["stock"]),
        "discard_top": (
            game["discard_pile"][-1].to_dict(game["wild_rank"])
            if game["discard_pile"]
            else None
        ),
        "players": [
            {
                "display_name": sessions.get(token, {}).get("display_name", "Left player"),
                "is_you": token == viewer_token,
                "is_active": token in game["active_tokens"],
                "score": game["scores"].get(token, 0),
                "round_score": game["round_scores"].get(token),
                "is_round_winner": token == game["round_winner"],
                "is_winner": token in winner_tokens,
            }
            for token in room["players"]
        ],
        "has_winner": bool(winner_tokens),
        "winner_names": [
            sessions.get(token, {}).get("display_name", "Left player")
            for token in winner_tokens
            if token in room["players"]
        ],
        "can_start_next_round": (
            game["status"] == "round_over"
            and viewer_token == room["host_token"]
            and mode in {"deals", "pool"}
        ),
        "round_result": [
            {
                "display_name": sessions.get(token, {}).get("display_name", "Left player"),
                "score": game["round_scores"].get(token),
                "total": game["scores"].get(token, 0),
                "is_round_winner": token == game["round_winner"],
                "is_winner": token in winner_tokens,
                "is_active": token in game["active_tokens"],
            }
            for token in room["players"]
        ] if game["status"] in {"round_over", "complete"} else [],
        "complete_message": game["complete_message"],
    }


def _json_safe_integer(value: int | None) -> int | str | None:
    if isinstance(value, int) and value > MAX_SAFE_JSON_INTEGER:
        return str(value)
    return value


def _room_summary(room: dict[str, Any], viewer_token: str | None = None) -> dict[str, Any]:
    game_options = room["game_options"].copy()
    game_options["pool_limit"] = _json_safe_integer(game_options["pool_limit"])
    return {
        "code": room["code"],
        "game_id": room["game_id"],
        "name": room["name"],
        "visibility": room["visibility"],
        "status": room["status"],
        "min_players": room["min_players"],
        "max_players": room["max_players"],
        "player_count": len(room["players"]),
        "is_host": viewer_token == room["host_token"],
        "players": [
            {
                "display_name": sessions[token]["display_name"],
                "is_host": token == room["host_token"],
                "is_you": token == viewer_token,
            }
            for token in room["players"]
            if token in sessions
        ],
        "game_options": game_options,
        "game": _game_summary(room, viewer_token) if viewer_token else None,
    }


@app.get("/")
async def home():
    return FileResponse(INDEX_FILE)


@app.get("/health")
async def health_check():
    return {"status": "ok", "message": "Game server is running"}


@app.get("/api/games")
async def list_games():
    return [
        {"id": game_id, **game}
        for game_id, game in SUPPORTED_GAMES.items()
    ]


@app.post("/api/session")
async def claim_session(request: ClaimSession):
    username = _normalize_name(request.username)
    if not username:
        raise HTTPException(status_code=422, detail="Enter a username.")
    if any(ord(character) < 32 for character in username):
        raise HTTPException(status_code=422, detail="Username contains unsupported characters.")
    async with state_lock:
        await _expire_and_notify()
        key = username.casefold()
        if key in usernames:
            raise HTTPException(status_code=409, detail="That username is already in use.")
        token = secrets.token_urlsafe(32)
        sessions[token] = {
            "username": username,
            "display_name": username,
            "room_code": None,
            "last_seen": time.monotonic(),
        }
        usernames[key] = token
        await _broadcast_lobby()
        return {"token": token, "username": username, "display_name": username}


@app.get("/api/session")
async def get_session(x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        session = _current_session(x_session_token)
        return {
            "username": session["username"],
            "display_name": session["display_name"],
            "room_code": session["room_code"],
        }


@app.post("/api/session/exit")
async def exit_session(x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        _release_session(x_session_token)
        await _broadcast_lobby()
        return {"status": "ok"}


@app.patch("/api/me")
async def update_display_name(
    request: UpdateDisplayName,
    x_session_token: str | None = Header(default=None),
):
    display_name = _normalize_name(request.display_name)
    if not display_name:
        raise HTTPException(status_code=422, detail="Enter a display name.")
    if any(ord(character) < 32 for character in display_name):
        raise HTTPException(status_code=422, detail="Display name contains unsupported characters.")
    async with state_lock:
        await _expire_and_notify()
        session = _current_session(x_session_token)
        session["display_name"] = display_name
        await _broadcast_lobby()
        return {"display_name": display_name}


@app.get("/api/rooms")
async def list_rooms(game_id: str = "rummy"):
    async with state_lock:
        await _expire_and_notify()
        return [
            _room_summary(room)
            for room in rooms.values()
            if room["game_id"] == game_id
            and room["visibility"] == "public"
            and room["status"] == "waiting"
            and len(room["players"]) < room["max_players"]
        ]


@app.post("/api/rooms")
async def create_room(
    request: CreateRoom,
    x_session_token: str | None = Header(default=None),
):
    async with state_lock:
        await _expire_and_notify()
        session = _current_session(x_session_token)
        if session["room_code"]:
            raise HTTPException(status_code=409, detail="Leave your current room before creating another.")
        game = SUPPORTED_GAMES.get(request.game_id)
        if not game or not game["available"]:
            raise HTTPException(status_code=404, detail="This game is not available yet.")
        if request.visibility not in {"public", "private"}:
            raise HTTPException(status_code=422, detail="Room visibility must be public or private.")
        if not game["min_players"] <= request.min_players <= request.max_players <= game["max_players"]:
            raise HTTPException(
                status_code=422,
                detail=f"{game['name']} rooms must allow {game['min_players']} to {game['max_players']} players.",
            )
        max_decks = request.game_options.get("max_decks", 2)
        if isinstance(max_decks, bool) or not isinstance(max_decks, int) or not 1 <= max_decks <= 4:
            raise HTTPException(status_code=422, detail="Maximum number of decks must be between 1 and 4.")
        scoring_mode = request.game_options.get("scoring_mode", "points")
        if not isinstance(scoring_mode, str) or scoring_mode not in {"points", "deals", "pool"}:
            raise HTTPException(status_code=422, detail="Choose Points, Deals, or Pool scoring.")
        deal_count = request.game_options.get("deal_count", 6)
        pool_limit = request.game_options.get("pool_limit")
        if isinstance(pool_limit, str) and len(pool_limit) <= 4300 and re.fullmatch(r"[0-9]+", pool_limit):
            pool_limit = int(pool_limit)
        if scoring_mode == "deals" and (
            isinstance(deal_count, bool) or not isinstance(deal_count, int) or deal_count not in {2, 3, 6, 10}
        ):
            raise HTTPException(status_code=422, detail="Deal Rummy must be configured for 2, 3, 6, or 10 deals.")
        if scoring_mode == "pool" and (
            isinstance(pool_limit, bool) or not isinstance(pool_limit, int) or pool_limit < 1
        ):
            raise HTTPException(status_code=422, detail="Pool Rummy limit must be a positive whole number.")
        game_options = {
            "max_decks": max_decks,
            "scoring_mode": scoring_mode,
            "deal_count": deal_count if scoring_mode == "deals" else None,
            "pool_limit": pool_limit if scoring_mode == "pool" else None,
        }

        code = _room_code()
        room = {
            "code": code,
            "game_id": request.game_id,
            "name": _normalize_name(request.room_name) or f"{game['name']} room",
            "visibility": request.visibility,
            "status": "waiting",
            "min_players": request.min_players,
            "max_players": request.max_players,
            "game_options": game_options,
            "host_token": x_session_token,
            "players": [x_session_token],
            "game": None,
            "created_at": time.time(),
        }
        rooms[code] = room
        session["room_code"] = code
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/join")
async def join_room(code: str, x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        session = _current_session(x_session_token)
        if session["room_code"]:
            raise HTTPException(status_code=409, detail="Leave your current room before joining another.")
        room = rooms.get(code.upper())
        if not room or room["status"] != "waiting":
            raise HTTPException(status_code=404, detail="That room is no longer available.")
        if len(room["players"]) >= room["max_players"]:
            raise HTTPException(status_code=409, detail="That room is full.")
        room["players"].append(x_session_token)
        session["room_code"] = room["code"]
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.get("/api/rooms/{code}")
async def get_room(code: str, x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"]:
            raise HTTPException(status_code=404, detail="You are not in that room.")
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/start")
async def start_game(code: str, x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"]:
            raise HTTPException(status_code=404, detail="You are not in that room.")
        if room["host_token"] != x_session_token:
            raise HTTPException(status_code=403, detail="Only the room host can start the game.")
        if room["status"] != "waiting" or room["game"]:
            raise HTTPException(status_code=409, detail="This room has already started.")
        if len(room["players"]) < room["min_players"]:
            raise HTTPException(status_code=409, detail="The room does not have enough players yet.")
        room["game"] = _new_game(room)
        room["status"] = "in_progress"
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/draw")
async def draw_card(
    code: str,
    request: DrawCard,
    x_session_token: str | None = Header(default=None),
):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"] or not room["game"]:
            raise HTTPException(status_code=404, detail="That active game was not found.")
        game = room["game"]
        if game["status"] != "playing" or game["turn_token"] != x_session_token or game["phase"] != "draw":
            raise HTTPException(status_code=409, detail="It is not your turn to draw.")
        if request.source == "stock":
            if not game["stock"] and len(game["discard_pile"]) > 1:
                top = game["discard_pile"].pop()
                game["stock"] = game["discard_pile"]
                secrets.SystemRandom().shuffle(game["stock"])
                game["discard_pile"] = [top]
            if not game["stock"]:
                raise HTTPException(status_code=409, detail="There are no cards left to draw.")
            card = game["stock"].pop()
        elif request.source == "discard":
            if not game["discard_pile"]:
                raise HTTPException(status_code=409, detail="The discard pile is empty.")
            if game["last_discarder"] == x_session_token:
                raise HTTPException(status_code=409, detail="You cannot pick up your own last discard.")
            card = game["discard_pile"].pop()
        else:
            raise HTTPException(status_code=422, detail="Draw source must be stock or discard.")
        game["hands"][x_session_token].append(card)
        game["phase"] = "discard"
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/discard")
async def discard_card(
    code: str,
    request: DiscardCard,
    x_session_token: str | None = Header(default=None),
):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"] or not room["game"]:
            raise HTTPException(status_code=404, detail="That active game was not found.")
        game = room["game"]
        if game["status"] != "playing" or game["turn_token"] != x_session_token or game["phase"] != "discard":
            raise HTTPException(status_code=409, detail="Draw a card before discarding.")
        hand = game["hands"][x_session_token]
        card = next((card for card in hand if card.card_id == request.card_id), None)
        if not card:
            raise HTTPException(status_code=404, detail="That card is not in your hand.")
        if len(hand) != 14:
            raise HTTPException(status_code=409, detail="A discard requires a 14-card hand.")
        hand.remove(card)
        game["discard_pile"].append(card)
        game["last_discarder"] = x_session_token
        current_index = game["active_tokens"].index(x_session_token)
        game["turn_token"] = game["active_tokens"][(current_index + 1) % len(game["active_tokens"])]
        game["phase"] = "draw"
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/declare")
async def declare_hand(
    code: str,
    request: DeclareHand,
    x_session_token: str | None = Header(default=None),
):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"] or not room["game"]:
            raise HTTPException(status_code=404, detail="That active game was not found.")
        game = room["game"]
        hand = game["hands"].get(x_session_token, [])
        if game["status"] != "playing" or game["turn_token"] != x_session_token or game["phase"] != "discard":
            raise HTTPException(status_code=409, detail="Draw a card before declaring.")
        if len(hand) != 14:
            raise HTTPException(status_code=409, detail="A declaration requires 14 cards before the final discard.")
        selected_ids = request.card_ids
        if len(set(selected_ids)) != 13:
            raise HTTPException(status_code=422, detail="Choose 13 different cards for your declaration.")
        selected = [card for card in hand if card.card_id in set(selected_ids)]
        if len(selected) != 13:
            raise HTTPException(status_code=422, detail="Your declaration contains a card not in your hand.")
        if not find_valid_partition(selected, game["wild_rank"]):
            raise HTTPException(
                status_code=422,
                detail="Invalid declaration. Make a valid 13-card hand with a pure sequence and a second sequence.",
            )
        discarded = next(card for card in hand if card.card_id not in set(selected_ids))
        game["discard_pile"].append(discarded)
        _finish_round(room, x_session_token)
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/next-round")
async def next_round(code: str, x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"] or not room["game"]:
            raise HTTPException(status_code=404, detail="That game was not found.")
        game = room["game"]
        if x_session_token != room["host_token"]:
            raise HTTPException(status_code=403, detail="Only the host can start the next deal.")
        if game["status"] != "round_over":
            raise HTTPException(status_code=409, detail="The current deal has not finished.")
        if room["game_options"]["scoring_mode"] == "points":
            raise HTTPException(status_code=409, detail="Points Rummy ends after one deal.")
        _start_next_round(room, game)
        await _broadcast_lobby()
        return _room_summary(room, x_session_token)


@app.post("/api/rooms/{code}/leave")
async def leave_room(code: str, x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        session = _current_session(x_session_token)
        room = rooms.get(code.upper())
        if not room or x_session_token not in room["players"]:
            raise HTTPException(status_code=404, detail="You are not in that room.")
        _remove_player_from_room(x_session_token)
        session["room_code"] = None
        await _broadcast_lobby()
        return {"status": "ok"}


@app.post("/api/session/heartbeat")
async def heartbeat(x_session_token: str | None = Header(default=None)):
    async with state_lock:
        await _expire_and_notify()
        _current_session(x_session_token)
        return {"status": "ok"}


@app.websocket("/ws/lobby")
async def lobby_websocket(websocket: WebSocket, token: str | None = None):
    async with state_lock:
        await _expire_and_notify()
        if not token or token not in sessions:
            await websocket.close(code=1008)
            return
        _current_session(token)
        await websocket.accept()
        lobby_connections[websocket] = token
    try:
        while True:
            await websocket.receive_text()
            async with state_lock:
                await _expire_and_notify()
                if token not in sessions:
                    await websocket.close(code=1008)
                    return
                _current_session(token)
    except WebSocketDisconnect:
        pass
    finally:
        async with state_lock:
            lobby_connections.pop(websocket, None)
