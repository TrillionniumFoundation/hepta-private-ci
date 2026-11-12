from pathlib import Path
import datetime,hashlib,json,subprocess,sys,time,tomllib,os
root=Path('/workspace/scratch/ff41dfc0f7bf/hepta-historical-read-cloud')
out=Path('/workspace/scratch/ff41dfc0f7bf/local-validation/current-historical-a-163667d6')
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
command=[sys.executable,'-m','unittest','-v','test_current_historical_a_recovery_source_closure','test_root_publication_existing_owner_source_closure']
with (out/'source-qa.log').open('w') as log:
    proc=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':'qa/b4-no-bypass'})
commands.append(dict(command=command,exit_code=proc.returncode))
sys.path.insert(0,str(root/'qa/b4-no-bypass'))
import test_historical_task_read_source_closure as route
manifest=tomllib.loads((root/'CALLERS.toml').read_text())
result={}
try:
    boundaries=route.PROOF._boundary_rows(manifest)
    inventory=route.PROOF._verify_privileged_inventory(manifest,boundaries)
    selected=[row for row in boundaries if row.identifier.startswith('root_current_historical_') or row.identifier=='q24_current_historical_recover']
    paths={row.definition_path for row in selected}
    paths.add('codex-rs/hepta-agentd/src/cell_q24_publication_driver.rs')
    protected=route.PROOF._verify_protected_files(root,{'protected_file':[row for row in manifest['protected_file'] if row['path'] in paths]})
    result=dict(status='PASS',inventory=len(inventory),selected_protected=len(protected),selected_boundaries=[row.identifier for row in selected])
except Exception as exc:
    result=dict(status='FAIL',error=f'{type(exc).__name__}: {exc}')
after=snap()
record=dict(before=before,after=after,started_utc=datetime.datetime.fromtimestamp(start,datetime.timezone.utc).isoformat(),duration_seconds=time.time()-start,commands=commands,markers=result,exact_source=before==after and not after['status'],native='NOT_RUN',full_caller='NOT_RUN',whole_protected='NOT_RUN_ON_THIS_COMMIT; development parent786 full-marker check failed in circuit_feature_learning_source submit after submit_until migration')
(out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2),flush=True)
sys.exit(0 if proc.returncode==0 and result.get('status')=='PASS' and record['exact_source'] else 1)
