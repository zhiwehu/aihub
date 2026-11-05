import shutil
import subprocess
import wave

import numpy as np
import pytest

from aihub_models.cleanup import PROFILES, CleanupError, clean_wav


def write_wav(path, seconds=1.0, rate=16000):
    tone = (np.sin(2 * np.pi * 220 * np.arange(int(seconds * rate)) / rate) * .3)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((tone * 32767).astype('<i2').tobytes())


def test_profiles_are_the_two_documented_ones():
    assert set(PROFILES) == {'mild', 'strong'}
    for chain in PROFILES.values():
        assert 'highpass' in chain
        assert 'alimiter' in chain


def test_unknown_profile_is_rejected_before_touching_files(tmp_path):
    with pytest.raises(CleanupError) as caught:
        clean_wav(tmp_path / 'missing.wav', tmp_path / 'out.wav', 'aggressive')
    assert caught.value.code == 'invalid_cleanup_profile'


def test_missing_source_is_reported(tmp_path):
    with pytest.raises(CleanupError) as caught:
        clean_wav(tmp_path / 'missing.wav', tmp_path / 'out.wav')
    assert caught.value.code == 'cleanup_source_missing'


def test_missing_ffmpeg_is_reported(monkeypatch, tmp_path):
    source = tmp_path / 'in.wav'
    write_wav(source)
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    with pytest.raises(CleanupError) as caught:
        clean_wav(source, tmp_path / 'out.wav')
    assert caught.value.code == 'cleanup_unavailable'


def test_failed_ffmpeg_is_reported(monkeypatch, tmp_path):
    source = tmp_path / 'in.wav'
    write_wav(source)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args, 1, b'', b'boom')

    monkeypatch.setattr(subprocess, 'run', fake_run)
    with pytest.raises(CleanupError) as caught:
        clean_wav(source, tmp_path / 'out.wav')
    assert caught.value.code == 'cleanup_failed'
    # A failed run must not leave a temporary file behind.
    assert list(tmp_path.glob('.*.wav')) == []


@pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg not installed')
def test_real_ffmpeg_keeps_duration_and_format(tmp_path):
    source = tmp_path / 'in.wav'
    destination = tmp_path / 'out.wav'
    write_wav(source, seconds=2.0)
    stats = clean_wav(source, destination, 'mild')
    assert stats['profile'] == 'mild'
    assert abs(stats['duration_ms'] - 2000) <= 2
    with wave.open(str(destination), 'rb') as handle:
        assert (handle.getnchannels(), handle.getsampwidth(),
                handle.getframerate()) == (1, 2, 16000)
    # The source is never modified.
    assert source.is_file()
