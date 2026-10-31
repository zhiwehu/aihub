import json
from unittest import IsolatedAsyncioTestCase, mock

from aihub_models.media_jobs import MediaJobError, MediaJobs
from aihub_models.records import Records

RID = 'd' * 32


class MediaJobsTests(IsolatedAsyncioTestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.recordings = self.root / 'recordings'
        self.recordings.mkdir()
        (self.recordings / f'{RID}.wav').write_bytes(b'RIFF')
        self.jobs = MediaJobs(self.root / 'media-jobs', self.recordings)

    def tearDown(self):
        self.jobs.close()
        self._tmp.cleanup()

    async def test_unknown_kind_is_rejected(self):
        with self.assertRaises(MediaJobError) as caught:
            await self.jobs.start('speech_only', RID)
        self.assertEqual(caught.exception.code, 'invalid_job_kind')

    async def test_missing_recording_is_rejected(self):
        with self.assertRaises(MediaJobError) as caught:
            await self.jobs.start('clean', 'e' * 32)
        self.assertEqual(caught.exception.code, 'recording_audio_missing')

    async def test_malformed_identity_is_rejected(self):
        for bad in ('', '../x', 'Z' * 32, None):
            with self.assertRaises(MediaJobError) as caught:
                await self.jobs.start('clean', bad)
            self.assertEqual(caught.exception.code, 'recording_not_found')

    async def test_unknown_clean_profile_is_rejected(self):
        with self.assertRaises(MediaJobError) as caught:
            await self.jobs.start('clean', RID, {'profile': 'aggressive'})
        self.assertEqual(caught.exception.code, 'invalid_cleanup_profile')

    async def test_invalid_diarize_options_are_rejected(self):
        with self.assertRaises(MediaJobError) as caught:
            await self.jobs.start('diarize', RID, {'mode': 'magic'})
        self.assertEqual(caught.exception.code, 'invalid_options')
        with self.assertRaises(MediaJobError) as caught:
            await self.jobs.start('diarize', RID, {'speakers': 99})
        self.assertEqual(caught.exception.code, 'invalid_options')

    async def test_clean_job_completes_and_records_outputs(self):
        fake = lambda source, destination, profile: {
            'profile': profile, 'bytes': 1234, 'duration_ms': 5000}
        destination = self.recordings / f'{RID}-clean.wav'
        destination.write_bytes(b'x')
        with mock.patch('aihub_models.media_jobs.clean_wav', fake):
            job = await self.jobs.start('clean', RID, {'profile': 'strong'})
            await self.jobs.tasks[job['id']]
        stored = self.jobs.get(job['id'])
        self.assertEqual(stored['status'], 'done')
        self.assertEqual(stored['progress'], 100)
        self.assertEqual(stored['outputs'][0]['name'], 'clean')
        self.assertEqual(stored['outputs'][0]['bytes'], 1234)
        self.assertEqual(stored['options'], {'profile': 'strong'})

    async def test_failed_clean_reports_the_cleanup_code(self):
        from aihub_models.cleanup import CleanupError

        def boom(source, destination, profile):
            raise CleanupError('cleanup_failed', '降噪处理失败，请检查原始音频。')

        with mock.patch('aihub_models.media_jobs.clean_wav', boom):
            job = await self.jobs.start('clean', RID)
            await self.jobs.tasks[job['id']]
        stored = self.jobs.get(job['id'])
        self.assertEqual(stored['status'], 'failed')
        self.assertEqual(stored['error']['code'], 'cleanup_failed')

    async def test_diarize_without_a_transcriber_fails_with_a_clear_code(self):
        with mock.patch('aihub_models.media_jobs.rediarize',
                        new=mock.AsyncMock(side_effect=AssertionError('should not run'))):
            job = await self.jobs.start('diarize', RID, {'mode': 'text'})
            await self.jobs.tasks[job['id']]
        stored = self.jobs.get(job['id'])
        self.assertEqual(stored['status'], 'failed')
        self.assertEqual(stored['error']['code'], 'transcribe_unavailable')

    async def test_diarize_passes_the_injected_transcriber(self):
        seen = {}

        async def fake_rediarize(recording_id, data_root, transcribe=None, speakers=0,
                                 mode='text', wait=False):
            seen.update(recording_id=recording_id, transcribe=transcribe,
                        speakers=speakers, mode=mode)
            return {'lines': 3, 'speakers': 2}

        async def transcribe(pcm):
            return 'x'

        self.jobs.transcribe = transcribe
        with mock.patch('aihub_models.media_jobs.rediarize', fake_rediarize):
            job = await self.jobs.start('diarize', RID, {'mode': 'asr', 'speakers': 2})
            await self.jobs.tasks[job['id']]
        stored = self.jobs.get(job['id'])
        self.assertEqual(stored['status'], 'done')
        self.assertEqual(seen['recording_id'], RID)
        self.assertIs(seen['transcribe'], transcribe)
        self.assertEqual(seen['speakers'], 2)
        self.assertEqual(seen['mode'], 'asr')
        self.assertEqual(stored['outputs'][0]['lines'], 3)

    def test_recover_marks_unfinished_jobs_interrupted(self):
        job = {'id': 'f' * 32, 'recording_id': RID, 'kind': 'clean',
               'status': 'running', 'created_at': 1}
        path = self.jobs.job_path(RID, job['id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job))
        self.jobs.recover()
        stored = json.loads(path.read_text())
        self.assertEqual(stored['status'], 'interrupted')
        self.assertIn('中断', stored['message'])

    def test_recover_leaves_completed_jobs_alone(self):
        job = {'id': 'a' * 32, 'recording_id': RID, 'kind': 'clean',
               'status': 'done', 'created_at': 1}
        path = self.jobs.job_path(RID, job['id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(job))
        self.jobs.recover()
        self.assertEqual(json.loads(path.read_text())['status'], 'done')

    async def test_list_filters_by_recording_and_validates_the_id(self):
        other = 'b' * 32
        (self.recordings / f'{other}.wav').write_bytes(b'RIFF')
        with mock.patch('aihub_models.media_jobs.clean_wav',
                        lambda *a: {'bytes': 1, 'duration_ms': 1}):
            first = await self.jobs.start('clean', RID)
            first_task = self.jobs.tasks[first['id']]
            second = await self.jobs.start('clean', other)
            second_task = self.jobs.tasks[second['id']]
            await first_task
            await second_task
        self.assertEqual([job['id'] for job in self.jobs.list(RID)], [first['id']])
        self.assertEqual(self.jobs.list('not-an-id'), [])

    async def test_cancel_before_the_job_runs(self):
        with mock.patch('aihub_models.media_jobs.clean_wav',
                        lambda *a: {'bytes': 1, 'duration_ms': 1}):
            job = await self.jobs.start('clean', RID)
        await self.jobs.cancel(job['id'])
        stored = self.jobs.get(job['id'])
        self.assertIn(stored['status'], ('cancelled', 'done'))
