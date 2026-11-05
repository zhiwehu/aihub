import json
import wave
from unittest import IsolatedAsyncioTestCase, mock

import numpy as np
import pytest

from aihub_models import diarize
from aihub_models.diarize import (cluster, consolidate_labels, label_existing_text,
                                  smooth_labels, turns_from_windows, windows)

RID = 'c' * 32


def write_wav(path, seconds, amplitude=.3, rate=16000):
    tone = (np.sin(2 * np.pi * 220 * np.arange(int(seconds * rate)) / rate) * amplitude)
    with wave.open(str(path), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes((tone * 32767).astype('<i2').tobytes())


def unit(index, size=8):
    vector = np.zeros(size, dtype=np.float32)
    vector[index] = 1.0
    return vector


# ---- pure helpers ----------------------------------------------------------

def test_windows_only_keep_frames_above_the_rms_floor():
    silence = np.zeros(16000 * 4, dtype=np.float32)
    assert windows(silence) == []
    tone = np.full(16000 * 4, .3, dtype=np.float32)
    rows = windows(tone)
    assert rows
    start, frame = rows[0]
    assert start == 0
    assert len(frame) == int(1.6 * 16000)


def test_windows_hop_and_size_decide_the_count():
    tone = np.full(16000 * 8, .3, dtype=np.float32)
    starts = [start for start, _ in windows(tone)]
    assert starts == sorted(starts)
    assert starts[1] - starts[0] == int(.8 * 16000)


def test_cluster_separates_two_orthogonal_groups():
    embeddings = [unit(0) for _ in range(6)] + [unit(1) for _ in range(6)]
    labels = cluster(embeddings, 2)
    assert len(set(labels[:6].tolist())) == 1
    assert len(set(labels[6:].tolist())) == 1
    assert labels[0] != labels[6]


def test_smooth_labels_removes_a_single_window_flicker():
    labels = np.array([1, 1, 2, 1, 1], dtype=int)
    assert smooth_labels(labels, radius=1).tolist() == [1, 1, 1, 1, 1]


def test_consolidate_labels_merges_a_tiny_cluster():
    embeddings = np.stack([unit(0)] * 9 + [unit(1)] * 1)
    labels = np.array([0] * 9 + [1], dtype=int)
    centroids = [embeddings[labels == index].mean(0) for index in (0, 1)]
    merged = consolidate_labels(labels, centroids, min_share=.06, min_count=3)
    assert len(set(merged.tolist())) == 1


def test_turns_from_windows_keeps_short_turns_merged():
    labels = np.array([1, 1, 1, 1], dtype=int)
    groups = turns_from_windows(labels, duration=3.2)
    assert len(groups) == 1
    start, end, speaker = groups[0]
    assert start == 0
    assert speaker == 1


def test_label_existing_text_splits_sentences_across_speakers():
    groups = [(0.0, 4.0, 1), (4.0, 8.0, 2)]
    text = '[00:00] 我们开始吧。今天讨论排期。\n'
    lines = label_existing_text(text, groups, 8.0)
    assert lines
    assert {line['speaker_id'] for line in lines} <= {1, 2}
    assert all(line['text'] for line in lines)


# ---- end-to-end with a fake embedding model --------------------------------

class FakeSpeakerEngine:
    """Alternating two orthogonal voices, so clustering has a clear answer."""

    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    def embed_batch(self, frames):
        rows = []
        for _ in frames:
            rows.append(unit(FakeSpeakerEngine.calls % 2))
            FakeSpeakerEngine.calls += 1
        return np.stack(rows)


class RediarizeTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        FakeSpeakerEngine.calls = 0

    async def test_text_mode_rewrites_the_transcript_and_bumps_the_revision(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            write_wav(recordings / f'{RID}.wav', 8)
            (recordings / f'{RID}.json').write_text(json.dumps({'id': RID, 'status': 'stopped'}))
            (recordings / f'{RID}.txt').write_text(
                '[00:00] 我们开始吧。\n[00:02] 今天讨论排期。\n[00:05] 我同意。\n')
            with mock.patch.object(diarize, 'SpeakerEngine', FakeSpeakerEngine):
                result = await diarize.rediarize(RID, root, speakers=2, mode='text')
            self.assertGreaterEqual(result['lines'], 1)
            metadata = json.loads((recordings / f'{RID}.json').read_text())
            self.assertEqual(metadata['diarization_revision'], 1)
            self.assertEqual(metadata['diarization_method'], 'ecapa-window-text-align')
            self.assertIsNone(metadata['transcription_error'])
            text = (recordings / f'{RID}.txt').read_text()
            self.assertIn('说话人', text)
            self.assertTrue((recordings / f'{RID}.txt.before-diarization').is_file())

    async def test_asr_mode_calls_the_injected_transcribe(self):
        import tempfile
        from pathlib import Path

        async def transcribe(pcm):
            self.calls.append(len(pcm))
            return '这是重新识别的文字。'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            write_wav(recordings / f'{RID}.wav', 8)
            (recordings / f'{RID}.json').write_text(json.dumps({'id': RID, 'status': 'stopped'}))
            (recordings / f'{RID}.txt').write_text('[00:00] 旧文字。\n')
            with mock.patch.object(diarize, 'SpeakerEngine', FakeSpeakerEngine):
                result = await diarize.rediarize(RID, root, transcribe=transcribe,
                                                 speakers=2, mode='asr')
            self.assertTrue(self.calls)
            self.assertGreaterEqual(result['lines'], 1)
            self.assertIn('这是重新识别的文字。', (recordings / f'{RID}.txt').read_text())

    async def test_asr_mode_without_a_transcriber_fails_loudly(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            write_wav(recordings / f'{RID}.wav', 8)
            (recordings / f'{RID}.json').write_text(json.dumps({'id': RID, 'status': 'stopped'}))
            with mock.patch.object(diarize, 'SpeakerEngine', FakeSpeakerEngine):
                with pytest.raises(ValueError) as caught:
                    await diarize.rediarize(RID, root, transcribe=None, speakers=2, mode='asr')
            self.assertEqual(str(caught.value), 'transcribe_required')

    async def test_active_recording_is_refused(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            write_wav(recordings / f'{RID}.wav', 8)
            (recordings / f'{RID}.json').write_text(json.dumps({'id': RID, 'status': 'active'}))
            with self.assertRaises(ValueError) as caught:
                await diarize.rediarize(RID, root, speakers=2, mode='text')
            self.assertEqual(str(caught.exception), 'recording_active')
