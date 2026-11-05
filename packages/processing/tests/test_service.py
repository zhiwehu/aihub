import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase, mock

from aiohttp.test_utils import TestClient, TestServer

from aihub_models.media_jobs import MediaJobs
from aihub_models.service import build, create_service_app

RID = '9' * 32
TOKEN = 'service-token'


class ServiceTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.recordings = self.root / 'recordings'
        self.recordings.mkdir()
        (self.recordings / f'{RID}.wav').write_bytes(b'RIFF')
        self.jobs, self.minutes = build(self.root, self.recordings)
        self.app = create_service_app(self.jobs, self.minutes, TOKEN)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self._tmp.cleanup()

    def auth(self):
        return {'Authorization': f'Bearer {TOKEN}'}

    async def test_health_requires_the_bearer_token(self):
        response = await self.client.get('/health')
        self.assertEqual(response.status, 401)
        response = await self.client.get('/health', headers=self.auth())
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertTrue(body['ready'])
        self.assertTrue(body['minutes'])
        # The console adds this up across the container boundary, so every
        # service reports its own footprint.
        self.assertEqual(body['pid'], __import__('os').getpid())
        self.assertGreater(body['rss'], 0)
        self.assertGreaterEqual(body['cpu_percent'], 0)
        self.assertGreater(body['threads'], 0)

    async def test_remote_peers_need_both_the_flag_and_the_token(self):
        # A container reaches this service through the host loopback, so the
        # address check alone would lock denoise/diarize/minutes out.
        with mock.patch('aihub_models.service.is_loopback', return_value=False):
            self.assertEqual((await self.client.get('/health', headers=self.auth())).status, 403)
            remote = create_service_app(self.jobs, self.minutes, TOKEN, allow_remote=True)
            client = TestClient(TestServer(remote))
            await client.start_server()
            try:
                self.assertEqual((await client.get('/health', headers=self.auth())).status, 200)
                self.assertEqual((await client.get('/health')).status, 401)
            finally:
                await client.close()

    async def test_a_wrong_token_is_rejected(self):
        response = await self.client.get('/health', headers={'Authorization': 'Bearer nope'})
        self.assertEqual(response.status, 401)

    async def test_unknown_job_kind_is_a_400_with_a_code(self):
        response = await self.client.post('/v1/media/jobs', headers=self.auth(),
                                          json={'kind': 'speech_only', 'recording_id': RID})
        self.assertEqual(response.status, 400)
        body = await response.json()
        self.assertEqual(body['error']['code'], 'invalid_job_kind')

    async def test_unknown_fields_are_rejected(self):
        response = await self.client.post('/v1/media/jobs', headers=self.auth(),
                                          json={'kind': 'clean', 'recording_id': RID,
                                                'surprise': 1})
        self.assertEqual(response.status, 400)

    async def test_create_read_and_list_a_clean_job(self):
        fake = lambda source, destination, profile: {'bytes': 10, 'duration_ms': 20}
        with mock.patch('aihub_models.media_jobs.clean_wav', fake):
            response = await self.client.post(
                '/v1/media/jobs', headers=self.auth(),
                json={'kind': 'clean', 'recording_id': RID, 'options': {'profile': 'mild'}})
            self.assertEqual(response.status, 202)
            job = (await response.json())['job']
            await self.jobs.tasks[job['id']]

        response = await self.client.get(f"/v1/media/jobs/{job['id']}", headers=self.auth())
        self.assertEqual(response.status, 200)
        stored = (await response.json())['job']
        self.assertEqual(stored['status'], 'done')
        self.assertEqual(stored['outputs'][0]['bytes'], 10)

        response = await self.client.get(f'/v1/media/jobs?recording_id={RID}',
                                         headers=self.auth())
        jobs = (await response.json())['jobs']
        self.assertEqual([item['id'] for item in jobs], [job['id']])

    async def test_unknown_job_is_a_404(self):
        response = await self.client.get(f"/v1/media/jobs/{'0' * 32}", headers=self.auth())
        self.assertEqual(response.status, 404)
        self.assertEqual((await response.json())['error']['code'], 'job_not_found')

    async def test_minutes_routes_are_mounted(self):
        response = await self.client.get('/v1/meeting-templates', headers=self.auth())
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertIn('templates', body)
        self.assertIn('model_id', body)

    async def test_minutes_listing_is_empty_for_a_recording_without_minutes(self):
        response = await self.client.get(f'/v1/recordings/{RID}/minutes', headers=self.auth())
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())['jobs'], [])

    async def test_minutes_listing_rejects_a_malformed_recording_id(self):
        response = await self.client.get('/v1/recordings/not-an-id/minutes',
                                         headers=self.auth())
        self.assertEqual(response.status, 404)


class ServiceWithoutMinutesTests(IsolatedAsyncioTestCase):
    async def test_minutes_can_be_disabled(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            jobs, minutes = build(root, recordings, minutes_model=False)
            self.assertIsNone(minutes)
            app = create_service_app(jobs, None, TOKEN)
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                response = await client.get('/health', headers={'Authorization': f'Bearer {TOKEN}'})
                self.assertFalse((await response.json())['minutes'])
                response = await client.get('/v1/meeting-templates',
                                            headers={'Authorization': f'Bearer {TOKEN}'})
                self.assertEqual(response.status, 404)
            finally:
                await client.close()


class JobsPersistenceTests(IsolatedAsyncioTestCase):
    async def test_recovered_status_is_visible_after_restart(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recordings = root / 'recordings'
            recordings.mkdir()
            (recordings / f'{RID}.wav').write_bytes(b'RIFF')
            first = MediaJobs(root / 'media-jobs', recordings)
            first.job_path(RID, 'a' * 32).parent.mkdir(parents=True)
            first.job_path(RID, 'a' * 32).write_text(json.dumps({
                'id': 'a' * 32, 'recording_id': RID, 'kind': 'clean',
                'status': 'running', 'created_at': 1}))
            second = MediaJobs(root / 'media-jobs', recordings)
            second.recover()
            job = second.get('a' * 32)
            self.assertEqual(job['status'], 'interrupted')
