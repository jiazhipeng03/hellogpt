from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


DeviceIndex = Optional[Union[int, str]]


def _parse_device(value: str) -> DeviceIndex:
    raw = (value or "default").strip()
    if not raw or raw.lower() == "default":
        return None
    try:
        return int(raw)
    except ValueError:
        return raw


@dataclass(slots=True)
class AppConfig:
    openai_api_key: str
    realtime_model: str = "gpt-realtime"
    realtime_voice: str = "marin"
    wake_phrase: str = "你好GPT"
    exit_phrase: str = "再见GPT"
    mic_device_index: DeviceIndex = None
    spk_device_index: DeviceIndex = None
    log_level: str = "INFO"
    vosk_model_path: str = "assets/vosk-model-cn"
    sample_rate: int = 24000
    channels: int = 1
    chunk_ms: int = 20
    assistant_instructions: str = "你是一个简洁的中文语音助手。回答尽量口语化、短句。"

    @property
    def chunk_frames(self) -> int:
        return int(self.sample_rate * self.chunk_ms / 1000)

    @property
    def chunk_bytes(self) -> int:
        return self.chunk_frames * self.channels * 2

    @classmethod
    def load(cls, project_root: Path) -> "AppConfig":
        env_path = project_root / ".env"
        if load_dotenv is not None and env_path.exists():
            load_dotenv(env_path)

        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ValueError("Missing OPENAI_API_KEY in environment or .env")

        return cls(
            openai_api_key=api_key,
            realtime_model=os.getenv("REALTIME_MODEL", "gpt-realtime").strip() or "gpt-realtime",
            realtime_voice=os.getenv("REALTIME_VOICE", "marin").strip() or "marin",
            wake_phrase=os.getenv("WAKE_PHRASE", "你好GPT").strip() or "你好GPT",
            exit_phrase=os.getenv("EXIT_PHRASE", "再见GPT").strip() or "再见GPT",
            mic_device_index=_parse_device(os.getenv("MIC_DEVICE_INDEX", "default")),
            spk_device_index=_parse_device(os.getenv("SPK_DEVICE_INDEX", "default")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip() or "INFO",
            vosk_model_path=os.getenv("VOSK_MODEL_PATH", "assets/vosk-model-cn").strip() or "assets/vosk-model-cn",
        )

