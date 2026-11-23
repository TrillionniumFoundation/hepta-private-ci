"""Native 50-Hz source segmentation, subject-held-out classifiers and work roster."""
import hashlib
import json
from pathlib import Path
import re
import zipfile
import numpy as np

HERE=Path(__file__).parent
ARCHIVE='4ac4ae064227c07045a99551876b54d204837e995e298b6488559e209b3deb09'
URL='https://archive.ics.uci.edu/static/public/341/smartphone+based+recognition+of+human+activities+and+postural+transitions.zip'
TEST=[3,6,9,12,15,18,21,24,27,30]; DEV=[2,7,11,16,20,25]; TRAIN=sorted(set(range(1,31))-set(TEST+DEV)); SPLITS={'train':TRAIN,'dev':DEV,'test':TEST}
TRANS={7:(1,0),8:(0,1),9:(0,2),10:(2,0),11:(1,2),12:(2,1)}


def sha(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def write(p,obj):
    payload=json.dumps(obj,separators=(',',':'),allow_nan=False)+'\n'
    with Path(p).open('x') as f:f.write(payload)


def inventory(archive):
    if sha(archive)!=ARCHIVE:raise ValueError('official archive provenance mismatch')
    with zipfile.ZipFile(archive) as z:
        members={}
        for i in z.infolist():
            m=re.fullmatch(r'RawData/(acc|gyro)_exp(\d+)_user(\d+)\.txt',i.filename)
            if m: members[i.filename]=dict(subject=int(m[3]),crc32=f'{i.CRC:08x}',bytes=i.file_size)
    return dict(url=URL,archive_sha=ARCHIVE,protocol_sha=sha(HERE/'protocol.json'),subjects=SPLITS,members=members,
                label_member='RawData/labels.txt',onset_context='annotated motion trigger + benchmark supplied starting posture')


def describe(signal,origin):
    # Each block ends at its decision. History starts at the beginning of the
    # physical pre-onset block used at the zero-time decision.
    blocks=signal[origin-23:origin+121].reshape(6,24,3)
    first=blocks[0].mean(0); rows=[]
    for t,block in enumerate(blocks):
        history=blocks[:t+1].reshape(-1,3); m=block.mean(0)
        rows.append(np.concatenate((m,block.std(0),block[-1]-block[0],block[-1],m-first,
              block[-8:].mean(0)-block[:8].mean(0),np.sqrt(np.mean(np.diff(block,axis=0)**2,0)),
              history.mean(0),np.ptp(history,axis=0))))
    return np.stack(rows)


def extract(archive,split):
    allowed=set(SPLITS[split]); records=[]; omitted=[]; exp={}
    with zipfile.ZipFile(archive) as z:
        with z.open('RawData/labels.txt') as f:
            for line in f:
                fields=line.split(); subject=int(fields[1]);
                if subject not in allowed: continue
                experiment,_,label,start,end=map(int,fields)
                if label in TRANS: exp.setdefault((experiment,subject),[]).append((label,start))
        for (e,subject), events in sorted(exp.items()):
            with z.open(f'RawData/acc_exp{e:02d}_user{subject:02d}.txt') as f: acc=np.loadtxt(f)
            with z.open(f'RawData/gyro_exp{e:02d}_user{subject:02d}.txt') as f: gyro=np.loadtxt(f)
            if acc.shape!=gyro.shape or acc.shape[1]!=3:raise ValueError('mismatched sensors')
            for label,start in events:
                i=start-1; uid=f'subject-{subject:02d}/trial-{e:02d}/sample-{start}'
                if i<23 or i+120>=len(acc): omitted.append(uid);continue
                source,dest=TRANS[label]; target=sorted(set(range(3))-{source}).index(dest)
                records.append((uid,subject,source,target,label,describe(acc,i),describe(gyro,i)))
    keys=('query_id','subject','posture','target','activity','acc','gyro'); out={k:np.asarray(v) for k,v in zip(keys,zip(*records))}
    if sorted(set(out['subject']))!=sorted(allowed) or len(set(out['query_id']))!=len(records):raise ValueError('participant or event missing')
    return out,omitted


def ridge(x,y,sub):
    _,idx,count=np.unique(sub,return_inverse=True,return_counts=True); w=1/count[idx]; w/=w.sum()
    mu=w@x; sd=np.sqrt(w@(x-mu)**2).clip(min=1e-6); a=(x-mu)/sd; b=float(w@y)
    coef=np.linalg.solve((a*w[:,None]).T@a+.10*np.eye(x.shape[1]),(a*w[:,None]).T@(y-b))
    return dict(mu=mu.tolist(),sd=sd.tolist(),coef=coef.tolist(),b=b)


def fit_classifiers(raw,mask):
    sensors={'free':raw['acc'],'paid':np.concatenate((raw['acc'],raw['gyro']),-1)}; models={}
    for name,v in sensors.items():
        models[name]=[]
        for posture in range(3):
            use=mask&(raw['posture']==posture)
            if len(set(raw['target'][use]))!=2:raise ValueError('destination class missing in source fold')
            models[name].append([ridge(v[use,t],raw['target'][use],raw['subject'][use]) for t in range(6)])
    return models


def classify(raw,models):
    out={}
    for name,obs in [('free',raw['acc']),('paid',np.concatenate((raw['acc'],raw['gyro']),-1))]:
        q=np.zeros(obs.shape[:2]);
        for posture in range(3):
            mask=raw['posture']==posture
            for t,m in enumerate(models[name][posture]):
                z=(obs[mask,t]-m['mu'])/m['sd'];q[mask,t]=(z@np.asarray(m['coef'])+m['b']).clip(.001,.999)
        out[name]=np.stack((1-q,q),-1)
    return out


def subset(raw,idx):return {k:v[idx] for k,v in raw.items()}


def frontend(raw,models,loo=False):
    if not loo: scores=classify(raw,models)
    else:
        scores={n:np.zeros((*raw['acc'].shape[:2],2)) for n in ('free','paid')}
        for subject in np.unique(raw['subject']):
            mask=raw['subject']==subject; local=fit_classifiers(raw,~mask); result=classify(subset(raw,mask),local)
            for n,r in result.items():scores[n][mask]=r
    p=scores['free'][:,:,1]; trajectory_shape=p.shape
    onehot=np.repeat(np.eye(3)[raw['posture']][:,None,:],6,axis=1)
    x=np.concatenate((raw['acc'],onehot,p[:,:,None],np.abs(2*p[:,:,None]-1)),2)
    return dict(x=x,scores=scores['free'],read_scores=scores['paid'],target=raw['target'],class_id=raw['activity'],
        dt=np.full(trajectory_shape,.48),query_id=raw['query_id'],source=raw['subject'].astype(str),group=raw['subject'].astype(str),posture=raw['posture'])
