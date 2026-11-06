"""HTTP adapters for ASR, LLM and TTS. No model code runs in this process.

Every provider is now either a supervised local worker (``builtin``, served by
``aihub-models``), a remote HTTP endpoint (``http``), or the macOS ``say``
command (``macos``). The in-process MLX path was removed with the split.
"""
import asyncio
import contextlib
import io
import json
import os
import queue
import tempfile
import threading
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import aiohttp
import numpy as np
from .audio import to_pcm16
from aihub_common import ProviderError, spoken_text


async def sse(response):
    data = []
    while line := await response.content.readline():
        if len(line) > 65536:
            raise ProviderError('provider_event_too_large')
        line = line.decode('utf-8').strip()
        if not line:
            if data:
                value = '\n'.join(data)
                data = []
                if value == '[DONE]':
                    return
                yield json.loads(value)
        elif line.startswith('data:'):
            data.append(line[5:].lstrip())
            if sum(map(len, data)) > 65536:
                raise ProviderError('provider_event_too_large')
    if data:
        value = '\n'.join(data)
        if value != '[DONE]':
            yield json.loads(value)


class Pipeline:
    def __init__(self, config, http, runtime):
        self.config, self.http, self.runtime = config, http, runtime

    def headers(self, kind):
        if self.config[kind]['provider'] == 'builtin':
            from .services import ServiceError
            try:
                return self.runtime.services.headers(kind)
            except ServiceError as exc:
                raise ProviderError(exc.code) from None
        value = os.environ.get(self.config[kind]['key_env'], '')
        return {'Authorization': 'Bearer '+value} if value else {}

    def endpoint(self, kind, path):
        if self.config[kind]['provider'] == 'builtin':
            return self.runtime.services.endpoint(kind) + '/' + path
        return self.config[kind]['url'].rstrip('/') + '/' + path

    def check(self, response):
        if response.status >= 400:
            raise ProviderError(f'provider_http_{response.status}')

    async def transcribe(self, pcm):
        c = self.config['asr']
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as f:
            f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            f.writeframes(to_pcm16(pcm, 16000))
        form = aiohttp.FormData()
        form.add_field('file', wav.getvalue(), filename='utterance.wav', content_type='audio/wav')
        form.add_field('model', c['model'])
        if c['language'] != 'auto':
            form.add_field('language', {'Chinese':'zh', 'English':'en'}[c['language']])
        async with self.http.post(self.endpoint('asr', 'audio/transcriptions'), data=form,
                                  headers=self.headers('asr')) as response:
            self.check(response)
            data = await self.read_json(response)
            if not isinstance(data.get('text'), str):
                raise ProviderError('invalid_transcript')
            return data['text'][:8000]

    async def read_json(self, response):
        raw = bytearray()
        async for chunk in response.content.iter_chunked(8192):
            raw.extend(chunk)
            if len(raw) > 1024*1024:
                raise ProviderError('provider_response_too_large')
        return json.loads(raw)

    async def chat(self, history):
        from aihub_tools.tool_chat import chat
        async with contextlib.aclosing(chat(self, history)) as source:
            async for item in source:
                yield item

    async def raw_chat(self, history, *, system_prompt=None, max_tokens=None):
        c = self.config['llm']
        token_limit=c['max_tokens'] if max_tokens is None else max_tokens
        if type(token_limit) is not int or not 16<=token_limit<=2048:raise ProviderError('invalid_token_limit')
        messages = [{'role':'system', 'content':system_prompt if system_prompt is not None else self.config['system_prompt']}] + history
        payload = dict(model=c['model'], messages=messages, max_tokens=token_limit, stream=True)
        # DeepSeek-compatible switch; ignored by providers that do not know it.
        if os.environ.get('AIHUB_LLM_THINKING', '').strip().lower() == 'disabled':
            payload['thinking'] = {'type': 'disabled'}
        async with self.http.post(self.endpoint('llm', 'chat/completions'),
                headers=self.headers('llm'), json=payload) as response:
            self.check(response)
            count = 0
            async for event in sse(response):
                choices = event.get('choices') or []
                if event.get('error'):
                    raise ProviderError('provider_stream_error')
                text = choices[0].get('delta', {}).get('content', '') if choices else ''
                if text:
                    count += len(text)
                    if count > 16000:
                        raise ProviderError('reply_text_limit')
                    yield text

    async def speech(self, text):
        text = spoken_text(text)
        if not text:
            return
        c = self.config['tts']
        if c['provider'] == 'macos':
            async with contextlib.aclosing(self.native_speech(text, c['voice'])) as source:
                async for block in source:
                    yield block
        else:
            # Compatible providers return raw signed little-endian PCM at the configured rate.
            import av
            rate = c['sample_rate']
            resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
            pending, total = b'', 0
            async with self.http.post(self.endpoint('tts', 'audio/speech'), headers=self.headers('tts'),
                    json=dict(model=c['model'], input=text, voice=c['voice'], response_format='pcm')) as response:
                self.check(response)
                content_type = response.headers.get('Content-Type', '').split(';')[0].lower()
                if content_type not in ('application/octet-stream', 'audio/pcm', 'audio/raw', 'audio/x-pcm'):
                    raise ProviderError('tts_format_mismatch')
                async for raw in response.content.iter_chunked(8192):
                    pending += raw
                    total += len(raw)
                    if total > rate*2*120:
                        raise ProviderError('tts_audio_limit')
                    size = len(pending)//2*2
                    if size:
                        frame = av.AudioFrame.from_ndarray(np.frombuffer(pending[:size], '<i2').reshape(1,-1),
                                                          format='s16', layout='mono')
                        frame.sample_rate = rate
                        pending = pending[size:]
                        for out in resampler.resample(frame):
                            yield out.to_ndarray().astype('<i2').tobytes()
                if pending:
                    raise ProviderError('invalid_pcm')
                for out in resampler.resample(None):
                    yield out.to_ndarray().astype('<i2').tobytes()

    async def native_speech(self, text, voice):
        processes = []
        with tempfile.TemporaryDirectory(prefix='voicehub-') as root:
            try:
                destination = str(Path(root)/'speech.aiff')
                say = await asyncio.create_subprocess_exec('/usr/bin/say', '-v', voice, '-o', destination,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL)
                processes.append(say)
                await asyncio.wait_for(say.communicate(text.encode()), 120)
                if say.returncode:
                    raise ProviderError('native_voice_failed')
                ffmpeg = await asyncio.create_subprocess_exec('ffmpeg', '-v', 'error', '-i', destination,
                        '-f', 's16le', '-ar', '16000', '-ac', '1', 'pipe:1',
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                processes.append(ffmpeg)
                while block := await ffmpeg.stdout.read(8192):
                    yield block
                if await ffmpeg.wait():
                    raise ProviderError('audio_conversion_failed')
            finally:
                for process in processes:
                    if process.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            process.kill()
                        await process.wait()
