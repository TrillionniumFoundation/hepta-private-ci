import os,json,subprocess,time,hashlib,signal
from pathlib import Path
root=Path('/home/qian-qi/work/hepta-e5-final-verification-20261120-e9e051');repo=root/'source';out=root/'candidate-object-fetch-1';out.mkdir(exist_ok=False)
report={'schema':'hepta.e5-exact-candidate-object-fetch.v1','candidate':'b6822f9afe283e1e1b4493173ee98cc2f740ef0a','timeout_seconds':30,'expected_tree':'ace010f9ff23207de53c5941db73c11079fc8034','refs_changed':False,'config_changed':False}
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo);refs=subprocess.check_output(['git','for-each-ref','--format=%(refname) %(objectname)'],cwd=repo)
gitdir=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=repo).decode().strip());gitdir=gitdir if gitdir.is_absolute() else (repo/gitdir).resolve();config=gitdir/'config';st=config.stat();config_before=(st.st_size,st.st_mtime_ns,st.st_ctime_ns)
report['source_head_before']=head.decode().strip();report['refs_before_sha256']=hashlib.sha256(refs).hexdigest()
argv=['git','fetch','--no-tags','--no-write-fetch-head','--no-recurse-submodules','--no-auto-gc','--filter=blob:none','origin',report['candidate']]
report['argv']=argv;(out/'INTENT.json').write_text(json.dumps(report,indent=2)+'\n')
t=time.monotonic();p=subprocess.Popen(argv,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True);timed=False
try:a,b=p.communicate(timeout=30)
except subprocess.TimeoutExpired:
 timed=True;os.killpg(p.pid,signal.SIGTERM)
 try:a,b=p.communicate(timeout=2)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);a,b=p.communicate()
(out/'stdout').write_bytes(a);(out/'stderr').write_bytes(b)
report.update(exit_code=p.returncode,timed_out=timed,wall_seconds=time.monotonic()-t,stdout_bytes=len(a),stdout_sha256=hashlib.sha256(a).hexdigest(),stderr_bytes=len(b),stderr_sha256=hashlib.sha256(b).hexdigest())
refs2=subprocess.check_output(['git','for-each-ref','--format=%(refname) %(objectname)'],cwd=repo);head2=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo);st=config.stat()
report['refs_unchanged']=refs2==refs;report['head_unchanged']=head2==head;report['config_stat_unchanged']=(st.st_size,st.st_mtime_ns,st.st_ctime_ns)==config_before
assert report['refs_unchanged'] and report['head_unchanged'] and report['config_stat_unchanged']
env=os.environ.copy();env['GIT_NO_LAZY_FETCH']='1'
q=subprocess.run(['git','cat-file','--batch-check=%(objectname) %(objecttype) %(objectsize)'],input=(report['candidate']+'\n').encode(),capture_output=True,cwd=repo,env=env,timeout=5)
report['candidate_local_status']=q.stdout.decode();report['candidate_local_check_exit']=q.returncode
if q.returncode==0 and ' commit ' in report['candidate_local_status']:
 raw=subprocess.check_output(['git','cat-file','commit',report['candidate']],cwd=repo,env=env,timeout=5);(out/'candidate.commit.raw').write_bytes(raw)
 report['commit_object_sha_verified']=hashlib.sha1(b'commit '+str(len(raw)).encode()+b'\0'+raw).hexdigest()==report['candidate'];report['candidate_tree']=raw.decode().splitlines()[0].split()[1];assert report['commit_object_sha_verified'] and report['candidate_tree']==report['expected_tree']
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report));raise SystemExit(0 if report['exit_code']==0 and not timed else 1)
