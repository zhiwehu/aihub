import numpy as np
import pytest

from aihub_common import TARGET_RATE, to_pcm16


def as_int16(payload):
    return np.frombuffer(payload, '<i2').tolist()


def test_target_rate_is_16k():
    assert TARGET_RATE == 16000


def test_float_input_is_clipped_not_wrapped():
    out = to_pcm16(np.array([0.0, 1.0, -1.0, 2.0, -2.0], dtype=np.float32), 16000)
    assert as_int16(out) == [0, 32767, -32767, 32767, -32767]


def test_float_input_keeps_little_endian_layout():
    out = to_pcm16(np.array([1.0], dtype=np.float32), 16000)
    assert out == b'\xff\x7f'


def test_empty_input_produces_no_bytes():
    assert to_pcm16(np.array([], dtype=np.float32), 16000) == b''
    assert to_pcm16(b'', 16000) == b''


def test_multichannel_input_is_flattened():
    # The boundary is mono-only; a 2-D array is flattened rather than silently
    # keeping the channel axis and producing interleaved garbage downstream.
    out = to_pcm16(np.zeros((2, 3), dtype=np.float32), 16000)
    assert len(out) == 6 * 2


def test_16k_resample_is_not_attempted():
    """A 16 kHz source must not require ``av`` to be installed."""
    import builtins

    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == 'av':
            raise AssertionError('av must not be imported for 16 kHz input')
        return real_import(name, *args, **kwargs)

    builtins.__import__ = guarded
    try:
        assert to_pcm16(np.zeros(160, dtype=np.float32), 16000) == b'\0' * 320
    finally:
        builtins.__import__ = real_import


def test_bytes_input_loses_one_lsb():
    """Documents current behaviour rather than endorsing it.

    Packed s16le is decoded with a 32768 divisor and re-encoded with a 32767
    multiplier, so it is not bit-exact. Callers in AIHub pass float arrays, so
    this path is unused today; changing it is a separate decision with its own
    audio-quality check.
    """
    source = np.array([1000, -2000], dtype='<i2').tobytes()
    out = as_int16(to_pcm16(source, 16000))
    assert out == [999, -1999]
    assert all(abs(a - b) <= 1 for a, b in zip(out, [1000, -2000]))


def test_24k_source_is_resampled_to_16k():
    pytest.importorskip('av')
    tone = np.sin(2 * np.pi * 440 * np.arange(24000) / 24000).astype(np.float32) * 0.5
    out = to_pcm16(tone, 24000)
    samples = len(out) // 2
    assert abs(samples - 16000) <= 64


def test_48k_source_is_resampled_to_16k():
    pytest.importorskip('av')
    tone = np.sin(2 * np.pi * 440 * np.arange(48000) / 48000).astype(np.float32) * 0.5
    samples = len(to_pcm16(tone, 48000)) // 2
    assert abs(samples - 16000) <= 64
