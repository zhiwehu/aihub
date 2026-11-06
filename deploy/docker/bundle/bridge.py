"""Speech bridge for the local AtomGradient service.

AIHub calls OpenAI-style /v1/audio/transcriptions and /v1/audio/speech. ASR
stays on the HTTP route; TTS first tries the native bidirectional WebSocket
(streaming PCM) and falls back to the existing non-streaming HTTP endpoint.
"""
import base64
import contextlib
import io
import json
import os
import struct
import uuid
import wave

import psutil
from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

ASR = 'http://127.0.0.1:18094/v1/asr'
TTS_HTTP = 'http://127.0.0.1:18094/api/v1/tts'
TTS_WS = os.environ.get('TTS_WS_URL', 'ws://127.0.0.1:18093/api/v3/tts/bidirection')
TTS_MODE = os.environ.get('TTS_MODE', 'ws').strip().lower()
TIMEOUT = ClientTimeout(total=180)
LANG = {'zh': 'Chinese', 'zh-CN': 'Chinese', 'en': 'English', 'auto': ''}


def _sized(value):
    return struct.pack('>I', len(value)) + value


def _frame(event, session, payload):
    body = json.dumps(payload or {}, ensure_ascii=False).encode()
    data = bytes([0x11, 0x14, 0x00, 0x00]) + struct.pack('>i', event)
    if event not in (1, 2):
        data += _sized(session.encode())
    return data + _sized(body)


def _parse(data):
    if len(data) < 12 or data[0] != 0x11 or data[1] not in (0x94, 0xB4):
        raise ValueError('bad event frame')
    event = struct.unpack_from('>i', data, 4)[0]
    offset = 8

    def take():
        nonlocal offset
        size = struct.unpack_from('>I', data, offset)[0]
        offset += 4
        value = data[offset:offset + size]
        offset += size
        return value

    session = take().decode('utf-8', 'replace')
    body = take()
    return event, session, body if event == 352 else json.loads(body)


async def _expect(ws, wanted):
    while True:
        message = await ws.receive()
        if message.type != WSMsgType.BINARY:
            raise RuntimeError('tts_socket_closed')
        event, _session, body = _parse(message.data)
        if event == wanted:
            return body
        if event in (51, 153):
            raise RuntimeError('tts_session_failed')


async def ws_pcm(text):
    """Yield 24 kHz PCM chunks as the native TTS produces them."""
    session = ClientSession(timeout=TIMEOUT)
    ws = None
    try:
        ws = await session.ws_connect(TTS_WS, max_msg_size=8 * 1024 * 1024)
        await ws.send_bytes(_frame(1, '', {}))
        await _expect(ws, 50)
        identity = uuid.uuid4().hex
        await ws.send_bytes(_frame(100, identity, {
            'req_params': {'audio_params': {'sample_rate': 24000, 'format': 'pcm'}}}))
        await _expect(ws, 150)
        await ws.send_bytes(_frame(200, identity, {'req_params': {'text': text}}))
        await ws.send_bytes(_frame(102, identity, {}))
        while True:
            message = await ws.receive()
            if message.type == WSMsgType.BINARY:
                event, _session, body = _parse(message.data)
                if event == 352:
                    if body:
                        yield body
                elif event in (151, 152):
                    return
                elif event == 153:
                    raise RuntimeError('tts_failed')
            elif message.type in (WSMsgType.CLOSE, WSMsgType.CLOSED, WSMsgType.ERROR):
                return
    finally:
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        await session.close()


async def http_pcm(text):
    payload = {'request': {'text': text}, 'audio': {'encoding': 'wav'}}
    async with ClientSession(timeout=TIMEOUT) as session:
        async with session.post(TTS_HTTP, json=payload) as response:
            data = await response.json()
            if response.status != 200:
                raise RuntimeError('tts_http_failed')
    with wave.open(io.BytesIO(base64.b64decode(data['data'])), 'rb') as source:
        return source.readframes(source.getnframes()), source.getframerate()


async def transcriptions(request):
    try:
        payload, fields = None, {}
        async for part in await request.multipart():
            if part.name == 'file':
                payload = await part.read()
            else:
                fields[part.name] = await part.text()
        if not payload:
            return web.json_response({'error': 'missing file'}, status=400)
        with wave.open(io.BytesIO(payload), 'rb') as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth(),
                    source.getcomptype()) != (16000, 1, 2, 'NONE'):
                return web.json_response({'error': 'expected 16 kHz mono s16le WAV'}, status=400)
            pcm = source.readframes(source.getnframes())
        language = LANG.get(fields.get('language', ''), fields.get('language') or 'Chinese')
        body = {'request_id': uuid.uuid4().hex, 'pcm_base64': base64.b64encode(pcm).decode(),
                'sample_rate': 16000, 'channels': 1, 'sample_width': 2,
                'language': language or 'Chinese', 'deadline_seconds': 45}
        async with ClientSession(timeout=TIMEOUT) as session:
            async with session.post(ASR, json=body) as response:
                data = await response.json()
                if response.status != 200:
                    return web.json_response({'error': data}, status=502)
        return web.json_response({'text': data.get('text', '')})
    except Exception as exc:
        return web.json_response({'error': type(exc).__name__}, status=500)


async def speech(request):
    try:
        body = await request.json()
        text = (body.get('input') or '').strip()
        if not text:
            return web.json_response({'error': 'empty input'}, status=400)
        text = text[:2000]
        if TTS_MODE != 'http':
            source = ws_pcm(text)
            try:
                first = await source.__anext__()
            except (StopAsyncIteration, Exception):
                first = None
            if first:
                response = web.StreamResponse(
                    headers={'Content-Type': 'audio/pcm', 'X-Sample-Rate': '24000'})
                await response.prepare(request)
                await response.write(first)
                try:
                    async for chunk in source:
                        await response.write(chunk)
                except Exception:
                    pass
                finally:
                    with contextlib.suppress(Exception):
                        await source.aclose()
                await response.write_eof()
                return response
            with contextlib.suppress(Exception):
                await source.aclose()
        pcm, rate = await http_pcm(text)
        return web.Response(body=pcm, content_type='audio/pcm',
                            headers={'X-Sample-Rate': str(rate)})
    except Exception as exc:
        return web.json_response({'error': type(exc).__name__}, status=500)


async def health(request):
    info = {'ok': True}
    try:
        async with ClientSession(timeout=ClientTimeout(total=2)) as session:
            async with session.get('http://127.0.0.1:18094/health') as response:
                upstream = await response.json()
        pid = upstream.get('pid')
        if pid:
            process = psutil.Process(pid)
            info.update(pid=pid, rss=process.memory_info().rss,
                        cpu_percent=process.cpu_percent(interval=None),
                        threads=process.num_threads(),
                        ready=upstream.get('status') == 'ready',
                        model=upstream.get('asr_model'))
    except Exception as exc:
        info['error'] = type(exc).__name__
    return web.json_response(info)


app = web.Application()
app.router.add_post('/v1/audio/transcriptions', transcriptions)
app.router.add_post('/v1/audio/speech', speech)
app.router.add_get('/health', health)
web.run_app(app, host='127.0.0.1', port=18095, access_log=None)
