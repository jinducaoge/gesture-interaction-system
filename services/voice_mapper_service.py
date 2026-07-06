from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger("services.voice_mapper_service")


class VoiceMapperService:
    """Maps spoken text or selected words to sign labels and actuator IDs.

    The competition archive includes only the local parsing scaffold. The complete
    lexicon, mapping table, and deployment rules are not bundled in this package.
    """

    def __init__(self) -> None:
        self.vocab_file = (os.getenv("VOICE_VOCAB_FILE") or os.getenv("SIGN_LABEL_PATH") or "").strip()
        self.vocab_text = (os.getenv("VOICE_VOCAB_TEXT") or "").strip()
        self.id_map_file = (os.getenv("VOICE_VOCAB_ID_MAP_FILE") or "").strip()

    def load_vocab_tokens(self) -> list[str]:
        entries = self._load_vocab_entries()
        tokens: list[str] = []
        for entry in entries:
            token = str(entry.get("primary") or "").strip()
            if token and token not in tokens:
                tokens.append(token)
        return tokens

    def load_vocab_id_map(self) -> dict[str, int]:
        if self.id_map_file and Path(self.id_map_file).is_file():
            raw = json.loads(Path(self.id_map_file).read_text(encoding="utf-8"))
            return self._normalize_id_map(raw)

        derived: dict[str, int] = {}
        for entry in self._load_vocab_entries():
            idx = entry.get("id")
            if idx is None:
                continue
            for token in [entry.get("primary"), *(entry.get("aliases") or [])]:
                token = str(token or "").strip()
                if not token:
                    continue
                derived[token] = int(idx)
                derived[self._normalize_lookup_key(token)] = int(idx)
        return derived

    async def convert_text(self, text: str) -> dict[str, Any]:
        text = (text or "").strip()
        if not text:
            return {"ok": False, "tokens": [], "token_text": "", "summary_status": "failed", "error": "empty input"}

        vocab = self.load_vocab_tokens()
        if not vocab:
            return {
                "ok": False,
                "tokens": [],
                "token_text": "",
                "summary_status": "failed",
                "error": "vocabulary is not included in public archive",
            }

        tokens = self._rule_pick_tokens(text, vocab)
        return {
            "ok": bool(tokens),
            "tokens": tokens,
            "token_text": " ".join(tokens),
            "summary_status": "done" if tokens else "failed",
            "error": "" if tokens else "no token matched the public vocabulary",
        }

    async def convert_text_to_ids(self, text: str) -> dict[str, Any]:
        converted = await self.convert_text(text)
        tokens = list(converted.get("tokens") or [])
        mapped = self.map_tokens_to_ids(tokens)
        return {
            **converted,
            "ids": list(mapped.get("ids") or []),
            "missing_tokens": list(mapped.get("missing_tokens") or []),
            "number_text": " ".join(str(i) for i in mapped.get("ids") or []),
            "convert_status": converted.get("summary_status", "failed"),
        }

    def map_tokens_to_ids(self, tokens: list[str]) -> dict[str, Any]:
        id_map = self.load_vocab_id_map()
        ids: list[int] = []
        missing: list[str] = []
        for token in tokens:
            key = self._normalize_lookup_key(str(token))
            if token in id_map:
                ids.append(int(id_map[token]))
            elif key in id_map:
                ids.append(int(id_map[key]))
            else:
                missing.append(str(token))
        return {"ids": ids, "missing_tokens": missing}

    def _load_vocab_entries(self) -> list[dict[str, Any]]:
        text = self.vocab_text
        if not text and self.vocab_file and Path(self.vocab_file).is_file():
            text = Path(self.vocab_file).read_text(encoding="utf-8")
        if not text:
            return []

        entries: list[dict[str, Any]] = []
        for line_no, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            idx: int | None = None
            m = re.match(r"^\s*(\d+)\s*[.、，,:：\-]?\s*(.+)$", line)
            if m:
                idx = int(m.group(1))
                line = m.group(2).strip()
            primary, aliases = self._split_aliases(line)
            entries.append({"id": idx if idx is not None else line_no, "primary": primary, "aliases": aliases})
        return entries

    @staticmethod
    def _split_aliases(line: str) -> tuple[str, list[str]]:
        aliases: list[str] = []
        bracket = re.search(r"[（(]([^）)]+)[）)]", line)
        if bracket:
            aliases = [p.strip() for p in re.split(r"[/,，、\s]+", bracket.group(1)) if p.strip()]
            line = (line[:bracket.start()] + line[bracket.end():]).strip()
        return line.strip(), aliases

    @staticmethod
    def _normalize_lookup_key(token: str) -> str:
        return re.sub(r"\s+", "", token or "").strip().lower()

    @classmethod
    def _normalize_id_map(cls, raw: dict[str, Any]) -> dict[str, int]:
        result: dict[str, int] = {}
        for key, value in raw.items():
            token = str(key).strip()
            if not token:
                continue
            result[token] = int(value)
            result[cls._normalize_lookup_key(token)] = int(value)
        return result

    @staticmethod
    def _rule_pick_tokens(text: str, vocab: list[str]) -> list[str]:
        normalized = re.sub(r"\s+", "", text)
        result: list[str] = []
        for token in vocab:
            if token and token in normalized and token not in result:
                result.append(token)
        return result
