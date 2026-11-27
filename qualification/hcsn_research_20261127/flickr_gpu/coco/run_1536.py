from pathlib import Path
import json,os,time,sys,hashlib,subprocess,resource,fcntl,datetime
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'coco1536';BASE.mkdir(exist_ok=True)
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def snapshot(p,x):
 t=p.with_suffix('.part');t.write_text(json.dumps(x,indent=2,sort_keys=True));t.replace(p)
lock=(BASE/'worker.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
src=json.loads((ROOT/'pinned_coco_sources.json').read_text())
checkout=BASE/'repo'
for name,entry in src.items():
 b=entry['content'].encode('utf8')
 assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==entry['git_blob']
 target=checkout/name;target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists(): assert target.read_bytes()==b
 else:target.write_bytes(b)
study=checkout/'qualification/hcsn_research_20261127/root/raw_train.py'
arms=['physical','smooth','gru','lif','attention','linear','rawcca','randomphysical','randomgru'];seeds=[27,117,207]
protocol={'source_commit':'cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0','source_files':{n:p['git_blob'] for n,p in src.items()},'arms':arms,'seeds':seeds,'steps':1536,'host':'ai395 CPU single thread','development_checkpoints':list(range(0,1537,192)),'readout_regularization':[.001,.01,.1,1.],'gallery_source':'historically used 384 fixed COCO images','selection':'mean development R1 over three declared seeds to nominate conventional comparator','test':'joint fit seal, cold ranking, cluster photos in fixed gallery','resource':'whole cold child elapsed/process user+system, method limits recorded separately','code_sha256':sha(Path(__file__))}
if (BASE/'protocol.json').exists():assert json.loads((BASE/'protocol.json').read_text())==protocol
else:snapshot(BASE/'protocol.json',protocol)
deadline=time.monotonic()+7200;ready=ROOT/'coco_restored/verification.json'
while not ready.is_file():
 if time.monotonic()>deadline:raise RuntimeError('canonical input receipt not available')
 time.sleep(15)
inputs=ROOT/'coco_restored/inputs';remote=json.loads((ROOT/'coco_input_manifest.json').read_text())
for split in ['train','val','test']:assert sha(inputs/(split+'.npz'))==remote[split]['sha256']
env=dict(os.environ,OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',PYTHONPATH=str(checkout),PYTHONUNBUFFERED='1')
base=BASE/'results';base.mkdir(exist_ok=True);events=BASE/'operations.jsonl'
for phase in ['fit','test']:
 if phase=='test':
  roster={a+'-'+str(s):sha(base/(a+'-'+str(s))/'selected.pt') for s in seeds for a in arms}
  seal={'states':roster,'source':protocol['source_commit'],'protocol':sha(BASE/'protocol.json')}
  if (base/'seal.json').exists():assert json.loads((base/'seal.json').read_text())==seal
  else:snapshot(base/'seal.json',seal)
 for i,seed in enumerate(seeds):
  for arm in arms[i:]+arms[:i]:
   job=base/(arm+'-'+str(seed));done=job/(phase+'.json')
   if done.exists():
    j=json.loads(done.read_text());key='state_sha256' if phase=='fit' else 'ranks_sha256';nm='selected.pt' if phase=='fit' else 'ranks.npz';assert j[key]==sha(job/nm);continue
   cmd=[sys.executable,str(study),phase,arm,str(seed),'--steps','1536','--inputs',str(inputs),'--out',str(base)]
   start=time.monotonic();pre=resource.getrusage(resource.RUSAGE_CHILDREN)
   with (BASE/'worker.log').open('a') as f:ret=subprocess.call(cmd,env=env,cwd=checkout,stdout=f,stderr=subprocess.STDOUT)
   after=resource.getrusage(resource.RUSAGE_CHILDREN)
   with events.open('a') as f:f.write(json.dumps(dict(completed=datetime.datetime.now(datetime.timezone.utc).isoformat(),phase=phase,arm=arm,seed=seed,wall_seconds=time.monotonic()-start,cpu_seconds=after.ru_utime+after.ru_stime-pre.ru_utime-pre.ru_stime,returncode=ret))+'\n')
   if ret:raise RuntimeError((phase,arm,seed,ret))
import numpy as np
res={};vectors={}
for arm in arms:
 rows=[];hits=[]
 for seed in seeds:
  p=base/f'{arm}-{seed}';tr=json.loads((p/'fit.json').read_text());ts=json.loads((p/'test.json').read_text())
  with np.load(p/'ranks.npz') as z:
   ir=z['image'];ar=z['caption'];ow=z['owner'];c=np.bincount(ow,minlength=len(ir));v=np.bincount(ow,weights=ar==1,minlength=len(ir));hits.append((ir==1,v))
  rows.append({'seed':seed,'best_dev':max(h['bidir_r1'] for h in tr['history']),'test':ts['metrics']['bidir_r1'],'selected':tr['selected'],'fit_cold_s':tr['cold_elapsed_seconds'],'test_cold_s':ts['cold_elapsed_seconds']})
 res[arm]={'rows':rows,'dev':np.mean([r['best_dev'] for r in rows]),'test':np.mean([r['test'] for r in rows])}
 vectors[arm]=np.mean([h[0] for h in hits],0),np.mean([h[1] for h in hits],0)
best=max((a for a in arms if a not in ['physical','randomphysical']),key=lambda a:res[a]['dev'])
rng=np.random.default_rng(113527);Q=rng.integers(len(c),size=(4000,len(c)))
for arm in arms:
 a,b=vectors['physical'];u,v=vectors[arm];d=.5*((a-u)[Q].mean(1)+(b-v)[Q].sum(1)/c[Q].sum(1))
 res[arm]['paired_physical_minus_95']=np.quantile(d,[.025,.975]).tolist()
snapshot(BASE/'summary.json',dict(arms=res,dev_comparator=best,images=len(c),captions=int(c.sum()),seals=sha(base/'seal.json')))
print('completed 1536-step roster',flush=True)
