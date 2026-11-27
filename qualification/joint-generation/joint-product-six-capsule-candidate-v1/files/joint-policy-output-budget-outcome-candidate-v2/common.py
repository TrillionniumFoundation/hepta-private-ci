import os,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent;WS=ROOT.parent;OUT=ROOT/'RUN_ONCE';FOLDER=OUT/'chain';SESSION=FOLDER/'delivery'
def canonical(x):return json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False).encode('ascii')
def sha(b):return hashlib.sha256(b).hexdigest()
FREEZE=sha((ROOT/'FREEZE.json').read_bytes());CFG=json.loads((ROOT/'INPUTS.json').read_bytes())
def read(k):
 r=CFG['inputs'][k];b=(WS/r['path']).read_bytes()
 if len(b)!=r['bytes']or sha(b)!=r['sha256']:raise ValueError('frozen input '+k)
 return b
def all_inputs():
 for k in CFG['inputs']:read(k)
def expected():
 a=json.loads(read('old_artifact'));a['source_freeze']=FREEZE;artifact=sha(canonical(a))
 request=json.loads(read('old_request'));request['artifact_sha256']=artifact;request['run_id']=CFG['new_run_id'];request['deadline_ns']=json.loads((FOLDER/'CLOCK.json').read_bytes())['deadline_ns']
 return a,artifact,canonical(request)
def write(name,value,raw=False):
 b=value if raw else canonical(value);p=FOLDER/name;temp=FOLDER/(name+'.tmp')
 with temp.open('xb')as f:f.write(b);f.flush();os.fsync(f.fileno())
 try:os.link(temp,p)
 finally:temp.unlink()
 return {'name':name,'bytes':len(b),'sha256':sha(b)}
def file_ref(p):
 b=p.read_bytes();return {'bytes':len(b),'sha256':sha(b)}
def inst(p):
 s=os.stat(p,follow_symlinks=False);return [s.st_dev,s.st_ino]
def inventory():return {str(p.relative_to(SESSION)):file_ref(p)for p in sorted(SESSION.rglob('*'))if p.is_file()}
def case_expected(name):
 if name not in ('known','uncommitted'):raise ValueError('fixed case')
 payload,artifact,raw=expected();v=json.loads(raw);v['run_id']+='-'+name;v['budget']['output_bytes']=34807
 return payload,artifact,canonical(v)
def case_manifest(name):
 b=(FOLDER/'MANIFESTS.json').read_bytes()
 if sha(b)!=os.environ['MANIFESTS_PIN']:raise ValueError('external manifests pin')
 v=json.loads(b)[name];return v,sha(canonical(v))
