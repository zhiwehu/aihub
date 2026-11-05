"""Command line entry points.

    python -m aihub_models worker --kind asr --model <id> --port 8781 --service-id <hex>
    python -m aihub_models tts --port 8767
    python -m aihub_models serve --data <dir> [--port 8790]
    python -m aihub_models diarize --data <dir> --id <32hex> [--mode asr]
    python -m aihub_models clean --source <in.wav> --destination <out.wav>

``worker`` is normally started by the server's supervisor, which generates the
bearer token and passes it in ``AIHUB_WORKER_TOKEN``.
"""

import argparse
import asyncio
import logging
import secrets
import sys
from pathlib import Path

from . import __version__


def _common_logging(level):
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO),
                        format='%(asctime)s %(name)s %(message)s')


def _worker(args):
    from aiohttp import web
    from .worker import create_worker_app, worker_token

    _common_logging(args.log_level)
    app = create_worker_app(args.kind, args.model, args.service_id, worker_token())
    web.run_app(app, host='127.0.0.1', port=args.port,
                handler_cancellation=True, access_log=None, shutdown_timeout=3)


def _tts(args):
    from aiohttp import web
    from .tts_qwen import create_tts_app

    _common_logging(args.log_level)
    web.run_app(create_tts_app(), host='127.0.0.1', port=args.port,
                handler_cancellation=True, access_log=None, shutdown_timeout=5)


def _serve(args):
    from aiohttp import web
    from aihub_common import env_value
    from .service import build, create_service_app

    _common_logging(args.log_level)
    data_root = Path(args.data).expanduser()
    recordings_root = data_root / 'recordings'
    token = args.token or env_value('MODELS_TOKEN') or secrets.token_urlsafe(32)
    transcribe = None
    asr_model = args.asr_model or env_value('MEDIA_ASR_MODEL')
    if asr_model or env_value('MEDIA_ASR_PROVIDER') == 'http':
        transcribe = make_transcribe(asr_model, args.log_level)
    jobs, minutes = build(data_root, recordings_root, transcribe=transcribe,
                          minutes_model=False if args.no_minutes else args.minutes_model)
    allow_remote = env_value('MODELS_ALLOW_REMOTE') in ('1', 'true', 'yes')
    app = create_service_app(jobs, minutes, token, allow_remote=allow_remote)
    print(f'aihub-models service: http://127.0.0.1:{args.port} (recordings {recordings_root})')
    if args.print_token:
        print(token)
    web.run_app(app, host='127.0.0.1', port=args.port,
                access_log=None, shutdown_timeout=5)


def make_transcribe(model_id=None, log_level='info'):
    """Return an async ``transcribe(pcm)`` backed by a lazily warmed local ASR."""
    from aihub_common import env_value
    provider = env_value('MEDIA_ASR_PROVIDER', 'local')
    if provider == 'http':
        from .http_processing import make_http_transcribe
        return make_http_transcribe(model_id)
    if provider != 'local':
        raise ValueError('MEDIA_ASR_PROVIDER must be local or http')
    from .worker import Engine

    _common_logging(log_level)
    engine = Engine('asr', model_id)
    warmed = False
    lock = asyncio.Lock()

    async def transcribe(pcm):
        nonlocal warmed
        async with lock:
            if not warmed:
                await engine.warm()
                warmed = True
        return await engine.transcribe(pcm, 'auto')

    return transcribe


def _diarize(args):
    from .diarize import rediarize

    data_root = Path(args.data).expanduser()
    transcribe = make_transcribe(args.asr_model, args.log_level) if args.mode == 'asr' else None
    result = asyncio.run(rediarize(args.id, data_root, transcribe=transcribe,
                                   speakers=args.speakers, mode=args.mode,
                                   wait=args.wait))
    print(f"lines={result['lines']} speakers={result['speakers']}")


def _clean(args):
    from .cleanup import clean_wav

    stats = clean_wav(args.source, args.destination, args.profile)
    print(f"wrote {args.destination} ({stats['bytes']} bytes, {stats['duration_ms']} ms)")


def build_parser():
    parser = argparse.ArgumentParser(prog='aihub_models',
                                     description='AIHub model runtime')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)

    worker = sub.add_parser('worker', help='serve one model over loopback HTTP')
    worker.add_argument('--kind', choices=('asr', 'llm', 'tts'), required=True)
    worker.add_argument('--model', required=True)
    worker.add_argument('--service-id', required=True)
    worker.add_argument('--port', type=int, required=True)
    worker.add_argument('--log-level', default='info')
    worker.set_defaults(func=_worker)

    tts = sub.add_parser('tts', help='standalone Qwen3-TTS service')
    tts.add_argument('--port', type=int, default=8767)
    tts.add_argument('--log-level', default='info')
    tts.set_defaults(func=_tts)

    serve = sub.add_parser('serve', help='media jobs and meeting minutes')
    serve.add_argument('--data', required=True)
    serve.add_argument('--port', type=int, default=8790)
    serve.add_argument('--token', help='bearer token (default: AIHUB_MODELS_TOKEN or random)')
    serve.add_argument('--print-token', action='store_true')
    serve.add_argument('--asr-model', help='ASR model id used for asr-mode re-diarization')
    serve.add_argument('--minutes-model', help='override the minutes model id')
    serve.add_argument('--no-minutes', action='store_true')
    serve.add_argument('--log-level', default='info')
    serve.set_defaults(func=_serve)

    diarize = sub.add_parser('diarize', help='re-cluster a finished recording')
    diarize.add_argument('--data', required=True)
    diarize.add_argument('--id', required=True)
    diarize.add_argument('--mode', choices=('text', 'asr'), default='text')
    diarize.add_argument('--speakers', type=int, default=0)
    diarize.add_argument('--wait', action='store_true')
    diarize.add_argument('--asr-model', required=False)
    diarize.add_argument('--log-level', default='info')
    diarize.set_defaults(func=_diarize)

    clean = sub.add_parser('clean', help='denoise one WAV')
    clean.add_argument('--source', required=True)
    clean.add_argument('--destination', required=True)
    clean.add_argument('--profile', choices=('mild', 'strong'), default='mild')
    clean.set_defaults(func=_clean)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        return 130
    except (ValueError, RuntimeError, OSError) as exc:
        print(f'error: {getattr(exc, "code", exc)}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
