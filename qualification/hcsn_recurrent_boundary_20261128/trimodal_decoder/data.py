"""Aligned quantized visual, acoustic and transcript streams, with target-free prefixes."""
from hashlib import sha256
import io
import lzma
from pathlib import Path
import numpy as np
import torch

DATA=Path(__file__).resolve().parent.parent/"returning_encoder"/"evidence"/"all.xz"
SHA="c74ae69666a2bf58a8147071dd9aa9fd67e00397966640d937634b0f05a16fd2"
SENTENCES={
 "IEO":"it's eleven o'clock","TIE":"that is exactly what happened","IOM":"i'm on my way to the meeting",
 "IWW":"i wonder what this is about","TAI":"the airplane is almost full","MTI":"maybe tomorrow it will be cold",
 "IWL":"i would like a new alarm clock","ITH":"i think i have a doctor's appointment","DFA":"don't forget a jacket",
 "ITS":"i think i've seen this before","TSI":"the surface is slick","WSI":"we'll stop in a couple of minutes"}
MODES=("visual","audio","text")
PAD=0;EOS=1;TARGET=5;START=33;LENGTH=50


def streams():
    raw=DATA.read_bytes()
    if sha256(raw).hexdigest()!=SHA:raise ValueError("Input digest mismatch")
    with np.load(io.BytesIO(lzma.decompress(raw)),allow_pickle=False) as a:
        p=a["nibbles"];codes=np.stack((p>>4,p&15),-1).reshape(-1,4,8)
        ids=a["ids"].tolist();splits=a["split"].copy()
    sentence=[SENTENCES[k.split("_")[1]].split() for k in ids]
    train_words=sorted({w for i in np.flatnonzero(splits==0) for w in sentence[i]})
    mapping={w:i+38 for i,w in enumerate(train_words)}
    # 16 consecutive target slots and the end token form a 17-slot suffix.
    X=np.zeros((3,len(p),LENGTH),dtype=np.int64)
    Y=np.full((3,len(p),17),-100,dtype=np.int64)
    actors=np.array([k.split("_")[0] for k in ids])
    for i,text in enumerate(sentence):
        seq=(codes[i,:,:4].reshape(-1).astype(int)+6,codes[i,:,4:].reshape(-1).astype(int)+22,
             np.array([mapping[w] for w in text]))
        for k in range(3):
            src=[j for j in range(3) if j!=k]
            X[k,i,0]=2+k
            for segment,j in enumerate(src):
                begin=1+segment*16;X[k,i,begin:begin+len(seq[j])]=seq[j]
            X[k,i,START]=TARGET
            X[k,i,START+1:START+1+len(seq[k])]=seq[k]
            Y[k,i,:len(seq[k])+1]=[*seq[k],EOS]
    split=[np.concatenate([i*len(p)+np.flatnonzero(splits==s) for i in range(3)]) for s in range(3)]
    assert all(len(set(actors[splits==i]) & set(actors[splits==j]))==0 for i,j in [(0,1),(0,2),(1,2)])
    return (torch.from_numpy(X.reshape(-1,LENGTH)),torch.from_numpy(Y.reshape(-1,17)),split,
            np.tile(actors,3),np.repeat(np.arange(3),len(p)),38+len(train_words),mapping)
