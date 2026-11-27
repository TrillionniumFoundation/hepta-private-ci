import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import resample_poly


def sha(data):
    return hashlib.sha256(data).hexdigest()


def features(x, hz):
    a = np.asarray(x, dtype=np.float64)
    if a.ndim != 1 or a.size < 160:
        raise ValueError("expected nonempty mono speech")
    gcd = math.gcd(hz, 8000)
    a = resample_poly(a, 8000 // gcd, hz // gcd)
    a -= a.mean()
    a /= max(np.sqrt(np.mean(a*a)), 1e-8)
    if len(a) < 256:
        a = np.pad(a, (0, 256-len(a)))
    idx = np.arange(256)[None, :] + np.arange(0, len(a)-255, 64)[:, None]
    power = abs(np.fft.rfft(a[idx]*np.hanning(256), axis=1))**2
    freq = np.fft.rfftfreq(256, 1/8000)
    fb = np.zeros((len(freq),16))
    edges = 700*np.expm1(np.linspace(np.log1p(30/700), np.log1p(4000/700),18))
    for j in range(16):
        fb[:,j] = np.maximum(0,np.minimum((freq-edges[j])/(edges[j+1]-edges[j]),(edges[j+2]-freq)/(edges[j+2]-edges[j+1])))
    mel = np.log1p(power @ fb)
    bins = [np.arange(int(t*len(mel)/6),max(int(t*len(mel)/6)+1,int((t+1)*len(mel)/6))) for t in range(6)]
    return np.stack([mel[ii].mean(0) for ii in bins]).astype('float32')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('fsdd',type=Path)
    parser.add_argument('audiomnist',type=Path)
    parser.add_argument('out',type=Path)
    a=parser.parse_args()
    timer=time.perf_counter(); cpu=time.process_time()
    a.out.mkdir(exist_ok=True,parents=True)
    groups={}; seen=set(); manifest=[]; duplicates=[]
    entries=[]
    for w in sorted((a.fsdd/'recordings').glob('*.wav')):
        digit,speaker,i=w.stem.split('_')
        part='old_test' if int(i)<5 else 'old_dev' if int(i)<10 else 'old_cal' if int(i)<15 else 'parent'
        entries.append((part,'FSDD',w,speaker,int(digit)))
    for s in range(1,59,3):
        part='new_cal' if s<=10 else 'new_dev' if s<=22 else 'new_test'
        for w in sorted((a.audiomnist/'data'/f'{s:02d}').glob('*.wav')):
            digit,speaker,i=w.stem.split('_')
            if int(i)<12: entries.append((part,'AudioMNIST',w,speaker,int(digit)))
    assert len(entries)==5400
    order={name:i for i,name in enumerate(['parent','old_cal','new_cal','old_dev','new_dev','old_test','new_test'])}
    for part,corpus,w,speaker,digit in sorted(entries,key=lambda el:(order[el[0]],el[2].name)):
        hz,x=wavfile.read(w)
        identity=sha(str((hz,x.shape,x.dtype)).encode()+x.tobytes())
        if identity in seen:
            duplicates.append([part,corpus,w.name,identity]);continue
        seen.add(identity)
        groups.setdefault(part,[]).append((features(x,hz),digit,speaker,w.name))
        manifest.append([part,corpus,w.name,sha(w.read_bytes()),identity])
    parts={}
    for part,rec in groups.items():
        X,y,s,n=zip(*rec);p=a.out/(part+'.npz')
        np.savez_compressed(p,x=np.array(X),y=np.array(y),speaker=np.array(s),record=np.array(n))
        parts[part]={'n':len(rec),'speakers':sorted(set(s)),'sha256':sha(p.read_bytes())}
    data={'fsdd':'26eb9aaf76e81b692f806f9140c2d2777410d7a1','audio_mnist':'630d7dab4c040882834de6fa21baf9a60372accd','parts':parts,'duplicate_pcm':duplicates,'cpu_seconds':time.process_time()-cpu,'wall_seconds':time.perf_counter()-timer}
    (a.out/'data.json').write_text(json.dumps(data,indent=2))
    (a.out/'sources.tsv').write_text('split\tcorpus\tfile\twav_sha256\tpcm_sha256\n'+''.join('\t'.join(row)+'\n' for row in manifest))
    print(json.dumps(data))


if __name__=='__main__':
    main()
