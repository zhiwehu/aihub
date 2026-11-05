"""The job service: media jobs plus meeting minutes on one loopback port.

Kept separate from the model workers because their lifetimes differ. A worker
owns one loaded model and is started/stopped from the console; this service owns
no model of its own and holds the queue, so it can stay up while workers come
and go.
"""

import secrets

from aiohttp import web

from .auth import is_loopback
from .media_jobs import MediaJobError, MediaJobs
from .minutes import MinutesError, MinutesService, setup_minutes

JOB_FIELDS = ('id', 'kind', 'recording_id', 'status', 'message', 'progress',
              'options', 'outputs', 'error', 'created_at', 'updated_at')

ERROR_STATUS = {
    'job_not_found': 404,
    'recording_not_found': 404,
    'recording_audio_missing': 404,
    'invalid_job_kind': 400,
    'invalid_options': 400,
    'invalid_cleanup_profile': 400,
    'queue_full': 429,
    'transcribe_unavailable': 503,
    'job_failed': 500,
    'cleanup_unavailable': 503,
    'cleanup_failed': 500,
    'cleanup_timeout': 504,
    'cleanup_source_missing': 404,
}


def summary(job):
    return {key: job.get(key) for key in JOB_FIELDS if key in job}


def error(code, message=None, status=None):
    return web.json_response(
        {'error': {'code': code, 'message': message or code}},
        status=status or ERROR_STATUS.get(code, 400),
        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


async def _json(request):
    try:
        body = await request.json()
    except Exception:
        raise MediaJobError('invalid_options', '请求格式无效。') from None
    if not isinstance(body, dict):
        raise MediaJobError('invalid_options', '请求格式无效。')
    return body


def create_service_app(jobs, minutes, token, allow_remote=False):
    @web.middleware
    async def guard(request, handler):
        # A container reaches this service through the host's loopback via
        # host.docker.internal, so the peer is the bridge gateway, not loopback.
        # allow_remote only relaxes the address check; the bearer token still
        # gates every request and the listener stays bound to 127.0.0.1.
        if not allow_remote and not is_loopback(request):
            raise web.HTTPForbidden()
        origin = request.headers.get('Origin')
        if origin and origin != f'{request.scheme}://{request.host}':
            raise web.HTTPForbidden()
        if not secrets.compare_digest(
                request.headers.get('Authorization', ''), 'Bearer ' + token):
            raise web.HTTPUnauthorized()
        return await handler(request)

    app = web.Application(middlewares=[guard], client_max_size=64 * 1024)

    async def lifetime(app):
        jobs.recover()
        if minutes is not None:
            await minutes.start()
        try:
            yield
        finally:
            jobs.close()
            if minutes is not None:
                await minutes.close()

    app.cleanup_ctx.append(lifetime)

    async def media(request):
        try:
            if request.path == '/v1/media/jobs':
                if request.method == 'GET':
                    recording_id = request.query.get('recording_id')
                    return web.json_response(
                        {'jobs': [summary(job) for job in jobs.list(recording_id)]})
                body = await _json(request)
                extra = set(body) - {'kind', 'recording_id', 'options'}
                if extra:
                    raise MediaJobError('invalid_options', '请求包含未知字段。')
                job = await jobs.start(body.get('kind'), body.get('recording_id'),
                                       body.get('options'))
                return web.json_response({'job': summary(job)}, status=202)
            job_id = request.match_info.get('job_id', '')
            if request.path.endswith('/cancel'):
                job = await jobs.cancel(job_id)
                return web.json_response({'job': summary(job)})
            job = jobs.get(job_id)
            if job is None:
                raise MediaJobError('job_not_found', '找不到这个任务。')
            return web.json_response({'job': summary(job)})
        except MediaJobError as exc:
            return error(exc.code, exc.message)
        except MinutesError as exc:
            return error(exc.code, exc.message)
        except Exception as exc:
            known = str(exc)
            return error(known if known in ERROR_STATUS else 'job_failed',
                         None if known in ERROR_STATUS else '任务处理失败。')

    app.router.add_route('*', '/v1/media/jobs', media)
    app.router.add_route('*', '/v1/media/jobs/{job_id}', media)
    app.router.add_post('/v1/media/jobs/{job_id}/cancel', media)
    if minutes is not None:
        setup_minutes(app, minutes)

    async def health(request):
        from .process_stats import stats
        return web.json_response({
            'ready': True,
            'minutes': minutes is not None,
            'active_jobs': len(jobs.active()),
            **stats(),
        })

    app.router.add_get('/health', health)
    return app


def build(data_root, recordings_root, transcribe=None, minutes_model=None):
    """Assemble the service app pieces from a data directory.

    Pass ``minutes_model=False`` to run without the minutes service (for a host
    that only needs denoise and re-diarization).
    """
    from .minutes import MinutesEngine
    from aihub_common import env_value
    from .records import Records

    records = Records(recordings_root)
    jobs = MediaJobs(data_root / 'media-jobs', recordings_root, transcribe=transcribe)
    minutes = None
    if minutes_model is not False:
        provider = env_value('MINUTES_PROVIDER', 'local')
        if provider == 'http':
            from .http_processing import HTTPMinutesEngine
            engine = HTTPMinutesEngine(minutes_model)
        elif provider == 'local':
            engine = MinutesEngine(minutes_model) if minutes_model else None
        else:
            raise ValueError('MINUTES_PROVIDER must be local or http')
        minutes = MinutesService(data_root, records, engine=engine)
    return jobs, minutes
