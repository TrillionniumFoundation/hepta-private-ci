"""Join exact original photo/caption numbers and tokenize real image, audio and text observations."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import gzip
import io
import json
from pathlib import Path
import re
import tarfile
import time
import wave
import zipfile

import numpy as np
from PIL import Image, ImageOps
from scipy.signal import resample_poly


def file_hash(path):
    with path.open('rb') as f:
        h=sha256()
        while block:=f.read(2**20):h.update(block)
        return h.hexdigest()


def visual_patches(raw):
    with Image.open(io.BytesIO(raw)) as image:
        small=ImageOps.fit(image.convert('RGB'),(64,64),method=Image.Resampling.BILINEAR)
        pix=np.asarray(small,dtype=np.float32)/255.
    return pix.reshape(4,2,8,4,2,8,3).mean((2,5)).transpose(0,2,1,3,4).reshape(16,12)


def filter_bank():
    hz=lambda m:700*np.expm1(m/1127.)
    edges=hz(np.linspace(1127*np.log1p(50/700),1127*np.log1p(7900/700),26))
    fftfreq=np.fft.rfftfreq(512,1/16000)
    rise=(fftfreq[:,None]-edges[:-2])/(edges[1:-1]-edges[:-2])
    fall=(edges[2:]-fftfreq[:,None])/(edges[2:]-edges[1:-1])
    filters=np.maximum(0,np.minimum(rise,fall)).astype(np.float32)
    return filters/np.maximum(1e-12,filters.sum(0))


BANK=filter_bank()
WINDOW=np.hanning(400).astype(np.float32)


def acoustic_patches(item):
    name,raw=item
    with wave.open(io.BytesIO(raw),'rb') as f:
        sr=f.getframerate()
        if f.getsampwidth()!=2:raise ValueError(('PCM width',name,f.getsampwidth()))
        pcm=np.frombuffer(f.readframes(f.getnframes()),dtype='<i2').reshape(-1,f.getnchannels())
    samples=pcm.astype(np.float32).mean(1)/32768.
    if sr!=16000:
        common=int(np.gcd(sr,16000))
        samples=resample_poly(samples,16000//common,sr//common)
    samples=np.pad(samples,(200,200))
    frames=np.lib.stride_tricks.sliding_window_view(samples,400)[::160]*WINDOW
    spectrum=np.square(abs(np.fft.rfft(frames,n=512,axis=1))).astype(np.float32)
    mel=np.log1p(100*spectrum@BANK)
    cuts=np.linspace(0,len(mel),17).astype(int)
    patches=np.stack([mel[a:max(a+1,b)].mean(0) for a,b in zip(cuts,cuts[1:])])
    if not np.isfinite(patches).all():raise ArithmeticError(name)
    return name,patches,sha256(raw).hexdigest(),len(raw)


def images_and_text(source):
    with zipfile.ZipFile(source/'Flickr8k_text.zip') as z:
        words={}
        for line in z.read('Flickr8k.token.txt').decode('utf-8').splitlines():
            path,text=line.split('\t',1); name,idx=path.rsplit('#',1)
            key=(Path(name).stem,int(idx))
            if key in words:raise ValueError(('duplicate caption',key))
            words[key]=re.findall(r"\w+|[^\w\s]",text.lower())
        splits={}
        for split,name in enumerate(('train','dev','test')):
            raw=z.read(f'Flickr_8k.{name}Images.txt').decode('utf-8').splitlines()
            for member in raw:
                stem=Path(member.strip()).stem
                if stem in splits:raise ValueError(('overlapping image name',stem))
                splits[stem]=split
    pixels={};digests={};removed={}
    with zipfile.ZipFile(source/'Flickr8k_Dataset.zip') as z:
        entries={Path(x.filename).stem:x for x in z.infolist()
                 if x.filename.lower().endswith('.jpg') and '__MACOSX/' not in x.filename}
        seen={}
        for key in sorted(splits,key=lambda s:(-splits[s],s)):
            raw=z.read(entries[key]);digest=sha256(raw).hexdigest()
            if digest in seen:
                removed[key]=seen[digest]
                continue
            seen[digest]=key
            pixels[key]=visual_patches(raw);digests[key]=digest
    return words,splits,pixels,digests,removed


def audio(source,out):
    features={};raw_ids={};notes={}
    with tarfile.open(source/'flickr_audio.tar.gz',mode='r|gz') as tar, ProcessPoolExecutor(3) as pool:
        batch=[]
        def consume():
            for name,patch,h,n in pool.map(acoustic_patches,batch,chunksize=8):
                if name in features:raise ValueError(('duplicate recording',name))
                features[name]=patch;raw_ids[name]=(h,n)
            batch.clear()
        for member in tar:
            leaf=Path(member.name).name
            if not member.isfile():continue
            if not leaf.endswith('.wav'):
                if member.size<5_000_000:notes[leaf]=tar.extractfile(member).read()
                continue
            key=Path(leaf).stem
            batch.append((key,tar.extractfile(member).read()))
            if len(batch)==96:
                consume()
                if len(features)%1920==0:print('audio',len(features),flush=True)
        if batch:consume()
    (out/'upstream-audio-readme.txt').write_bytes(notes.get('readme.txt',b''))
    # Raw identifiers are retained separately as an authenticated derived index.
    return features,raw_ids,sorted(notes)


def assign(x,centers):
    lab=[]
    for batch in np.array_split(x,max(1,(len(x)+2047)//2048)):
        cost=(centers*centers).sum(1)-2*batch@centers.T
        lab.append(cost.argmin(1))
    return np.concatenate(lab)


def quantize(values,training,seed):
    train=values[training].reshape(-1,values.shape[-1])
    rng=np.random.default_rng(seed)
    chosen=rng.choice(len(train),min(60000,len(train)),replace=False)
    sample=train[chosen].copy()
    mean=sample.mean(0);std=np.maximum(sample.std(0),1e-4)
    sample=(sample-mean)/std
    center=sample[rng.choice(len(sample),64,replace=False)].copy()
    for _ in range(16):
        labels=assign(sample,center)
        for k in range(64):
            group=sample[labels==k]
            if len(group):center[k]=group.mean(0)
    all_values=(values.reshape(-1,values.shape[-1])-mean)/std
    ids=assign(all_values,center).reshape(values.shape[:2]).astype('uint8')
    return ids,dict(mean=mean,std=std,centers=center),np.bincount(ids[training].ravel(),minlength=64).tolist()


def build(source,out):
    started=time.time();out.mkdir(parents=True,exist_ok=True)
    words,splits,pixels,image_sha,removed=images_and_text(source)
    sounds,audio_ids,notes=audio(source,out)
    photos=sorted(pixels)
    photo_index={p:i for i,p in enumerate(photos)}
    keys=sorted((p,k) for p,k in words if p in pixels and f'{p}_{k}' in sounds)
    audio_names=[f'{p}_{k}' for p,k in keys]
    split=np.asarray([splits[p] for p,k in keys],dtype=np.int8)
    photo_split=np.asarray([splits[p] for p in photos])
    if set(split)!={0,1,2}:raise ValueError('missing split')
    vis,vis_book,vis_counts=quantize(np.stack([pixels[p] for p in photos]),photo_split==0,137)
    aud,aud_book,aud_counts=quantize(np.stack([sounds[a] for a in audio_names]),split==0,311)
    counts=Counter(w for k,s in zip(keys,split) if s==0 for w in words[k])
    vocab=['<pad>','<end>','<unknown>']+[w for w,n in sorted(counts.items(),key=lambda t:(-t[1],t[0]))
                                          if n>=3][:4093]
    to_id={w:i for i,w in enumerate(vocab)}
    txt=np.zeros((len(keys),48),dtype=np.int16)
    lengths=np.zeros(len(keys),dtype=np.int16)
    clipped=np.zeros(len(keys),dtype=np.int8)
    for i,k in enumerate(keys):
        seq=[to_id.get(w,2) for w in words[k]]
        if len(seq)>47:clipped[i]=1
        seq=seq[:47]+[1];lengths[i]=len(seq);txt[i,:len(seq)]=seq
    output=out/'codes.npz'
    np.savez_compressed(output,visual=vis,audio=aud,words=txt,word_length=lengths,split=split,
                        photo_index=np.asarray([photo_index[p] for p,k in keys],np.int32),
                        caption_index=np.asarray([k for p,k in keys],np.int8),photo_names=np.asarray(photos),
                        **{'visual_'+k:v for k,v in vis_book.items()},**{'audio_'+k:v for k,v in aud_book.items()})
    with gzip.open(out/'source-identities.json.gz','wt',encoding='utf-8') as f:
        json.dump(dict(pictures=image_sha,audio=audio_ids,matched_audio=audio_names),f)
    receipts={str(j):dict(photos=int((photo_split==j).sum()),utterances=int((split==j).sum()),
                          distinct_descriptions=len({tuple(words[k]) for k,s in zip(keys,split) if s==j}),
                          truncated=int(clipped[split==j].sum()),unknown=int((txt[split==j]==2).sum()),
                          target_words_with_end=int(lengths[split==j].sum())) for j in (0,1,2)}
    files=['Flickr8k_text.zip','Flickr8k_Dataset.zip','flickr_audio.tar.gz']
    meta=dict(utc=time.time(),processing_wall_s=time.time()-started,sources={f:file_hash(source/f) for f in files},
              matched=len(keys),raw_recordings=len(sounds),published_split_photos=len(splits),removed_duplicate_photos=removed,
              unmatched_recordings=len(sounds)-len(keys),unmatched_numbered_texts=len(words)-len(keys),scores_by_split=receipts,
              image_codes_fit_train=vis_counts,audio_codes_fit_train=aud_counts,vocabulary=vocab,
              derived_sha256=file_hash(output),identity_index_sha256=file_hash(out/'source-identities.json.gz'),other_archive_files=notes)
    (out/'dataset.json').write_text(json.dumps(meta,indent=2)+'\n')
    print('joined',len(keys),receipts,meta['derived_sha256'],flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('source',type=Path)
    ap.add_argument('output',type=Path)
    ap.add_argument('--wait',action='store_true')
    args=ap.parse_args()
    if args.wait:
        while not all((args.source/f).is_file() for f in ('source.sha256','flickr_image_text_source.json')):
            time.sleep(30)
    build(args.source,args.output)
