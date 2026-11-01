"""Runtime footprint for the console: deployment mode, CPU, memory, disk, network.

Every number is what this process can see. Inside a container that is the
container (and its VM) rather than the Mac itself, which is why ``deployment``
travels with the payload: the console labels the numbers accordingly.
"""
import os
import shutil
import time
from pathlib import Path

import psutil

_previous = {}
_data_cache = {'at': -1.0, 'bytes': 0}
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


def directory_bytes(root, ttl=60.0):
    """Size of the data directory, recomputed at most once per ``ttl`` seconds."""
    now = time.monotonic()
    if now - _data_cache['at'] < ttl:
        return _data_cache['bytes']
    total = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            try:
                total += os.stat(os.path.join(base, name)).st_size
            except OSError:
                pass
    _data_cache.update(at=now, bytes=total)
    return total


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
    children = [child for child in _self.children(recursive=True) if child.is_running()]
    rss = _self.memory_info().rss
    for child in children:
        try:
            rss += child.memory_info().rss
        except psutil.Error:
            pass
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
                 'data_bytes': directory_bytes(root)},
        'network': {'rx_bytes': net.bytes_recv, 'tx_bytes': net.bytes_sent,
                    'rx_rate': round(rx_rate, 1), 'tx_rate': round(tx_rate, 1)},
        'process': {'rss': rss, 'cpu_percent': round(_self.cpu_percent(interval=None), 1),
                    'threads': _self.num_threads(), 'children': len(children)},
    }
