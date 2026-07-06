from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


class SignSessionStore:
    """管理手语识别会话的文件落盘。"""

    def __init__(self, base_dir: str | Path) -> None:
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create_session(self, mode: str = "SENTENCE") -> dict[str, Any]:
        session_id = self._new_session_id()
        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "recognized_words.jsonl").touch(exist_ok=True)

        now = self._now_iso()
        session = {
            "session_id": session_id,
            "mode": mode,
            "status": "running",
            "summary_status": "pending",
            "summary_error": "",
            "raw_text": "",
            "summary_text": "",
            "word_count": 0,
            "words": [],
            "created_at": now,
            "updated_at": now,
            "stopped_at": "",
            "session_dir": str(session_dir),
        }
        self._write_session(session_dir, session)
        return session

    def append_word(self, session_id: str, word: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        session = self.get_session(session_id)
        words = list(session.get("words") or [])
        words.append(word)

        line = {
            "index": len(words),
            "word": word,
            "ts": time.time(),
            "payload": payload or {},
        }
        with (session_dir / "recognized_words.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

        session["words"] = words
        session["word_count"] = len(words)
        session["raw_text"] = self.build_raw_text(words)
        session["status"] = "running"
        session["updated_at"] = self._now_iso()
        self._write_session(session_dir, session)
        return session

    def update_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        session_dir = self._session_dir(session_id)
        session = self.get_session(session_id)
        session.update(fields)
        session["updated_at"] = self._now_iso()
        self._write_session(session_dir, session)
        return session

    def mark_summary_processing(self, session_id: str, raw_text: str) -> dict[str, Any]:
        return self.update_session(
            session_id,
            status="stopped",
            raw_text=raw_text,
            word_count=len(self.get_session(session_id).get("words") or []),
            summary_status="processing",
            stopped_at=self._now_iso(),
        )

    def save_summary_result(
        self,
        session_id: str,
        *,
        raw_text: str,
        summary_text: str,
        summary_status: str,
        summary_error: str = "",
    ) -> dict[str, Any]:
        return self.update_session(
            session_id,
            status="stopped",
            raw_text=raw_text,
            summary_text=summary_text,
            summary_status=summary_status,
            summary_error=summary_error,
            stopped_at=self.get_session(session_id).get("stopped_at") or self._now_iso(),
        )

    def get_session(self, session_id: str) -> dict[str, Any]:
        session_path = self._session_dir(session_id) / "session.json"
        if not session_path.exists():
            raise FileNotFoundError(f"sign session not found: {session_id}")
        with session_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def get_latest_session(self) -> Optional[dict[str, Any]]:
        session_files = sorted(self.base_dir.glob("*/session.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not session_files:
            return None
        with session_files[0].open("r", encoding="utf-8") as f:
            return json.load(f)

    def load_words(self, session_id: str) -> list[str]:
        session_path = self._session_dir(session_id) / "recognized_words.jsonl"
        if not session_path.exists():
            return []
        words: list[str] = []
        with session_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                word = str(item.get("word", "")).strip()
                if word:
                    words.append(word)
        return words

    @staticmethod
    def build_raw_text(words: list[str]) -> str:
        text = " ".join(str(word).strip() for word in words if str(word).strip()).strip()
        return text

    def _session_dir(self, session_id: str) -> Path:
        return self.base_dir / session_id

    @staticmethod
    def _write_session(session_dir: Path, session: dict[str, Any]) -> None:
        with (session_dir / "session.json").open("w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

    @staticmethod
    def _new_session_id() -> str:
        return "sign_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now().isoformat(timespec="seconds")
