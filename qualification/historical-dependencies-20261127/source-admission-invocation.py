from pathlib import Path
import sys,json,subprocess,resource,time
root=Path('/home/qian-qi/codex-historical-dependencies-20261127-2ac5');sys.path.insert(0,str(root/'historical-helper-v5'));sys.dont_write_bytecode=True
from file_update_oracle import identity,historical
output=root/'historical-source-projection-v2';output.mkdir()
record=json.loads((root/'historical-a201-probe-v2-receipt.json').read_text())['qualification']
manifest=identity.snapshot(root/'file-update-original',output/'original')
result=identity.producer_inputs(root/'candidate',output/'original',manifest,dependency_baseline=record)
(output/'source-admission.json').write_text(json.dumps({'passed':True,'scope':'Exact whole source admission only; complete public owner comparisons remain required','record':result},indent=2)+'\n')
print(json.dumps({'passed':True,'source_projections':result.get('dependency_source_projections'),'path_projections':result.get('path_dependency_projections')}),flush=True)
def limited():
 soft,hard=resource.getrlimit(resource.RLIMIT_AS);resource.setrlimit(resource.RLIMIT_AS,(2*1024*1024*1024,hard))
rows=[]
for name in ('candidate','file-update-original','unified-original'):
 argv=['/usr/bin/git','-c','core.packedGitWindowSize=16m','-c','core.packedGitLimit=64m','-C',str(root/name),'status','--porcelain=v1','--untracked-files=all']
 p=subprocess.run(argv,capture_output=True,text=True,preexec_fn=limited);row={'argv':argv,'returncode':p.returncode,'stdout':p.stdout,'stderr':p.stderr,'address_space_soft_limit_bytes':2*1024*1024*1024};rows.append(row);print(json.dumps(row),flush=True)
 assert p.returncode==0 and not p.stdout
 for key,value in [('core.packedGitWindowSize','16m'),('core.packedGitLimit','64m')]:subprocess.run(['/usr/bin/git','-C',str(root/name),'config','--local',key,value],check=True)
(output/'git-small-mmap-within-original-bound.json').write_text(json.dumps(rows,indent=2)+'\n')

