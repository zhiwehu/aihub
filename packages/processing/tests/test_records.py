import json

from aihub_models.records import Records

RID = 'a' * 32


def build(tmp_path, metadata=None, transcript=None, speech_map=None):
    root = tmp_path / 'recordings'
    root.mkdir()
    if metadata is not None:
        (root / f'{RID}.json').write_text(json.dumps(metadata))
    if transcript is not None:
        (root / f'{RID}.txt').write_text(transcript)
    if speech_map is not None:
        (root / f'{RID}-speech.json').write_text(json.dumps(speech_map))
    return Records(root)


def test_unknown_recording_returns_none(tmp_path):
    records = Records(tmp_path / 'recordings')
    assert records.get(RID) is None
    assert records.transcript(RID) is None


def test_invalid_identity_is_rejected(tmp_path):
    records = Records(tmp_path)
    for bad in ('', '../etc/passwd', 'A' * 32, 'a' * 31, None, 'a' * 33):
        assert records.get(bad) is None
        assert records.transcript(bad) is None


def test_metadata_mismatch_is_rejected(tmp_path):
    records = build(tmp_path, metadata={'id': 'b' * 32, 'status': 'stopped'})
    assert records.get(RID) is None


def test_get_decorates_missing_fields(tmp_path):
    records = build(tmp_path, metadata={'id': RID, 'status': 'stopped'})
    metadata = records.get(RID)
    assert metadata['status'] == 'stopped'
    assert metadata['transcript_available'] is False
    assert metadata['transcript_lines'] == 0
    assert metadata['speaker_count'] == 0
    assert metadata['transcription_error'] is None


def test_transcript_parses_stamps_and_speakers(tmp_path):
    text = '[00:00] 说话人1：大家好。\n[00:12] 说话人2：你好。\n[01:02:03] 说话人1：很久以后。\n'
    records = build(tmp_path, metadata={'id': RID, 'status': 'stopped'}, transcript=text)
    result = records.transcript(RID)
    assert result['available'] is True
    assert result['count'] == 3
    first, second, third = result['lines']
    assert first == {'stamp': '00:00', 'elapsed_ms': 0, 'speaker': '说话人1',
                     'speaker_id': 1, 'text': '大家好。'}
    assert second['elapsed_ms'] == 12_000
    assert second['speaker_id'] == 2
    assert third['elapsed_ms'] == 3_723_000
    assert third['speaker'] == '说话人1'


def test_transcript_accepts_lines_without_stamp_or_speaker(tmp_path):
    records = build(tmp_path, metadata={'id': RID}, transcript='没有任何标记的一行\n')
    line = records.transcript(RID)['lines'][0]
    assert line == {'stamp': '', 'elapsed_ms': None, 'speaker': None,
                    'speaker_id': None, 'text': '没有任何标记的一行'}


def test_incomplete_trailing_line_is_dropped(tmp_path):
    """A reader can race the next append; only the partial tail is discarded."""
    text = '[00:00] 说话人1：第一行。\n[00:05] 说话人1：还没写完'
    records = build(tmp_path, metadata={'id': RID}, transcript=text)
    result = records.transcript(RID)
    assert result['count'] == 1
    assert result['lines'][0]['text'] == '第一行。'


def test_missing_transcript_reports_unavailable(tmp_path):
    records = build(tmp_path, metadata={'id': RID, 'status': 'stopped'})
    result = records.transcript(RID)
    assert result['available'] is False
    assert result['text'] == ''
    assert result['count'] == 0


def test_speech_map_is_attached_when_present(tmp_path):
    mapping = {'segments': [[0, 1000]]}
    records = build(tmp_path, metadata={'id': RID},
                    transcript='[00:00] 说话人1：好。\n', speech_map=mapping)
    assert records.transcript(RID)['speech_map'] == mapping
