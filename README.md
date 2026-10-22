# R_Games

A small multiplayer game platform. Rummy is the first playable game; Ludo and
Solitaire appear in the catalog as coming soon.

## Current features

- Game catalog with Rummy available and Ludo/Solitaire marked as coming soon.
- Temporary unique usernames (no account or password) and editable player names.
- Public rooms and private rooms joinable by six-character code.
- Rummy room settings for minimum/maximum players, maximum decks, and scoring
  format.
- Join/leave room flows and automatic cleanup after the last player leaves.
- Live waiting-room and game-state updates over WebSockets.
- 13-card Indian Rummy: draw/discard turns, printed and wild jokers, valid
  declarations, and scoring. Players can manually group cards in their own
  hand into pairs or other groups; grouping is only for arranging cards and
  does not check or suggest combinations.
- Points Rummy (one deal), Deals Rummy (2/3/6/10 deals), and Pool Rummy
  (a creator-selected positive whole-number elimination limit).

The implemented hand rules require one pure sequence and a second sequence.
Ace can be low or high but does not wrap; a losing hand is capped at 80 points.
The game selects the fewest decks needed for the seated players, subject to
the room's maximum-decks setting.

Rooms and usernames are held in server memory. They are temporary and will be
cleared when the service restarts; this initial deployment is intended for trying
the flow, not as durable production storage. Inactive sessions expire after
90 seconds. An open browser tab sends WebSocket heartbeats.

## Project structure

- `app/main.py` contains the platform API, rooms, sessions, and WebSocket handling.
- `app/games/<game>/` contains each game's rules and game-specific logic.
- `static/` contains the browser client.
- `tests/platform/` contains platform and API tests.
- `tests/games/<game>/` contains tests for each game's rules.

## Run locally

```powershell
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. The health endpoint is http://localhost:8000/health.

## Run tests

```powershell
pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

## Deploy on Render

The `render.yaml` Blueprint configures the Python web service. Push the project
to GitHub, then in Render choose **New → Blueprint** and select this repository.
For a manual Web Service, choose **Python** (not Docker) with:

- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`

After deploy, open the service URL and try creating a public room. Open the URL
in a second browser or device with a different username to join it.
