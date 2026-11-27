"""Reconstruct language-only control and paired grounding strata from sealed per-caption costs."""
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path
import numpy as np


def sentence(row):return tuple(int(x) for x in row if x)


class Language:
    def __init__(self,train,vocab):
        self.uni=Counter();self.bi=defaultdict(Counter);self.tri=defaultdict(Counter)
        self.vocab=vocab
        for sentence_ in train:
            for j in range(1,len(sentence_)):
                w=sentence_[j];prefix=sentence_[j-1];ctx=sentence_[max(0,j-2):j]
                self.uni[w]+=1;self.bi[prefix][w]+=1;self.tri[ctx][w]+=1
        self.n=sum(self.uni.values())
    def costs(self,sents,weights):
        a,b=weights
        result=[]
        for sent in sents:
            total=0.
            for j in range(1,len(sent)):
                w=sent[j];bi=self.bi[sent[j-1]];tri=self.tri[sent[max(0,j-2):j]]
                uni=(self.uni[w]+1)/(self.n+self.vocab-1)
                p2=(bi[w]+6*uni)/(bi.total()+6);p3=(tri[w]+3*p2)/(tri.total()+3)
                total-=np.log(a*p3+b*p2+(1-a-b)*uni)
            result.append(total)
        return np.array(result)


def stats(loss,counts,mask,groups):
    if mask.sum()==0:return None
    vals=(loss*mask).sum(1)
    n=(counts*mask).sum(1);keep=n>0;vals=vals[keep];n=n[keep]
    ids=np.random.default_rng(54701).integers(0,len(n),(4000,len(n)))
    ci=vals[ids].sum(1)/n[ids].sum(1)
    return {'NLL_or_difference':float(vals.sum()/n.sum()),'image_bootstrap':np.quantile(ci,[.025,.975]).tolist(),'images':int(keep.sum()),'captions':int(mask.sum()),'tokens':int(n.sum())}


def main(pack,cold,seal,out):
    with np.load(pack) as raw:
        s=raw['split'];c=raw['captions'];im=raw['images'];v=int(raw['vocab_size'])
    sentences={i:[sentence(x) for x in c[s==i].reshape(-1,c.shape[-1])] for i in (0,1,2)}
    tr=set(sentences[0]);known=np.array([k in tr for k in sentences[2]]).reshape(-1,c.shape[1])
    known_dev=np.array([k in tr for k in sentences[1]])
    old=set(x.tobytes() for x in im[s!=2]);dupe=np.array([x.tobytes() in old for x in im[s==2]])
    strata={'all':np.ones_like(known),'seen_text':known,'new_text':~known,'unique_pixels':np.broadcast_to((~dupe)[:,None],known.shape),'new_text_unique_pixels':~known&(~dupe)[:,None]}
    lang=Language(sentences[0],v);pairs=[(.2,.4),(.5,.3),(.8,.15),(.95,.04)]
    val=[float(lang.costs(sentences[1],p).sum()/sum(len(z)-1 for z in sentences[1])) for p in pairs]
    best=pairs[int(np.argmin(val))];baseline=lang.costs(sentences[2],best).reshape(known.shape)
    se=json.loads(seal.read_text())
    with np.load(cold) as z:
        count=z['tokens'];assert count.shape==known.shape
        assert np.array_equal(count,(c[s==2,:,1:]!=0).sum(-1))
        outp={'dev_duplicate_sentences':[int(known_dev.sum()),len(known_dev)],'quantized_duplicate_cold_photos':int(dupe.sum()),'language_control':{'weights':best,'all_dev_nll':val,'cold':{k:stats(baseline,count,m,None) for k,m in strata.items()}},'size':{}}
        sizes=sorted(set(key.split('-')[0] for key in se['models']))
        for d in sizes:
            models={}
            for arm in ('physical','smooth','mean','dense'):
                ids=[k for k in se['models'] if k.startswith(d+'-') and k.endswith('-'+arm)]
                cost=np.stack([z[k] for k in ids]).mean(0);swap=np.stack([z[k+'-shuffled'] for k in ids]).mean(0)
                models[arm]=(cost,swap)
            outp['size'][d]={}
            for arm,(cost,swap) in models.items():
                outp['size'][d][arm]={k:{'nll':stats(cost,count,m,None),'shuffled_minus_true':stats(swap-cost,count,m,None),'physical_minus_arm':stats(models['physical'][0]-cost,count,m,None)} for k,m in strata.items()}
    out.write_text(json.dumps(outp,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('pack','cold','seal','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();main(a.pack,a.cold,a.seal,a.out)
