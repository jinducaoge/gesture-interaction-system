from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("services.sign_text_service")


class SignTextService:
    """Lightweight post-processor for recognized sign labels.

    This public version keeps only deterministic formatting logic. Project-specific
    text generation rules and private service endpoints are intentionally omitted.
    """

    async def summarize_sign_text(self, raw_text: str) -> dict[str, Any]:
        text = self._normalize(raw_text)
        if not text:
            return {"ok": True, "summary_text": "", "summary_status": "skipped", "model": "local-rule"}
        if text == "（本次未识别到词）":
            return {
                "ok": True,
                "summary_text": "本次未识别到可整理的手语内容。",
                "summary_status": "skipped",
                "model": "local-rule",
            }
        return {
            "ok": True,
            "summary_text": text,
            "summary_status": "done",
            "model": "local-rule",
        }

    @staticmethod
    def _normalize(raw_text: str) -> str:
        parts = [p.strip() for p in re.split(r"[\s,，、]+", raw_text or "") if p.strip()]
        compact: list[str] = []
        for item in parts:
            if not compact or compact[-1] != item:
                compact.append(item)
        return " ".join(compact).strip()
