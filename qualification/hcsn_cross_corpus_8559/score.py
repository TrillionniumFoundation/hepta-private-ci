"""Per-photo cross-modal retrieval under caption equivalences and exact ties."""
import numpy as np


def metrics(sim,groups):
    n=len(sim);assert sim.shape==(n,n)
    out=[]
    for s in (sim,sim.T):
        pair=[];exact=[];equiv=[];gap=[]
        for j,row in enumerate(s):
            positives=groups==groups[j];negative=row[~positives]
            val=row[j]
            pair.append((np.sum(val>negative)+.5*np.sum(val==negative))/len(negative))
            gap.append(val-negative.mean())
            ties=row==row.max()
            exact.append(float(ties[j])/ties.sum())
            equiv.append(np.sum(ties & positives)/ties.sum())
        out.append(np.stack((pair,exact,equiv,gap),axis=1))
    return np.asarray(out).transpose(1,0,2)


def score_embeddings(img,txt,grp):
    return metrics(img@txt.T,grp)
