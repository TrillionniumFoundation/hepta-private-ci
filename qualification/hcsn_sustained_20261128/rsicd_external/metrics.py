"""Corpus BLEU-4, COCO-style ROUGE-L and CIDEr-D on tokenized human reference lists."""
from collections import Counter
import math

import numpy as np


def counts(tokens,n):
    return Counter(tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1))


def lcs(x,y):
    last=[0]*(len(y)+1)
    for t in x:
        line=[0]
        for j,s in enumerate(y):
            line.append(last[j]+1 if t==s else max(last[j+1],line[-1]))
        last=line
    return last[-1]


class CaptionMetrics:
    def __init__(self,references):
        self.refs=references
        self.df=Counter()
        for group in references:
            grams=set()
            for ref in group:
                for n in range(1,5):grams.update(counts(ref,n))
            self.df.update(grams)
        self.n=len(references)
        self.cider_refs=[[self.vector(r) for r in group] for group in references]
        self.maximum=[]
        for group in references:
            table=[]
            for n in range(1,5):
                ref=Counter()
                for item in group:ref|=counts(item,n)
                table.append(ref)
            self.maximum.append(table)

    def vector(self,tokens):
        weighted=[]
        for n in range(1,5):
            grams={g:c*math.log(self.n/max(1,self.df[g])) for g,c in counts(tokens,n).items()}
            norm=math.sqrt(sum(v*v for v in grams.values()))
            weighted.append((grams,norm))
        return weighted,max(0,len(tokens)-1)

    def cider(self,candidate,refs):
        hv,hlen=self.vector(candidate);scores=[]
        for rv,rlen in refs:
            score=0.
            for (x,nx),(y,ny) in zip(hv,rv):
                if nx and ny:
                    score+=sum(min(w,y.get(g,0))*y.get(g,0) for g,w in x.items())/(nx*ny)
            scores.append((score/4)*math.exp(-((hlen-rlen)**2)/72)*10.)
        return sum(scores)/len(scores)

    def evaluate(self,pred):
        if len(pred)!=len(self.refs):raise ValueError("image counts")
        clipped=np.zeros((len(pred),4),np.int64);den=np.zeros_like(clipped)
        cand=np.zeros(len(pred),np.int64);reference=np.zeros_like(cand)
        rouge=[];cider=[]
        for i,(hyp,rs) in enumerate(zip(pred,self.refs)):
            cand[i]=len(hyp)
            reference[i]=min([len(v) for v in rs],key=lambda n:(abs(n-len(hyp)),n))
            for j,n in enumerate((1,2,3,4)):
                hs=counts(hyp,n)
                clipped[i,j]=sum((hs&self.maximum[i][j]).values());den[i,j]=sum(hs.values())
            if hyp:
                common=[lcs(hyp,r) for r in rs]
                precision=max(l/len(hyp) for l in common)
                recall=max(l/max(1,len(r)) for l,r in zip(common,rs))
                rouge.append((2.44*precision*recall/(recall+1.44*precision)) if precision*recall else 0.)
            else:rouge.append(0.)
            cider.append(self.cider(hyp,self.cider_refs[i]))
        totals=den.sum(0);matched=clipped.sum(0)
        if np.all(matched>0) and np.all(totals>0) and cand.sum()>0:
            bp=min(1.,math.exp(1.-reference.sum()/cand.sum()))
            bleu=float(bp*np.exp(np.log(matched/totals).mean()))
        else:bleu=0.
        by=dict(rouge_l=np.asarray(rouge),cider_d=np.asarray(cider),clipped=clipped,total_ngrams=den,
                candidate_lengths=cand,reference_lengths=reference)
        gram_summary={}
        for n in (1,2,3,4):
            all_counts=Counter()
            for h in pred:all_counts.update(counts(h,n))
            gram_summary[str(n)]=len(all_counts)/max(1,sum(all_counts.values()))
        summary=dict(bleu4=bleu,rouge_l=float(np.mean(rouge)),cider_d=float(np.mean(cider)),
             unique_captions=len(set(tuple(h) for h in pred)),empty=int((cand==0).sum()),mean_length=float(cand.mean()),
             distinct_ngram_fraction=gram_summary)
        return summary,by
