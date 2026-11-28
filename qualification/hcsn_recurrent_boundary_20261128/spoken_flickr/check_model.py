"""Validate the actual decoder, streaming state, loss masking and temporal ordering before using the corpus."""
import tempfile
from pathlib import Path
import numpy as np
import torch

from decoder import Corpus, KINDS, architecture, greedy
from train_threeway import shuffled


def checks():
    rng=np.random.default_rng(147);torch.set_num_threads(1)
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp)/'codes.npz'
        np.savez(p,photo_index=[0,0,1,1,2,2],split=[0,0,1,1,2,2],caption_index=[0,1,0,1,0,1],
                 visual=rng.integers(64,size=(3,16)),audio=rng.integers(64,size=(6,16)),
                 words=rng.integers(2,87,size=(6,48)),word_length=[7,8,12,9,6,5])
        data=Corpus(p,'cpu');results={};inds=np.array([0,5])
        for kind in KINDS:
            model=architecture(87,kind,137)
            worst=0.;zeros=0.
            for mode in range(3):
                x,y,t=data.assemble(inds,mode)
                assert x.shape[1]==82 and y.shape[1] in (16,48)
                full=model(x,mode,t)
                states=[None,None];seq=[]
                for j in range(x.shape[1]):
                    nxt,states=model.step(x[:,j],j,mode,states)
                    if j>=t:seq.append(nxt)
                err=float((torch.stack(seq,1)-full).abs().max().detach())
                if err>1e-4:raise ValueError((kind,mode,err))
                worst=max(worst,err)
                cut=model(x,mode,t,cut=True)
                zeros=max(zeros,float((cut[0]-cut[1]).abs().max().detach()))
                modified=x.clone();modified[:,-3:]=(modified[:,-3:]+1)%86
                torch.testing.assert_close(full[:,:-3],model(modified,mode,t)[:,:-3],atol=1e-5,rtol=1e-5)
                pred=greedy(model,data,inds,mode)
                if pred.shape!=y.shape:raise AssertionError(pred.shape)
            assert zeros==0.
            results[kind]=(model.width,sum(v.numel() for v in model.parameters()),worst)
        groups=shuffled(77,137,2)
        for m in range(3):assert sorted(np.concatenate([s for i,s in groups if i==m]).tolist())==list(range(77))
        print(results)


if __name__=='__main__':checks()
