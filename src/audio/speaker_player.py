from __future__ import annotations

import logging
import queue
import threading
from typing import Optional

try:
    import numpy as np
    import sounddevice as sd
except Exception:  # pragma: no cover
    np = None
    sd = None


logger = logging.getLogger(__name__)


class SpeakerPlayer:
    def __init__(self, sample_rate: int, channels: int, chunk_frames: int, device=None) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_frames = chunk_frames
        self.device = device
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=512)
        self._stream = None
        self._started = False
        self._buf = bytearray()
        self._buf_lock = threading.Lock()

    def start(self) -> None:
        if self._started:
            return
        if sd is None or np is None:
            raise RuntimeError("sounddevice/numpy is not installed")

        def _callback(outdata, frames, time_info, status) -> None:
            if status:
                logger.warning("Speaker status: %s", status)
            needed_bytes = frames * self.channels * 2
            chunk = self._read_bytes(needed_bytes)
            if len(chunk) < needed_bytes:
                chunk += b"\x00" * (needed_bytes - len(chunk))
            arr = np.frombuffer(chunk, dtype=np.int16).reshape(frames, self.channels)
            outdata[:] = arr

        self._stream = sd.OutputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            blocksize=self.chunk_frames,
            device=self.device,
            callback=_callback,
        )
        self._stream.start()
        self._started = True
        logger.info("Speaker player started (rate=%s, chunk=%s)", self.sample_rate, self.chunk_frames)

    def _read_bytes(self, n: int) -> bytes:
        with self._buf_lock:
            while len(self._buf) < n:
                try:
                    self._buf.extend(self._q.get_nowait())
                except queue.Empty:
                    break
            data = bytes(self._buf[:n])
            del self._buf[:n]
            return data

    def enqueue(self, pcm_bytes: bytes) -> None:
        if not pcm_bytes:
            return
        try:
            self._q.put_nowait(pcm_bytes)
        except queue.Full:
            logger.warning("Speaker queue full, dropping audio chunk")

    def clear(self) -> None:
        with self._buf_lock:
            self._buf.clear()
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

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
            self.clear()
            logger.info("Speaker player stopped")

