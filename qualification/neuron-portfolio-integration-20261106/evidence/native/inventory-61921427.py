import datetime,hashlib,json,os,pathlib,shutil,subprocess,sys,time,xml.etree.ElementTree as ET
root=pathlib.Path('/home/qq/work/hepta-portfolio-816d-20261106');source=root/'source';records=root/'records';dest=records/'formal-61921427-test-inventory';dest.mkdir(exist_ok=False)
expected='61921427dc19223fd8c9d0ded1a4723b255c5df5';tree='31d99be67393619aca47436d82f9dca909cba359'
env=os.environ.copy();env.update(json.loads((root/'env.json').read_text()));env.update(CARGO_TERM_COLOR='never',CARGO_NET_OFFLINE='true',GIT_TERMINAL_PROMPT='0',GIT_LFS_SKIP_SMUDGE='1',CODEX_REPO_ROOT=str(source),BINDGEN_EXTRA_CLANG_ARGS='-isystem /usr/lib/gcc/x86_64-linux-gnu/15/include',LIBCLANG_PATH='/usr/lib/x86_64-linux-gnu',RUST_MIN_STACK='8388608',NEXTEST_PROFILE='local');env.update(json.loads((records/'current-helper-env.json').read_text()))
v8=json.loads((records/'formal-61921427-tests/receipt.json').read_text())['v8_build_assets']
for key,item in v8.items():
 p=pathlib.Path(item['path']);assert hashlib.sha256(p.read_bytes()).hexdigest()==item['sha256'];env[key]=str(p)
def git(*args):return subprocess.check_output(['git',*args],cwd=source,env=env,text=True).strip()
def identity():return {'head':git('rev-parse','HEAD'),'tree':git('rev-parse','HEAD^{tree}'),'status':git('status','--porcelain=v1','--untracked-files=all')}
before=identity();assert before=={'head':expected,'tree':tree,'status':''},before
test_receipt=json.loads((records/'formal-61921427-tests/receipt.json').read_text())
junit=source/'codex-rs/target/nextest/local/junit.xml';assert junit.is_file() and junit.stat().st_mtime_ns>=test_receipt['started_ns']
saved=records/'formal-61921427-tests/junit.xml';shutil.copy2(junit,saved);cases=list(ET.parse(saved).iter('testcase'))
jr={'origin':str(junit),'copied_to':str(saved),'origin_mtime_ns':junit.stat().st_mtime_ns,'tests_started_ns':test_receipt['started_ns'],'collected_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'freshness':True,'sha256':hashlib.sha256(saved.read_bytes()).hexdigest(),'bytes':saved.stat().st_size,'testcases':len(cases),'failures':sum(c.find('failure') is not None for c in cases),'errors':sum(c.find('error') is not None for c in cases),'skipped_elements':sum(c.find('skipped') is not None for c in cases),'note':'Original runner expected CARGO_TARGET_DIR/nextest/local/junit.xml. Actual nextest report is under source workspace target/nextest/local; original test receipt is preserved unchanged.'}
(records/'junit-collection-receipt.json').write_text(json.dumps(jr,indent=2)+'\n')
cmds=[['cargo','metadata','--locked','--offline','--no-deps','--format-version=1'],['cargo','nextest','list','--locked','--offline','-p','codex-hepta-neuron','-p','codex-hepta-intelligence','-p','codex-hepta-agentd','-p','codex-hepta-infer-worker-host','--cargo-metadata',str(dest/'cargo-metadata.json'),'--profile','local','--message-format','json']]
receipt={'source_before':before,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'commands':cmds,'action':'Enumerate compiled tests using the same selection/profile; do not execute test bodies.','cpu_time':'unknown'}
start=time.monotonic()
for cmd,name in zip(cmds,['cargo-metadata','nextest-list']):
 with (dest/(name+'.json')).open('wb') as out,(dest/(name+'.stderr.log')).open('wb') as err:rc=subprocess.call(cmd,cwd=source/'codex-rs',env=env,stdout=out,stderr=err)
 receipt[name+'_exit_code']=rc
 if rc:receipt.update(elapsed_seconds=time.monotonic()-start,source_after=identity());(dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');raise SystemExit(rc)
data=json.loads((dest/'nextest-list.json').read_text());entries=[]
for binary_id,suite in data['rust-suites'].items():
 for name,case in suite.get('testcases',{}).items():
  entries.append({'binary_id':binary_id,'package_name':suite.get('package-name'),'test_name':name,**case})
skipped=[c for c in entries if c.get('filter-match',{}).get('status')!='matches']
classified={'total_listed':len(entries),'selected':len(entries)-len(skipped),'skipped':len(skipped),'reason_counts':{},'skipped_tests':skipped}
for c in skipped:
 reason=c.get('filter-match',{}).get('reason','unknown');classified['reason_counts'][reason]=classified['reason_counts'].get(reason,0)+1
(dest/'skipped-tests.json').write_text(json.dumps(classified,indent=2)+'\n')
receipt.update(elapsed_seconds=time.monotonic()-start,source_after=identity(),list_sha256=hashlib.sha256((dest/'nextest-list.json').read_bytes()).hexdigest(),state='succeeded')
assert receipt['source_after']==before
(dest/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({'receipt':receipt,'summary':{k:v for k,v in classified.items() if k!='skipped_tests'}},indent=2))
