from __future__ import annotations

import queue
from typing import Optional


class RingBuffer:
    def __init__(self, max_chunks: int = 256) -> None:
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=max_chunks)

    def put(self, chunk: bytes) -> None:
        try:
            self._q.put_nowait(chunk)
        except queue.Full:
            try:
                _ = self._q.get_nowait()
            except queue.Empty:
                pass
            self._q.put_nowait(chunk)

    def get(self, timeout: Optional[float] = None) -> bytes:
        return self._q.get(timeout=timeout)

    def clear(self) -> None:
        while True:
            try:
                self._q.get_nowait()
            except queue.Empty:
                break

