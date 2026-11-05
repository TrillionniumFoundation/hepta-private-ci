python3 - <<'PY'
import datetime, hashlib, json, os, pathlib, shutil, stat, subprocess, sys, time
root=pathlib.Path('/home/qian-qi/work/hepta-pq-effects-2c2b-20261105')
target=pathlib.Path('/home/qian-qi/work/hepta-pq-effects-2c2b-target')
evidence=pathlib.Path('/home/qian-qi/work/hepta-pq-effects-2c2b-evidence')
expected='ee57cd57c322a8fecdf674a662c741452baf6478'
expected_tree='ec40412aff2091fd05e0feaf31a46179f8afaa46'
lock_expected='0f458d7746a0ca0b95bedc5404fd3347c1b0a7508f1c387f3b1f3f71ced08663'
chain_source='04be5f02c84cf5cb626a53f34bc03a5bd6ff5137'
chain_tree='d4f4a85c439982d8decec9265c1993408f3577cf'
chain_lock='00f3573879f3da7d5a702a8bc13245196bbfd53b86b0b6eb19c51f14887cef61'
chain_sha='095458755051afd137478145a42b5edb94ee32587837e4723931317900a955d9'
chain=pathlib.Path('/home/qian-qi/work/hepta-pq-effects-2c2b-chain-04be-20261105/bin/trnm-pon-node')
binding_path=chain.parent.parent/'evidence/node-build-binding.json'
binding_sha='dee03d77a98ce9a0d2f781f1c18666401a73efda4594b068d7f1b73fc534b08a'
def emit(event,**kw): print(json.dumps({'event':event,**kw},sort_keys=True),flush=True)
def check(argv,cwd=root,env=None):
 p=subprocess.run(argv,cwd=cwd,env=env,capture_output=True,text=True)
 if p.returncode:
  emit('preflight_command_failed',argv=argv,returncode=p.returncode,stdout=p.stdout,stderr=p.stderr)
  raise SystemExit(p.returncode)
 return p.stdout.strip()
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''): h.update(chunk)
 return h.hexdigest()
if root.resolve()!=root or target.resolve()!=target or not target.is_dir(): raise SystemExit('unexpected isolated paths')
if check(['git','rev-parse','HEAD'])!=expected or check(['git','rev-parse','HEAD^{tree}'])!=expected_tree or check(['git','status','--porcelain']): raise SystemExit('refuse changed Hepta source')
if sha(root/'codex-rs/Cargo.lock')!=lock_expected: raise SystemExit('lock identity changed')
for stem in ['agentd-effects-','agentd-negative-qualification-']:
 previous=json.loads((evidence/(stem+expected+'.json')).read_text())
 if previous['head']!=expected or previous['returncode']!=0 or previous['git_status']: raise SystemExit('prior phase incomplete or changed source')
if chain.resolve()!=chain or binding_path.resolve()!=binding_path: raise SystemExit('refuse artifact symlink')
st=chain.lstat()
if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or stat.S_IMODE(st.st_mode)&0o222 or not stat.S_IMODE(st.st_mode)&0o111 or st.st_size!=14519384: raise SystemExit('unexpected native artifact metadata')
with chain.open('rb') as f:
 header=f.read(20)
if header[:4]!=b'\x7fELF' or header[4]!=2 or header[5]!=1 or int.from_bytes(header[18:20],'little')!=62: raise SystemExit('unexpected ELF identity')
if sha(chain)!=chain_sha or sha(binding_path)!=binding_sha: raise SystemExit('transferred artifact/binding hash mismatch')
binding=json.loads(binding_path.read_text())
identity={'commit':chain_source,'tree':chain_tree,'cargo_lock_sha256':chain_lock,'manifest_files_verified':51,'clean':True}
if binding['source_before']!=identity or binding['source_after']!=identity or binding['binary_sha256']!=chain_sha or binding['binary_bytes']!=st.st_size or binding['build_profile']!='original-default-release' or binding['source_modified'] or binding['cache_reused']: raise SystemExit('source/build binding mismatch')
build=[c for c in binding['commands'] if c['name']=='node-release-build']
if len(build)!=1 or build[0]['exit_code']!=0: raise SystemExit('no successful original Node build binding')
env=os.environ.copy()
overrides=sorted(k for k,v in env.items() if v and (k.startswith('CARGO_PROFILE_') or k.startswith('NEXTEST_') or k in ['RUSTFLAGS','CARGO_ENCODED_RUSTFLAGS']))
if overrides:
 emit('unexpected_overrides',names=overrides)
 raise SystemExit(8)
env['RUSTUP_TOOLCHAIN']='1.96.0'
env['CARGO_TARGET_DIR']=str(target)
env['CARGO_BUILD_JOBS']='2'
env['CARGO_TERM_COLOR']='never'
env['CARGO_NET_OFFLINE']='true'
env['PATH']='/home/qian-qi/.cargo/bin:/home/qian-qi/work/hepta-audit-r3-fullgate-20261104/tools/bin:'+env.get('PATH','')
env['HEPTA_PON_CHAIN_SOURCE']=chain_source
env['HEPTA_PON_CHAIN_BINARY']=str(chain)
env['HEPTA_PON_CHAIN_SHA256']=chain_sha
cargo=check(['/home/qian-qi/.cargo/bin/cargo','--version'],root/'codex-rs',env)
rustc=check(['/home/qian-qi/.cargo/bin/rustc','--version'],root/'codex-rs',env)
if not cargo.startswith('cargo 1.96.0') or not rustc.startswith('rustc 1.96.0'): raise SystemExit('toolchain mismatch')
nextest=check(['/home/qian-qi/.cargo/bin/cargo','nextest','--version'],root/'codex-rs',env)
def junit_files():
 files=[]
 for directory in [target/'nextest',root/'codex-rs/target/nextest',root/'target/nextest']:
  if directory.is_dir():
   files.extend(p for p in directory.glob('*/junit.xml') if p.is_file() and not p.is_symlink())
   files.extend(p for p in directory.glob('junit.xml') if p.is_file() and not p.is_symlink())
 return sorted(set(files))
def elf_files():
 files={}
 for path in (target/'debug/deps').glob('codex_hepta_agentd-*'):
  if not path.is_file() or path.is_symlink(): continue
  with path.open('rb') as f:
   if f.read(4)!=b'\x7fELF': continue
  s=path.stat()
  files[str(path)]={'path':str(path),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'sha256':sha(path)}
 return files
before_junit={str(p):(p.stat().st_mtime_ns,p.stat().st_size) for p in junit_files()}
before_elf=elf_files()
stem='agentd-real-chain-'+expected
log_path=evidence/(stem+'.log')
meta_path=evidence/(stem+'.json')
if log_path.exists() or meta_path.exists(): raise SystemExit('refuse existing independent real Chain evidence')
argv=['/home/qian-qi/.cargo/bin/just','test','--locked','-p','codex-hepta-agentd','--lib','-E','test(real_chain_ordinary_pq_loader_dispatches_once_and_reads_original_receipt)','--run-ignored','only','--no-capture']
record={'head':expected,'tree':expected_tree,'lock_sha256':lock_expected,'source_clean_before':True,'command':argv,'cargo_version':cargo,'rustc_version':rustc,'nextest_version':nextest,'target':str(target),'build_jobs':2,'profile':'original just local nextest profile and default Cargo test profile; original native-pair --run-ignored only --no-capture flags','nextest_config_sha256':sha(root/'codex-rs/.config/nextest.toml'),'real_chain_test_sha256':sha(root/'codex-rs/hepta-agentd/src/automation_effect_host_pq_chain_tests.rs'),'start_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'free_bytes_before':shutil.disk_usage(root).free,'target_du_bytes_before':int(check(['du','-s','-B1',str(target)]).split()[0]),'chain_source':chain_source,'chain_tree':chain_tree,'chain_lock_sha256':chain_lock,'chain_binary':str(chain),'chain_sha256':chain_sha,'chain_size':st.st_size,'chain_mode':oct(stat.S_IMODE(st.st_mode)),'chain_nlink':st.st_nlink,'chain_build_binding_sha256':binding_sha,'test_library_elf_before':list(before_elf.values()),'full_checkout_ci_harness_executed':False}
emit('real_chain_test_start',**record,log_path=str(log_path))
started=time.monotonic()
start_ns=time.time_ns()
with log_path.open('xb') as log:
 proc=subprocess.Popen(argv,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 for line in iter(proc.stdout.readline,b''):
  log.write(line);log.flush();sys.stdout.buffer.write(line);sys.stdout.buffer.flush()
 code=proc.wait()
 log.flush();os.fsync(log.fileno())
junit=[]
for n,path in enumerate(junit_files()):
 s=path.stat()
 fresh=(str(path) not in before_junit or before_junit[str(path)]!=(s.st_mtime_ns,s.st_size)) and s.st_mtime_ns>=start_ns
 item={'source_path':str(path),'size':s.st_size,'mtime_ns':s.st_mtime_ns,'fresh_for_this_command':fresh}
 if fresh:
  dest=evidence/(stem+'.junit-'+str(n)+'.xml')
  with path.open('rb') as src,dest.open('xb') as dst: shutil.copyfileobj(src,dst)
  item.update(saved_path=str(dest),sha256=sha(dest))
 junit.append(item)
observations=[]
for line in log_path.read_text(errors='replace').splitlines():
 if line.startswith('PON_ORDINARY_PQ_PAIR '):
  observations.append(json.loads(line[len('PON_ORDINARY_PQ_PAIR '):]))
after_elf=elf_files()
record.update(returncode=code,duration_seconds=round(time.monotonic()-started,3),end_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),free_bytes_after=shutil.disk_usage(root).free,target_du_bytes_after=int(check(['du','-s','-B1',str(target)]).split()[0]),log_sha256=sha(log_path),git_status=check(['git','status','--porcelain']),head_after=check(['git','rev-parse','HEAD']),lock_sha256_after=sha(root/'codex-rs/Cargo.lock'),chain_sha256_after=sha(chain),junit=junit,test_library_elf_after=list(after_elf.values()),original_case_observations=observations)
with meta_path.open('x') as out: json.dump(record,out,indent=2);out.write('\n')
emit('real_chain_test_complete',**record,log_path=str(log_path),meta_path=str(meta_path))
raise SystemExit(code)
PY
