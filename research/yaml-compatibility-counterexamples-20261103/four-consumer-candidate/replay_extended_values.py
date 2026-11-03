#!/usr/bin/env python3
"""Run the frozen structural/number/style/encoding matrix against a specific rlib."""
from pathlib import Path
import argparse,hashlib,json,subprocess,time,shutil
ap=argparse.ArgumentParser();ap.add_argument('--out',type=Path,required=True);ap.add_argument('--library',type=Path,required=True);ap.add_argument('--dependencies',type=Path,required=True);ap.add_argument('--rustc',type=Path,required=True);a=ap.parse_args()
root=Path(__file__).resolve().parent;run=a.out;run.mkdir(exist_ok=False)
shutil.copy2(root/'probe/extended_values.rs',run/'main.rs');shutil.copy2(root/'probe/compatible_value.rs',run/'safe_yaml.rs')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
inputs={str(p):sha(p) for p in [run/'main.rs',run/'safe_yaml.rs',a.library]}
args=[str(a.rustc),'--edition=2024','-C','debuginfo=0','-C','opt-level=0','-L','dependency='+str(a.dependencies),'--extern','serde_saphyr='+str(a.library)]
for name in ['serde','serde_yaml','serde_json','ryu','indexmap']:
 ps=list(a.dependencies.glob('lib'+name+'-*.rlib'));assert len(ps)==1
 inputs[str(ps[0])]=sha(ps[0]);args+=['--extern',name+'='+str(ps[0])]
args+=[str(run/'main.rs'),'-o',str(run/'probe')]
records=[]
for name,argv in [('compile',args),('run',[str(run/'probe')])]:
 start=time.monotonic();p=subprocess.run(argv,capture_output=True,timeout=60)
 (run/(name+'.stdout')).write_bytes(p.stdout);(run/(name+'.stderr')).write_bytes(p.stderr)
 records.append({'name':name,'argv':argv,'exit_code':p.returncode,'seconds':time.monotonic()-start,'stdout_sha256':hashlib.sha256(p.stdout).hexdigest(),'stderr_sha256':hashlib.sha256(p.stderr).hexdigest()})
 print(json.dumps({k:records[-1][k] for k in ['name','exit_code','seconds']}))
 if name=='compile' and p.returncode:print(p.stderr.decode());break
 if name=='run':print(p.stderr.decode())
(run/'RECEIPT.json').write_text(json.dumps({'schema':'extended-value-bounded-probe-v1','orchestrator_sha256':sha(__file__),'inputs_sha256':inputs,'records':records,'inputs_unchanged':all(sha(p)==h for p,h in inputs.items()),'compiler':subprocess.check_output([str(a.rustc),'--version'],text=True).strip(),'compiler_sha256':sha(a.rustc),'production_accepted':False},indent=2)+'\n')
