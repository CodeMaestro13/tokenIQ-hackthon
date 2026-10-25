from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
import asyncio
import json
import logging

from delta_client import DeltaClient
from strategy import Strategy

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Simple WebSocket App")

# Shared instances
client = DeltaClient()
strategy = Strategy()


class ConnectionManager:
    """Manage active WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected. Total: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client disconnected. Total: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"Broadcast error: {e}")
                self.disconnect(connection)


manager = ConnectionManager()


@app.get("/")
async def get_index():
    return HTMLResponse("""
    <html>
      <head><title>WS Demo</title></head>
      <body>
        <h1>WebSocket Demo</h1>
        <div id="log" style="font-family: monospace; white-space: pre;"></div>
        <script>
          const ws = new WebSocket(`ws://${location.host}/ws`);
          const log = document.getElementById('log');
          ws.onmessage = (e) => { log.textContent += e.data + "\\n"; };
          ws.onopen = () => {
            ws.send(JSON.stringify({type: "ping"}));
          };
          setInterval(() => {
            if (ws.readyState === 1) {
              ws.send(JSON.stringify({type: "tick", price: Math.random() * 100}));
            }
          }, 2000);
        </script>
      </body>
    </html>
    """)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "invalid JSON"})
                continue

            msg_type = message.get("type")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "tick":
                price = message.get("price", 0)
                signal = strategy.on_tick(price)
                await websocket.send_json({
                    "type": "signal",
                    "price": price,
                    "signal": signal,
                })

                # Optionally query mock client data
                quote = await client.get_quote("BTCUSD")
                await websocket.send_json({"type": "quote", "data": quote})

            else:
                await websocket.send_json({"error": f"unknown type: {msg_type}"})

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        manager.disconnect(websocket)


@app.get("/health")
async def health():
    return {"status": "ok", "connections": len(manager.active_connections)}


# Optional: background task broadcasting server ticks
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_broadcast())


async def background_broadcast():
    while True:
        await asyncio.sleep(10)
        if manager.active_connections:
            await manager.broadcast({
                "type": "heartbeat",
                "message": "server alive",
            })