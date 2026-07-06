"""NiceGUI 前端应用入口。"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nicegui import app, ui

from web_ui.api_client import ApiClient
from web_ui.components import apply_theme, top_nav
from web_ui.pages.chat import build_chat
from web_ui.pages.home import build_home
from web_ui.pages.sign import build_sign
from web_ui.pages.voice import build_voice
from web_ui.state import FrontendSettings, SharedState
from web_ui.ws_client import WSClient


@dataclass
class AppContext:
    settings: FrontendSettings
    state: SharedState
    api: ApiClient
    ws: WSClient


WEB_UI_STATIC_DIR = Path(__file__).resolve().parent / 'static'
try:
    app.add_static_files('/static', str(WEB_UI_STATIC_DIR))
except RuntimeError:
    pass


def create_context() -> AppContext:
    settings = FrontendSettings(
        http_base=os.getenv('ORCH_HTTP_BASE', 'http://127.0.0.1:8001'),
        ws_url=os.getenv('ORCH_WS_URL', 'ws://127.0.0.1:8001/ws'),
        preview_url=os.getenv('PREVIEW_URL', 'http://127.0.0.1:8000'),
        togetheros_ws_port=int(os.getenv('TOGETHEROS_WS_PORT', '8080')),
        togetheros_ws_override=os.getenv('TOGETHEROS_WS_URL', '').strip() or None,
        togetheros_filter_prefix=os.getenv('TOGETHEROS_FILTER_PREFIX', ''),
    )
    state = SharedState()
    api_client = ApiClient(settings.http_base)

    def apply_sign_session(data: dict[str, Any]) -> None:
        words = [str(item) for item in (data.get('words') or []) if str(item).strip()]
        state.current_sign_session_id = data.get('session_id') or state.current_sign_session_id
        state.current_sign_status = data.get('status') or state.current_sign_status
        state.sign_summary_status = data.get('summary_status') or state.sign_summary_status
        state.sign_summary_error = data.get('summary_error') or ''
        state.recognized_sign_words = words[-30:]
        state.latest_sign_word = words[-1] if words else '—'
        raw_text = data.get('raw_text') or (' '.join(words) if words else '')
        summary_text = data.get('summary_text') or ''
        state.latest_sign_sentence = raw_text or '—'
        state.latest_chat_translation = state.latest_sign_sentence
        state.latest_sign_summary = summary_text or '—'
        state.latest_chat_reply = state.latest_sign_summary
        if data.get('status') == 'running':
            state.sign_running = True

    def apply_voice_session(data: dict[str, Any]) -> None:
        state.current_voice_session_id = data.get('session_id') or state.current_voice_session_id
        state.current_voice_status = data.get('status') or state.current_voice_status
        state.latest_voice_text = data.get('latest_text') or state.latest_voice_text or '—'
        state.latest_voice_tokens = data.get('latest_tokens') or state.latest_voice_tokens or '—'
        state.latest_voice_ids = list(data.get('latest_ids') or [])
        state.voice_convert_status = data.get('convert_status') or state.voice_convert_status
        state.voice_convert_error = data.get('convert_error') or ''
        state.voice_send_status = data.get('send_status') or state.voice_send_status
        state.voice_send_error = data.get('send_error') or ''
        state.set_voice_records(list(data.get('records') or []))
        if data.get('status') == 'running':
            state.voice_running = True

    def on_status(message: str) -> None:
        state.add_log(message)

    def on_event(event: dict[str, Any]) -> None:
        event_type = event.get('type')
        payload = event.get('payload') or {}
        if event_type == 'ros_log':
            proc = payload.get('proc', '')
            line = payload.get('line', '')
            if line:
                state.add_log(f'[{proc}] {line}')
        elif event_type == 'sign_runtime_state':
            state.add_log(f'SIGN_RUNTIME_STATE: {payload}')
        elif event_type == 'sign_diag':
            msg = payload.get('message') or ''
            if msg:
                state.add_log(f'SIGN_DIAG: {msg}')
        elif event_type == 'voice_diag':
            msg = payload.get('message') or ''
            if msg:
                state.add_log(f'VOICE_DIAG: {msg}')
        elif event_type not in {'mode_changed','kp_state','sign_state','sign_mode_changed','sign_session_reset','sign_word','sign_sentence','sign_summary_result','sign_summary_done','voice_state','voice_sentence','voice_convert_result','voice_send_result','chat_reply','chat_translation','chat_display_text','chat_display_arm'}:
            state.add_log(f'WS {event_type}: {payload}')

        if event_type == 'mode_changed':
            state.current_mode = payload.get('mode', state.current_mode)
        elif event_type == 'kp_state':
            state.kp_running = bool(payload.get('running', False))
            if not state.kp_running:
                state.sign_running = False
        elif event_type in ('sign_state', 'iso_state'):
            state.sign_running = bool(payload.get('running', False))
            state.current_sign_session_id = payload.get('session_id') or state.current_sign_session_id
        elif event_type == 'sign_mode_changed':
            state.sign_mode = payload.get('mode', state.sign_mode)
        elif event_type == 'sign_session_reset':
            state.current_sign_session_id = payload.get('session_id') or ''
            state.current_sign_status = 'running'
            state.sign_summary_status = payload.get('summary_status') or 'pending'
            state.sign_summary_error = ''
            state.latest_sign_word = '—'
            state.latest_sign_sentence = '—'
            state.latest_sign_summary = '—'
            state.recognized_sign_words = []
        elif event_type == 'sign_word':
            state.current_sign_session_id = payload.get('session_id') or state.current_sign_session_id
            state.current_sign_status = 'running'
            state.sign_summary_status = 'pending'
            state.sign_summary_error = ''
            state.latest_sign_word = payload.get('label') or payload.get('text') or '—'
            if state.latest_sign_word and state.latest_sign_word != '—':
                if not state.recognized_sign_words or state.recognized_sign_words[-1] != state.latest_sign_word:
                    state.recognized_sign_words.append(state.latest_sign_word)
                    state.recognized_sign_words = state.recognized_sign_words[-30:]
            state.latest_sign_sentence = payload.get('raw_text') or (' '.join(state.recognized_sign_words) if state.recognized_sign_words else '—')
            state.latest_chat_translation = state.latest_sign_sentence
        elif event_type == 'sign_sentence':
            state.current_sign_session_id = payload.get('session_id') or state.current_sign_session_id
            state.latest_sign_sentence = payload.get('text') or payload.get('sentence') or '—'
            state.latest_chat_translation = state.latest_sign_sentence
            if payload.get('summary_status'):
                state.sign_summary_status = payload.get('summary_status') or state.sign_summary_status
        elif event_type == 'sign_summary_result':
            state.current_sign_session_id = payload.get('session_id') or state.current_sign_session_id
            state.current_sign_status = 'stopped'
            state.sign_summary_status = payload.get('summary_status') or state.sign_summary_status
            state.sign_summary_error = payload.get('summary_error') or ''
            state.latest_sign_summary = payload.get('text') or '—'
            state.latest_chat_reply = state.latest_sign_summary
        elif event_type == 'sign_summary_done':
            state.current_sign_session_id = payload.get('session_id') or state.current_sign_session_id
            state.current_sign_status = 'stopped'
            state.sign_summary_status = payload.get('summary_status') or state.sign_summary_status
            state.sign_summary_error = payload.get('summary_error') or ''
            state.latest_sign_sentence = payload.get('summary_text') or payload.get('raw_text') or state.latest_sign_sentence
            state.latest_chat_translation = state.latest_sign_sentence
            state.latest_sign_summary = payload.get('summary_text') or state.latest_sign_summary
            state.latest_chat_reply = state.latest_sign_summary
        elif event_type == 'voice_state':
            state.voice_running = bool(payload.get('running', False))
            state.current_voice_session_id = payload.get('session_id') or state.current_voice_session_id
            if payload.get('latest_text'):
                state.latest_voice_text = payload.get('latest_text') or state.latest_voice_text
            if payload.get('latest_tokens'):
                state.latest_voice_tokens = payload.get('latest_tokens') or state.latest_voice_tokens
            if payload.get('latest_ids') is not None:
                state.latest_voice_ids = list(payload.get('latest_ids') or [])
            state.current_voice_status = 'running' if state.voice_running else 'stopped'
        elif event_type == 'voice_sentence':
            state.current_voice_session_id = payload.get('session_id') or state.current_voice_session_id
            state.current_voice_status = 'running'
            state.latest_voice_text = payload.get('text') or state.latest_voice_text
            state.set_voice_records(list(payload.get('records') or state.voice_records))
        elif event_type == 'voice_convert_result':
            state.current_voice_session_id = payload.get('session_id') or state.current_voice_session_id
            state.latest_voice_text = payload.get('text') or state.latest_voice_text
            state.latest_voice_tokens = payload.get('token_text') or '—'
            state.voice_convert_status = payload.get('convert_status') or state.voice_convert_status
            state.voice_convert_error = payload.get('convert_error') or ''
            state.set_voice_records(list(payload.get('records') or state.voice_records))
        elif event_type == 'voice_send_result':
            state.current_voice_session_id = payload.get('session_id') or state.current_voice_session_id
            state.latest_voice_ids = list(payload.get('ids') or [])
            state.voice_send_status = payload.get('send_status') or state.voice_send_status
            state.voice_send_error = payload.get('send_error') or ''
            state.set_voice_records(list(payload.get('records') or state.voice_records))
        elif event_type == 'chat_reply':
            user_text = payload.get('user') or ''
            summary_text = payload.get('ai') or payload.get('text') or ''
            if user_text:
                state.latest_chat_translation = user_text
                state.add_chat_message('user', user_text)
            if summary_text:
                state.latest_chat_reply = summary_text
                state.latest_chat_tokens = payload.get('token_text') or summary_text
                state.add_chat_message('ai', summary_text)
        elif event_type == 'chat_translation':
            state.latest_chat_translation = payload.get('text') or state.latest_chat_translation
        elif event_type == 'chat_display_text':
            state.latest_text_display = payload.get('text') or state.latest_text_display
        elif event_type == 'chat_display_arm':
            state.latest_chat_tokens = payload.get('token_text') or state.latest_chat_tokens
            state.latest_chat_ids = list(payload.get('ids') or [])
            state.chat_send_status = payload.get('send_status') or state.chat_send_status
            state.chat_send_error = payload.get('send_error') or ''
            state.latest_arm_display = payload.get('text') or state.latest_arm_display

    ws_client = WSClient(settings.ws_url, on_event=on_event, on_status=on_status)
    ctx = AppContext(settings=settings, state=state, api=api_client, ws=ws_client)
    ctx.apply_sign_session = apply_sign_session  # type: ignore[attr-defined]
    ctx.apply_voice_session = apply_voice_session  # type: ignore[attr-defined]
    return ctx


APP_CTX = create_context()


async def initial_sync() -> None:
    try:
        data = await APP_CTX.api.get_state()
        APP_CTX.state.current_mode = data.get('mode', APP_CTX.state.current_mode)
        APP_CTX.state.sign_mode = data.get('sign_mode', APP_CTX.state.sign_mode)
    except Exception as exc:
        APP_CTX.state.add_log(f'Initial state sync failed: {exc}')
    try:
        info = await APP_CTX.api.get_system_info()
        APP_CTX.state.system_info = info
        if info.get('preview_url'):
            APP_CTX.settings.preview_url = info['preview_url']
    except Exception as exc:
        APP_CTX.state.add_log(f'Initial system info sync failed: {exc}')
    try:
        sign_session = await APP_CTX.api.get_current_sign_session()
        APP_CTX.apply_sign_session(sign_session)  # type: ignore[attr-defined]
    except Exception as exc:
        APP_CTX.state.add_log(f'Initial sign session sync failed: {exc}')
    try:
        voice_session = await APP_CTX.api.get_current_voice_session()
        APP_CTX.apply_voice_session(voice_session)  # type: ignore[attr-defined]
    except Exception as exc:
        APP_CTX.state.add_log(f'Initial voice session sync failed: {exc}')


def render_layout() -> None:
    apply_theme()
    top_nav()


def setup_app() -> None:
    @app.on_startup
    async def _startup() -> None:
        await initial_sync()
        APP_CTX.ws.start()

    @app.on_shutdown
    async def _shutdown() -> None:
        APP_CTX.ws.stop()
        await asyncio.sleep(0.1)

    @ui.page('/')
    async def home_page() -> None:
        render_layout()
        await build_home(APP_CTX)

    @ui.page('/sign')
    async def sign_page() -> None:
        render_layout()
        await build_sign(APP_CTX)

    @ui.page('/voice')
    async def voice_page() -> None:
        render_layout()
        await build_voice(APP_CTX)

    @ui.page('/chat')
    async def chat_page() -> None:
        render_layout()
        await build_chat(APP_CTX)


setup_app()


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(host=os.getenv('WEB_UI_HOST', '0.0.0.0'), port=int(os.getenv('WEB_UI_PORT', '8081')), title='RDK X5 NiceGUI Web UI', reload=False, show=False)
