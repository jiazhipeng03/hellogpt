from __future__ import annotations

import base64
from typing import Any, Dict


def build_session_update(model: str, voice: str, sample_rate: int, instructions: str) -> Dict[str, Any]:
    return {
        "type": "session.update",
        "session": {
            "type": "realtime",
            "model": model,
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": sample_rate},
                    "turn_detection": {"type": "semantic_vad"},
                },
                "output": {
                    "format": {"type": "audio/pcm"},
                    "voice": voice,
                },
            },
            "instructions": instructions,
        },
    }


def build_input_audio_append(pcm_bytes: bytes) -> Dict[str, Any]:
    return {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm_bytes).decode("ascii"),
    }


def build_input_audio_commit() -> Dict[str, Any]:
    return {"type": "input_audio_buffer.commit"}


def build_response_create() -> Dict[str, Any]:
    return {
        "type": "response.create",
        "response": {
            "modalities": ["audio"],
        },
    }

