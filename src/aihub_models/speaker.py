"""SpeechBrain ECAPA speaker embeddings.

The model half of the old ``voicehub/speaker.py``. The clustering half —
``SpeakerTracker`` — moved to ``aihub-common`` because it needs no model and is
also used by the server while a recording is still running.

Embeddings are normalised here and returned as float32; callers never persist
them. Lazy loading keeps torch and speechbrain out of the import path until the
first embedding is actually requested.
"""

import os
import threading
from pathlib import Path

import numpy as np

from aihub_common import SpeakerUnavailable, env_value, normalize

class SpeakerEngine:
    """Lazy, process-wide ECAPA model; CPU inference guarded by a lock."""
    def __init__(self, cache_dir=None):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self._model = None
        self._lock = threading.Lock()

    def _snapshot(self):
        override = env_value('SPEAKER_MODEL')
        if override:
            path = Path(override).expanduser()
            if (path/'hyperparams.yaml').is_file():
                return path
            raise SpeakerUnavailable('speaker_model_missing')
        base = Path.home()/'.cache/huggingface/hub/models--speechbrain--spkrec-ecapa-voxceleb/snapshots'
        for candidate in sorted(base.glob('*')):
            if (candidate/'hyperparams.yaml').is_file():
                return candidate
        raise SpeakerUnavailable('speaker_model_missing')

    def _load(self):
        with self._lock:
            if self._model is not None:
                return self._model
            try:
                import torch
                from speechbrain.inference.speaker import SpeakerRecognition
            except Exception:
                raise SpeakerUnavailable('speaker_runtime_unavailable') from None
            snapshot = self._snapshot()
            cached = self.cache_dir or (Path.home()/'.cache/aihub-speaker')
            cached.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault('HF_HUB_OFFLINE', '1')
            torch.set_num_threads(1)
            try:
                model = SpeakerRecognition.from_hparams(
                    source=str(snapshot), savedir=str(cached),
                    run_opts={'device': 'cpu'})
            except Exception:
                raise SpeakerUnavailable('speaker_model_load_failed') from None
            self._model = model
            return model

    def embed_batch(self, frames):
        """Embed equal-length 16 kHz frames in one model call."""
        if not isinstance(frames, (list, tuple)) or not frames:
            return np.zeros((0, 192), dtype=np.float32)
        lengths = {len(frame) for frame in frames}
        if len(lengths) != 1:
            raise SpeakerUnavailable('speaker_batch_invalid')
        audio = np.stack([np.asarray(frame, dtype=np.float32).reshape(-1)
                          for frame in frames])
        if audio.shape[1] < 800:
            raise SpeakerUnavailable('speaker_segment_too_short')
        model = self._load()
        with self._lock:
            try:
                import torch
                with torch.no_grad():
                    tensor = torch.from_numpy(audio)
                    embeddings = model.encode_batch(tensor).reshape(len(frames), -1)
                    embeddings = embeddings.cpu().numpy()
            except SpeakerUnavailable:
                raise
            except Exception:
                raise SpeakerUnavailable('speaker_embedding_failed') from None
        output = []
        for embedding in embeddings:
            output.append(normalize(embedding))
        return np.stack(output)

    def embed(self, pcm):
        """Return one normalized 192-d embedding for 16 kHz mono PCM."""
        audio = np.asarray(pcm)
        if audio.dtype.kind in 'iu':
            audio = audio.astype(np.float32)/32768.0
        else:
            audio = audio.astype(np.float32, copy=False)
        audio = audio.reshape(-1)
        if audio.size < 800:
            raise SpeakerUnavailable('speaker_segment_too_short')
        model = self._load()
        with self._lock:
            try:
                import torch
                with torch.no_grad():
                    tensor = torch.from_numpy(audio).unsqueeze(0)
                    embedding = model.encode_batch(tensor).reshape(-1)
                    embedding = embedding.cpu().numpy()
            except SpeakerUnavailable:
                raise
            except Exception:
                raise SpeakerUnavailable('speaker_embedding_failed') from None
        return normalize(embedding)
