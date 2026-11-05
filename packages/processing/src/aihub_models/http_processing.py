"""HTTP providers for post-recording processing; never load a local model."""
import asyncio
import io
import json
import os
import wave
from urllib.parse import urlsplit

import aiohttp
from aihub_common import env_value, to_pcm16

from .minutes.inference import MinutesError


class ProcessingHTTP:
    def __init__(self, prefix, model_id=None):
        self.url = (env_value(prefix + '_URL') or '').rstrip('/')
        parsed = urlsplit(self.url)
        self.model_id = (model_id or env_value(prefix + '_MODEL') or '').strip()
        if (parsed.scheme not in ('http', 'https') or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not self.model_id):
            raise ValueError(f'{prefix}: HTTP URL and actual model ID are required')
        self.key_env = env_value(prefix + '_KEY_ENV', '')
        self.timeout = float(env_value(prefix + '_TIMEOUT', '240'))
        if not 0 < self.timeout <= 3600:
            raise ValueError(f'{prefix}: timeout must be in (0, 3600]')

    async def post(self, path, *, timeout=None, **kwargs):
        headers = {}
        key = os.environ.get(self.key_env, '') if self.key_env else ''
        if key:
            headers['Authorization'] = 'Bearer ' + key
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
                total=timeout or self.timeout, connect=10)) as session:
            async with session.post(self.url + '/' + path, headers=headers,
                                    allow_redirects=False, **kwargs) as response:
                if not 200 <= response.status < 300:
                    raise RuntimeError(f'http_{response.status}')
                raw = bytearray()
                async for chunk in response.content.iter_chunked(8192):
                    raw.extend(chunk)
                    if len(raw) > 1024 * 1024:
                        raise ValueError('response_too_large')
                return json.loads(raw)


class HTTPMinutesEngine:
    def __init__(self, model_id=None):
        self.http = ProcessingHTTP('MINUTES', model_id)
        self.model_id = self.http.model_id
        # Only bounds this processing process. Shared-model scheduling must be
        # configured in the serving backend; this is not a cross-process lock.
        self._semaphore = asyncio.Semaphore(1)

    async def check_available(self):
        # Do not perform billable generation as a preflight. Actual connectivity
        # and model availability are checked by the job's first request.
        return None

    async def generate(self, messages, *, max_tokens=1400, timeout=None):
        if (not isinstance(messages, list) or not messages
                or type(max_tokens) is not int or not 64 <= max_tokens <= 4096):
            raise MinutesError('minutes_invalid_request')
        async with self._semaphore:
            try:
                data = await self.http.post('chat/completions', timeout=timeout, json={
                    'model': self.model_id, 'messages': messages,
                    'max_tokens': max_tokens, 'stream': False})
                content = data['choices'][0]['message']['content']
                if not isinstance(content, str) or not content.strip():
                    raise ValueError('invalid_content')
                return content
            except TimeoutError:
                raise MinutesError('minutes_timeout', 'HTTP 纪要服务超时。') from None
            except RuntimeError as exc:
                raise MinutesError('minutes_' + str(exc), 'HTTP 纪要服务请求失败。') from None
            except (aiohttp.ClientError, ValueError, KeyError, IndexError, TypeError):
                raise MinutesError('minutes_generation_failed', 'HTTP 纪要服务响应无效或不可用。') from None

    def close(self):
        pass  # HTTP sessions belong to individual cancellable requests.


def make_http_transcribe(model_id=None):
    http = ProcessingHTTP('MEDIA_ASR', model_id)

    async def transcribe(pcm):
        wav = io.BytesIO()
        with wave.open(wav, 'wb') as output:
            output.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            output.writeframes(to_pcm16(pcm, 16000))
        form = aiohttp.FormData()
        form.add_field('file', wav.getvalue(), filename='recording.wav', content_type='audio/wav')
        form.add_field('model', http.model_id)
        try:
            data = await http.post('audio/transcriptions', data=form)
            if not isinstance(data.get('text'), str):
                raise ValueError('invalid_transcript')
            return data['text']
        except TimeoutError:
            raise RuntimeError('asr_timeout') from None
        except RuntimeError as exc:
            raise RuntimeError('asr_' + str(exc)) from None
        except (aiohttp.ClientError, ValueError, TypeError, AttributeError):
            raise RuntimeError('asr_invalid_response') from None

    return transcribe
