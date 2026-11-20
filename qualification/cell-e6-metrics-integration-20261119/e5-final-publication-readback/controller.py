import base64,gzip,hashlib,json,os,signal,subprocess,time
from pathlib import Path
root=Path('/home/qian-qi/work/hepta-e5-final-verification-20261120-e9e051')
source=root/'source'
out=root/'root-final-policy-1';out.mkdir(exist_ok=False)
head='78eb0dfdb28563f2527aa1cfc27f9b40997f70ea'
tree='551a7a9122037050d0d7b98880eebac80d69a8f3'
base='e4b4eb5028578be87d5cad0829103632f2bff3a3'
def sha(b): return hashlib.sha256(b).hexdigest()
def git(*a):
 return subprocess.check_output(['git',*a],cwd=source)
tracked=['scripts/check_blob_size.py','.github/blob-size-allowlist.txt']
before={'head':git('rev-parse','HEAD').decode().strip(),'refs_sha256':sha(git('show-ref')),'config_sha256':sha(git('config','--local','--list','--show-origin')),'index_entries_sha256':sha(git('ls-files','-s')),'gate_sha256':{p:sha((source/p).read_bytes()) for p in tracked}}
intent={'schema':'hepta.e5.final-evidence-head-original-blob-gate.v1','tested_head':head,'tested_tree':tree,'base':base,'checkout_head':before['head'],'maximum_bytes':512000,'expected_pack_sha256':'09e60fa88a5e8fddea442b47067538aaa8af3562687fffed3846d29786a6fefd','new_model_calls':0,'new_training_updates':0,'new_native_task_children':0,'before':before}
(out/'INTENT.json').write_text(json.dumps(intent,indent=2)+'\n')
stages=[]
def run(name,args,timeout):
 start=time.monotonic();p=subprocess.Popen(args,cwd=source,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
 expired=False
 try: stdout,stderr=p.communicate(timeout=timeout)
 except subprocess.TimeoutExpired:
  expired=True;os.killpg(p.pid,signal.SIGTERM)
  try: stdout,stderr=p.communicate(timeout=5)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGKILL);stdout,stderr=p.communicate()
 (out/(name+'.stdout')).write_bytes(stdout);(out/(name+'.stderr')).write_bytes(stderr)
 r={'name':name,'argv':args,'exit_code':p.returncode,'timed_out':expired,'wall_seconds':time.monotonic()-start,'stdout_bytes':len(stdout),'stdout_sha256':sha(stdout),'stderr_bytes':len(stderr),'stderr_sha256':sha(stderr)}
 stages.append(r);(out/(name+'.EXIT.json')).write_text(json.dumps(r,indent=2)+'\n')
 assert p.returncode==0 and not expired,(name,p.returncode)
 return stdout
error=None
start=time.monotonic()
try:
 raw=(root/'root-final-policy-1.objects.json.gz').read_bytes();assert sha(raw)==intent['expected_pack_sha256']
 rows=json.loads(gzip.decompress(raw))['files'];assert len(rows)==35
 for row in rows:
  b=base64.b64decode(row['data'],validate=True);assert len(b)==row['bytes'] and sha(b)==row['sha256'] and len(b)<=512000
  got=subprocess.check_output(['git','hash-object','-w','--stdin'],cwd=source,input=b).decode().strip();assert got==row['sha']
 run('fetch-final-tree',['git','fetch','--no-tags','--no-write-fetch-head','--filter=blob:none','origin',head],30)
 assert git('rev-parse',head+'^{tree}').decode().strip()==tree
 output=run('original-full-pr-blob-gate',['/usr/bin/python3','scripts/check_blob_size.py','--base',base,'--head',head,'--max-bytes','512000','--allowlist','.github/blob-size-allowlist.txt'],120)
 intent['stdout_first_line']=output.decode().splitlines()[:1]
except Exception as exc:
 error=repr(exc)
after={'head':git('rev-parse','HEAD').decode().strip(),'refs_sha256':sha(git('show-ref')),'config_sha256':sha(git('config','--local','--list','--show-origin')),'index_entries_sha256':sha(git('ls-files','-s')),'gate_sha256':{p:sha((source/p).read_bytes()) for p in tracked}}
result={**intent,'after':after,'repository_identity_unchanged':before==after,'stages':stages,'wall_seconds':time.monotonic()-start,'error':error,'exit_code':0 if error is None and before==after else 1}
(out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'result':str(out/'RESULT.json'),'exit_code':result['exit_code'],'result_sha256':sha((out/'RESULT.json').read_bytes()),'stdout_first_line':result.get('stdout_first_line'),'error':error}))
raise SystemExit(result['exit_code'])
