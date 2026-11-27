from pathlib import Path
import fcntl,hashlib,json,shutil,time,os,datetime
r=Path.cwd();d=Path.home()/'.local'/'share'/'hepta-research'/'hcsn-flickr8k-c511-9c415';d.mkdir(parents=True,exist_ok=True)
lock=(d/'backup.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
obj=d/'objects';obj.mkdir(exist_ok=True); st=d/'snapshots';st.mkdir(exist_ok=True)
def sha(x):
 with x.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def copy(x,h=None):
 h=sha(x) if h is None else h;y=obj/h
 if not y.exists():
  t=obj/(h+'.part');shutil.copyfile(x,t)
  if sha(t)!=h:t.unlink();return None
  t.replace(y)
 assert sha(y)==h
 return {'sha256':h,'bytes':y.stat().st_size,'file':str(y)}
def snap(n,b,fit,sel,res):
 target=st/f'{n}-{b:04d}.json'
 if target.exists():return
 q=fit.read_bytes();j=json.loads(q)
 if j['checkpoints'][-1]['nominal_s']!=b:return
 if sel.stat().st_mtime_ns>fit.stat().st_mtime_ns or res.stat().st_mtime_ns>fit.stat().st_mtime_ns:return
 a=copy(sel);z=copy(res);f=copy(fit)
 if not a or not z or not f or fit.read_bytes()!=q:return
 receipt={'cell':n,'budget':b,'steps':j['steps'],'best_step':j['best_step'],'fit':f,'selected':a,'resume':z,'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
 tmp=target.with_suffix('.part');tmp.write_text(json.dumps(receipt,sort_keys=True));tmp.replace(target)
names=[f'{a}-{s}' for a in ['hcsn','smooth','lif','mean','dense'] for s in [17011,24203,39827]]
end=time.monotonic()+45000
stages=(120,420,720,1020,1320,1620,1920,2220,2520)
while time.monotonic()<end:
 for n in names:
  p=r/'panel_gpu'/n;fit=p/'fit.json';j=json.loads(fit.read_bytes());b=j['checkpoints'][-1]['nominal_s']
  if b in stages:snap(n,b,fit,p/'selected.pt',p/'resume.pt')
 if all((st/f'{n}-2520.json').is_file() for n in names):break
 time.sleep(5)
assert all((st/f'{n}-2520.json').is_file() for n in names)
records={n:json.loads((st/f'{n}-2520.json').read_text()) for n in names}
(d/'final_manifest.json').write_text(json.dumps({'states':records,'scientific_job':'dpty-571841018c706229a3c2902dd3ba97d265d3a166545af72c134d20215f083deb','source':'c511a75b04eb24719f9d5e424d190b071c78f261','dataset':sha(r/'data/manifest.json')},sort_keys=True,indent=2))
print('persisted and validated 15 selected weights and 15 optimizer/sampler/device checkpoints',flush=True)
