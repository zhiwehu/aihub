"""Lazy local model loading on one GPU worker thread.

Extracted from the old server-side ``Pipeline``/``LocalModels`` pair. The
server no longer loads model weights at all: it talks HTTP to this package.
Everything here runs off the asyncio thread, so a slow load or an
un-cancellable MLX call never blocks the event loop.

At most one model call runs at a time and at most one more waits. Waiting
longer than the acquire timeout reports ``local_model_busy`` instead of
silently queueing.
"""

import asyncio
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aihub_common import ProviderError

__all__ = ["LocalModels"]

#: Files needed by either mlx-audio (ASR) or mlx-lm (chat) when resolving a
#: cached Hugging Face snapshot. README and other repo files are not required.
MODEL_PATTERNS = ['*.json', '*.safetensors', '*.model', '*.tiktoken', '*.txt']


class LocalModels:
    """One GPU worker, at most one queued call. Cancellation never blocks the event loop."""

    def __init__(self):
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='aihub-model')
        self.slots = asyncio.Semaphore(2)
        self.cache = {}
        self.active_stops = set()

    def model(self, kind, name):
        key = (kind, name)
        if key not in self.cache:
            # Release the previous model of this kind before a configuration-driven replacement.
            for old in list(self.cache):
                if old[0] == kind:
                    del self.cache[old]
            if not Path(name).is_dir():
                from huggingface_hub import snapshot_download
                try:
                    name = snapshot_download(name, local_files_only=True,
                                             allow_patterns=MODEL_PATTERNS)
                except Exception:
                    raise ProviderError('local_model_not_cached') from None
            if kind == 'asr':
                from mlx_audio.stt.utils import load_model
                self.cache[key] = load_model(name)
            else:
                import mlx_lm
                self.cache[key] = mlx_lm.load(name)
        return self.cache[key]

    async def stream(self, factory):
        try:
            await asyncio.wait_for(self.slots.acquire(), 5)
        except TimeoutError:
            raise ProviderError('local_model_busy') from None
        stop, output = threading.Event(), queue.Queue(maxsize=16)
        self.active_stops.add(stop)

        def put(value):
            while not stop.is_set():
                try:
                    output.put(value, timeout=.05)
                    return
                except queue.Full:
                    continue

        def work():
            try:
                if not stop.is_set():
                    for value in factory(stop):
                        if stop.is_set():
                            break
                        put(('value', value))
            except Exception as exc:
                put(('error', exc.code if isinstance(exc, ProviderError) else 'local_model_failed'))
            finally:
                put(('done', None))

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self.pool, work)

        def release(_):
            self.active_stops.discard(stop)
            self.slots.release()

        future.add_done_callback(release)
        try:
            while True:
                try:
                    kind, value = output.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(.01)
                    continue
                if kind == 'done':
                    break
                if kind == 'error':
                    raise ProviderError(value)
                yield value
        finally:
            stop.set()

    def close(self):
        for stop in self.active_stops:
            stop.set()
        self.pool.shutdown(wait=False, cancel_futures=True)
