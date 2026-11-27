"""Serial cold GPU workers with durable state and per-wave pretest seals."""
import subprocess,sys,json,hashlib,os,time,traceback
from pathlib import Path
base=Path(__file__).resolve().parent
plan=json.loads((base/'gpu_protocol.json').read_text());runs=base/'runs';runs.mkdir(exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def emit(p,r):
    tmp=p.with_suffix('.pending');tmp.write_text(json.dumps(r,sort_keys=True,allow_nan=False)+"\n");os.replace(tmp,p)
def event(r):
    with (runs/'ledger.jsonl').open("a") as f:f.write(json.dumps(r,sort_keys=True)+"\n")
    print(json.dumps(r),flush=True)
def work(mode,i,arm):
    folder=runs/f'{i:04}'/arm;folder.mkdir(parents=True,exist_ok=True);receipt=folder/(mode+'-process.json')
    if receipt.exists():return json.loads(receipt.read_text())
    start=time.perf_counter()
    with (folder/(mode+'.log')).open('ab') as f:
        q=subprocess.run([sys.executable,str(base/'gpu_worker.py'),mode,str(i),arm],cwd=base,stdout=f,stderr=f)
    r=dict(mode=mode,idx=i,arm=arm,code=q.returncode,seconds=time.perf_counter()-start)
    emit(receipt,r);event(r);return r
budget=plan['wall_budget_s']
for name,expect in json.loads((base/'gpu_freeze.json').read_text()).items():
    if sha(base/name)!=expect:raise RuntimeError('input drift: '+name)
for i,w in enumerate(plan['waves']):
    folder=runs/f'{i:04}';folder.mkdir(exist_ok=True)
    result={}
    for arm in w['arms']:
        r=work("fit",i,arm);p=folder/arm/'fit.json'
        if r['code']==0 and p.exists():result[arm]=sha(p)
    f=folder/'seal.json'
    if f.exists() and json.loads(f.read_text())!=result:raise ValueError('seal differs')
    if not f.exists():emit(f,result)
    for arm in result:work('confirm',i,arm)
    complete=folder/'wave_complete.json';elapsed=sum(json.loads(p.read_text())['seconds'] for p in runs.glob('*/*/*-process.json'))
    if not complete.exists():emit(complete,dict(w=w,arms_ok=sorted(result),budget_consumed_s=elapsed))
    if elapsed>=budget:break
emit(runs/'complete.json',dict(last_wave=i,worker_seconds=elapsed,plan_sha256=sha(base/'gpu_protocol.json')))
