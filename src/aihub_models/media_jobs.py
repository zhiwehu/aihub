"""Async file-to-file media jobs that must not run on the voice hot path.

Two kinds are owned here:

* ``clean`` — ffmpeg denoise of a finished recording (``<id>-clean.wav``).
* ``diarize`` — re-cluster speakers and rewrite the transcript.

``speech_only`` is **not** here on purpose: trimming the WAV to speech needs the
Silero VAD that runs inline with the live audio stream, which lives in the
server. Moving it would either duplicate the model or add a round trip per
audio packet.

Meeting minutes are also not here: they have templates, evidence and revisions,
so they keep their own job model (see ``aihub_models.minutes``).

Every path is validated against ``recordings_root``; a job can never be asked
to touch an arbitrary file.
"""

import asyncio
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from aihub_common import ProviderError
from .cleanup import CleanupError, clean_wav
from .diarize import rediarize
from .records import IDENTITY

__all__ = ["MediaJobs", "MediaJobError"]

KINDS = ('clean', 'diarize')
STATUSES = ('queued', 'running', 'done', 'failed', 'cancelled', 'interrupted')
JOB_ID = re.compile(r'[a-f0-9]{32}')
MAX_QUEUED = 8
CLEAN_PROFILES = ('mild', 'strong')
#: ``audio`` is the untouched recording; ``speech`` is the VAD-trimmed copy the
#: server writes next to it. The player prefers a denoised ``ready`` cut.
CLEAN_SOURCES = ('audio', 'speech')
CLEAN_TARGETS = ('clean', 'ready')


class MediaJobError(RuntimeError):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or code
        super().__init__(code)


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix('.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        temporary.unlink(missing_ok=True)


class MediaJobs:
    """One-at-a-time job runner with a small persistent queue."""

    def __init__(self, root, recordings_root, transcribe=None):
        self.root = Path(root)
        self.records_root = Path(recordings_root)
        self.transcribe = transcribe
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.jobs = {}
        self.tasks = {}
        self.cancel_events = {}
        self._lock = asyncio.Lock()

    # ---- persistence ---------------------------------------------------

    def job_dir(self, recording_id):
        return self.root / recording_id

    def job_path(self, recording_id, job_id):
        return self.job_dir(recording_id) / f'{job_id}.json'

    def recover(self):
        """A job cannot survive a restart; anything unfinished is ``interrupted``."""
        for path in self.root.glob('*/*.json'):
            try:
                job = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if job.get('status') in ('queued', 'running'):
                job['status'] = 'interrupted'
                job['message'] = '服务重启，任务已中断；可以重新提交。'
                job['updated_at'] = time.time()
                _atomic_json(path, job)

    def save(self, job):
        job['updated_at'] = time.time()
        _atomic_json(self.job_path(job['recording_id'], job['id']), job)
        self.jobs[job['id']] = job

    def get(self, job_id):
        job = self.jobs.get(job_id)
        if job is not None:
            return job
        if not JOB_ID.fullmatch(job_id or ''):
            return None
        for path in self.root.glob(f'*/{job_id}.json'):
            try:
                job = json.loads(path.read_text())
            except (OSError, ValueError):
                return None
            if isinstance(job, dict) and job.get('id') == job_id:
                return job
        return None

    def list(self, recording_id=None):
        jobs = []
        pattern = f'{recording_id}/*.json' if recording_id else '*/*.json'
        if recording_id and not IDENTITY.fullmatch(recording_id):
            return []
        for path in self.root.glob(pattern):
            try:
                job = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(job, dict) and JOB_ID.fullmatch(str(job.get('id', ''))):
                jobs.append(job)
        return sorted(jobs, key=lambda item: item.get('created_at') or 0, reverse=True)

    def active(self):
        return [job for job in self.list() if job.get('status') in ('queued', 'running')]

    # ---- validation ----------------------------------------------------

    def source_path(self, recording_id, source='audio'):
        """Resolve one input WAV inside the recordings root."""
        if source not in CLEAN_SOURCES:
            raise MediaJobError('invalid_options', '未知的音频来源。')
        suffix = '' if source == 'audio' else '-speech'
        return self.records_root / f'{recording_id}{suffix}.wav'

    def target_path(self, recording_id, target='clean'):
        if target not in CLEAN_TARGETS:
            raise MediaJobError('invalid_options', '未知的输出版本。')
        return self.records_root / f'{recording_id}-{target}.wav'

    def _validate(self, kind, recording_id, options):
        if kind not in KINDS:
            raise MediaJobError('invalid_job_kind', f'不支持的任务类型：{kind}')
        if not isinstance(recording_id, str) or not IDENTITY.fullmatch(recording_id):
            raise MediaJobError('recording_not_found', '找不到这条录音。')
        if not isinstance(options, dict):
            raise MediaJobError('invalid_options', '任务参数必须是对象。')
        if kind == 'clean':
            profile = options.get('profile', 'mild')
            source = options.get('source', 'audio')
            target = options.get('target', 'clean')
            if profile not in CLEAN_PROFILES:
                raise MediaJobError('invalid_cleanup_profile', '未知的降噪档位。')
            if source not in CLEAN_SOURCES:
                raise MediaJobError('invalid_options', '未知的音频来源。')
            if target not in CLEAN_TARGETS:
                raise MediaJobError('invalid_options', '未知的输出版本。')
            if not self.source_path(recording_id, source).is_file():
                raise MediaJobError('recording_audio_missing', '这条录音没有可用的音频文件。')
            return {'profile': profile, 'source': source, 'target': target}
        if not self.source_path(recording_id, 'audio').is_file():
            raise MediaJobError('recording_audio_missing', '这条录音没有可用的音频文件。')
        mode = options.get('mode', 'text')
        if mode not in ('text', 'asr'):
            raise MediaJobError('invalid_options', '重分轨只支持 text 或 asr 模式。')
        speakers = options.get('speakers', 0)
        if type(speakers) is not int or not 0 <= speakers <= 12:
            raise MediaJobError('invalid_options', '说话人数量必须在 0–12 之间。')
        return {'mode': mode, 'speakers': speakers}

    # ---- lifecycle -----------------------------------------------------

    async def start(self, kind, recording_id, options=None):
        options = self._validate(kind, recording_id, {} if options is None else options)
        async with self._lock:
            if len(self.active()) >= MAX_QUEUED:
                raise MediaJobError('queue_full', '任务队列已满，请稍后再试。')
            job = {
                'id': uuid.uuid4().hex,
                'kind': kind,
                'recording_id': recording_id,
                'options': options,
                'status': 'queued',
                'message': '已排队',
                'progress': 0,
                'created_at': time.time(),
                'outputs': [],
                'error': None,
            }
            self.cancel_events[job['id']] = threading.Event()
            self.save(job)
            self.tasks[job['id']] = asyncio.create_task(self._run(job))
        return job

    async def cancel(self, job_id):
        job = self.get(job_id)
        if job is None:
            raise MediaJobError('job_not_found', '找不到这个任务。')
        if job.get('status') not in ('queued', 'running'):
            return job
        event = self.cancel_events.get(job_id)
        if event is not None:
            event.set()
        # A queued job can be cancelled immediately; a running one finishes the
        # step it is in, because ffmpeg and the embedding loop are not interruptible
        # without leaving a half-written output.
        job['status'] = 'cancelled'
        job['message'] = '已取消'
        self.save(job)
        return job

    async def _run(self, job):
        job_id = job['id']
        event = self.cancel_events.get(job_id)
        try:
            if job.get('status') == 'cancelled' or (event and event.is_set()):
                return
            job['status'] = 'running'
            job['message'] = '正在处理'
            job['progress'] = 5
            self.save(job)
            if job['kind'] == 'clean':
                outputs = await self._run_clean(job)
            else:
                outputs = await self._run_diarize(job)
            if event and event.is_set():
                job['status'] = 'cancelled'
                job['message'] = '已取消'
            else:
                job['status'] = 'done'
                job['message'] = '已完成'
                job['progress'] = 100
                job['outputs'] = outputs
            self.save(job)
        except CleanupError as exc:
            job['status'] = 'failed'
            job['error'] = {'code': exc.code, 'message': exc.message}
            job['message'] = exc.message
            self.save(job)
        except ProviderError as exc:
            job['status'] = 'failed'
            job['error'] = {'code': exc.code, 'message': exc.code}
            job['message'] = exc.code
            self.save(job)
        except MediaJobError as exc:
            job['status'] = 'failed'
            job['error'] = {'code': exc.code, 'message': exc.message}
            job['message'] = exc.message
            self.save(job)
        except Exception:
            job['status'] = 'failed'
            job['error'] = {'code': 'job_failed', 'message': '任务处理失败。'}
            job['message'] = '任务处理失败。'
            self.save(job)
        finally:
            self.cancel_events.pop(job_id, None)
            self.tasks.pop(job_id, None)

    async def _run_clean(self, job):
        recording_id = job['recording_id']
        options = job['options']
        source = self.source_path(recording_id, options.get('source', 'audio'))
        destination = self.target_path(recording_id, options.get('target', 'clean'))
        stats = await asyncio.to_thread(
            clean_wav, source, destination, options['profile'])
        job['progress'] = 95
        self.save(job)
        return [{'name': options.get('target', 'clean'), 'path': str(destination),
                 'source': options.get('source', 'audio'),
                 'bytes': stats['bytes'], 'duration_ms': stats['duration_ms']}]

    async def _run_diarize(self, job):
        if self.transcribe is None:
            raise MediaJobError('transcribe_unavailable', '本机没有可用的 ASR，无法重新分轨。')
        result = await rediarize(
            job['recording_id'], self.records_root.parent,
            transcribe=self.transcribe,
            speakers=job['options']['speakers'],
            mode=job['options']['mode'])
        job['progress'] = 95
        self.save(job)
        return [{'name': 'transcript',
                 'path': str(self.records_root / f"{job['recording_id']}.txt"),
                 'lines': result.get('lines'), 'speakers': result.get('speakers')}]

    def close(self):
        for event in self.cancel_events.values():
            event.set()
        for task in self.tasks.values():
            task.cancel()
        self.tasks.clear()
