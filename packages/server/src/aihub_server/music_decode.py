"""Private, cancellable local-file decoder. Stdout is 16 kHz mono s16 PCM only."""
import argparse
import sys
import av


def decode(path, offset=0):
    with av.open(path) as source:
        if offset:source.seek(int(offset*av.time_base),backward=True)
        resampler=av.AudioResampler(format='s16',layout='mono',rate=16000)
        next_time=0
        for frame in source.decode(audio=0):
            for out in resampler.resample(frame):
                start=float(out.time) if out.time is not None else next_time
                pcm=out.to_ndarray().astype('<i2').tobytes()
                next_time=start+len(pcm)/32000
                skip=max(0,int((offset-start)*16000))*2
                if skip<len(pcm):yield pcm[skip:]
        for out in resampler.resample(None):
            yield out.to_ndarray().astype('<i2').tobytes()


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path');parser.add_argument('--offset',type=float,default=0)
    args=parser.parse_args()
    if not 0<=args.offset<=10800:parser.error('invalid offset')
    for block in decode(args.path,args.offset):sys.stdout.buffer.write(block)
    sys.stdout.buffer.flush()
