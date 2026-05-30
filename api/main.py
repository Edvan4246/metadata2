"""
FastAPI application entry point.

Starts the trading bot as a background task and serves:
  - REST API at /api/*
  - WebSocket feed at /ws
  - Static dashboard at /
"""
import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from api.routes import router, set_bot
from api.websocket_manager import WebSocketManager
from bot.trading_bot import TradingBot
from core.mt5_client import MT5Client
from config.settings import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

ws_manager = WebSocketManager()
bot: TradingBot = None
_bot_task: asyncio.Task = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot, _bot_task

    client = MT5Client(
        login=settings.mt5_login,
        password=settings.mt5_password,
        server=settings.mt5_server,
        magic=settings.magic_number,
    )

    bot = TradingBot(client=client, symbols=settings.symbols_list())
    bot.register_state_callback(ws_manager.broadcast)
    set_bot(bot)

    _bot_task = asyncio.create_task(_run_bot(bot))
    logger.info("Bot task started")

    yield

    logger.info("Shutting down…")
    await bot.stop()
    if _bot_task:
        _bot_task.cancel()


async def _run_bot(bot: TradingBot):
    try:
        await bot.start()
    except Exception as exc:
        logger.exception("Bot crashed: %s", exc)


app = FastAPI(
    title="Forex Trading Bot",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        # Send current state immediately on connect
        if bot:
            await ws.send_json(bot.get_state())
        while True:
            # Keep connection alive; bot pushes updates via callback
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


DASHBOARD_PATH = os.path.join(os.path.dirname(__file__), "..", "dashboard", "index.html")


@app.get("/")
async def serve_dashboard():
    if os.path.exists(DASHBOARD_PATH):
        return FileResponse(DASHBOARD_PATH)
    return {"message": "Forex Trading Bot API", "docs": "/docs"}


if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level=settings.log_level.lower(),
    )
