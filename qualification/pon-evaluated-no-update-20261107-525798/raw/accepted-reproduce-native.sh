python3 - <<'PY'
import pathlib,subprocess,json,time,resource,threading,sys,datetime,hashlib,os
repo=pathlib.Path.cwd().parent
outdir=pathlib.Path('/home/qian-qi/workspace/pon-hepta-acceptance-525798-20261107-evidence')
prefix=outdir/'accepted-evaluated-noupdate-native-v1'
assert not prefix.with_suffix('.receipt.json').exists()
def source():
 return {key:subprocess.run(args,cwd=repo,capture_output=True,text=True,check=True).stdout.strip() for key,args in [('head',['git','rev-parse','HEAD']),('tree',['git','rev-parse','HEAD^{tree}']),('status',['git','status','--porcelain']),('sparse',['git','sparse-checkout','list'])]}
helper=json.loads((outdir/'accepted-evaluated-noupdate-helper-v1.receipt.json').read_text())
assert helper['exit_code']==0 and helper['source_integrity_pass']
assert helper['source']['head']=='e0a3bd2bde77c58a0ae7d211214f326371a72a4a'
assert hashlib.sha256(pathlib.Path(helper['executable']).read_bytes()).hexdigest()==helper['executable_sha256']
os.environ['CARGO_BIN_EXE_hepta_joint_propose']=helper['executable']
artifacts=outdir/'accepted-evaluated-noupdate-artifacts-v1'
assert not artifacts.exists()
os.environ['HEPTA_NO_UPDATE_EVIDENCE_DIR']=str(artifacts)
argv=['just','test','-p','codex-hepta-agentd','--lib','-E','test(neuron_generation) | test(learning_iteration)','--status-level','all','--final-status-level','all']
record={'helper_env_key':'CARGO_BIN_EXE_hepta_joint_propose','helper':helper,'schema':'hepta-native-acceptance-invocation-v1','source':source(),'argv':argv,'cwd':str(pathlib.Path.cwd()),'build_jobs':os.environ['CARGO_BUILD_JOBS'],'target_dir':os.environ['CARGO_TARGET_DIR'],'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'native owner tests; deterministic trainer and numeric fixture model; no production or external-demand claim','fixture_artifact_directory':str(artifacts)}
assert record['source']['head']=='e0a3bd2bde77c58a0ae7d211214f326371a72a4a' and record['source']['status']==''
prefix.with_suffix('.start.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
start=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
with prefix.with_suffix('.stdout.log').open('wb') as out,prefix.with_suffix('.stderr.log').open('wb') as err:
 child=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 def copy(stream,log,dest):
  for chunk in iter(stream.readline,b''):log.write(chunk);log.flush();dest.buffer.write(chunk);dest.flush()
 threads=[threading.Thread(target=copy,args=(child.stdout,out,sys.stdout)),threading.Thread(target=copy,args=(child.stderr,err,sys.stderr))]
 for t in threads:t.start()
 code=child.wait()
 for t in threads:t.join()
end=resource.getrusage(resource.RUSAGE_CHILDREN)
record.update(exit_code=code,wall_seconds=time.monotonic()-start,child_user_seconds=end.ru_utime-before.ru_utime,child_system_seconds=end.ru_stime-before.ru_stime,maximum_child_rss_kib=end.ru_maxrss,finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_after=source())
record['source_integrity_pass']=record['source']==record['source_after']
record['helper_integrity_pass']=hashlib.sha256(pathlib.Path(helper['executable']).read_bytes()).hexdigest()==helper['executable_sha256']
record['logs']={name:{'bytes':prefix.with_suffix('.'+name+'.log').stat().st_size,'sha256':hashlib.sha256(prefix.with_suffix('.'+name+'.log').read_bytes()).hexdigest()} for name in ['stdout','stderr']}
record['fixture_artifacts']=[{'path':str(p.relative_to(outdir)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(artifacts.rglob('*')) if p.is_file()]
prefix.with_suffix('.receipt.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record),flush=True)
sys.exit(code if record['source_integrity_pass'] and record['helper_integrity_pass'] else 98)
PY
