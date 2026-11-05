import pytest

from aihub_common import stamp_ms, stamp_text


@pytest.mark.parametrize('ms,text', [
    (0, '00:00'),
    (999, '00:00'),
    (1000, '00:01'),
    (59_999, '00:59'),
    (60_000, '01:00'),
    (3_599_000, '59:59'),
    (3_600_000, '1:00:00'),
    (7_384_000, '2:03:04'),
])
def test_stamp_text_formats(ms, text):
    assert stamp_text(ms) == text


def test_stamp_text_switches_to_hours_only_past_one_hour():
    assert stamp_text(3_599_999) == '59:59'
    assert stamp_text(3_600_000) == '1:00:00'


def test_negative_elapsed_clamps_to_zero():
    assert stamp_text(-5000) == '00:00'


@pytest.mark.parametrize('text', ['00:00', '00:01', '01:00', '59:59', '1:00:00', '2:03:04'])
def test_stamp_round_trips(text):
    assert stamp_text(stamp_ms(text)) == text


def test_stamp_ms_values():
    assert stamp_ms('00:12') == 12_000
    assert stamp_ms('02:03') == 123_000
    assert stamp_ms('1:02:03') == 3_723_000


def test_stamp_ms_rejects_garbage():
    with pytest.raises(ValueError):
        stamp_ms('not-a-stamp')
    with pytest.raises(ValueError):
        stamp_ms('1:2:3:4')
