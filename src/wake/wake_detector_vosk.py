from __future__ import annotations

import json
import logging
import queue
import threading
import time
from pathlib import Path
from typing import Callable, Literal, Optional

try:
    from vosk import KaldiRecognizer, Model, SetLogLevel
except Exception:  # pragma: no cover
    KaldiRecognizer = None
    Model = None
    SetLogLevel = None


logger = logging.getLogger(__name__)
EventSink = Callable[[str, dict], None]
Mode = Literal["idle", "in_call"]


def _normalize_text(text: str) -> str:
    return (text or "").replace(" ", "").lower()


class WakeDetectorVosk:
    def __init__(
        self,
        model_path: str,
        sample_rate: int,
        wake_phrase: str,
        exit_phrase: str,
        event_sink: EventSink,
        cooldown_sec: float = 2.0,
        require_consecutive_finals: int = 2,
    ) -> None:
        self.model_path = model_path
        self.sample_rate = sample_rate
        self.wake_phrase = _normalize_text(wake_phrase)
        self.exit_phrase = _normalize_text(exit_phrase)
        self.event_sink = event_sink
        self.cooldown_sec = cooldown_sec
        self.require_consecutive_finals = max(1, require_consecutive_finals)
        self._audio_q: "queue.Queue[bytes]" = queue.Queue(maxsize=512)
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._mode_lock = threading.Lock()
        self._mode: Mode = "idle"
        self._enabled = False
        self._last_trigger_ts = 0.0
        self._wake_hits = 0
        self._exit_hits = 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_mode(self, mode: Mode) -> None:
        with self._mode_lock:
            self._mode = mode
        self._wake_hits = 0
        self._exit_hits = 0
        logger.info("Wake detector mode=%s", mode)

    def push_audio(self, pcm_bytes: bytes) -> None:
        if not self._enabled:
            return
        try:
            self._audio_q.put_nowait(pcm_bytes)
        except queue.Full:
            try:
                _ = self._audio_q.get_nowait()
            except queue.Empty:
                pass
            self._audio_q.put_nowait(pcm_bytes)

    def start(self) -> None:
        if self._thread is not None:
            return
        if Model is None or KaldiRecognizer is None:
            logger.warning("Vosk not installed, wake detector disabled")
            return
        model_dir = Path(self.model_path)
        if not model_dir.exists():
            logger.warning("Vosk model not found at %s, wake detector disabled", model_dir)
            return
        if SetLogLevel is not None:
            SetLogLevel(-1)
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="WakeThread", daemon=True)
        self._thread.start()
        self._enabled = True
        logger.info("Wake detector started (vosk)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._enabled = False
        logger.info("Wake detector stopped")

    def _get_mode(self) -> Mode:
        with self._mode_lock:
            return self._mode

    def _run(self) -> None:
        try:
            model = Model(self.model_path)
            recognizer = KaldiRecognizer(model, float(self.sample_rate))
            recognizer.SetWords(False)
        except Exception:
            logger.exception("Failed to initialize Vosk")
            self._enabled = False
            return

        while not self._stop.is_set():
            try:
                pcm_bytes = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                is_final = recognizer.AcceptWaveform(pcm_bytes)
                if is_final:
                    result = json.loads(recognizer.Result())
                    self._handle_transcript(result.get("text", ""), final=True)
                else:
                    partial = json.loads(recognizer.PartialResult())
                    text = partial.get("partial", "")
                    if text:
                        logger.debug("Wake partial=%s", text)
            except Exception:
                logger.exception("Wake recognition loop error")

    def _handle_transcript(self, text: str, final: bool) -> None:
        norm = _normalize_text(text)
        if not norm:
            return
        logger.info("Wake final transcript=%s", text)
        now = time.time()
        if now - self._last_trigger_ts < self.cooldown_sec:
            return

        mode = self._get_mode()
        if mode == "idle":
            if self.wake_phrase and self.wake_phrase in norm:
                self._wake_hits += 1
                if final and self._wake_hits >= self.require_consecutive_finals:
                    self._last_trigger_ts = now
                    self._wake_hits = 0
                    self.event_sink("wake.detected", {"text": text})
            else:
                self._wake_hits = 0
        elif mode == "in_call":
            if self.exit_phrase and self.exit_phrase in norm:
                self._exit_hits += 1
                if final and self._exit_hits >= self.require_consecutive_finals:
                    self._last_trigger_ts = now
                    self._exit_hits = 0
                    self.event_sink("exit.detected", {"text": text})
            else:
                self._exit_hits = 0

