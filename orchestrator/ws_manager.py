from __future__ import annotations
import asyncio
import json
import logging
from typing import Set
from fastapi import WebSocket

logger = logging.getLogger("orchestrator.ws")

class WSManager:
    def __init__(self) -> None:
        self._conns: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._conns.add(ws)
        logger.info(f"ws connected, total={len(self._conns)}")

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._conns.discard(ws)
        logger.info(f"ws disconnected, total={len(self._conns)}")

    async def broadcast(self, message: dict) -> None:
        data = json.dumps(message, ensure_ascii=False)
        async with self._lock:
            conns = list(self._conns)
        if not conns:
            return
        dead = []
        for ws in conns:
            try:
                await ws.send_text(data)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._conns.discard(ws)
            logger.warning(f"cleaned dead conns={len(dead)}, total={len(self._conns)}")
