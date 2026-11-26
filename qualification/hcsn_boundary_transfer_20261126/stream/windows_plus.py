"""Choose disjoint future-day windows while retaining previous training normalization."""
import csv
from datetime import datetime
import numpy as np
import torch
import run


def disjoint_test(data):
    buckets={}
    for name,digest in run.FILES.items():
        path=data/name
        assert run.sha(path)==digest
        with path.open(newline='') as stream:
            reader=csv.reader(stream)
            next(reader)
            for row in reader:
                date=row[1][:10]
                if '2015-02-08'<date<='2015-02-11':
                    continue
                buckets.setdefault((date,name),[]).append((datetime.fromisoformat(row[1]),row[2:7],int(row[7])))
    initial=run.load_data(data,['train','test'])
    previous=set(initial['test'][2]); previous_train=set(initial['train'][2]); train=[]; control=[]; held=[]
    for (date,name),records in sorted(buckets.items()):
        windows=[]
        for start in range(0,len(records)-7,8):
            chunk=records[start:start+8]
            gaps=[(r[0]-l[0]).total_seconds() for l,r in zip(chunk,chunk[1:])]
            if min(gaps)<58 or max(gaps)>62:
                continue
            obs=[[*(float(x) for x in row[1]),g-60] for row,g in zip(chunk,[60,*gaps])]
            windows.append((chunk[-1][0].isoformat(),date,obs,chunk[-1][2]))
        if date<='2015-02-08':
            train.extend(windows[i] for i in np.linspace(0,len(windows)-1,min(32,len(windows)),dtype=int))
        else:
            control.extend(w for w in windows if w[0] in previous)
            left=[w for w in windows if w[0] not in previous]
            held.extend(left[i] for i in np.linspace(0,len(left)-1,min(32,len(left)),dtype=int))
    assert previous_train=={w[0] for w in train}
    assert previous=={w[0] for w in control}
    assert previous.isdisjoint(w[0] for w in held)
    tx=np.asarray([w[2] for w in train]); mean=tx.mean(axis=(0,1)); std=tx.std(axis=(0,1)).clip(1e-6)
    def convert(windows):
        values=((np.asarray([r[2] for r in windows])-mean)/std).clip(-6,6).astype('float32')
        return torch.from_numpy(values).transpose(0,1),torch.tensor([r[3] for r in windows]),[r[0] for r in windows],[r[1] for r in windows]
    for rows,key in [(train,'train'),(control,'test')]:
        current=convert(rows)
        assert torch.equal(current[0],initial[key][0]) and torch.equal(current[1],initial[key][1]) and current[2:]==initial[key][2:]
    return convert(held)
