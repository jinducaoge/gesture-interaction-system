from __future__ import annotations
import asyncio
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from utils.ids import new_job_id

logger = logging.getLogger("services.serial_stub")

@dataclass
class SerialState:
    status: str = "IDLE"      # IDLE | BUSY
    current_id: Optional[int] = None
    queue_len: int = 0
    last_error: Optional[str] = None

class SerialStub:
    """Serial service stub.
    Requirements:
      1) all calls never raise
      2) return structures consistent with future real impl
      3) periodically push arm_state events for UI/dev
    """

    def __init__(self, *, tick_s: float = 1.0) -> None:
        self._tick_s = tick_s
        self._queue: asyncio.Queue[int] = asyncio.Queue()
        self._state = SerialState()
        self._job_id: Optional[str] = None
        self._task: Optional[asyncio.Task] = None
        self._stop_evt = asyncio.Event()
        self._push_event: Optional[Callable[[dict], "asyncio.Future[None]"]] = None

    def bind_event_pusher(self, push_event: Callable[[dict], "asyncio.Future[None]"]) -> None:
        self._push_event = push_event

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop_evt.clear()
        self._task = asyncio.create_task(self._run_loop())
        logger.info("serial stub started")

    async def stop(self) -> None:
        self._stop_evt.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                pass
        self._task = None
        logger.info("serial stub stopped")

    def enqueue_job(self, ids: List[int]) -> Dict[str, Any]:
        """Enqueue IDs for execution; returns job_id."""
        try:
            self._job_id = new_job_id()
            if ids:
                for _id in ids:
                    self._queue.put_nowait(int(_id))
            self._state.status = "BUSY" if self._queue.qsize() > 0 else "IDLE"
            self._state.queue_len = self._queue.qsize()
            self._state.last_error = None
            return {"job_id": self._job_id, "accepted": True, "queue_len": self._state.queue_len}
        except Exception as e:
            # never throw
            self._state.last_error = str(e)
            return {"job_id": self._job_id or new_job_id(), "accepted": False, "error": str(e), "queue_len": self._queue.qsize()}

    def get_state(self) -> Dict[str, Any]:
        try:
            self._state.queue_len = self._queue.qsize()
            return {
                "status": self._state.status,
                "current_id": self._state.current_id,
                "queue_len": self._state.queue_len,
                "job_id": self._job_id,
                "last_error": self._state.last_error,
            }
        except Exception as e:
            return {"status": "UNKNOWN", "current_id": None, "queue_len": 0, "job_id": self._job_id, "last_error": str(e)}

    def stop_all(self) -> Dict[str, Any]:
        try:
            while not self._queue.empty():
                self._queue.get_nowait()
                self._queue.task_done()
            self._state.status = "IDLE"
            self._state.current_id = None
            self._state.queue_len = 0
            self._state.last_error = None
            return {"stopped": True}
        except Exception as e:
            self._state.last_error = str(e)
            return {"stopped": False, "error": str(e)}

    async def _emit_arm_state(self) -> None:
        if not self._push_event:
            return
        payload = self.get_state()
        evt = {
            "type": "arm_state",
            "ts": __import__("time").time(),
            "job_id": payload.get("job_id"),
            "payload": payload
        }
        try:
            await self._push_event(evt)
        except Exception:
            # ignore
            pass

    async def _run_loop(self) -> None:
        # Periodically consumes queue and emits state.
        while not self._stop_evt.is_set():
            try:
                if self._queue.qsize() > 0:
                    self._state.status = "BUSY"
                    _id = await self._queue.get()
                    self._state.current_id = _id
                    self._queue.task_done()
                    self._state.queue_len = self._queue.qsize()
                else:
                    self._state.status = "IDLE"
                    self._state.current_id = None
                    self._state.queue_len = 0
                await self._emit_arm_state()
            except Exception as e:
                self._state.last_error = str(e)
                await self._emit_arm_state()
            await asyncio.sleep(self._tick_s)
