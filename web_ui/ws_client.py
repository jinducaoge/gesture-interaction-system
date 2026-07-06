"""orchestrator WebSocket 客户端。"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Callable
from typing import Any

import websockets


class WSClient:
    """后台线程版 WebSocket 客户端。

    说明：
    - NiceGUI 本身已有自己的 WebSocket，不适合直接复用页面连接。
    - 这里单独启动一个到 orchestrator 的后台连接。
    - 收到消息后通过 Python 回调更新共享状态。
    """

    def __init__(
        self,
        url: str,
        on_event: Callable[[dict[str, Any]], None],
        on_status: Callable[[str], None] | None = None,
    ) -> None:
        self.url = url
        self.on_event = on_event
        self.on_status = on_status or (lambda message: None)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """启动后台连接线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台连接线程。"""
        self._stop_event.set()

    def _run(self) -> None:
        """在线程中运行异步事件循环。"""
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        """自动重连循环。"""
        while not self._stop_event.is_set():
            try:
                self.on_status(f"WS connecting: {self.url}")
                async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as websocket:
                    self.on_status("WS connected")
                    while not self._stop_event.is_set():
                        try:
                            message = await asyncio.wait_for(websocket.recv(), timeout=10)
                            event = json.loads(message)
                            self.on_event(event)
                        except asyncio.TimeoutError:
                            await websocket.send("ping")
                        except json.JSONDecodeError:
                            self.on_status("WS invalid json")
                        except websockets.ConnectionClosed:
                            self.on_status("WS disconnected")
                            break
            except Exception as exc:
                self.on_status(f"WS error: {exc}")
            await asyncio.sleep(2)
