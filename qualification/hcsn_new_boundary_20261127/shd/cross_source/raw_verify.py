"""Rebuild selected real inputs from PCM or original released Arabic MFCC frames."""
from pathlib import Path
import hashlib, io, json, zipfile
import numpy as np
from scipy.fft import dct
from scipy.io import wavfile
from scipy.signal import resample_poly
from core import DATA,HERE,dump,sha,use

def sample(m):
    p=np.linspace(0,len(m)-1,6);lo=np.floor(p).astype(int);hi=np.ceil(p).astype(int)
    return m[lo]+(m[hi]-m[lo])*(p-lo)[:,None]
def mfcc(raw):
    fs,pcm=wavfile.read(io.BytesIO(raw));assert pcm.ndim==1 and pcm.dtype==np.int16 and fs in (8000,16000)
    z=pcm.astype('float64')
    if fs==16000:z=resample_poly(z,1,2)
    z/=32768.;u=np.concatenate([z[:1],z[1:]-.97*z[:-1]]);u=np.pad(u,(0,max(0,200-len(u))))
    frames=np.lib.stride_tricks.sliding_window_view(u,200)[::80]*np.hamming(200)
    power=abs(np.fft.rfft(frames,512))**2/512.;bank=np.linspace(0,2595*np.log10(1+4000/700),28)
    hz=700*(10**(bank/2595)-1);f=np.fft.rfftfreq(512,1/8000)
    tri=np.maximum(0,np.minimum((f-hz[:-2,None])/(hz[1:-1,None]-hz[:-2,None]),(hz[2:,None]-f)/(hz[2:,None]-hz[1:-1,None])))
    feature=sample(dct(np.log(np.maximum(1e-12,power@tri.T)),type=2,norm='ortho',axis=-1)[:,:13])
    return feature, hashlib.sha256(pcm.tobytes()).hexdigest()
def main():
    fs=zipfile.ZipFile(DATA/'fsdd.zip');gsc=zipfile.ZipFile(DATA/'command'/'selected-originals.zip');arabic=zipfile.ZipFile(DATA/'arabic.zip')
    metadata=json.loads((DATA/'dataset.json').read_text());m=json.loads((DATA/'command'/'retained-source.json').read_text())
    for archive,digest in metadata['data_files'].items():assert sha(DATA/archive)==digest
    members={r['path']:r for r in map(json.loads,(DATA/'command'/'members.jsonl').open())}
    fsfiles={Path(n).stem:n for n in fs.namelist() if '/recordings/' in n and n.endswith('.wav')}
    gsc_labels='zero one two three four five six seven eight nine'.split()
    ar={}
    for name,expected in [('Train','cecd3ee9951658e5391f0342e9b6467ba7c0e7ecff5c9012b9c1ed9f81b97bc6'),('Test','de40eac66ce18fca8924bad592002ee7ef646fc84d48b065ce21ac9f88946922')]:
        b=arabic.read(name+'_Arabic_Digit.txt');assert hashlib.sha256(b).hexdigest()==expected
        blocks=[];now=[]
        for l in b.splitlines():
            if l.strip():now.append(l)
            elif now:blocks.append(now);now=[]
        if now:blocks.append(now)
        assert len(blocks)==(6600 if name=='Train' else 2200);ar[name]=blocks
    scalers={'fsdd':dict(np.load(DATA/'english_scaler.npz')),'gsc':dict(np.load(DATA/'command'/'scaler.npz'))}
    rows={};wavs={};counts={}
    for p in ('train','dev','test'):
        A=np.load(DATA/f'{p}.npz');G=np.load(DATA/'command'/f'{p}.npz');scope={}
        for nm,ids,target,labels in [('fsdd',A[f'eng_{p}_id'],A[f'eng_{p}_x'],A[f'eng_{p}_y']),('gsc',G['id'],G['x'],G['y'])]:
            feat=[]
            for ident,label in zip(ids,labels):
                if nm=='fsdd':
                    raw=fs.read(fsfiles[ident]);v,h=mfcc(raw);assert int(ident.split('_')[0])==label
                else:
                    raw=gsc.read(ident);v,h=mfcc(raw);old=members[ident]
                    assert hashlib.sha256(raw).hexdigest()==m['byte_checks'][ident] and h==old['pcm_sha256'] and old['partition']==p
                    assert gsc_labels.index(ident.split('/')[0])==label==old['digit']
                feat.append(v);wavs.setdefault(h,set()).add(p)
            sc=scalers[nm];replay=np.clip((np.array(feat)-sc['mean'])/sc['std'],-5,5).astype('f4')
            delta=float(abs(replay-target).max());assert delta<2e-5
            scope[nm]={'recordings':len(feat),'max_mfcc_difference':delta}
        arr=[];idx=A[f'ar_{p}_id'];blocks=ar['Test' if p=='test' else 'Train'];div=len(blocks)//10
        for i in idx:arr.append(sample(np.fromstring(b' '.join(blocks[i]),sep=' ').reshape(-1,13)))
        assert np.array_equal(idx//div,A[f'ar_{p}_y']);delta=float(abs(np.array(arr)-A[f'ar_{p}_x']).max());assert delta<1e-9
        scope['arabic']={'recordings':len(arr),'max_mfcc_difference':delta};rows[p]=scope
    assert all(len(v)==1 for v in wavs.values())
    dump(HERE/'raw-verified.json',dict(splits=rows,distinct_pcm=len(wavs),cross_split_pcm_overlap=0,source_sha256={'fsdd':sha(DATA/'fsdd.zip'),'arabic':sha(DATA/'arabic.zip'),'selected_gsc_pcm_archive':sha(DATA/'command'/'selected-originals.zip'),'full_gsc_archive_historical_receipt':json.loads((DATA/'command'/'dataset.json').read_text())['sha256']},**use()))
    print(rows,flush=True)
if __name__=='__main__':main()
