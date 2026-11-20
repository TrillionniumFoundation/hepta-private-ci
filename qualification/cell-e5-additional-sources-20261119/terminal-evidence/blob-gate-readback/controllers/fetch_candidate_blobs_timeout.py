import os,json,subprocess,time,hashlib,signal
from pathlib import Path
root=Path('/home/qian-qi/work/hepta-e5-final-verification-20261120-e9e051');repo=root/'source';out=root/'candidate-blob-fetch-1';out.mkdir(exist_ok=False)
source=json.loads((root/'candidate-object-closure-1/RESULT.json').read_text());oids=source['missing_unique_oids']
report={'schema':'hepta.e5-exact-missing-blob-fetch.v1','candidate':source['candidate'],'requested_oids':oids,'timeout_seconds':30,'refs_changed':False,'config_changed':False}
head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo);refs=subprocess.check_output(['git','for-each-ref','--format=%(refname) %(objectname)'],cwd=repo)
gitdir=Path(subprocess.check_output(['git','rev-parse','--git-common-dir'],cwd=repo).decode().strip());gitdir=gitdir if gitdir.is_absolute() else (repo/gitdir).resolve();config=gitdir/'config';st=config.stat();cs=(st.st_size,st.st_mtime_ns,st.st_ctime_ns)
argv=['git','fetch','--no-tags','--no-write-fetch-head','--no-recurse-submodules','--no-auto-gc','origin',*oids];report['argv']=argv
(out/'INTENT.json').write_text(json.dumps(report,indent=2)+'\n')
t=time.monotonic();p=subprocess.Popen(argv,cwd=repo,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True);timed=False
try:a,b=p.communicate(timeout=30)
except subprocess.TimeoutExpired:
 timed=True;os.killpg(p.pid,signal.SIGTERM)
 try:a,b=p.communicate(timeout=2)
 except subprocess.TimeoutExpired:os.killpg(p.pid,signal.SIGKILL);a,b=p.communicate()
(out/'stdout').write_bytes(a);(out/'stderr').write_bytes(b)
report.update(exit_code=p.returncode,timed_out=timed,wall_seconds=time.monotonic()-t,stdout_bytes=len(a),stdout_sha256=hashlib.sha256(a).hexdigest(),stderr_bytes=len(b),stderr_sha256=hashlib.sha256(b).hexdigest())
report['head_unchanged']=head==subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo);report['refs_unchanged']=refs==subprocess.check_output(['git','for-each-ref','--format=%(refname) %(objectname)'],cwd=repo);st=config.stat();report['config_stat_unchanged']=(st.st_size,st.st_mtime_ns,st.st_ctime_ns)==cs
assert report['head_unchanged'] and report['refs_unchanged'] and report['config_stat_unchanged']
env=os.environ.copy();env['GIT_NO_LAZY_FETCH']='1'
q=subprocess.run(['git','cat-file','--batch-check=%(objectname) %(objecttype) %(objectsize)'],input=('\n'.join(r['git_sha'] for r in source['expected_changed_files'])+'\n').encode(),cwd=repo,env=env,capture_output=True,timeout=5)
(out/'closure.stdout').write_bytes(q.stdout);(out/'closure.stderr').write_bytes(q.stderr)
lines=q.stdout.decode().splitlines();report['closure_exit']=q.returncode;report['all_candidate_changed_blobs_present']=q.returncode==0 and len(lines)==64 and all(' blob ' in x for x in lines);report['checked_lines']=len(lines)
(out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ('argv','requested_oids')}))
raise SystemExit(0 if report['all_candidate_changed_blobs_present'] else 1)
