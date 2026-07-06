"""网页前端共享状态模块。"""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import Lock
from urllib.parse import parse_qs, urlparse
from typing import Any


@dataclass
class FrontendSettings:
    http_base: str = "http://127.0.0.1:8001"
    ws_url: str = "ws://127.0.0.1:8001/ws"
    preview_url: str = "http://127.0.0.1:8000"
    togetheros_ws_port: int = 8080
    togetheros_ws_override: str | None = None
    togetheros_filter_prefix: str = ""
    togetheros_proto_url: str = "/static/togetheros/x3.proto"

    def _parsed_preview(self):
        return urlparse((self.preview_url or '').strip())

    def _normalized_preview_path(self) -> str:
        raw = (self.preview_url or '').strip()
        if not raw:
            return ''
        parsed = self._parsed_preview()
        candidate = parsed.path if (parsed.scheme or parsed.netloc) else raw
        return candidate.strip().strip('/')

    def resolved_togetheros_ws_url(self) -> str:
        if self.togetheros_ws_override:
            return self.togetheros_ws_override
        parsed = self._parsed_preview()
        host = parsed.hostname or '127.0.0.1'
        scheme = 'wss' if parsed.scheme == 'https' else 'ws'
        return f"{scheme}://{host}:{int(self.togetheros_ws_port)}"

    def resolved_togetheros_filter_prefix(self) -> str:
        explicit_setting = (self.togetheros_filter_prefix or '').strip().strip('/')
        if explicit_setting:
            return explicit_setting
        parsed = self._parsed_preview()
        query = parse_qs(parsed.query) if parsed.query else {}
        explicit_query = (query.get('filter_prefix') or [''])[0].strip().strip('/')
        if explicit_query:
            return explicit_query
        netid = (query.get('netid') or [''])[0].strip()
        camera = (query.get('camera') or [''])[0].strip()
        target_id = (query.get('id') or [''])[0].strip()
        if netid and camera and target_id:
            return f"{netid}/{camera}/{target_id}"
        path_prefix = self._normalized_preview_path()
        if path_prefix.count('/') >= 2 and 'TogetheROS' not in path_prefix:
            return path_prefix
        return ''

    def official_togetheros_page_url(self) -> str:
        parsed = self._parsed_preview()
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}".rstrip('/') + '/TogetheROS/'
        return '/'


@dataclass
class SharedState:
    current_mode: str = 'SIGN'
    sign_mode: str = 'SENTENCE'
    kp_running: bool = False
    sign_running: bool = False
    voice_running: bool = False
    current_sign_session_id: str = ''
    current_sign_status: str = 'idle'
    sign_summary_status: str = 'idle'
    sign_summary_error: str = ''
    latest_sign_word: str = '—'
    latest_sign_sentence: str = '—'
    latest_sign_summary: str = '—'
    current_voice_session_id: str = ''
    current_voice_status: str = 'idle'
    latest_voice_text: str = '—'
    latest_voice_tokens: str = '—'
    latest_voice_ids: list[int] = field(default_factory=list)
    voice_convert_status: str = 'idle'
    voice_convert_error: str = ''
    voice_send_status: str = 'idle'
    voice_send_error: str = ''
    voice_error: str = ''
    latest_chat_translation: str = '—'
    latest_chat_reply: str = '—'
    latest_chat_tokens: str = '—'
    latest_chat_ids: list[int] = field(default_factory=list)
    chat_send_status: str = 'idle'
    chat_send_error: str = ''
    latest_text_display: str = '—'
    latest_arm_display: str = '—'
    logs: list[str] = field(default_factory=list)
    recognized_sign_words: list[str] = field(default_factory=list)
    chat_messages: list[dict[str, str]] = field(default_factory=list)
    voice_records: list[dict[str, Any]] = field(default_factory=list)
    system_info: dict[str, Any] = field(default_factory=dict)
    lock: Lock = field(default_factory=Lock)

    def add_log(self, message: str) -> None:
        with self.lock:
            self.logs.append(message)
            if len(self.logs) > 200:
                self.logs = self.logs[-200:]

    def add_chat_message(self, role: str, text: str) -> None:
        if not text:
            return
        with self.lock:
            if self.chat_messages and self.chat_messages[-1].get('role') == role and self.chat_messages[-1].get('text') == text:
                return
            self.chat_messages.append({'role': role, 'text': text})
            if len(self.chat_messages) > 100:
                self.chat_messages = self.chat_messages[-100:]

    def set_voice_records(self, records: list[dict[str, Any]]) -> None:
        with self.lock:
            self.voice_records = list(records)[-100:]
