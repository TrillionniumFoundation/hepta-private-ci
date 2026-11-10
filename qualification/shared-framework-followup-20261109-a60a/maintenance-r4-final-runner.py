from pathlib import Path
import os,subprocess,json,time,hashlib,sys
base=Path('/home/qq/hepta-shared-framework-f8e4-20261109');task=Path('/home/qq/hepta-framework-followup-a60a-20261110');source=task/'source';record=task/'maintenance-r4-final';record.mkdir(exist_ok=True)
tools=task/'formatter-tools';env=os.environ.copy();env.update(PATH=str(tools/'bin')+':'+str(base/'tools/bin')+':/home/qq/.cargo/bin:'+env.get('PATH',''),RUSTUP_TOOLCHAIN='1.96.0',CARGO_TARGET_DIR=str(base/'target'),TMPDIR='/home/qq/t-a60a4',UV_CACHE_DIR=str(task/'uv-cache'),PIP_CACHE_DIR=str(task/'pip-cache'),CARGO_BUILD_JOBS='2',CARGO_INCREMENTAL='0',PYTHONDONTWRITEBYTECODE='1')
result={'source':'fb1397873bef0eea81efe0c8aac48c56385ffe55','commands':[],'complete':False}
def save():(record/'progress.json').write_text(json.dumps(result,indent=2)+'\n')
def run(name,args,cwd=None):
 t=time.time()
 with (record/(name+'.log')).open('wb') as log:p=subprocess.run(args,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=600)
 r={'name':name,'argv':args,'exit_code':p.returncode,'wall_seconds':time.time()-t};result['commands'].append(r);save();print(json.dumps(r),flush=True)
 if p.returncode:sys.exit(p.returncode)
save();(record/'before-final-format.patch').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=source))
if not (tools/'bin/python').exists():run('venv',['python3','-m','venv',str(tools)])
run('install-uv',[str(tools/'bin/python'),'-m','pip','install','--disable-pip-version-check','uv==0.11.3'])
run('uv-version',['uv','--version'])
run('fmt',['just','fmt','--base','71738345326b98d88b738250d2b84ecbcb466eb8'],source/'codex-rs')
run('diff-check',['git','diff','--check'],source)
patch=subprocess.check_output(['git','diff','--binary'],cwd=source);(record/'maintenance.patch').write_bytes(patch);result['patch_sha256']=hashlib.sha256(patch).hexdigest()
result['changed']=[]
for p in subprocess.check_output(['git','diff','--name-only'],cwd=source,text=True).splitlines():
 b=(source/p).read_bytes();result['changed'].append({'path':p,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()})
result['stat']=subprocess.check_output(['git','diff','--stat'],cwd=source,text=True);result['complete']=True;save();print(json.dumps(result),flush=True)

