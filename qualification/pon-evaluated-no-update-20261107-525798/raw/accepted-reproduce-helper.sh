python3 - <<'PY'
import pathlib,subprocess,json,time,resource,datetime,hashlib,os,sys
repo=pathlib.Path.cwd().parent
outdir=pathlib.Path('/home/qian-qi/workspace/pon-hepta-acceptance-525798-20261107-evidence')
prefix=outdir/'accepted-evaluated-noupdate-helper-v1'
assert not prefix.with_suffix('.receipt.json').exists()
def source():
 return {k:subprocess.check_output(v,cwd=repo,text=True).strip() for k,v in [('head',['git','rev-parse','HEAD']),('tree',['git','rev-parse','HEAD^{tree}']),('status',['git','status','--porcelain'])]}
argv=['cargo','build','--locked','-p','codex-hepta-infer-worker-host','--bin','hepta-joint-propose','--message-format=json']
r={'schema':'hepta-native-helper-build-v2','source':source(),'argv':argv,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'build_jobs':os.environ['CARGO_BUILD_JOBS'],'target_dir':os.environ['CARGO_TARGET_DIR']}
assert r['source']['head']=='e0a3bd2bde77c58a0ae7d211214f326371a72a4a' and not r['source']['status']
print(json.dumps(r),flush=True)
t=time.monotonic();before=resource.getrusage(resource.RUSAGE_CHILDREN)
with prefix.with_suffix('.stdout.log').open('wb') as stdout,prefix.with_suffix('.stderr.log').open('wb') as stderr:
 child=subprocess.run(argv,stdout=stdout,stderr=stderr)
end=resource.getrusage(resource.RUSAGE_CHILDREN)
r.update(exit_code=child.returncode,wall_seconds=time.monotonic()-t,child_user_seconds=end.ru_utime-before.ru_utime,child_system_seconds=end.ru_stime-before.ru_stime,maximum_child_rss_kib=end.ru_maxrss,source_after=source(),finished_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
r['source_integrity_pass']=r['source']==r['source_after']
r['logs']={n:{'bytes':prefix.with_suffix('.'+n+'.log').stat().st_size,'sha256':hashlib.sha256(prefix.with_suffix('.'+n+'.log').read_bytes()).hexdigest()} for n in ['stdout','stderr']}
if child.returncode==0:
 rows=[json.loads(l)for l in prefix.with_suffix('.stdout.log').read_text().splitlines() if l.startswith('{')]
 exes=[x['executable']for x in rows if x.get('reason')=='compiler-artifact' and x.get('target',{}).get('name')=='hepta-joint-propose' and x.get('executable')]
 assert len(exes)==1
 r['executable']=exes[0];r['executable_sha256']=hashlib.sha256(pathlib.Path(exes[0]).read_bytes()).hexdigest()
prefix.with_suffix('.receipt.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r),flush=True)
sys.exit(child.returncode if r['source_integrity_pass']else 98)
PY

