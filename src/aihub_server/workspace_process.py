"""Identity-checked workspace launcher processes (never stop by port number)."""
import argparse
import asyncio
import json
import os
from pathlib import Path

import psutil


def owned(pidfile, module):
    try:
        record = json.loads(Path(str(pidfile) + '.identity').read_text())
        if int(Path(pidfile).read_text()) != record['pid']:
            return None
        process = psutil.Process(record['pid'])
        cmd = process.cmdline()
        if (process.uids().real == os.getuid()
                and abs(process.create_time() - record['created']) < .001
                and '-m' in cmd and cmd[cmd.index('-m') + 1] == module):
            return process
    except (OSError, ValueError, KeyError, IndexError, psutil.Error):
        pass
    return None


def remember(pidfile, module):
    process = psutil.Process(int(Path(pidfile).read_text()))
    cmd = process.cmdline()
    if '-m' not in cmd or cmd[cmd.index('-m') + 1] != module:
        raise ValueError('workspace_process_identity_mismatch')
    path = Path(str(pidfile) + '.identity')
    path.write_text(json.dumps({'pid': process.pid, 'created': process.create_time()}))


def stop(pidfile, module):
    process = owned(pidfile, module)
    if process:
        try:
            process.terminate()
            process.wait(6)
        except psutil.TimeoutExpired:
            current = owned(pidfile, module)
            if current:
                current.kill()
                current.wait(2)
        except psutil.NoSuchProcess:
            pass
    Path(pidfile).unlink(missing_ok=True)
    Path(str(pidfile) + '.identity').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=('remember', 'stop', 'workers'))
    parser.add_argument('path')
    parser.add_argument('module', nargs='?')
    args = parser.parse_args()
    if args.action == 'workers':
        from .config import ConfigFile
        from .services import ServiceManager
        root = Path(args.path)
        asyncio.run(ServiceManager(root, ConfigFile(root / 'settings.json').get).shutdown(stop_workers=True))
    elif args.action == 'remember':
        remember(args.path, args.module)
    else:
        stop(args.path, args.module)


if __name__ == '__main__':
    main()
