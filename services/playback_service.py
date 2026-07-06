from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("services.playback_service")


@dataclass
class PlaybackConfig:
    enabled: bool = False
    local_word_audio_enabled: bool = False
    local_word_audio_dir: str = ""
    local_word_audio_ext: str = ".mp3"
    local_word_audio_index_pad: int = 3
    local_word_audio_player_cmd: str = ""
    local_word_audio_label_path: str = ""


class LocalWordAudioResolver:
    def __init__(self, label_path: str, audio_dir: str, file_ext: str = ".mp3", index_pad: int = 3) -> None:
        self.label_path = Path(label_path).expanduser()
        self.audio_dir = Path(audio_dir).expanduser()
        self.file_ext = file_ext if file_ext.startswith(".") else f".{file_ext}"
        self.index_pad = max(1, int(index_pad))
        self._label_to_path = self._build_label_map()

    @staticmethod
    def _normalize_label(label: str) -> str:
        text = (label or "").strip()
        text = re.sub(r"^\s*\d+[.、，,:：\-]\s*", "", text)
        return text.strip()

    def _build_label_map(self) -> dict[str, Path]:
        if not self.label_path.is_file() or not self.audio_dir.is_dir():
            return {}
        mapping: dict[str, Path] = {}
        for idx, raw_line in enumerate(self.label_path.read_text(encoding="utf-8").splitlines(), start=1):
            label = self._normalize_label(raw_line)
            if not label:
                continue
            audio_path = self.audio_dir / f"{idx:0{self.index_pad}d}{self.file_ext}"
            if audio_path.is_file():
                mapping[label] = audio_path
        return mapping

    def resolve(self, label: str) -> Optional[Path]:
        return self._label_to_path.get(self._normalize_label(label))


class PlaybackSpeakerService:
    """Audio playback façade.

    The public archive keeps only the interface and local-file lookup scaffold.
    Online speech generation and private provider settings are not included.
    """

    def __init__(self, config: PlaybackConfig | None = None, resolver: LocalWordAudioResolver | None = None) -> None:
        self.config = config or PlaybackConfig()
        self.resolver = resolver

    @classmethod
    def from_env(cls) -> "PlaybackSpeakerService":
        config = PlaybackConfig(
            enabled=os.getenv("PLAYBACK_ENABLED", "0") == "1",
            local_word_audio_enabled=os.getenv("LOCAL_WORD_AUDIO_ENABLED", "0") == "1",
            local_word_audio_dir=os.getenv("LOCAL_WORD_AUDIO_DIR", ""),
            local_word_audio_ext=os.getenv("LOCAL_WORD_AUDIO_EXT", ".mp3"),
            local_word_audio_index_pad=int(os.getenv("LOCAL_WORD_AUDIO_INDEX_PAD", "3")),
            local_word_audio_player_cmd=os.getenv("LOCAL_WORD_AUDIO_PLAYER_CMD", ""),
            local_word_audio_label_path=os.getenv("LOCAL_WORD_AUDIO_LABEL_PATH", os.getenv("SIGN_LABEL_PATH", "")),
        )
        resolver = None
        if config.local_word_audio_enabled:
            resolver = LocalWordAudioResolver(
                config.local_word_audio_label_path,
                config.local_word_audio_dir,
                config.local_word_audio_ext,
                config.local_word_audio_index_pad,
            )
        return cls(config=config, resolver=resolver)

    async def speak_word(self, label: str) -> bool:
        if not self.config.enabled or not self.resolver:
            return False
        path = self.resolver.resolve(label)
        if not path:
            return False
        return await self._play_file(path)

    async def speak_summary(self, text: str) -> bool:
        return False

    async def _play_file(self, path: Path) -> bool:
        cmd = (self.config.local_word_audio_player_cmd or "").strip()
        if not cmd:
            return False
        process = await asyncio.create_subprocess_shell(
            cmd.replace("{file}", str(path)),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.communicate()
        return process.returncode == 0
