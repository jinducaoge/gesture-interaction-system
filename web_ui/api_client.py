"""orchestrator HTTP 客户端。"""

from __future__ import annotations

from typing import Any

import httpx


class ApiClient:
    def __init__(self, base_url: str, timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def _request_json(self, method: str, path: str, *, params: dict[str, Any] | None = None, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, f"{self.base_url}{path}", params=params, json=payload)
            if response.status_code >= 400:
                try:
                    data = response.json()
                    detail = str(data.get('detail') or data) if isinstance(data, dict) else str(data)
                except Exception:
                    detail = response.text.strip() or f"HTTP {response.status_code}"
                raise RuntimeError(detail)
            return response.json()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request_json("GET", path, params=params)

    async def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request_json("POST", path, payload=payload or {})

    async def get_state(self) -> dict[str, Any]:
        return await self._get("/state")

    async def get_system_info(self) -> dict[str, Any]:
        return await self._get("/system/info")

    async def select_mode(self, mode: str) -> dict[str, Any]:
        return await self._post("/mode/select", {"mode": mode})

    async def select_sign_mode(self, mode: str) -> dict[str, Any]:
        return await self._post("/sign/mode/select", {"mode": mode})

    async def start_kp(self) -> dict[str, Any]:
        return await self._post("/kp/start")

    async def stop_kp(self) -> dict[str, Any]:
        return await self._post("/kp/stop")

    async def start_sign(self, mode: str) -> dict[str, Any]:
        return await self._post("/sign/start", {"mode": mode})

    async def stop_sign(self) -> dict[str, Any]:
        return await self._post("/sign/stop")

    async def get_current_sign_session(self) -> dict[str, Any]:
        return await self._get("/sign/session/current")

    async def start_voice(self) -> dict[str, Any]:
        return await self._post("/voice/start")

    async def stop_voice(self) -> dict[str, Any]:
        return await self._post("/voice/stop")

    async def convert_voice(self, text: str = "") -> dict[str, Any]:
        return await self._post("/voice/convert", {"text": text})

    async def send_voice(self, token_text: str = "") -> dict[str, Any]:
        return await self._post("/voice/send", {"token_text": token_text})

    async def get_current_voice_session(self) -> dict[str, Any]:
        return await self._get("/voice/session/current")

    async def generate_chat(self, text: str) -> dict[str, Any]:
        return await self._post("/chat/generate", {"text": text})

    async def chat_display_text(self, text: str) -> dict[str, Any]:
        return await self._post("/chat/display/text", {"text": text})

    async def chat_display_arm(self, text: str) -> dict[str, Any]:
        return await self._post("/chat/display/arm", {"text": text})
