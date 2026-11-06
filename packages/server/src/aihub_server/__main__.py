import argparse
import json
from pathlib import Path
from aiohttp import web
from .app import create_app, HUB


def main():
    parser = argparse.ArgumentParser(description='AIHub realtime voice server')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--client-host', default='127.0.0.1', help='Separate authenticated web-client listener')
    parser.add_argument('--client-port', type=int, default=8768)
    parser.add_argument('--no-client', action='store_true',
                        help='Do not start the web-client listener (server-only deployment)')
    parser.add_argument('--device-host', help='Specific private IP for an authenticated device-only listener')
    parser.add_argument('--device-bind', help='Listen address for the device listener (default: --device-host); 0.0.0.0 when running behind a container port mapping')
    parser.add_argument('--device-port', type=int, default=8766)
    parser.add_argument('--local-console', action='store_true',
                        help='Trust every admin-API peer as local. Use only when the console port is bound to '
                             'loopback (e.g. a container publishing 127.0.0.1:8765); otherwise the admin API is exposed')
    parser.add_argument('--mqtt-config', help='Private per-device MQTT/UDP config; disabled by default')
    parser.add_argument('--data', default=str(Path.cwd()/'data'),
                        help='Runtime data directory (default: ./data)')
    parser.add_argument('--print-device-token', action='store_true')
    parser.add_argument('--print-admin-token', action='store_true')
    args = parser.parse_args()
    client_host = None if args.no_client else args.client_host
    app = create_app(args.data, device_host=args.device_host, device_port=args.device_port,
                     mqtt_config=args.mqtt_config, device_bind=args.device_bind,
                     local_console=args.local_console, client_host=client_host, client_port=args.client_port)
    if args.print_device_token or args.print_admin_token:
        print(app[HUB].auth['device_token' if args.print_device_token else 'admin_token'])
        app[HUB].store.close()
        return
    print(f'AIHub console: http://127.0.0.1:{args.port} (bind {args.host})')
    if args.device_host or args.device_bind:
        print(f'Device ingress: {args.device_bind or args.device_host}:{args.device_port} '
              f'(advertised {args.device_host or "from connections.json"}; token required; no management routes)')
    print('Model loading is lazy. Settings apply to new connections. Ctrl+C stops this server.')
    web.run_app(app, host=args.host, port=args.port, access_log=None, shutdown_timeout=5)


if __name__ == '__main__':
    main()
