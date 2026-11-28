"""Descriptive follow-up: discriminate emotions within each RAVDESS actor; no fitted calibration."""
from pathlib import Path
import json,hashlib
import numpy as np
import sys

def statistics(raw,y,a):
 z=raw.astype('float64');z-=z.max(1,keepdims=True);prob=np.exp(z);prob/=prob.sum(1,keepdims=True)
 ar=[];cb=[]
 for who in range(1,25):
  rows=a==who;labels=y[rows];p=prob[rows]
  cls=[]
  for i in range(6):
   diff=p[labels==i,i,None]-p[labels!=i,i][None,:]
   cls.append(np.mean((diff>0)+.5*(diff==0)))
  pred=p.argmax(1);target=np.eye(6)[labels]
  brier=float(np.mean(np.sum((p-target)**2,1)))
  conf=p.max(1).mean();hit=np.mean(pred==labels)
  ar.append([float(np.mean(cls)),brier,conf-hit,conf,hit])
 return np.array(ar)

def run(root,out):
 results={}
 columns=['macro_ovr_auc_within_actor','multiclass_brier','mean_confidence_minus_accuracy','mean_confidence','accuracy']
 ix=np.random.default_rng(413126).integers(24,size=(4000,24))
 for family in ('full','analytic'):
  sub=root/('scores-'+family);t=json.loads((sub/'terminal.json').read_text());groups={}
  for name,rec in t['models'].items():
   path=sub/(name+'.npz')
   if hashlib.sha256(path.read_bytes()).hexdigest()!=rec['external_scores_sha256']:raise ValueError('wrong scores')
   with np.load(path) as d:
    y=d['labels'];a=np.array([int(k.rsplit('-',1)[1]) for k in d['ids']])
    arm,tag,seed=name.rsplit('-',2);groups.setdefault(arm+'-'+tag,[]).append(statistics(d['emotion_logits'],y,a))
  mean={n:np.mean(x,axis=0) for n,x in groups.items()}
  stats={}
  for n,x in mean.items():
   tag=n.rsplit('-',1)[1];ref=('same_site_bp' if family=='full' else 'sdpa')+'-'+tag
   d=x-mean[ref];dist=d[ix].mean(1);bounds=np.quantile(dist,[.025,.975],axis=0)
   stats[n]=dict(means=dict(zip(columns,x.mean(0).tolist())),reference=ref,
                 differences={k:[float(d[:,i].mean()),*bounds[:,i].tolist()] for i,k in enumerate(columns)},
                 actor_means=x.tolist())
  with np.load(sub/'controls.npz') as d:
   ctrl={n:dict(zip(columns,statistics(d[n],y,a).mean(0).tolist())) for n in ('ridge','uniform','class_prior')}
  results[family]={'methods':stats,'controls':ctrl,'sorted_actors':list(range(1,25))}
 out.write_text(json.dumps(results,indent=1)+'\n')
 print(json.dumps({f:{n:[v['means']['macro_ovr_auc_within_actor'],v['differences']['macro_ovr_auc_within_actor'],v['differences']['multiclass_brier']] for n,v in q['methods'].items()} for f,q in results.items()}))
if __name__=='__main__':run(Path(sys.argv[1]),Path(sys.argv[2]))
