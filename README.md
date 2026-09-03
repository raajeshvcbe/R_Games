# R_Games
Game Platform — Step 1: Deploy Skeleton
This is intentionally NOT the Rummy game yet. It's the smallest possible app that proves your deployment pipeline (GitHub → Render → live WebSocket) actually works. Once this is live, we add the room/chat/game logic on top of the exact same pattern.
What's here
main.py — a FastAPI app with:
/ — health check
/test — a page that opens a WebSocket and echoes messages between everyone connected (open it in two tabs to see it work)
/ws — the WebSocket endpoint itself
requirements.txt — dependencies
Steps to deploy
1. Push this to GitHub
Create a free GitHub account if you don't have one: https://github.com/signup
Create a new repository (e.g. game-platform)
Upload these 3 files to it (via the GitHub web UI "Add file → Upload files", or git push if you're comfortable with git)
2. Create a Render account
Go to https://render.com and sign up free (no card needed)
Click New → Web Service
Connect your GitHub account, select the game-platform repo
3. Configure the service
When Render asks for settings, use:
Runtime: Python 3
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Instance Type: Free
Click Create Web Service. First deploy takes a couple of minutes.
4. Test it
Render gives you a URL like https://game-platform-xxxx.onrender.com.
Visit / — you should see {"status": "ok", ...}
Visit /test on your phone AND your laptop at the same time, type a message on one, and confirm it appears on the other instantly.
If that works, the whole pipeline is proven: your server is live, and real-time sync between two different devices works. That's the foundation everything else (Rummy, then Ludo) gets built on.
Next step
Once this is deployed and the two-tab test works, come back and we'll add: room codes, player join, deck shuffle/deal, hands, and chat.