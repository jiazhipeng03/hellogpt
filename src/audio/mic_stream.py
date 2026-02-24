from __future__ import annotations

import logging
import threading
from typing import Callable, Dict

try:
    import sounddevice as sd
except Exception:  # pragma: no cover
    sd = None


logger = logging.getLogger(__name__)
MicCallback = Callable[[bytes], None]


class MicStream:
    def __init__(
        self,
        sample_rate: int,
        channels: int,
        chunk_frames: int,
        device=None,
    ) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_frames = chunk_frames
        self.device = device
        self._stream = None
        self._lock = threading.Lock()
        self._listeners: Dict[int, MicCallback] = {}
        self._next_listener_id = 1
        self._started = False

    def subscribe(self, callback: MicCallback) -> int:
        with self._lock:
            token = self._next_listener_id
            self._next_listener_id += 1
            self._listeners[token] = callback
            return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._listeners.pop(token, None)

    def _dispatch(self, data: bytes) -> None:
        with self._lock:
            listeners = list(self._listeners.values())
        for cb in listeners:
            try:
                cb(data)
            except Exception:
                logger.exception("Mic listener callback failed")

    def start(self) -> None:
        if self._started:
            return
        if sd is None:
            raise RuntimeError("sounddevice is not installed")

        def _callback(indata, frames, time_info, status) -> None:
            if status:
                logger.warning("Mic status: %s", status)
            if frames <= 0:
                return
            self._dispatch(bytes(indata))

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_frames,
            device=self.device,
            callback=_callback,
        )
        self._stream.start()
        self._started = True
        logger.info("Mic stream started (rate=%s, chunk=%s)", self.sample_rate, self.chunk_frames)

    def stop(self) -> None:
        if not self._started:
            return
        try:
            if self._stream is not None:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
            self._started = False
            logger.info("Mic stream stopped")

