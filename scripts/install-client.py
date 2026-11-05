"""Install a verified explicit client artifact; never read sibling source trees."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

FILES = {'index.html', 'client.js', 'chat-view.js', 'tool-calls.mjs', 'audio.js', 'capture.js', 'style.css', 'LICENSE'}
def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('artifact', type=Path)
    parser.add_argument('--destination', type=Path, default=Path(__file__).resolve().parents[1]/'.artifacts/client-web')
    args=parser.parse_args()
    manifest=json.loads((args.artifact/'manifest.json').read_text())
    if manifest.get('protocol_version')!=1 or set(manifest.get('files',{}))!=FILES:
        raise ValueError('Invalid client artifact manifest')
    for name in FILES:
        path=args.artifact/name
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['files'][name]:
            raise ValueError('Client artifact checksum mismatch: '+name)
    args.destination.mkdir(parents=True,exist_ok=True)
    for name in FILES|{'manifest.json'}:
        shutil.copyfile(args.artifact/name,args.destination/name)
    print('Installed client artifact:',args.destination)
if __name__=='__main__':main()
