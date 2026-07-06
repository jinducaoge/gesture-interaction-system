from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class VoiceSessionStore:
    """管理语音识别/转化/发送会话的文件落盘。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> dict[str, Any]:
        session_id = self._new_session_id()
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / 'recognized_sentences.jsonl').touch(exist_ok=True)

        now = self._now_iso()
        session = {
            'session_id': session_id,
            'status': 'running',
            'latest_text': '',
            'latest_tokens': '',
            'latest_ids': [],
            'convert_status': 'idle',
            'convert_error': '',
            'send_status': 'idle',
            'send_error': '',
            'records': [],
            'created_at': now,
            'updated_at': now,
            'stopped_at': '',
            'session_dir': str(session_dir),
        }
        self._write_session(session_dir, session)
        return session

    def append_sentence(self, session_id: str, text: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        session = self.get_session(session_id)
        records = list(session.get('records') or [])
        item = {
            'index': len(records) + 1,
            'asr_text': text,
            'tokens': '',
            'ids': [],
            'send_result': {},
            'ts': time.time(),
            'payload': payload or {},
        }
        records.append(item)
        with (session_dir / 'recognized_sentences.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')

        session.update({
            'records': records,
            'latest_text': text,
            'status': 'running',
            'updated_at': self._now_iso(),
        })
        self._write_session(session_dir, session)
        return session

    def update_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        session = self.get_session(session_id)
        session.update(fields)
        session['updated_at'] = self._now_iso()
        self._write_session(session_dir, session)
        return session

    def save_convert_result(self, session_id: str, *, latest_text: str, latest_tokens: str, convert_status: str, convert_error: str = '') -> dict[str, Any]:
        session = self.get_session(session_id)
        records = list(session.get('records') or [])
        if records:
            records[-1]['tokens'] = latest_tokens
        return self.update_session(
            session_id,
            latest_text=latest_text,
            latest_tokens=latest_tokens,
            convert_status=convert_status,
            convert_error=convert_error,
            records=records,
        )

    def save_send_result(self, session_id: str, *, latest_ids: list[int], send_status: str, send_error: str = '', send_result: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        session = self.get_session(session_id)
        records = list(session.get('records') or [])
        if records:
            records[-1]['ids'] = list(latest_ids)
            records[-1]['send_result'] = send_result or {}
        return self.update_session(
            session_id,
            latest_ids=list(latest_ids),
            send_status=send_status,
            send_error=send_error,
            records=records,
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        session_path = self._session_dir(session_id) / 'session.json'
        if not session_path.exists():
            raise FileNotFoundError(f'voice session not found: {session_id}')
        with session_path.open('r', encoding='utf-8') as f:
            return json.load(f)

    def get_latest_session(self) -> Optional[dict[str, Any]]:
        session_files = sorted(self.base_dir.glob('*/session.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not session_files:
            return None
        with session_files[0].open('r', encoding='utf-8') as f:
            return json.load(f)

    def close_session(self, session_id: str) -> dict[str, Any]:
        return self.update_session(session_id, status='stopped', stopped_at=self._now_iso())

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    @staticmethod
    def _write_session(session_dir: Path, session: dict[str, Any]) -> None:
        with (session_dir / 'session.json').open('w', encoding='utf-8') as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _new_session_id() -> str:
        return 'voice_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec='seconds')
