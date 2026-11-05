"""Create a new Linux HTTP settings file; never overwrite live settings."""
import argparse
import copy
import json
import os
from pathlib import Path

from aihub_server.config import DEFAULT, validate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--vad-model', required=True)
    for kind in ('asr', 'llm', 'tts'):
        parser.add_argument('--' + kind + '-url', required=True)
        parser.add_argument('--' + kind + '-model', required=True)
    parser.add_argument('--tts-voice', required=True)
    parser.add_argument('--tts-sample-rate', type=int, default=24000)
    args = parser.parse_args()
    if not Path(args.vad_model).is_file():
        parser.error('VAD ONNX file does not exist')
    config = copy.deepcopy(DEFAULT)
    for kind in ('asr', 'llm', 'tts'):
        config[kind].update(provider='http', url=getattr(args, kind + '_url'),
                            model=getattr(args, kind + '_model'))
    config['tts'].update(voice=args.tts_voice, sample_rate=args.tts_sample_rate)
    config['audio']['vad_model'] = str(Path(args.vad_model).resolve())
    config['tools'].update(planner='llm', music=False)
    config = validate(config)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(config, output, ensure_ascii=False, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
