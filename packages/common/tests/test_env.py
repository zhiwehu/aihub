import pytest

from aihub_common import env_value


def test_reads_the_aihub_prefix(monkeypatch):
    monkeypatch.setenv('AIHUB_SAMPLE', 'new')
    assert env_value('SAMPLE') == 'new'


def test_falls_back_to_the_legacy_prefix(monkeypatch):
    monkeypatch.delenv('AIHUB_SAMPLE', raising=False)
    monkeypatch.setenv('VOICEHUB_SAMPLE', 'old')
    assert env_value('SAMPLE') == 'old'


def test_aihub_prefix_wins_when_both_are_set(monkeypatch):
    monkeypatch.setenv('AIHUB_SAMPLE', 'new')
    monkeypatch.setenv('VOICEHUB_SAMPLE', 'old')
    assert env_value('SAMPLE') == 'new'


def test_default_is_returned_when_neither_is_set(monkeypatch):
    monkeypatch.delenv('AIHUB_SAMPLE', raising=False)
    monkeypatch.delenv('VOICEHUB_SAMPLE', raising=False)
    assert env_value('SAMPLE') is None
    assert env_value('SAMPLE', 'fallback') == 'fallback'


def test_empty_string_counts_as_set(monkeypatch):
    # An explicitly exported empty value must not silently fall through to the
    # legacy name; that would make "unset it" impossible.
    monkeypatch.setenv('AIHUB_SAMPLE', '')
    monkeypatch.setenv('VOICEHUB_SAMPLE', 'old')
    assert env_value('SAMPLE') == ''


@pytest.mark.parametrize('name', ['WORKER_TOKEN', 'SPEAKER_MODEL', 'MINUTES_MODEL'])
def test_known_knobs_follow_the_same_rule(monkeypatch, name):
    monkeypatch.setenv('AIHUB_' + name, 'x')
    monkeypatch.setenv('VOICEHUB_' + name, 'y')
    assert env_value(name) == 'x'
