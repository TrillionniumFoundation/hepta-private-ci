"""Seed-separated synthetic tasks; no downloaded data and no test-time tuning."""

import hashlib
import numpy as np

INPUT_DIM = 16
OUTPUT_DIM = 4
TASKS = ("memory", "retrieval", "irregular")


def make_data(task, seed, count, length=32, noise=.1, missing=.25):
    rng = np.random.default_rng(seed)
    x = np.zeros((count,length,INPUT_DIM),np.float32)
    dt = np.ones((count,length),np.float32)
    if task == "memory":
        labels = rng.integers(0,4,count)
        symbols = rng.integers(0,4,(count,length))
        symbols[:,0] = labels
        x[np.arange(count)[:,None],np.arange(length)[None,:],symbols] = 1.
        x[:,0,4]=1.
        x[:,-1,:4]=0.
        x[:,-1,5]=1.
        # The first marked symbol must be retained across all distractors.
    elif task == "retrieval":
        labels = np.zeros(count,np.int32)
        for i in range(count):
            keys = rng.choice(8,4,replace=False)
            values = rng.integers(0,4,4)
            positions = np.sort(rng.choice(length-2,4,replace=False))
            x[i,positions,keys]=1.
            x[i,positions,8+values]=1.
            x[i,positions,12]=1.
            query = rng.integers(4)
            x[i,-1,keys[query]]=1.
            x[i,-1,13]=1.
            labels[i]=values[query]
        # All unmarked filler tokens are noninformative Gaussian distractors.
        filler = x[:,:,12]+x[:,:,13] == 0
        x[:,:,:12] += (rng.normal(0,.05,x[:,:,:12].shape)*filler[:,:,None]).astype(np.float32)
    elif task == "irregular":
        dt = np.clip(rng.lognormal(-.25,.8,(count,length)),.05,4.).astype(np.float32)
        clean = rng.normal(0,1,(count,length,2)).astype(np.float32)
        observed = rng.random((count,length)) > missing
        x[:,:,:2] = (clean+rng.normal(0,noise,clean.shape))*observed[:,:,None]
        x[:,:,12] = observed
        state=np.zeros((count,2))
        for t in range(length):
            decay=np.exp(-dt[:,t,None]/4.)
            state=decay*state+(1-decay)*clean[:,t]*observed[:,t,None]
        labels=(state[:,0]>0).astype(np.int32)+2*(state[:,1]>0).astype(np.int32)
    else:
        raise ValueError(task)
    return {"x":x,"dt":dt,"y":np.asarray(labels,np.int32)}


def fingerprint(data):
    h=hashlib.sha256()
    for k in ("x","dt","y"):
        h.update(k.encode()); h.update(data[k].tobytes())
    return h.hexdigest()


def dataset_suite(task, seed, train_count=2048, eval_count=512, length=32):
    base=10000+100*seed
    split = {
        "train": make_data(task,base,train_count,length),
        "validation": make_data(task,base+1,eval_count,length),
        "test": make_data(task,base+2,eval_count,length),
        "long": make_data(task,base+3,eval_count,length*2),
    }
    if task == "irregular":
        split["corrupt"] = make_data(task,base+4,eval_count,length,noise=.35,missing=.5)
    return split
