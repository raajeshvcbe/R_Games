# Game Platform — Spec

Living document. Add to it as your thinking evolves — each new section should
say whether it's a **confirmed requirement** or an **open question**.

---

## 1. Vision

A web/mobile platform to play small games — both multiplayer (Rummy, Ludo)
and single-player (Solitaire) — where the app handles setup mechanics
(shuffling, dealing, turn tracking, room management, chat) but players make
all actual game decisions themselves — no AI/bot opponents.

---

## 2. User / Identity

- A user must choose a **username** to play. No account, no password —
  identity is just the username for that session.
- Usernames must be **unique among currently active users** — two people
  can't hold the same username at the same time.
- When a user **exits** (leaves/disconnects), their username is released
  and becomes available for anyone to use again.
- **Consequence:** identity is ephemeral, tied to the active session, not
  a persistent account. There is no "login" — just "claim a name."

### Open question / suggestion
- What counts as "exit"? A closed tab and a dropped WiFi connection look
  identical to the server at first. Recommend a **short grace period**
  (e.g. 30–60 seconds) before releasing the username and removing the
  player from their room — otherwise a brief network blip mid-game kicks
  them out and frees their seat to someone else mid-round. During the
  grace period, if they reconnect with the same username, they resume
  their seat.

---

## 3. Game & Room Model

- A user selects **one game** (e.g. Rummy) from the available games.
- Within that game, the user either:
  - **Joins an available room**, or
  - **Creates a new room**.
- Rooms support both **single-player** and **multiplayer** modes — the
  room concept applies either way.
- A user can only be **active in one game/room at a time.**
- A player can **exit a room** and then **join a different room** (if one
  is available).

### Open questions / suggestions
- **"Available" room** — recommend defining this as: room exists, game
  hasn't started yet (still in lobby/waiting state), and isn't full.
  Rooms that are mid-game shouldn't show as joinable.
- **Room discovery** — two patterns, not mutually exclusive:
  - **Public list**: browse open rooms for a given game and tap to join.
  - **Private code**: create a room, share a short code with specific
    friends (this was the original Rummy plan). Suggest supporting a
    `private: true/false` flag per room so both patterns work from day one.
- **Room cleanup** — when the last player leaves a room, recommend
  auto-closing/deleting it rather than leaving empty rooms around.
- ~~Single-player mode meaning~~ **Resolved:** single-player rooms are for
  games like **Solitaire**, which are inherently one-player and need no
  opponent — not applicable to Rummy/Ludo. So a room's mode (single vs.
  multiplayer) is really a property of the **game itself**, not something
  every game supports both ways. Suggest each game declares its own
  `min_players` / `max_players` (Solitaire: 1/1, Rummy: 2/6, Ludo: 2/4),
  and the room model just enforces whatever that game declares — no
  separate "single-player toggle" needed.
- **One game at a time — enforcement** — if a user tries to join/create a
  second room while already active in one, recommend either (a) blocking
  the action with "leave your current room first," or (b) auto-leaving
  the old room. (a) is safer — avoids surprise exits mid-game.
- **Max players per room** — likely varies per game (Rummy: 2–6, Ludo:
  2–4). Suggest this be a per-game config value, not hardcoded globally.

---

## 4. Architecture implications (from discussion so far)

- One shared **session/lobby layer** tracks: active usernames, which
  room/game each user is currently in, and room lifecycle (open → full →
  in-progress → closed).
- Each game (rummy, ludo, ...) is a **separate module** with its own state
  and rules, plugging into the shared session/room/chat layer — so adding
  a new game doesn't mean rebuilding user/room handling.
- Real-time sync via WebSockets (per earlier decision to host on Render).

---

## 6. Platform structure (reference: poki.com)

Poki is a useful reference for the **game catalog / browsing layer** — not
for room/multiplayer mechanics, since Poki's multiplayer games run their
own logic inside each embedded game, invisible to the platform shell.
Patterns worth borrowing:

- **One dedicated page per game**, clean URL pattern (e.g. `/games/rummy`,
  `/games/ludo`, `/games/solitaire`).
- **Home page = a browsable catalog**, grouped by category, not a flat
  list. For us, categories are more like: `Multiplayer`, `Single Player`,
  `Card Games`, `Board Games` — small now, but keeps the model extensible
  as more games are added.
- **Click straight into play** — no account/signup friction, just a
  username to claim (matches Section 2 already).
- A **game's own page** is where the "join available room / create room"
  flow lives (Section 3) — the home catalog just routes you there.

### Open question / suggestion
- Once there are enough games, consider a "Popular now" or "Currently
  active rooms" strip on the home page — shows which games have people
  actively playing, nudges users toward joinable rooms instead of empty
  ones.

---

## 7. Not yet decided (parking lot)

- Reconnect/grace-period exact duration
- Public room list vs. private code — support both, or pick one first?
- Per-game player limits
- What "single player" room means across different games
- Chat scope: per-room only, or also a global lobby chat before joining a room?

---

*Next: once you add more thoughts, we'll turn Sections 2–4 into actual
data models (User, Room, Game) and the WebSocket message contract between
client and server.*
