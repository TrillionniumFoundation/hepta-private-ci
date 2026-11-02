"""Hash-pinned raw accepted-prefix native mouth pixel acquisition."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.request

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
COHORT = ROOT/'experiments/hcsn_four_stage_flow_20261031/data/COHORT.json'
RAW = ROOT.parent/'video_raw_r2_media'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path,value):
    with Path(path).open('x') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def acquire(row):
    RAW.mkdir(exist_ok=True)
    path=RAW/(row['clip']+'.flv');tick=time.perf_counter()
    repair_empty=False
    if path.exists():
        assert not path.is_symlink() and path.is_file()
        repair_empty=path.stat().st_size==0
        if not repair_empty:
            assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256']
            return dict(clip=row['clip'],sha256=row['sha256'],bytes=row['bytes'],reused=True,wall_seconds=time.perf_counter()-tick)
    with urllib.request.urlopen(row['url'],timeout=90) as response:
        data=response.read(row['bytes']+1)
    assert len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256']
    if path.exists():
        assert not path.is_symlink() and path.is_file() and path.stat().st_size==0
        mode='wb'
    else:mode='xb'
    with path.open(mode) as stream:stream.write(data)
    assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256']
    return dict(clip=row['clip'],sha256=row['sha256'],bytes=row['bytes'],reused=False,repaired_empty=repair_empty,wall_seconds=time.perf_counter()-tick)


def decode(row):
    path=RAW/(row['clip']+'.flv')
    assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256']
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames','-show_entries',
        'stream=codec_type,start_time,width,height:frame=media_type,best_effort_timestamp_time','-of','json',str(path)]))
    ts=np.asarray([float(f['best_effort_timestamp_time']) for f in probe['frames'] if f.get('media_type')=='video'])
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio')
    origin=max(float(audio.get('start_time',0)),float(ts[0]))
    assert np.all(np.diff(ts)>0) and ts[-1]>=origin+1
    selected=np.searchsorted(ts,origin+np.arange(1,17)/16,side='right')-1
    assert selected.min()>=0 and np.all(ts[selected]<=origin+np.arange(1,17)/16)
    crop='crop=w=trunc(iw*.34/2)*2:h=trunc(ih*.30/2)*2:x=trunc(iw*.33/2)*2:y=trunc(ih*.40/2)*2'
    pixels=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(path),'-map','0:v:0','-an',
        '-vf',crop+',scale=48:32:flags=area,format=gray','-filter_threads','1','-threads','1','-vsync','0','-f','rawvideo','-'])
    frames=np.frombuffer(pixels,dtype=np.uint8).reshape(-1,32,48)
    assert len(frames)==len(ts)
    return frames[selected].copy(),dict(clip=row['clip'],raw_sha256=row['sha256'],origin=origin,
        selected_timestamps=ts[selected].tolist(),accepted_end=origin+1,source_frames=len(ts),
        source_geometry=[next(s for s in probe['streams'] if s['codec_type']=='video')[k] for k in ['width','height']])


def prepare(split):
    assert split in ['train','validation']
    out=HERE/'inputs';out.mkdir(exist_ok=True)
    target=out/f'{split}_pixels.npz'
    if target.exists():raise FileExistsError(target)
    rows=sorted([r for r in json.loads(COHORT.read_text())['records'] if r['split']==split],key=lambda r:r['clip'])
    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts=list(executor.map(acquire,rows))
    write(out/f'{split}_ACQUISITION.json',dict(cohort_sha256=sha(COHORT),source_sha256=sha(__file__),protocol_sha256=sha(HERE/'PROTOCOL.json'),records=receipts))
    pixels=[];metadata=[]
    for i,row in enumerate(rows):
        cube,detail=decode(row);pixels.append(cube);metadata.append(detail)
        if (i+1)%48==0:print(json.dumps(dict(split=split,decoded=i+1,total=len(rows))),flush=True)
    np.savez_compressed(target,pixels=np.stack(pixels),actor=np.asarray([r['actor'] for r in rows]),
        clip=np.asarray([r['clip'] for r in rows]),label=np.asarray([('DFA','IOM').index(r['sentence']) for r in rows]),emotion=np.asarray([r['emotion'] for r in rows]))
    write(out/f'{split}_IDENTITY.json',dict(records=metadata,source_sha256=sha(__file__),protocol_sha256=sha(HERE/'PROTOCOL.json'),cohort_sha256=sha(COHORT),
        pixels_sha256=sha(target),split=split,actor_count=len({r['actor'] for r in rows}),raw_bytes=sum(r['bytes'] for r in rows)))
    print(json.dumps(dict(split=split,clips=len(rows),pixel_bytes=target.stat().st_size,pixels_sha256=sha(target))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('split',choices=['train','validation']);args=parser.parse_args();prepare(args.split)
