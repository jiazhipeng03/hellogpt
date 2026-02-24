from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any, Optional

from .audio.mic_stream import MicStream
from .audio.speaker_player import SpeakerPlayer
from .realtime.realtime_client import RealtimeClient
from .wake.wake_detector_vosk import WakeDetectorVosk


logger = logging.getLogger(__name__)


class AppState(str, Enum):
    IDLE_LISTENING = "IDLE_LISTENING"
    CONNECTING = "CONNECTING"
    IN_CALL = "IN_CALL"
    STOPPING = "STOPPING"
    SHUTDOWN = "SHUTDOWN"


@dataclass(slots=True)
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time)


class HelloGptStateMachine:
    def __init__(self, config) -> None:
        self.config = config
        self.state = AppState.IDLE_LISTENING
        self.events: "queue.Queue[Event]" = queue.Queue()
        self._stop = threading.Event()
        self._realtime: Optional[RealtimeClient] = None
        self._mic_forward_sub: Optional[int] = None
        self._call_stopping = False

        self.mic = MicStream(
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            chunk_frames=self.config.chunk_frames,
            device=self.config.mic_device_index,
        )
        self.speaker = SpeakerPlayer(
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            chunk_frames=self.config.chunk_frames,
            device=self.config.spk_device_index,
        )
        self.wake_detector = WakeDetectorVosk(
            model_path=self.config.vosk_model_path,
            sample_rate=self.config.sample_rate,
            wake_phrase=self.config.wake_phrase,
            exit_phrase=self.config.exit_phrase,
            event_sink=self.post_event,
        )
        self._wake_sub = self.mic.subscribe(self.wake_detector.push_audio)

    def post_event(self, event_type: str, payload: Optional[dict] = None) -> None:
        self.events.put(Event(type=event_type, payload=payload or {}))

    def run(self) -> None:
        self._startup()
        try:
            while not self._stop.is_set():
                try:
                    event = self.events.get(timeout=0.2)
                except queue.Empty:
                    continue
                self._handle_event(event)
        finally:
            self.shutdown()

    def stop(self) -> None:
        self._stop.set()

    def _startup(self) -> None:
        self.speaker.start()
        self.mic.start()
        self.wake_detector.start()
        self.wake_detector.set_mode("idle")
        self._set_state(AppState.IDLE_LISTENING)

    def shutdown(self) -> None:
        if self.state != AppState.SHUTDOWN:
            self._set_state(AppState.SHUTDOWN, print_state=False)
        try:
            self._stop_call(reason="shutdown")
        except Exception:
            logger.exception("Stop call during shutdown failed")
        try:
            self.mic.unsubscribe(self._wake_sub)
        except Exception:
            pass
        self.wake_detector.stop()
        self.mic.stop()
        self.speaker.stop()

    def _set_state(self, new_state: AppState, print_state: bool = True) -> None:
        self.state = new_state
        logger.info("STATE=%s", new_state.value)
        if print_state and new_state in {
            AppState.IDLE_LISTENING,
            AppState.CONNECTING,
            AppState.IN_CALL,
            AppState.STOPPING,
        }:
            print(f"STATE={new_state.value}", flush=True)

    def _handle_event(self, event: Event) -> None:
        logger.info("EVENT=%s payload=%s", event.type, event.payload)
        if event.type == "wake.detected" and self.state == AppState.IDLE_LISTENING:
            self._start_call()
            return

        if event.type == "realtime.ready" and self.state == AppState.CONNECTING:
            self._call_stopping = False
            self.wake_detector.set_mode("in_call")
            self._set_state(AppState.IN_CALL)
            return

        if event.type == "exit.detected" and self.state == AppState.IN_CALL:
            self._stop_call(reason="exit phrase")
            return

        if event.type in {"realtime.closed", "realtime.error"} and self.state in {
            AppState.CONNECTING,
            AppState.IN_CALL,
        }:
            self._stop_call(reason=event.type)
            return

        if event.type == "app.stop":
            self.stop()

    def _start_call(self) -> None:
        self._call_stopping = False
        self._set_state(AppState.CONNECTING)
        try:
            self._realtime = RealtimeClient(self.config, self.speaker, self.post_event)
            self._realtime.start()
            self._mic_forward_sub = self.mic.subscribe(self._realtime.send_audio)
        except Exception as exc:
            logger.exception("Failed to start realtime client")
            self.post_event("realtime.error", {"error": str(exc)})

    def _stop_call(self, reason: str) -> None:
        if self._call_stopping:
            return
        if self.state not in {AppState.CONNECTING, AppState.IN_CALL, AppState.STOPPING} and reason != "shutdown":
            return
        self._call_stopping = True
        if reason != "shutdown":
            self._set_state(AppState.STOPPING)

        self.wake_detector.set_mode("idle")
        if self._mic_forward_sub is not None:
            self.mic.unsubscribe(self._mic_forward_sub)
            self._mic_forward_sub = None

        if self._realtime is not None:
            try:
                self._realtime.close()
            except Exception:
                logger.exception("Realtime close failed")
            finally:
                self._realtime = None

        self.speaker.clear()
        if not self._stop.is_set() and reason != "shutdown":
            self._set_state(AppState.IDLE_LISTENING)

