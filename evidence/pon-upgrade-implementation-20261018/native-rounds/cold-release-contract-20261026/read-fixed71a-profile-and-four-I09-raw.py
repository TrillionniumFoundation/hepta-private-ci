import os,stat,json,hashlib,subprocess,datetime
from pathlib import Path
base=Path('/home/qian-qi/Documents/Codex/2026-10-22/github-trillionnium-chain-https-github-com/work');repo=base/'hepta-windows-portable-tools-20261024';H='71a8850fb30e57c77ff58dc08cb6cc78f53ad1c8'
env=dict(os.environ,GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0')
out={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'read_only':True,'hepta_source_commit':H,'sources':[],'fixed_I09_raw':[]}
for path in ['codex-rs/hepta-infer-worker-host/src/smollm_neural_profile.rs','codex-rs/hepta-infer-worker-host/src/smollm_cell_wire.rs']:
 r=subprocess.run(['git','-c','core.fsmonitor=false','-C',str(repo),'show',H+':'+path],capture_output=True,timeout=8,env=env);assert r.returncode==0 and len(r.stdout)<=65536
 out['sources'].append({'path':path,'bytes':len(r.stdout),'sha256':hashlib.sha256(r.stdout).hexdigest(),'git_blob':hashlib.sha1(b'blob '+str(len(r.stdout)).encode()+b'\0'+r.stdout).hexdigest(),'content':r.stdout.decode()})
rawroot=base/'root-i09-eleven-material-native-positive-preparation-20261026-002'
for name in ['11-actual-run-full-raw-manifest.json','12-actual-I09-result-and-limits.json','13-execution-material-manifest.json','14-actual-execution-final-freeze.json']:
 p=rawroot/name;fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  a=os.fstat(fd);assert stat.S_ISREG(a.st_mode) and a.st_size<=131072
  raw=b''
  while True:
   b=os.read(fd,16384)
   if not b:break
   raw+=b;assert len(raw)<=131072
  z=os.fstat(fd);assert (a.st_dev,a.st_ino,a.st_size,a.st_mtime_ns)==(z.st_dev,z.st_ino,z.st_size,z.st_mtime_ns)
 finally:os.close(fd)
 out['fixed_I09_raw'].append({'path':str(p),'name':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'regular_nofollow_stable':True,'content':raw.decode()})
out['finished_utc']=datetime.datetime.now(datetime.timezone.utc).isoformat()
print(json.dumps(out,ensure_ascii=False,sort_keys=True))

