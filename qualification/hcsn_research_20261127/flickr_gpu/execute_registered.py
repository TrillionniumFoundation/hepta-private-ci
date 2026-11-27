"""Run the frozen Flickr caption panel once after the canonical inputs arrive."""
from pathlib import Path
import fcntl,hashlib,json,os,subprocess,sys,time,datetime
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'panel_gpu'
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sh(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def js(p,x):
 t=p.with_name(p.name+'.part'); t.write_text(json.dumps(x,indent=2,sort_keys=True)); t.replace(p)
def main():
 lock=(ROOT/'registered_gpu_panel.lock').open('a+')
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 OUT.mkdir(exist_ok=True)
 end=time.monotonic()+4800
 while not (ROOT/'canonical_check.json').is_file():
  if time.monotonic()>end:raise RuntimeError('No completed canonical data receipt before allocation deadline')
  time.sleep(15)
 receipt=json.loads((ROOT/'canonical_check.json').read_text())
 assert receipt['manifest_equal'] and len(receipt['all_files'])==9 and all(v['match'] for v in receipt['all_files'].values())
 expected=json.loads((ROOT/'CANONICAL_MANIFEST.json').read_text())
 assert (ROOT/'data/manifest.json').read_bytes()==(ROOT/'CANONICAL_MANIFEST.json').read_bytes()
 for part in expected['splits'].values():
  for n,h in part['files'].items():assert sh(ROOT/'data'/n)==h
 import torch
 assert torch.cuda.is_available() and torch.version.hip
 z=torch.ones(16,16,device='cuda')
 assert (z@z).eq(16).all().item()
 env=dict(os.environ,OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',PYTHONUNBUFFERED='1')
 # An existing successful exact-source qualification may be provided by its owner.
 # Otherwise validate the five actual models on this device before any training.
 if not (OUT/'qualification.json').is_file():
  r=subprocess.run([sys.executable,str(ROOT/'qualify.py'),'--device','cuda'],cwd=ROOT,env=env,capture_output=True,text=True)
  (OUT/'qualification.stderr').write_text(r.stderr)
  if r.returncode:raise RuntimeError('Original ROCm model qualification failed: '+r.stderr[-800:])
  q=json.loads(r.stdout);assert q['causality']=='exact-prefix' and len(q['arms'])==5 and q['device']=='cuda'
  js(OUT/'qualification.json',q)
 rr=dict(started=now(),device=torch.cuda.get_device_name(0),torch=str(torch.__version__),hip=torch.version.hip,
         canonical_manifest=sh(ROOT/'data/manifest.json'),source={k:sh(ROOT/k) for k in ['model.py','panel.py','parent_cell.py','prepare.py','PROTOCOL.md','SOURCE_AMENDMENT.md','qualify.py']},script=sh(Path(__file__)))
 js(OUT/'launch.json',rr)
 command=[sys.executable,str(ROOT/'panel.py'),'fit','--data',str(ROOT/'data'),'--out',str(OUT),'--device','cuda','--threads','1']
 status=OUT/'driver.jsonl'
 with (OUT/'driver.stdout').open('a') as a,(OUT/'driver.stderr').open('a') as b:
  start=time.monotonic()
  ret=subprocess.call(command,cwd=ROOT,env=env,stdout=a,stderr=b)
 with status.open('a') as f:f.write(json.dumps(dict(ended=now(),phase='complete_protocol',returncode=ret,wall_seconds=time.monotonic()-start))+'\n')
 if ret:raise SystemExit(ret)
 subprocess.run([sys.executable,str(ROOT/'quality_time.py'),str(ROOT/'data'),str(OUT),str(OUT/'matched_quality.json')],cwd=ROOT,env=env,check=True)
 assert len(list(OUT.glob('*/cold.json')))==15
 js(OUT/'completion.json',dict(completed=now(),seal=sh(OUT/'seal.json'),raw={str(p.relative_to(OUT)):sh(p) for p in OUT.glob('*/cold.npz')}))
if __name__=='__main__':main()
