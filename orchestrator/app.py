from __future__ import annotations
import logging
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware

from orchestrator.ws_manager import WSManager
from orchestrator.routes import router
from orchestrator.task_hub import TaskHub
from services.serial_stub import SerialStub
from utils.logging import setup_logging
from utils.ids import new_request_id

logger = logging.getLogger("orchestrator.app")


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="RDK Orchestrator (Framework)", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.ws = WSManager()
    app.state.serial = SerialStub()
    app.state.tasks = TaskHub()
    app.state.current_mode = "SIGN"
    app.state.current_sign_mode = os.getenv("DEFAULT_SIGN_MODE", "SENTENCE")

    async def push_evt(evt: dict):
        await app.state.ws.broadcast(evt)

    app.state.serial.bind_event_pusher(push_evt)
    app.state.tasks.bind_pusher(push_evt)
    app.state.tasks.bind_serial_service(app.state.serial)

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        request_id = new_request_id()
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.on_event("startup")
    async def _startup():
        await app.state.serial.start()
        await app.state.tasks.playback_service.start()
        logger.info("orchestrator startup ok")

    @app.on_event("shutdown")
    async def _shutdown():
        await app.state.serial.stop()
        await app.state.tasks.stop_kp()
        await app.state.tasks.stop_sign()
        await app.state.tasks.stop_voice()
        try:
            await app.state.tasks.stop_chat_stack()
        except Exception:
            pass
        try:
            await app.state.tasks.playback_service.close()
        except Exception:
            pass
        logger.info("orchestrator shutdown ok")

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await app.state.ws.connect(ws)
        try:
            while True:
                _ = await ws.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception:
            pass
        finally:
            await app.state.ws.disconnect(ws)

    app.include_router(router)
    return app


app = create_app()
