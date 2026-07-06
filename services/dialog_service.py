from __future__ import annotations

import logging
from typing import Any

from services.voice_mapper_service import VoiceMapperService

logger = logging.getLogger("services.dialog_service")


class DialogService:
    """Minimal dialog scaffold used by the public archive."""

    def __init__(self, voice_mapper_service: VoiceMapperService | None = None) -> None:
        self.voice_mapper_service = voice_mapper_service or VoiceMapperService()

    async def generate_reply(self, user_text: str) -> dict[str, Any]:
        text = (user_text or "").strip()
        if not text:
            return {
                "ok": False,
                "user_text": "",
                "reply_text": "",
                "reply_tokens": [],
                "reply_token_text": "",
                "reply_ids": [],
                "reply_number_text": "",
                "summary_status": "failed",
                "error": "empty input",
            }

        reply_text = self._fallback_reply_text(text)
        arm_plan = await self.voice_mapper_service.convert_text_to_ids(reply_text)
        return {
            "ok": True,
            "user_text": text,
            "raw_reply": reply_text,
            "reply_text": reply_text,
            "reply_tokens": list(arm_plan.get("tokens") or []),
            "reply_token_text": str(arm_plan.get("token_text") or "").strip(),
            "reply_ids": list(arm_plan.get("ids") or []),
            "reply_number_text": str(arm_plan.get("number_text") or "").strip(),
            "summary_status": str(arm_plan.get("summary_status") or "done"),
            "error": str(arm_plan.get("error") or ""),
            "model": "local-rule",
            "convert_status": str(arm_plan.get("convert_status") or arm_plan.get("summary_status") or "done"),
            "convert_error": str(arm_plan.get("error") or ""),
        }

    @staticmethod
    def _fallback_reply_text(text: str) -> str:
        if any(word in text for word in ("谢谢", "感谢")):
            return "不用谢，我很高兴帮助你。"
        if any(word in text for word in ("你好", "您好")):
            return "你好，请问需要什么帮助？"
        if any(word in text for word in ("水", "喝")):
            return "好的，我现在帮你拿水。"
        return "好的，我已经收到你的表达。"
