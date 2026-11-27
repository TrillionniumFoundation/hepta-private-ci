"""Prepare numbered English MFCC sequences and source-disjoint Arabic partitions."""
import argparse
import hashlib
import io
import json
import time
import zipfile
from pathlib import Path
from urllib.request import urlretrieve
import numpy as np
from scipy.fft import dct
from scipy.io import wavfile

PIN = '26eb9aaf76e81b692f806f9140c2d2777410d7a1'
FSDD = 'https://codeload.github.com/Jakobovski/free-spoken-digit-dataset/zip/' + PIN
UCI = 'https://archive.ics.uci.edu/static/public/195/spoken+arabic+digit.zip'
ARABIC = {'Train_Arabic_Digit.txt': 'cecd3ee9951658e5391f0342e9b6467ba7c0e7ecff5c9012b9c1ed9f81b97bc6',
          'Test_Arabic_Digit.txt': 'de40eac66ce18fca8924bad592002ee7ef646fc84d48b065ce21ac9f88946922'}
SPLITS = [('train', ('george','jackson','lucas')), ('dev', ('yweweler',)), ('test', ('nicolas','theo'))]


def sha(x):
    return hashlib.sha256(x).hexdigest()


def sample(rows):
    t=np.linspace(0,len(rows)-1,6)
    lo,hi=t.astype(int),np.ceil(t).astype(int)
    return rows[lo] + (rows[hi]-rows[lo])*(t-lo)[:,None]


def mfcc(signal, sr):
    assert sr==8000 and signal.ndim==1
    signal=signal.astype('float64')/(2**15)
    z=np.r_[signal[0], signal[1:]-.97*signal[:-1]]
    size,stride=round(sr*.025),round(sr*.010)
    if len(z)<size: z=np.pad(z,(0,size-len(z)))
    frames=np.lib.stride_tricks.sliding_window_view(z,size)[::stride]*np.hamming(size)
    power=np.abs(np.fft.rfft(frames,n=512))**2/512.
    melmax=2595.*np.log10(1+4000/700)
    hz=700*(10**(np.linspace(0,melmax,28)/2595)-1)
    frequencies=np.fft.rfftfreq(512,1./sr)[None,:]
    triangles=np.maximum(0,np.minimum((frequencies-hz[:-2,None])/(hz[1:-1,None]-hz[:-2,None]),
                                      (hz[2:,None]-frequencies)/(hz[2:,None]-hz[1:-1,None])))
    return sample(dct(np.log((power@triangles.T).clip(1e-12)),type=2,axis=1,norm='ortho')[:,:13])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',type=Path,required=True)
    ns=parser.parse_args(); root=ns.input;root.mkdir(exist_ok=True,parents=True)
    stamp=time.perf_counter()
    for name,url in [('fsdd.zip',FSDD),('arabic.zip',UCI)]:
        if not (root/name).is_file(): urlretrieve(url,root/name)
    out={}; receipts={}; excluded=[]
    with zipfile.ZipFile(root/'fsdd.zip') as z:
        found={};seen={}
        for name in z.namelist():
            if '/recordings/' not in name or not name.endswith('.wav'): continue
            label,person,rep=Path(name).stem.split('_')
            found[(person,int(label),int(rep))]=name
        for split,people in SPLITS:
            seq=[]; labels=[]; ids=[]
            for person in people:
                for label in range(10):
                    for rep in range(0,50,1 if split=='test' else 5):
                        entry=found[(person,label,rep)]
                        rate,signal=wavfile.read(io.BytesIO(z.read(entry)))
                        sig=sha(signal.tobytes())
                        if sig in seen and seen[sig]!=split:
                            excluded.append([entry,seen[sig],split]);continue
                        seen[sig]=split
                        seq.append(mfcc(signal,rate));labels.append(label);ids.append(Path(entry).stem)
            out['eng_'+split+'_x']=np.asarray(seq)
            out['eng_'+split+'_y']=np.asarray(labels)
            out['eng_'+split+'_id']=np.asarray(ids)
    with zipfile.ZipFile(root/'arabic.zip') as z:
        for name,digest in ARABIC.items():
            b=z.read(name);assert sha(b)==digest
            blocks=[];now=[]
            for line in b.splitlines():
                if line.strip():now.append(line)
                elif now: blocks.append(now);now=[]
            if now:blocks.append(now)
            test=name.startswith('Test')
            divisor=220 if test else 660
            assert len(blocks)==divisor*10
            groups={}
            for pos in range(0,len(blocks),1 if test else 10):
                idx=pos%divisor
                seg='test' if test else ('dev' if (idx//10)%3==2 else 'train')
                groups.setdefault(seg,[]).append(pos)
            for seg,positions in groups.items():
                out['ar_'+seg+'_x']=np.stack([sample(np.fromstring(b' '.join(blocks[pos]),sep=' ').reshape(-1,13)) for pos in positions])
                out['ar_'+seg+'_y']=np.array(positions)//divisor
                out['ar_'+seg+'_id']=np.array(positions)
    train=out['eng_train_x'];mean=train.mean((0,1));std=train.std((0,1)).clip(1e-6)
    for split,_ in SPLITS:
        k='eng_'+split+'_x';out[k]=((out[k]-mean)/std).clip(-5,5).astype(np.float32)
    out['english_mean']=mean;out['english_std']=std
    parts={}
    for target in ('train','dev','test'):
        subset={k:v for k,v in out.items() if ('_'+target+'_') in k}
        path=root/(target+'.npz')
        np.savez_compressed(path,**subset)
        parts[target]=dict(sha256=sha(path.read_bytes()),english=len(subset['eng_'+target+'_y']),arabic=len(subset['ar_'+target+'_y']))
    np.savez_compressed(root/'english_scaler.npz',mean=mean,std=std)
    receipts=dict(data_files={n:sha((root/n).read_bytes()) for n in ['fsdd.zip','arabic.zip']},
                  fsdd_commit=PIN,arabic_source=UCI,source_code=sha(Path(__file__).read_bytes()),
                  parts=parts,cross_split_exclusions=excluded,wall_s=time.perf_counter()-stamp)
    (root/'dataset.json').write_text(json.dumps(receipts,indent=2)+'\n')
    print(json.dumps(receipts,indent=2))


if __name__=='__main__': main()
