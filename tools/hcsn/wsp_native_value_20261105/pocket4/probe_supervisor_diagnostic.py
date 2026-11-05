import json,sys,pathlib,os,subprocess,time,resource,hashlib
payload=json.load(sys.stdin);os.umask(0o077)
root=pathlib.Path.home()/'.local/state/hepta-wsp/20261105-head-probe-237419-diagnostic'
root.mkdir(parents=True,exist_ok=False)
script=root/'probe_adapter_heads.py';script.write_text(payload['source'])
env=os.environ.copy();env.update(OMP_NUM_THREADS='1',MKL_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
before=resource.getrusage(resource.RUSAGE_CHILDREN);start=time.perf_counter();cpu=time.process_time()
with (root/'stdout.log').open('xb') as out,(root/'stderr.log').open('xb') as err:
 try:
  p=subprocess.run([payload['python'],'-B',str(script),'--output',str(root/'attempt1')],stdout=out,stderr=err,env=env,timeout=150)
  code=p.returncode;status='COMPLETED'
 except subprocess.TimeoutExpired:code=None;status='TIMEOUT_PRESERVED'
after=resource.getrusage(resource.RUSAGE_CHILDREN)
receipt={'schema':'hepta.wsp.head_probe.supervisor.v1','status':status,'exit_code':code,'source_sha256':hashlib.sha256(payload['source'].encode()).hexdigest(),'child_user_cpu_seconds':after.ru_utime-before.ru_utime,'child_system_cpu_seconds':after.ru_stime-before.ru_stime,'supervisor_cpu_seconds':time.process_time()-cpu,'elapsed_wall_seconds':time.perf_counter()-start,'child_peak_rss_bytes':after.ru_maxrss*1024,'stdout_sha256':hashlib.sha256((root/'stdout.log').read_bytes()).hexdigest(),'stderr_sha256':hashlib.sha256((root/'stderr.log').read_bytes()).hexdigest(),'stderr_bytes':(root/'stderr.log').stat().st_size,'accounting':'complete waited child including imports/final write, supervisor window excludes setup/final receipt','source_files_or_production_mutated':False}
(root/'SUPERVISOR_RECEIPT.json').write_text(json.dumps(receipt,indent=2,sort_keys=True)+'\n')
print(json.dumps(receipt))
