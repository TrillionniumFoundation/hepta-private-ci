"""Frozen original-author lipreading model on the accepted1s native prefix.

The fixed native crop is an explicit CREMA adaptation, not the upstream
68-landmark affine alignment. It never sees another clip or future-frame pixels.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
from PIL import Image
import torch

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
UPSTREAM=ROOT.parent/'upstream_lipreading_tcn'
WEIGHTS=ROOT.parent/'pretrained_lipreading_weights/resnet18_mstcn_video.pth'
COHORT=ROOT/'experiments/hcsn_four_stage_flow_20261031/data/COHORT.json'
RAW=ROOT.parent/'video_raw_r2_media'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load():
    source=json.loads((HERE/'SOURCE_IDENTITY.json').read_text())
    assert all(sha(UPSTREAM/name)==digest for name,digest in source['upstream_files_sha256'].items())
    assert sha(WEIGHTS)==source['checkpoint_sha256']
    sys.path.insert(0,str(UPSTREAM))
    from lipreading.model import Lipreading
    c=json.loads((UPSTREAM/'configs/lrw_resnet18_mstcn.json').read_text())
    options={k.removeprefix('tcn_'):v for k,v in c.items() if k.startswith('tcn_')}
    model=Lipreading(modality='video',num_classes=500,tcn_options=options,backbone_type=c['backbone_type'],relu_type=c['relu_type'],width_mult=c['width_mult'],use_boundary=False,extract_feats=True).cpu().eval()
    checkpoint=torch.load(WEIGHTS,map_location='cpu',weights_only=True)
    model.load_state_dict(checkpoint['model_state_dict'],strict=True)
    assert all(bool(torch.isfinite(v).all()) for v in model.state_dict().values())
    for parameter in model.parameters():parameter.requires_grad_(False)
    return model


def decode(row):
    path=RAW/(row['clip']+'.flv')
    assert path.stat().st_size==row['bytes'] and sha(path)==row['sha256']
    probe=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_frames','-show_entries',
        'stream=codec_type,codec_name,has_b_frames,start_time,width,height:frame=media_type,best_effort_timestamp_time','-of','json',str(path)]))
    timestamps=np.asarray([float(f['best_effort_timestamp_time']) for f in probe['frames'] if f.get('media_type')=='video'])
    audio=next(s for s in probe['streams'] if s['codec_type']=='audio');video=next(s for s in probe['streams'] if s['codec_type']=='video')
    assert video.get('has_b_frames',0)==0, 'Future-reordered frames are outside this registered prefix profile'
    origin=max(float(audio.get('start_time',0)),float(timestamps[0]));cutoffs=origin+np.arange(1,26)/25
    assert np.all(np.diff(timestamps)>0) and timestamps[-1]>=origin+1
    selected=np.searchsorted(timestamps,cutoffs,side='right')-1
    assert selected.min()>=0 and np.all(timestamps[selected]<=cutoffs)
    x=int(round(.53*video['width']))-48;y=int(round(.54*video['height']))-48
    assert x>=0 and y>=0 and x+96<=video['width'] and y+96<=video['height']
    count=int(selected.max())+1
    rgb=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-xerror','-threads','1','-i',str(path),'-map','0:v:0','-an',
        '-vf',f'format=rgb24,crop=96:96:{x}:{y}','-filter_threads','1','-threads','1','-frames:v',str(count),'-vsync','0','-f','rawvideo','-'])
    frames=np.frombuffer(rgb,dtype=np.uint8).reshape(-1,96,96,3)
    assert len(frames)==count
    gray=np.stack([np.asarray(Image.fromarray(frame).convert('L'))[4:92,4:92] for frame in frames[selected]])
    assert gray.shape==(25,88,88)
    return gray,dict(clip=row['clip'],raw_sha256=row['sha256'],origin=origin,accepted_end=origin+1,cutoffs=cutoffs.tolist(),selected_indices=selected.tolist(),selected_timestamps=timestamps[selected].tolist(),decoded_frames=count,codec_name=video.get('codec_name'),has_b_frames=video.get('has_b_frames',0),crop_native_xywh=[x,y,96,96],source_geometry=[video['width'],video['height']])


def encode(model,pixels):
    # Fixed upstream intensity normalization. No clip/actor/test-fitted statistics.
    x=(torch.from_numpy(np.ascontiguousarray(pixels)).float()/255-.421)/.165
    with torch.inference_mode():
        frames=model(x[None,None],lengths=[len(x)])
        logits=model.tcn(frames,[len(x)],1)
    assert frames.shape==(1,25,512) and logits.shape==(1,500)
    assert bool(torch.isfinite(frames).all()) and bool(torch.isfinite(logits).all())
    return frames[0].numpy(),logits[0].numpy()


def descriptor(frames,logits):
    assert frames.shape[-2:]==(25,512) and logits.shape[-1]==500
    shape=frames.shape[:-2]
    bins=frames.reshape(*shape,5,5,512).mean(-2).reshape(*shape,2560)
    return np.concatenate((bins,logits),axis=-1)
