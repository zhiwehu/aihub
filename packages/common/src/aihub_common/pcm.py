"""The 16 kHz mono PCM boundary shared by the server and the model services.

Every producer in AIHub (browser, ESP32 Opus, macOS ``say`` at 22.05 kHz, local
TTS at 24 kHz) funnels through :func:`to_pcm16` before audio reaches a model.
"""

import numpy as np

#: Everything downstream assumes 16 kHz mono s16le.
TARGET_RATE = 16000

__all__ = ["TARGET_RATE", "to_pcm16"]


def to_pcm16(audio, source_rate):
    """Return mono s16le little-endian bytes resampled to :data:`TARGET_RATE`.

    ``audio`` is either packed s16le bytes or a float array in ``[-1, 1]``.
    Values outside that range are clipped rather than wrapped.

    ``av`` is imported only when a real resample is required, so callers that
    already produce 16 kHz (the device path, the browser path) never pay for
    the import or depend on the package.
    """
    if isinstance(audio, bytes):
        audio = np.frombuffer(audio, '<i2').astype(np.float32) / 32768
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if source_rate != TARGET_RATE and len(audio):
        return _resample(audio, source_rate)
    return (np.clip(audio, -1, 1) * 32767).astype('<i2').tobytes()


def _resample(audio, source_rate):
    import av  # optional dependency: only non-16 kHz sources need it

    frame = av.AudioFrame.from_ndarray(audio.reshape(1, -1), format='flt', layout='mono')
    frame.sample_rate = source_rate
    resampler = av.AudioResampler(format='s16', layout='mono', rate=TARGET_RATE)
    frames = resampler.resample(frame) + resampler.resample(None)
    return b''.join(item.to_ndarray().astype('<i2').tobytes() for item in frames)
