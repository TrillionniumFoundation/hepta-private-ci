"""Recover the one verified short CREMA-D development clip using its own observed frames/windows."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np

NAME='1076_MTI_NEU_XX'
DIGEST='5152cf0f07dd16c3df3a088855a47b51258cfc23c2fc42826e1c2fdd3051acaf'
POINTER='845b3af118a8696b6eefd479d946b64079392380'


def run(root):
    base=root/'data';dest=base/'repairs'/'8559-short-clip';dest.mkdir(exist_ok=True,parents=True)
    err=base/'failures.json';saved=dest/'original-failures.json'
    if not saved.exists():
        failures=err.read_bytes();assert json.loads(failures)==[[NAME,'AssertionError','']]
        with saved.open('xb') as f:f.write(failures)
    roster=json.loads((base/'roster.json').read_bytes())
    assert roster['actors']['1076']==1 and next(s[1] for s in roster['sources'] if s[0].endswith('/'+NAME+'.flv'))==POINTER
    path=base/'raw'/(NAME+'.flv');raw=path.read_bytes();assert len(raw)==35166 and hashlib.sha256(raw).hexdigest()==DIGEST
    cmd=[str(root/'env/ffmpeg'),'-nostdin','-loglevel','error','-threads','1','-filter_threads','1','-i',str(path)]
    def dec(extra):return subprocess.run(cmd+extra+['pipe:1'],capture_output=True,check=True,timeout=75).stdout
    video=np.frombuffer(dec(['-map','0:v:0','-vf','scale=28:28:flags=area','-pix_fmt','gray','-f','rawvideo']),np.uint8).reshape(-1,28,28)
    pcm=np.frombuffer(dec(['-map','0:a:0','-ac','1','-ar','8000','-f','s16le']),'<i2')
    assert (len(video),len(pcm),len(np.unique(video)),len(np.unique(pcm)))==(3,836,149,228)
    bins=12;vix=np.floor((np.arange(bins)+.5)*len(video)/bins).astype(int)
    w=pcm.astype(np.float32)/32768
    windows=np.lib.stride_tricks.sliding_window_view(w,256)[::80]
    assert len(windows)==8
    power=np.abs(np.fft.rfft(windows*np.hanning(256),axis=-1))**2
    bands=.5*(power[:,1:129:2]+power[:,2:129:2])
    aix=np.floor((np.arange(bins)+.5)*len(windows)/bins).astype(int)
    sound=np.log1p(bands[aix]).astype('float32');frames=video[vix]
    assert np.isfinite(sound).all()
    fields={'video':frames,'audio':sound,'frames':len(video),'samples':len(pcm),'sha256':DIGEST,'pointer':POINTER,'short_source':True,'video_source_indices':vix,'audio_source_window_indices':aix}
    out=base/'clips'/(NAME+'.npz')
    if out.exists():
        with np.load(out) as z:assert all(k in z and np.array_equal(z[k],v) for k,v in fields.items())
    else:
        with tempfile.NamedTemporaryFile(dir=dest,delete=False) as f:
            temp=Path(f.name);np.savez_compressed(f,**fields)
        try:os.link(temp,out)
        finally:temp.unlink(missing_ok=True)
    report=dict(source=NAME,split='development',source_sha256=DIGEST,pointer=POINTER,file_bytes=len(raw),frames=len(video),samples_at_8khz=len(pcm),windows=len(windows),video_indices=vix.tolist(),audio_window_indices=aix.tolist(),clip_sha256=hashlib.sha256(out.read_bytes()).hexdigest(),source_decoder=json.loads((root/'env/decoder.json').read_text()))
    (dest/'repair.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root.resolve())
