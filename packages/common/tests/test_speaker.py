import numpy as np
import pytest

from aihub_common import SpeakerTracker, SpeakerUnavailable, normalize


def unit(index, size=8):
    """One-hot direction: two different indices have zero cosine similarity."""
    vector = np.zeros(size, dtype=np.float32)
    vector[index] = 1.0
    return vector


def test_normalize_returns_unit_length():
    out = normalize(np.array([3.0, 4.0], dtype=np.float32))
    assert out.dtype == np.float32
    assert pytest.approx(float(np.linalg.norm(out)), abs=1e-6) == 1.0
    assert out.tolist() == pytest.approx([0.6, 0.8], abs=1e-6)


def test_normalize_rejects_degenerate_vectors():
    for bad in ([0.0, 0.0], [float('nan'), 1.0], [float('inf'), 1.0]):
        with pytest.raises(SpeakerUnavailable) as caught:
            normalize(np.array(bad, dtype=np.float32))
        assert caught.value.code == 'speaker_embedding_invalid'


def test_assign_starts_at_speaker_one():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2)
    assert tracker.assign(unit(0), 1.0) == (1, '说话人1')
    assert tracker.count == 1


def test_similar_embedding_joins_existing_speaker():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2)
    tracker.assign(unit(0), 1.0)
    # Same direction with a little noise is still the same person.
    noisy = unit(0) + np.array([0, .1, 0, 0, 0, 0, 0, 0], dtype=np.float32)
    assert tracker.assign(noisy, 1.0) == (1, '说话人1')
    assert tracker.count == 1


def test_orthogonal_embedding_creates_a_new_speaker():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2)
    tracker.assign(unit(0), 1.0)
    assert tracker.assign(unit(1), 1.0) == (2, '说话人2')
    assert tracker.count == 2


def test_short_segment_never_creates_a_speaker():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=1.2)
    tracker.assign(unit(0), 1.0)
    # Below min_seconds the orthogonal segment joins the nearest speaker instead.
    identity, label = tracker.assign(unit(1), .5)
    assert identity == 1
    assert label == '说话人1'
    assert tracker.count == 1


def test_max_speakers_caps_growth():
    tracker = SpeakerTracker(threshold=.25, max_speakers=2, min_seconds=.2)
    tracker.assign(unit(0), 1.0)
    tracker.assign(unit(1), 1.0)
    assert tracker.assign(unit(2), 1.0)[0] in (1, 2)
    assert tracker.count == 2


def test_promote_seconds_requires_persistent_evidence():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2,
                             promote_seconds=2.0)
    tracker.assign(unit(0), 1.0)
    # First unmatched window is provisional: no new speaker yet.
    assert tracker.assign(unit(1), 1.0) == (1, '说话人1')
    assert tracker.count == 1
    # Second window pushes accumulated evidence past the threshold.
    assert tracker.assign(unit(1), 1.0) == (2, '说话人2')
    assert tracker.count == 2


def test_refine_folds_singleton_clusters():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2)
    tracker.assign(unit(0), 1.0)
    tracker.assign(unit(1), 1.0)
    tracker.assign(unit(0), 1.0)   # speaker 1 now has two segments
    tracker.assign(unit(2), 1.0)   # speaker 3 has only one
    mapping, count = tracker.refine()
    assert count == 2
    assert mapping == {1: 1, 2: 2, 3: 2}


def test_refine_renumbers_by_first_appearance():
    tracker = SpeakerTracker(threshold=.25, max_speakers=6, min_seconds=.2)
    tracker.assign(unit(0), 1.0)
    tracker.assign(unit(1), 1.0)
    tracker.assign(unit(0), 1.0)
    tracker.assign(unit(1), 1.0)
    mapping, count = tracker.refine()
    assert count == 2
    assert mapping == {1: 1, 2: 2}


def test_refine_with_no_speakers_is_empty():
    tracker = SpeakerTracker()
    assert tracker.refine() == ({}, 0)


def test_aihub_env_prefix_wins_over_the_legacy_voicehub_prefix(monkeypatch):
    monkeypatch.setenv('VOICEHUB_SPEAKER_MAX', '6')
    monkeypatch.setenv('AIHUB_SPEAKER_MAX', '3')
    assert SpeakerTracker().max_speakers == 3


def test_legacy_voicehub_env_still_works(monkeypatch):
    monkeypatch.delenv('AIHUB_SPEAKER_MAX', raising=False)
    monkeypatch.setenv('VOICEHUB_SPEAKER_MAX', '4')
    assert SpeakerTracker().max_speakers == 4


def test_env_values_are_clamped(monkeypatch):
    monkeypatch.setenv('AIHUB_SPEAKER_MAX', '99')
    assert SpeakerTracker().max_speakers == 12
    monkeypatch.setenv('AIHUB_SPEAKER_THRESHOLD', '-1')
    assert SpeakerTracker().threshold == .05
