import os,json,subprocess,time,hashlib,signal
from pathlib import Path
root=Path('/home/qian-qi/work/hepta-e5-final-verification-20261120-e9e051');repo=root/'source';out=root/'blob-gate-original-restored-1';out.mkdir(exist_ok=False)
expected={'scripts/check_blob_size.py':'eb7a9eab936b7c7948ed13fbd6d6aca09aa38997c20685a8ee12d72e388d52c3','.github/blob-size-allowlist.txt':'56a9a1cd05a0d81bba73a43c19e1451b213443f631dabacfa5b4e8d145e43d1c'}
report={'schema':'hepta.e5-original-blob-gate-restored-objects.v1','source_head':'1818fde55d964a87cfc8aed49f26a6a866a0e0a5','base':'e4b4eb5028578be87d5cad0829103632f2bff3a3','original_gate_and_allowlist_sha256':expected,'timeout_seconds':120,'model_calls':0,'training_updates':0,'native_task_children':0,'refs_changed':False}
for p,s in expected.items():assert hashlib.sha256((repo/p).read_bytes()).hexdigest()==s
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip();assert head==report['source_head']
argv=['/usr/bin/python3','scripts/check_blob_size.py','--base',report['base'],'--head',report['source_head'],'--max-bytes','512000','--allowlist','.github/blob-size-allowlist.txt'];report['argv']=argv
(out/'INTENT.json').write_text(json.dumps(report,indent=2)+'\n')
t=time.monotonic();cpu=time.process_time();p=subprocess.Popen(argv,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True);timeout=False
try:a,b=p.communicate(timeout=120)
except subprocess.TimeoutExpired:
 timeout=True;os.killpg(p.pid,signal.SIGTERM)
 try:a,b=p.communicate(timeout=2)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);a,b=p.communicate()
(out/'stdout').write_bytes(a);(out/'stderr').write_bytes(b)
report.update(exit_code=p.returncode,timed_out=timeout,wall_seconds=time.monotonic()-t,owner_self_cpu_seconds=time.process_time()-cpu,stdout_bytes=len(a),stdout_sha256=hashlib.sha256(a).hexdigest(),stderr_bytes=len(b),stderr_sha256=hashlib.sha256(b).hexdigest(),stdout_first_line=a.decode('utf-8','replace').splitlines()[:1])
for p,s in expected.items():assert hashlib.sha256((repo/p).read_bytes()).hexdigest()==s
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo).decode().strip()==head
report['gate_and_allowlist_unchanged']=True;report['head_unchanged']=True
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(0 if report['exit_code']==0 and not timeout else 1)
