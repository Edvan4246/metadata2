"""
WebSocket connection manager — broadcasts bot state to all connected dashboard clients.
"""
import json
import logging
from typing import Set

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)
        logger.debug("WS client connected | total=%d", len(self._connections))

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)
        logger.debug("WS client disconnected | total=%d", len(self._connections))

    async def broadcast(self, data: dict):
        if not self._connections:
            return
        message = json.dumps(data)
        dead = set()
        for ws in self._connections:
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        self._connections -= dead
