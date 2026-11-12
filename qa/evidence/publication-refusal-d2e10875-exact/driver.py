from pathlib import Path
import datetime,hashlib,json,subprocess,sys,time,tomllib
root=Path('/workspace/scratch/ff41dfc0f7bf/hepta-historical-read-cloud')
out=Path('/workspace/scratch/ff41dfc0f7bf/local-validation/publication-refusal-d2e10875')
def snap():
    head=subprocess.check_output(['git','rev-parse','HEAD','HEAD^{tree}'],cwd=root,text=True).splitlines()
    status=subprocess.check_output(['git','status','--porcelain'],cwd=root,text=True)
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=root).split(b'\0')
    h=hashlib.sha256();count=0
    for path in paths:
        if not path:continue
        f=root/path.decode()
        if f.is_file() and (f.suffix in ('.rs','.py','.toml','.yml','.yaml') or f.name=='.github/blob-size-allowlist.txt'):
            h.update(path+b'\0'+hashlib.sha256(f.read_bytes()).digest()); count+=1
    return dict(head=head[0],tree=head[1],status=status,source_files=count,source_digest=h.hexdigest())
before=snap();start=time.time()
commands=[]
command=[sys.executable,'-m','unittest','discover','-s','qa/b4-no-bypass','-p','*source_closure.py','-v']
with (out/'source-qa.log').open('w') as log:
    proc=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT)
commands.append(dict(command=command,exit_code=proc.returncode))
sys.path.insert(0,str(root/'qa/b4-no-bypass'))
import test_historical_task_read_source_closure as route
manifest=tomllib.loads((root/'CALLERS.toml').read_text())
result={}
try:
    boundaries=route.PROOF._boundary_rows(manifest)
    inventory=route.PROOF._verify_privileged_inventory(manifest,boundaries)
    protected=route.PROOF._verify_protected_files(root,manifest)
    result=dict(status='PASS',inventory=len(inventory),protected=len(protected))
except Exception as exc:
    result=dict(status='FAIL',error=f'{type(exc).__name__}: {exc}')
after=snap()
record=dict(before=before,after=after,started_utc=datetime.datetime.fromtimestamp(start,datetime.timezone.utc).isoformat(),duration_seconds=time.time()-start,commands=commands,markers=result,exact_source=before==after and not after['status'],native='NOT_RUN',full_caller='NOT_RUN')
(out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2),flush=True)
sys.exit(0 if proc.returncode==0 and result.get('status')=='PASS' and record['exact_source'] else 1)
