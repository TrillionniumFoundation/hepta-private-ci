"""Behavioral future-frame/PTS and raw-source rejection checks, no real dev data."""
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from experiments.hcsn_video_raw_r2_20261101 import raw_data


def main(output=None):
    original_raw=raw_data.RAW;original_call=raw_data.subprocess.check_output
    checks=[]
    with tempfile.TemporaryDirectory(prefix='hcsn-raw-prefix-') as temporary:
        root=Path(temporary);data=b'fixture';(root/'fixture.flv').write_bytes(data)
        row=dict(clip='fixture',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        times=[0.,.25,.5,.75,1.,1.25]
        pixels=np.stack([np.full((32,48),i,dtype=np.uint8) for i in range(6)])
        def fake(command):
            if command[0]=='ffprobe':
                return json.dumps(dict(streams=[dict(codec_type='audio',start_time='0'),dict(codec_type='video',width=480,height=360)],
                    frames=[dict(media_type='video',best_effort_timestamp_time=str(t)) for t in times])).encode()
            return pixels.tobytes()
        raw_data.RAW=root;raw_data.subprocess.check_output=fake
        try:
            first,metadata=raw_data.decode(row)
            assert first[:,0,0].tolist()==[0]*3+[1]*4+[2]*4+[3]*4+[4]
            checks.append('last original PTS selected at every fixed prefix cutoff')
            pixels[-1]=255
            future,_=raw_data.decode(row);assert np.array_equal(first,future)
            checks.append('changed future frame after accepted1s leaves every model-input pixel unchanged')
            pixels[3]=70
            present,_=raw_data.decode(row);assert not np.array_equal(first,present)
            checks.append('changed accepted-prefix frame changes model input')
            try:raw_data.decode(row|dict(sha256='0'*64))
            except AssertionError:checks.append('wrong raw source hash rejected before decode')
            else:raise AssertionError('wrong raw source hash accepted')
            times[:]=[0.,.1,.2,.3,.4,.5]
            try:raw_data.decode(row)
            except AssertionError:checks.append('recording shorter than fixed1s rejected')
            else:raise AssertionError('short recording accepted')
        finally:raw_data.RAW=original_raw;raw_data.subprocess.check_output=original_call
    result=dict(passed=True,checks=checks,count=len(checks),real_validation_data_loaded=False,source_sha256=raw_data.sha(raw_data.__file__))
    raw_data.write(output or raw_data.HERE/'PREFIX_CHECKS.json',result);print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path);args=parser.parse_args();main(args.out)
