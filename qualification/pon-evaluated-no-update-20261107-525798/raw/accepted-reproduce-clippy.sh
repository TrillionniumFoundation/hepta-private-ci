python3 - <<'PY'
import pathlib,subprocess,json,time,resource,threading,sys,datetime,hashlib,os
repo=pathlib.Path.cwd().parent
outdir=pathlib.Path('/home/qian-qi/workspace/pon-hepta-acceptance-525798-20261107-evidence')
prefix=outdir/'accepted-evaluated-noupdate-clippy-v1'
assert not prefix.with_suffix('.receipt.json').exists()
def source():
 return {k:subprocess.check_output(v,cwd=repo,text=True).strip() for k,v in [('head',['git','rev-parse','HEAD']),('tree',['git','rev-parse','HEAD^{tree}']),('status',['git','status','--porcelain=v1']),('sparse',['git','sparse-checkout','list'])]}
argv=['just','fix','-p','codex-hepta-agentd']
r={'schema':'hepta-native-clippy-invocation-v1','source':source(),'argv':argv,'cwd':str(pathlib.Path.cwd()),'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'build_jobs':os.environ['CARGO_BUILD_JOBS'],'target_dir':os.environ['CARGO_TARGET_DIR']}
assert r['source']['head']=='e0a3bd2bde77c58a0ae7d211214f326371a72a4a' and not r['source']['status']
prefix.with_suffix('.start.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r),flush=True)
t=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
with prefix.with_suffix('.stdout.log').open('wb') as out,prefix.with_suffix('.stderr.log').open('wb') as err:
 child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 def copy(stream,log,dest):
  for chunk in iter(stream.readline,b''):log.write(chunk);log.flush();dest.buffer.write(chunk);dest.flush()
 threads=[threading.Thread(target=copy,args=(child.stdout,out,sys.stdout)),threading.Thread(target=copy,args=(child.stderr,err,sys.stderr))]
 for thread in threads:thread.start()
 code=child.wait()
 for thread in threads:thread.join()
end=resource.getrusage(resource.RUSAGE_CHILDREN)
r.update(exit_code=code,wall_seconds=time.monotonic()-t,child_user_seconds=end.ru_utime-before.ru_utime,child_system_seconds=end.ru_stime-before.ru_stime,maximum_child_rss_kib=end.ru_maxrss,source_after=source(),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
r['source_integrity_pass']=r['source']==r['source_after']
r['logs']={n:{'bytes':prefix.with_suffix('.'+n+'.log').stat().st_size,'sha256':hashlib.sha256(prefix.with_suffix('.'+n+'.log').read_bytes()).hexdigest()} for n in ['stdout','stderr']}
prefix.with_suffix('.receipt.json').write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps(r),flush=True)
sys.exit(code if r['source_integrity_pass'] else 98)
PY
