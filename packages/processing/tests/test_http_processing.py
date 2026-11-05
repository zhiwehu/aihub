import asyncio
import io
import wave
from unittest import IsolatedAsyncioTestCase, mock

import numpy as np
from aiohttp import web
from aiohttp.test_utils import TestServer

from aihub_models.__main__ import make_transcribe
from aihub_models.service import build


class HTTPProcessingTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.status = 200
        self.content = '{"topics": []}'
        self.delay = 0
        app = web.Application()

        async def minutes(request):
            self.requests.append((request.headers.get('Authorization'), await request.json()))
            await asyncio.sleep(self.delay)
            return web.json_response({'choices': [{'message': {'content': self.content}}]}, status=self.status)

        async def asr(request):
            data = await request.post()
            with wave.open(io.BytesIO(data['file'].file.read())) as wav:
                self.audio = (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes())
            self.requests.append((request.headers.get('Authorization'), data['model']))
            return web.json_response({'text': '会议内容'}, status=self.status)

        app.router.add_post('/v1/chat/completions', minutes)
        app.router.add_post('/v1/audio/transcriptions', asr)
        self.server = TestServer(app)
        await self.server.start_server()
        self.env = mock.patch.dict('os.environ', {
            'AIHUB_MINUTES_PROVIDER': 'http', 'AIHUB_MINUTES_URL': str(self.server.make_url('/v1')),
            'AIHUB_MINUTES_MODEL': 'local-llm', 'AIHUB_MINUTES_KEY_ENV': 'TEST_MODEL_KEY',
            'AIHUB_MEDIA_ASR_PROVIDER': 'http', 'AIHUB_MEDIA_ASR_URL': str(self.server.make_url('/v1')),
            'AIHUB_MEDIA_ASR_MODEL': 'local-asr', 'AIHUB_MEDIA_ASR_KEY_ENV': 'TEST_MODEL_KEY',
            'TEST_MODEL_KEY': 'test-secret',
        })
        self.env.start()

    async def asyncTearDown(self):
        self.env.stop()
        await self.server.close()

    def engine(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        _, minutes = build(Path(tmp.name), Path(tmp.name) / 'recordings')
        self.addCleanup(minutes.engine.close)
        return minutes.engine

    async def test_minutes_uses_http_without_loading_mlx(self):
        engine = self.engine()
        await engine.check_available()
        self.assertEqual(await engine.generate([{'role': 'user', 'content': '总结'}]), self.content)
        token, body = self.requests[0]
        self.assertEqual(token, 'Bearer test-secret')
        self.assertEqual(body['model'], 'local-llm')
        self.assertFalse(body['stream'])
        self.assertEqual(engine.model_id, 'local-llm')

    async def test_minutes_reports_http_error_without_response_secrets(self):
        engine = self.engine()
        self.status = 503
        with self.assertRaisesRegex(RuntimeError, 'minutes_http_503'):
            await engine.generate([{'role': 'user', 'content': '总结'}])

    async def test_minutes_timeout_and_cancellation(self):
        engine = self.engine()
        self.delay = .1
        with self.assertRaisesRegex(RuntimeError, 'minutes_timeout'):
            await engine.generate([{'role': 'user', 'content': '总结'}], timeout=.01)
        task = asyncio.create_task(engine.generate([{'role': 'user', 'content': '总结'}]))
        await asyncio.sleep(.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.delay = 0
        self.assertEqual(await engine.generate([{'role': 'user', 'content': '总结'}]), self.content)

    async def test_asr_sends_mono_pcm_wav_and_model(self):
        transcribe = make_transcribe(None)
        self.assertEqual(await transcribe(np.zeros(1600, dtype=np.float32)), '会议内容')
        self.assertEqual(self.audio, (1, 2, 16000, 1600))
        self.assertEqual(self.requests[0], ('Bearer test-secret', 'local-asr'))

    async def test_asr_failure_is_not_an_empty_transcript(self):
        transcribe = make_transcribe(None)
        self.status = 500
        with self.assertRaisesRegex(RuntimeError, 'asr_http_500'):
            await transcribe(np.zeros(1600, dtype=np.float32))

    async def test_failed_retranscription_does_not_succeed_with_missing_lines(self):
        from aihub_models.diarize import _transcribe_turns
        async def failed(pcm):
            raise RuntimeError('asr_http_503')
        with mock.patch('aihub_models.diarize.asyncio.sleep', new=mock.AsyncMock()):
            with self.assertRaisesRegex(RuntimeError, 'asr_http_503'):
                await _transcribe_turns(np.zeros(16000, dtype=np.float32), [(0, 1, 1)], failed)

    async def test_invalid_minutes_payload_is_a_stable_error(self):
        engine = self.engine()
        self.content = None
        with self.assertRaisesRegex(RuntimeError, 'minutes_generation_failed'):
            await engine.generate([{'role': 'user', 'content': '总结'}])
