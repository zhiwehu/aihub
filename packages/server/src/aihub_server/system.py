"""Runtime footprint for the console: deployment mode, CPU, memory, disk, network.

Every number is what this process can see. Inside a container that is the
container (and its VM) rather than the Mac itself, which is why ``deployment``
travels with the payload: the console labels the numbers accordingly.

The model tier is measured differently. ASR/LLM/TTS run natively on the host
while the server may sit in a container, so nothing here can inspect their
processes. Each service reports its own pid/rss/cpu through ``/health`` and this
module adds those up.
"""
import asyncio
import importlib.util
import os
import shutil
import time
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
import psutil

_previous = {}
_size_cache = {}
_self = psutil.Process()


def deployment(environ=None):
    """'docker' when this process runs inside a container, else 'native'."""
    environ = os.environ if environ is None else environ
    override = (environ.get('AIHUB_DEPLOYMENT') or '').strip().lower()
    if override in ('docker', 'native'):
        return override
    if Path('/.dockerenv').exists():
        return 'docker'
    try:
        cgroup = Path('/proc/self/cgroup').read_text()
    except OSError:
        return 'native'
    return 'docker' if ('docker' in cgroup or 'kubepods' in cgroup) else 'native'


def directory_bytes(path, ttl=60.0):
    """Recursive size of ``path``, recomputed at most once per ``ttl`` seconds."""
    key = str(path)
    now = time.monotonic()
    cached = _size_cache.get(key)
    if cached is not None and now - cached[0] < ttl:
        return cached[1]
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(base, name)).st_size
            except OSError:
                pass
    _size_cache[key] = (now, total)
    return total


def application_bytes():
    """Size of the AIHub packages plus the web assets, i.e. the product itself."""
    total = 0
    for module in ('aihub_common', 'aihub_tools', 'aihub_server', 'aihub_models'):
        try:
            spec = importlib.util.find_spec(module)
        except (ImportError, ValueError):
            continue
        if spec and spec.origin:
            total += directory_bytes(Path(spec.origin).parent, ttl=300.0)
    web = os.environ.get('AIHUB_WEB_ROOT')
    if web:
        total += directory_bytes(Path(web), ttl=300.0)
    return total


def _health_url(base):
    base = (base or '').rstrip('/')
    if base.endswith('/v1'):
        base = base[:-3]
    return base + '/health'


def _targets(config, services):
    rows = []
    for kind in ('asr', 'llm', 'tts'):
        try:
            section = config[kind]
        except (KeyError, TypeError):
            continue
        try:
            if section.get('provider') == 'builtin':
                base = services.endpoint(kind)
                headers = services.headers(kind)
            else:
                base = section.get('url', '')
                token = os.environ.get(section.get('key_env', ''), '')
                headers = {'Authorization': 'Bearer ' + token} if token else {}
        except Exception:
            continue
        rows.append((kind, _health_url(base), headers))
    base = (os.environ.get('AIHUB_MODELS_URL') or '').rstrip('/')
    token = os.environ.get('AIHUB_MODELS_TOKEN') or ''
    if base and token:
        rows.append(('media', base + '/health', {'Authorization': 'Bearer ' + token}))
    return rows


async def _probe(client, kind, url, headers):
    try:
        async with client.get(url, headers=headers) as response:
            if response.status != 200:
                return None
            body = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    return {'kind': kind, 'pid': body.get('pid'), 'rss': body.get('rss'),
            'cpu_percent': body.get('cpu_percent'), 'threads': body.get('threads'),
            'ready': body.get('ready'), 'model': body.get('model')}


def _external(url):
    """True when the endpoint is not this host, so local RSS cannot apply."""
    try:
        host = urlsplit(url or '').hostname
    except ValueError:
        return True
    return host not in (None, '127.0.0.1', 'localhost', '::1')


async def model_tier(config, services, timeout=1.5):
    """Report every configured model endpoint, even when it cannot be probed."""
    targets = _targets(config, services)
    planner = (config.get('tools') or {}).get('planner', 'llm') if isinstance(config, dict) else 'llm'
    if not targets:
        return {'total': 0, 'reachable': 0, 'rss': 0, 'cpu_percent': 0.0,
                'processes': [], 'planner': planner}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as client:
        results = await asyncio.gather(*[_probe(client, *row) for row in targets])
    rows, seen = [], set()
    rss = cpu = 0
    for (kind, url, _headers), result in zip(targets, results):
        row = dict(result or {})
        row.update(kind=kind, reachable=bool(result), external=_external(url))
        rows.append(row)
        if not result:
            continue
        pid = result.get('pid')
        # ASR and TTS can share one native process; count its memory once.
        if pid is not None and pid in seen:
            continue
        if pid is not None:
            seen.add(pid)
        rss += result.get('rss') or 0
        cpu += result.get('cpu_percent') or 0
    return {'total': len(targets), 'reachable': sum(1 for row in rows if row['reachable']),
            'rss': rss, 'cpu_percent': round(cpu, 1), 'processes': rows,
            'planner': planner}


def _rates(net, now):
    previous = _previous.get('net')
    rx = tx = 0.0
    if previous is not None:
        elapsed = max(now - _previous['at'], 1e-6)
        rx = max(net.bytes_recv - previous.bytes_recv, 0) / elapsed
        tx = max(net.bytes_sent - previous.bytes_sent, 0) / elapsed
    _previous.update(net=net, at=now)
    return rx, tx


def snapshot(root):
    now = time.monotonic()
    net = psutil.net_io_counters()
    rx_rate, tx_rate = _rates(net, now)
    memory = psutil.virtual_memory()
    disk = shutil.disk_usage(root)
    load = os.getloadavg() if hasattr(os, 'getloadavg') else (0.0, 0.0, 0.0)
    return {
        'deployment': deployment(),
        'hostname': os.uname().nodename,
        'uptime_seconds': int(time.time() - _self.create_time()),
        'cpu': {'percent': round(psutil.cpu_percent(interval=None), 1),
                'cores': psutil.cpu_count() or 1,
                'load': [round(value, 2) for value in load]},
        'memory': {'total': memory.total, 'used': memory.total - memory.available,
                   'percent': round(memory.percent, 1)},
        'disk': {'path': str(root), 'total': disk.total, 'used': disk.used,
                 'free': disk.free, 'percent': round(disk.used / disk.total * 100, 1),
                 'data_bytes': directory_bytes(root),
                 'recordings_bytes': directory_bytes(Path(root) / 'recordings'),
                 'app_bytes': application_bytes()},
        'network': {'rx_bytes': net.bytes_recv, 'tx_bytes': net.bytes_sent,
                    'rx_rate': round(rx_rate, 1), 'tx_rate': round(tx_rate, 1)},
        # The server itself only; worker memory arrives through ``model_tier``,
        # otherwise native children would be counted twice.
        'process': {'rss': _self.memory_info().rss,
                    'cpu_percent': round(_self.cpu_percent(interval=None), 1),
                    'threads': _self.num_threads()},
    }
