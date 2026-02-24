from __future__ import annotations

import base64
import json
import logging
import queue
import threading
from typing import Callable, Optional

from .realtime_protocol import (
    build_input_audio_append,
    build_input_audio_commit,
    build_response_create,
    build_session_update,
)

try:
    import websocket
except Exception:  # pragma: no cover
    websocket = None


logger = logging.getLogger(__name__)
EventSink = Callable[[str, dict], None]


class RealtimeClient:
    def __init__(self, config, speaker_player, event_sink: EventSink) -> None:
        self.config = config
        self.speaker_player = speaker_player
        self.event_sink = event_sink
        self._audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=1024)
        self._stop = threading.Event()
        self._send_lock = threading.Lock()
        self._ws_app = None
        self._ws_thread: Optional[threading.Thread] = None
        self._sender_thread: Optional[threading.Thread] = None
        self._connected = threading.Event()

    def start(self) -> None:
        if websocket is None:
            raise RuntimeError("websocket-client is not installed")
        if self._ws_thread is not None:
            return
        self._stop.clear()
        self._ws_thread = threading.Thread(target=self._run_ws, name="RealtimeThread", daemon=True)
        self._sender_thread = threading.Thread(target=self._run_sender, name="RealtimeSender", daemon=True)
        self._ws_thread.start()
        self._sender_thread.start()

    def send_audio(self, pcm_bytes: bytes) -> None:
        if self._stop.is_set():
            return
        try:
            self._audio_q.put_nowait(pcm_bytes)
        except queue.Full:
            logger.warning("Realtime audio queue full, dropping chunk")

    def close(self) -> None:
        self._stop.set()
        self._connected.clear()
        if self._ws_app is not None:
            try:
                self._ws_app.close()
            except Exception:
                logger.exception("Failed to close websocket")
        if self._sender_thread is not None:
            self._sender_thread.join(timeout=2.0)
        if self._ws_thread is not None:
            self._ws_thread.join(timeout=2.0)
        self._sender_thread = None
        self._ws_thread = None
        self._ws_app = None

    def _emit(self, event_type: str, payload: Optional[dict] = None) -> None:
        self.event_sink(event_type, payload or {})

    def _run_ws(self) -> None:
        url = f"wss://api.openai.com/v1/realtime?model={self.config.realtime_model}"
        headers = [f"Authorization: Bearer {self.config.openai_api_key}"]

        def on_open(ws) -> None:
            logger.info("Realtime WS opened")

        def on_message(ws, message: str) -> None:
            try:
                data = json.loads(message)
            except json.JSONDecodeError:
                logger.debug("Non-JSON WS message received")
                return
            self._handle_message(data)

        def on_error(ws, error) -> None:
            logger.exception("Realtime WS error: %s", error)
            self._emit("realtime.error", {"error": str(error)})

        def on_close(ws, status_code, close_msg) -> None:
            logger.info("Realtime WS closed code=%s msg=%s", status_code, close_msg)
            self._connected.clear()
            self._emit("realtime.closed", {"code": status_code, "message": close_msg})

        self._ws_app = websocket.WebSocketApp(
            url,
            header=headers,
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close,
        )
        try:
            self._ws_app.run_forever()
        except Exception as exc:
            logger.exception("Realtime WS run_forever failed")
            self._emit("realtime.error", {"error": str(exc)})

    def _run_sender(self) -> None:
        while not self._stop.is_set():
            try:
                pcm_bytes = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if not self._connected.is_set():
                continue
            self._send_json(build_input_audio_append(pcm_bytes))

    def _send_json(self, payload: dict) -> None:
        text = json.dumps(payload, ensure_ascii=False)
        ws = self._ws_app
        if ws is None:
            return
        with self._send_lock:
            try:
                ws.send(text)
            except Exception:
                logger.exception("WS send failed")

    def _handle_message(self, data: dict) -> None:
        event_type = data.get("type", "")
        logger.debug("Realtime event=%s", event_type)

        if event_type == "session.created":
            self._connected.set()
            self._send_json(
                build_session_update(
                    model=self.config.realtime_model,
                    voice=self.config.realtime_voice,
                    sample_rate=self.config.sample_rate,
                    instructions=self.config.assistant_instructions,
                )
            )
            self._emit("realtime.ready", {"event": "session.created"})
            return

        if event_type == "input_audio_buffer.speech_started":
            self.speaker_player.clear()
            return

        if event_type == "input_audio_buffer.speech_stopped":
            self._send_json(build_input_audio_commit())
            self._send_json(build_response_create())
            return

        audio_b64 = self._extract_audio_b64(data)
        if audio_b64:
            try:
                self.speaker_player.enqueue(base64.b64decode(audio_b64))
            except Exception:
                logger.exception("Failed to decode audio delta")

        if event_type.startswith("response."):
            self._emit("realtime.response_event", {"type": event_type})

    @staticmethod
    def _extract_audio_b64(data: dict) -> Optional[str]:
        event_type = data.get("type", "")
        if event_type in {"response.audio.delta", "response.output_audio.delta"}:
            return data.get("delta")
        delta = data.get("delta")
        if isinstance(delta, dict):
            for key in ("audio", "audio_base64"):
                value = delta.get(key)
                if isinstance(value, str):
                    return value
        for key in ("audio", "audio_base64"):
            value = data.get(key)
            if isinstance(value, str):
                return value
        return None

