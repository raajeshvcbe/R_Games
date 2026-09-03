"""
Step 1 skeleton: prove FastAPI + WebSockets work on Render.
No game logic yet on purpose — get this deployed and working first.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

app = FastAPI()


@app.get("/")
def health_check():
    """Render (and you) can hit this to confirm the server is alive."""
    return {"status": "ok", "message": "Game server is running"}


@app.get("/test", response_class=HTMLResponse)
def test_page():
    """
    A bare-bones page that opens a WebSocket to /ws and echoes messages.
    Open this in two browser tabs (or two phones) to confirm real-time
    messages travel between clients through the server.
    """
    return """
    <html>
      <body style="font-family: sans-serif; padding: 20px;">
        <h2>WebSocket Test</h2>
        <input id="msg" placeholder="Type a message" />
        <button onclick="send()">Send</button>
        <ul id="log"></ul>
        <script>
          const ws = new WebSocket(
            (location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws"
          );
          ws.onmessage = (event) => {
            const li = document.createElement("li");
            li.textContent = event.data;
            document.getElementById("log").appendChild(li);
          };
          function send() {
            const input = document.getElementById("msg");
            ws.send(input.value);
            input.value = "";
          }
        </script>
      </body>
    </html>
    """


# Keep track of everyone currently connected, so we can broadcast to all of them.
connected_clients: list[WebSocket] = []


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Broadcast to every connected client (this is the pattern
            # the real game — room state, chat, turns — will reuse).
            for client in connected_clients:
                await client.send_text(data)
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
