"""P3 end-to-end four-modality BYTE decoding + trained encoder on synthetic media.

This uses *actual* UTF-8, PNG, WAV, MP4 files but all contents are authored
synthetically in code. It proves pipeline connectivity only. It is NOT
real-world text/image/audio/video alignment, and is not HCSN's Encoder.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
import numpy as np
import torch
from torch import nn
from PIL import Image
import soundfile as sf
from media_bytes_gate import check_bytes,digest_file

COLORS=((215,35,55),(45,160,75),(45,65,220),(205,150,35))
NAMES=('scarlet','emerald','azure','amber')
MODALITIES=('text','image','audio','video')


def _video_frames(cls,seed):
    rng=np.random.default_rng(seed)
    output=[]
    for t in range(6):
        frame=np.full((48,48,3),np.array(COLORS[cls],dtype=np.uint8)[None,None,:],dtype=np.uint8)
        px=(2*seed+5*t)%36
        frame[7:19,px:px+12,:]=240
        frame[30:34,4+(seed%10):12+(seed%10),:]=rng.integers(0,45,(1,1,3))
        output.append(frame)
    return np.stack(output)


def create_corpus(root,counts=(20,8,12)):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    records=[]
    index=0
    for split,n in zip(('train','validation','holdout'),counts):
        for j in range(n):
            cls=(j+(0 if split=='train' else (1 if split=='validation' else 2)))%4
            seed=20260701+index*47
            rng=np.random.default_rng(seed)
            scene_dir=root/f'{split}_{j:04d}'
            scene_dir.mkdir(parents=True,exist_ok=True)
            text=scene_dir/'caption.txt'
            img=scene_dir/'frame.png'
            audio=scene_dir/'sound.wav'
            video=scene_dir/'clip.mp4'
            text.write_text(f'An {NAMES[cls]} light pulsing. Scene {seed}.\n',encoding='utf-8')
            pix=np.full((48,48,3),COLORS[cls],dtype=np.uint8)
            pix[5+(j%8):15+(j%8),5+(j%13):19+(j%13)]=235
            # Unique benign per-scene pixel identity, no label leakage via digest.
            pix[38:46,2:10,:]=rng.integers(0,80,(8,8,3),dtype=np.uint8)
            Image.fromarray(pix,mode='RGB').save(img)
            time=np.arange(24000,dtype=np.float64)/16000.
            hz=300+120*cls
            phase=(seed%17)*.1 + index*.0031
            wave=.33*np.sin(2*np.pi*hz*time+phase)
            wave+=.04*np.sin(2*np.pi*(hz/2)*time)
            sf.write(audio,wave,16000,subtype='PCM_16')
            frames=_video_frames(cls,seed)
            cmd=['ffmpeg','-hide_banner','-loglevel','error','-y',
                 '-f','rawvideo','-pix_fmt','rgb24','-s','48x48','-r','4',
                 '-i','pipe:0','-frames:v','6','-an','-c:v','mpeg4','-qscale:v','5',str(video)]
            proc=subprocess.run(cmd,input=frames.tobytes(),capture_output=True,timeout=15)
            if proc.returncode:
                raise RuntimeError(f'ffmpeg encode failed: {proc.stderr[:180]}')
            files={key:{'path':str(path.relative_to(root)), 'sha256':digest_file(path)}
                   for key,path in [('text',text),('image',img),('audio',audio),('video',video)]}
            records.append({'sample_id':f'clip-{index:05d}','entity_id':f'generated-id-{index}',
                            'scene_id':f'generated-scene-{index}','split':split,
                            't_start_sec':0.,'t_end_sec':1.,
                            'provenance':'LOCAL PROCEDURALLY GENERATED synthetic fixture; no real-world data',
                            'files':files,'concept':cls})
            index+=1
    (root/'manifest.json').write_text(json.dumps(records,indent=2))
    return records


def _decode_video(path):
    args=['ffmpeg','-v','error','-i',str(path),'-f','rawvideo','-pix_fmt','rgb24','pipe:1']
    p=subprocess.run(args,capture_output=True,timeout=12,check=True)
    if len(p.stdout)==0 or len(p.stdout)%(48*48*3)!=0:
        raise ValueError('video decode wrong frame count')
    return np.frombuffer(p.stdout,dtype=np.uint8).reshape(-1,48,48,3)


def _extract(rec,root):
    files={m:root/rec['files'][m]['path'] for m in MODALITIES}
    s=files['text'].read_text()
    text=np.asarray([1. if key in s else 0. for key in NAMES],dtype=np.float32)
    with Image.open(files['image']) as im:
        img=np.asarray(im.convert('RGB'),dtype=np.float32)/255.
    image=np.concatenate((img.mean(axis=(0,1)),img.std(axis=(0,1)))).astype(np.float32)
    wave,sr=sf.read(files['audio'],dtype='float32')
    # Fixed-bin log magnitude at class-specific frequencies (synthetic toy).
    freq=np.fft.rfftfreq(len(wave),1./sr)
    fft=np.abs(np.fft.rfft(wave))
    audio=np.asarray([np.log1p(fft[np.argmin(abs(freq-f))])/8 for f in
                      (300,420,540,660,150,210,270,330)],dtype=np.float32)
    frames=_decode_video(files['video']).astype(np.float32)/255.
    vid=np.concatenate((frames.mean(axis=(0,1,2)),frames.std(axis=(0,1,2)))).astype(np.float32)
    return {'text':text,'image':image,'audio':audio,'video':vid}


class TinyPairedEncoder(nn.Module):
    def __init__(self):
        super().__init__()
        self.proj=nn.ModuleDict({m:nn.Sequential(nn.Linear(d,16),nn.Tanh(),nn.Linear(16,12))
                                 for m,d in [('text',4),('image',6),('audio',8),('video',6)]})
        self.classifier=nn.Linear(12,4)
    def represent(self,x):
        return {k:nn.functional.normalize(self.proj[k](v),dim=-1) for k,v in x.items()}


def run(root,steps=400,seed=2026):
    root=Path(root)
    manifest=root/'manifest.json'
    records=json.loads(manifest.read_text()) if manifest.is_file() else create_corpus(root)
    verified=check_bytes(records,root)
    if not verified['byte_integrity_metadata_valid']:
        raise AssertionError(f'failed media bytes: {verified["failures"][:4]}')
    feats=[_extract(rec,root) for rec in records]
    x={m:torch.tensor(np.stack([f[m] for f in feats]),dtype=torch.float32) for m in MODALITIES}
    labels=torch.tensor([rec['concept'] for rec in records],dtype=torch.long)
    splits={s:torch.tensor([i for i,r in enumerate(records) if r['split']==s])
            for s in ('train','validation','holdout')}
    torch.manual_seed(seed)
    torch.set_num_threads(1)
    model=TinyPairedEncoder()
    opt=torch.optim.Adam(model.parameters(),lr=.02)
    rng=np.random.default_rng(seed)
    for _ in range(steps):
        idx=torch.tensor(rng.choice(splits['train'].numpy(),size=16,replace=True))
        z=model.represent({m:x[m][idx] for m in MODALITIES})
        target=labels[idx]
        ce=sum(nn.functional.cross_entropy(model.classifier(z[m]),target) for m in MODALITIES)/4
        mean=torch.stack([z[m] for m in MODALITIES]).mean(0)
        align=sum(((z[m]-mean)**2).mean() for m in MODALITIES)/4
        loss=ce+0.4*align
        opt.zero_grad(set_to_none=True);loss.backward();opt.step()
    model.eval()
    result={}
    with torch.no_grad():
        z=model.represent(x)
        for split,idx in splits.items():
            # Do not make a sample-level recall claim: several clips depict
            # identical semantic classes; evaluate class-level retrieval.
            by_mod={}
            for m in MODALITIES:
                pred=model.classifier(z[m][idx]).argmax(-1)
                by_mod[m]=float((pred==labels[idx]).float().mean())
            retrieval={}
            for src in MODALITIES:
                for dst in MODALITIES:
                    if src==dst:continue
                    scores=z[src][idx]@z[dst][idx].T
                    pick=scores.argmax(dim=1)
                    retrieval[f'{src}_to_{dst}_same_class_at_1']=float(
                        (labels[idx][pick]==labels[idx]).float().mean())
            # Missing one modality (average 3) is tested, not omitted from input silently.
            missing={}
            for excluded in MODALITIES:
                ensemble=sum(z[m][idx] for m in MODALITIES if m!=excluded)/3
                pred=model.classifier(ensemble).argmax(-1)
                missing[f'without_{excluded}']=float((pred==labels[idx]).float().mean())
            result[split]={'n':len(idx),'class_accuracy':by_mod,
                           'cross_modal_class_retrieval_at_1':retrieval,
                           'missing_modality_accuracy':missing}
        # Noise on *extracted embeddings* is a diagnostic, not corrupted byte OOD.
        idx=splits['holdout'];noise={}
        torch.manual_seed(seed+1)
        for m in MODALITIES:
            corrupted_x=x[m][idx]+.1*torch.randn_like(x[m][idx])
            z_noisy=model.represent({m:corrupted_x})[m]
            pred=model.classifier(z_noisy).argmax(-1)
            noise[m]=float((pred==labels[idx]).float().mean())
    return {'scope':'trained synthetic four-modality byte corpus with class labels; NOT real-world data',
            'samples':len(records),'train_steps':steps,
            'decoded_bytes_checked':verified['samples_checked'],
            'media_byte_validation':verified['byte_integrity_metadata_valid'],
            'results':result,'feature_noise_accuracy_holdout':noise,
            'real_world_data':False,'model_is_HCSN_encoder':False,
            'natural_data_generalization_proven':False,
            'production_evidence_accepted':False}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',default='reports/toy_media_corpus')
    parser.add_argument('--out',default='reports/p3_toy_media_encoder.json')
    parser.add_argument('--steps',type=int,default=400)
    a=parser.parse_args()
    result=run(a.root,steps=a.steps)
    Path(a.out).write_text(json.dumps(result,indent=2))
    print('saved',a.out,'split scores',
          {s:v['class_accuracy'] for s,v in result['results'].items()})
