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

- Reconnect behavior when a session expires after 90 seconds
- Confirm per-game player limits against each game's final rules
- Chat scope: per-room only, or also a global lobby chat before joining a room?

## 8. First implementation slice — **current implementation**

- The home page presents a game catalog. Rummy is the first available game;
  Ludo and Solitaire are visible as coming soon.
- Rummy players can create a public room or a private room with a shareable
  code, or join a public waiting room/private room by code.
- Rummy room settings include a minimum and maximum player count, plus a
  configurable maximum number of decks. The initial limits are 2–6 players;
  the game uses the fewest decks needed for the current seats, subject to the
  room's 1–4 maximum-deck setting.
- Indian 13-card Rummy is playable: the host starts a deal; players draw from
  the stock or discard pile, then discard or declare. A declaration must use
  all 13 cards in melds, with at least one pure sequence and a second sequence.
  Printed jokers and a randomly selected wild rank are supported. Ace can be
  low or high, but sequences do not wrap. Players can manually group selected
  cards into pairs or other groups to arrange their own hand; the game does not
  suggest or validate those groups.
- Points Rummy ends after one deal; Deals Rummy supports 2, 3, 6, or 10 deals;
  Pool Rummy uses a positive whole-number elimination limit selected by the
  room creator. Losing hands score up to 80 points.
- A player claims a unique temporary username, starts with that as their
  display name, and can change their display name while active.
- A player can only be in one room at a time. Leaving the final seat removes
  the room; if the host leaves, another player becomes host.
- Initial lobby state is held in process memory and is not durable across a
  service restart. Inactive sessions expire after 90 seconds; the browser
  refreshes its activity heartbeat while open.
- Lobby and game state changes are sent over WebSockets; each player's hand is
  only returned to that player.

### Open questions for future improvements

- Whether reconnect grace periods should preserve a seat after the temporary
  session timeout.
- Durable/shared storage for rooms and usernames before production use.
- Whether to add voluntary drop/invalid-declaration penalties and alternate
  scoring settings.

---

*Next: validate the chosen Rummy rules with players, then add any requested
scoring, reconnect, or production-persistence improvements.*
