"""Read-only view of the server's finished recordings.

The model service never owns a recording: capture, fsync and the WAV header all
stay in the server. It only needs to read a finished recording back so that
diarization and meeting minutes can run out of process.

This is a deliberately small subset of the server's ``Recordings`` manager —
just ``get()`` and ``transcript()`` with the same return shapes — so that
``MinutesService`` and the job runner do not need to know where the data lives.

Only files matching ``<32 hex>.json`` / ``.txt`` are ever opened, and every path
is resolved inside ``root``.
"""

import json
import re
from pathlib import Path

from aihub_common import stamp_ms

__all__ = ["Records"]

IDENTITY = re.compile(r'[a-f0-9]{32}')
_STAMP = re.compile(r'^\[(\d{1,3}:\d{2}(?::\d{2})?)\]\s?(.*)$')
_SPEAKER = re.compile(r'^(说话人\s*(\d+))[：:]\s?(.*)$')

#: A reader can race the next append, so an incomplete final line is dropped.
MAX_TRANSCRIPT_BYTES = 4_000_000


class Records:
    """Filesystem-backed recordings/transcript access limited to ``root``."""

    def __init__(self, root):
        self.root = Path(root)

    def _valid(self, identity):
        return bool(IDENTITY.fullmatch(identity or ''))

    def metadata_path(self, identity):
        if not self._valid(identity):
            return None
        path = self.root / f'{identity}.json'
        return path if path.is_file() and not path.is_symlink() else None

    def transcript_path(self, identity):
        if not self._valid(identity):
            return None
        path = self.root / f'{identity}.txt'
        return path if path.is_file() and not path.is_symlink() else None

    def speech_map_path(self, identity):
        if not self._valid(identity):
            return None
        path = self.root / f'{identity}-speech.json'
        return path if path.is_file() and not path.is_symlink() else None

    def audio_path(self, identity):
        if not self._valid(identity):
            return None
        path = self.root / f'{identity}.wav'
        return path if path.is_file() and not path.is_symlink() else None

    def get(self, identity):
        """Return the metadata sidecar, or ``None`` when it does not exist."""
        path = self.metadata_path(identity)
        if path is None:
            return None
        try:
            metadata = json.loads(path.read_text())
        except (OSError, ValueError):
            return None
        if not isinstance(metadata, dict) or metadata.get('id') != identity:
            return None
        transcript = self.transcript_path(identity)
        metadata['transcript_available'] = bool(transcript)
        metadata.setdefault('transcript_lines', 0)
        metadata.setdefault('speaker_count', 0)
        metadata.setdefault('transcription_error', None)
        return metadata

    def transcript(self, identity):
        """Return the parsed transcript, or ``None`` when the recording is unknown.

        Line shape matches the server exactly: ``stamp``, ``elapsed_ms``,
        ``speaker``, ``speaker_id``, ``text``. The final line is discarded when
        it has no trailing newline, because that means a writer is mid-append.
        """
        metadata = self.get(identity)
        if metadata is None:
            return None
        path = self.transcript_path(identity)
        if path is None:
            return {'id': identity, 'status': metadata.get('status'), 'available': False,
                    'text': '', 'count': 0}
        try:
            data = path.read_text(encoding='utf-8', errors='replace')
        except OSError:
            data = ''
        if len(data) > MAX_TRANSCRIPT_BYTES:
            data = data[-MAX_TRANSCRIPT_BYTES:]
        if data and not data.endswith('\n'):
            cut = data.rfind('\n')
            data = data[:cut + 1] if cut >= 0 else ''
        raw_lines = data.splitlines()
        lines = []
        for raw in raw_lines:
            match = _STAMP.match(raw)
            if match:
                stamp, rest = match.group(1), match.group(2)
                speaker_match = _SPEAKER.match(rest)
                if speaker_match:
                    speaker, speaker_id, text = (speaker_match.group(1),
                                                 int(speaker_match.group(2)),
                                                 speaker_match.group(3))
                else:
                    speaker, speaker_id, text = None, None, rest
                lines.append({'stamp': stamp, 'elapsed_ms': stamp_ms(stamp),
                              'speaker': speaker, 'speaker_id': speaker_id,
                              'text': text})
            else:
                lines.append({'stamp': '', 'elapsed_ms': None, 'speaker': None,
                              'speaker_id': None, 'text': raw})
        mapping = None
        map_path = self.speech_map_path(identity)
        if map_path:
            try:
                mapping = json.loads(map_path.read_text())
            except (OSError, ValueError):
                mapping = None
        return {'id': identity, 'status': metadata.get('status'), 'available': True,
                'text': '\n'.join(raw_lines), 'lines': lines, 'count': len(lines),
                'speech_map': mapping}
