from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,json,os,re,shutil,stat,subprocess,sys
sys.dont_write_bytecode=True
repo=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
root=Path("/home/qian-qi/hepta-utility-36fa-evidence")
out=root/"e8b6-new-build-diagnostic-v3"
source="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd";tree="b607ff5f50812c5e0f932d7dae18d4c74f1269cb";inventory="efdf0a2b8aa9879d3ae03c256ac24a23263a195c306f25d9815b05a4af702d56"
def sha(b):return hashlib.sha256(b).hexdigest()
def write(p,b):
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(b);f.flush();os.fsync(f.fileno())
def save(p,v):write(p,(json.dumps(v,sort_keys=True,indent=2)+"\n").encode())
def git(*args):return subprocess.check_output(["git",*args],cwd=repo,env={**os.environ,"GIT_OPTIONAL_LOCKS":"0"})
def snap(label):
 names=sorted(set(git("ls-files","-z").split(b"\0")+git("ls-files","--others","--exclude-standard","-z").split(b"\0"))-{b""});rows=[]
 for raw in names:
  p=repo/os.fsdecode(raw);m=p.lstat()
  if stat.S_ISLNK(m.st_mode):b=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(m.st_mode):b=p.read_bytes();mode="100755" if m.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported source type")
  rows.append({"path":os.fsdecode(raw),"mode":mode,"bytes":len(b),"sha256":sha(b),"blob":hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()})
 data=json.dumps(rows,sort_keys=True,separators=(",",":")).encode()
 v={"commit":git("rev-parse","HEAD").decode().strip(),"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"status":git("status","--porcelain=v1","--untracked-files=all").decode(),"files":len(rows),"inventory_sha256":sha(data)}
 write(out/(label+".files.json.gz"),gzip.compress(data,mtime=0));save(out/(label+".json"),v)
 if v["commit"]!=source or v["tree"]!=tree or v["status"] or len(rows)!=14741 or sha(data)!=inventory:raise RuntimeError("source not exact clean e8")
 return v
out.mkdir(exist_ok=False)
r={"status":"preparing","label":"NEW_BUILD_DIAGNOSTIC","source_sha":source,"source_tree":tree,"original_run_binary_available":False,"original_binary_disappearance_cause":"Unknown","qualification":"Fresh controlled nextest binaries-only build/list for diagnosis; zero test execution, not the original run binary or a native full gate","started_at":datetime.now(timezone.utc).isoformat(),"build_started":False,"tests_executed":0}
before=None
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 lock=(root/"REVIEW_SOURCE.lock").open("a+");fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 native=json.loads((root/"native-e8b6fe2a-v1/RESULT.json").read_text());control=json.loads((root/"countercontrol-e8b6fe2a-v1/RESULT.json").read_text())
 if native["status"]!="failed" or native["source_sha"]!=source or native["source_before"]!=native["source_after"] or control["status"]!="expected_regression_observed" or not native["finished_at"] or not control["finished_at"]:raise RuntimeError("old Cargo owners not in known terminal states")
 basic_raw=(root/"e8b6-target-directory-readonly-v1.json").read_bytes()
 if len(basic_raw)!=6859 or sha(basic_raw)!="ad54aa4ae51568c844e5ebd1f198d8b25dea34812b8577ea68c71c4ab5ac8e4c":raise RuntimeError("original missing-artifact observation differs")
 basic=json.loads(basic_raw)
 if len(basic["roots"])!=2 or any(x["symlink"] or x["all_file_listing"]["agentd_names"] for x in basic["roots"]):raise RuntimeError("known original binary may still be available")
 write(out/"ORIGINAL_ARTIFACT_UNAVAILABLE.json",basic_raw)
 active=[]
 for p in Path("/proc").iterdir():
  if not p.name.isdigit():continue
  try:
   if p.stat().st_uid!=os.geteuid():continue
   comm=(p/"comm").read_text().strip()
   if comm not in ("cargo","rustc","cargo-nextest","just"):continue
   cwd=os.readlink(p/"cwd")
   if cwd.startswith(("/home/qian-qi/hepta-utility-36fa-review-19aa","/home/qian-qi/hepta-utility-36fa-control-e8b6fe2a","/home/qian-qi/hepta-utility-36fa-target")):active.append({"pid":int(p.name),"comm":comm,"cwd":cwd})
  except (FileNotFoundError,ProcessLookupError,PermissionError):pass
 save(out/"OWN_CARGO_PRECONDITION.json",{"matching_live_processes":active,"native_finished_at":native["finished_at"],"control_finished_at":control["finished_at"]})
 if active:raise RuntimeError("own Cargo process is still active")
 restored=json.loads((root/"e8b6-missing-source-restoration-v1/RESULT.json").read_text())
 preserved=json.loads((root/"retained-e8b6fe2a-preservation-v3/RESULT.json").read_text())
 if restored["status"]!="restored_exact_canonical_source" or preserved["status"]!="retained_exact_e8_source" or preserved["source_after"]["inventory_sha256"]!=inventory:raise RuntimeError("exact restoration/preservation incomplete")
 r["historical_artifact_scope"]={"retained_original_stage_gzips":preserved["retained_original_stage_gzips"],"unavailable_original_stage_gzips":preserved["missing_original_stage_gzips"],"missing_original_gzips_reconstructed":False,"current_source_basis":"New full physical inventories before and after this diagnostic; independent preserved exact checkout"}
 before=snap("source-before")
 env=dict(os.environ);env.update(json.loads((root/"MAINTENANCE_STARTED.json").read_text())["environment"])
 helper_env=json.loads((root/"native-e8b6fe2a-v1/focused/helpers/env.json").read_text())
 env.update(helper_env)
 env.update(SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",RUST_MIN_STACK="8388608",NEXTEST_PROFILE="local")
 if env.get("RUSTUP_TOOLCHAIN")!="1.96.0" or env.get("CARGO_TARGET_DIR")!="/home/qian-qi/hepta-utility-36fa-target" or env.get("CARGO_BUILD_JOBS")!="2":raise RuntimeError("pinned build environment differs")
 os.environ.update(env);sys.path.insert(0,str(repo/"scripts"))
 from hepta_ci_exec import execute_logged
 target=Path(env["CARGO_TARGET_DIR"])
 target_state={"path":str(target),"observed_at":datetime.now(timezone.utc).isoformat(),"existed_before":target.exists(),"is_symlink":target.is_symlink(),"created_only_if_absent":False}
 if target.is_symlink():raise RuntimeError("task target became a symlink")
 if not target.exists():
  parent=target.parent
  if parent.is_symlink() or not parent.is_dir():raise RuntimeError("target parent differs")
  target_state["parent_before"]={"device":parent.stat().st_dev,"inode":parent.stat().st_ino,"mtime_ns":parent.stat().st_mtime_ns}
  save(out/"TARGET_ABSENT_BEFORE.json",target_state)
  target.mkdir(mode=0o700,exist_ok=False)
  target_state["created_only_if_absent"]=True
 if not target.is_dir():raise RuntimeError("task target is not directory")
 target_state["after"]={"device":target.stat().st_dev,"inode":target.stat().st_ino,"mode":oct(stat.S_IMODE(target.stat().st_mode)),"mtime_ns":target.stat().st_mtime_ns}
 save(out/"TARGET_STATE.json",target_state);r["target_state"]=target_state
 st=os.statvfs(target);r["free_bytes_before"]=st.f_bavail*st.f_frsize
 if r["free_bytes_before"]<6*1024**3:raise RuntimeError("insufficient task-target free space for controlled build")
 command=["cargo","nextest","list","--list-type","binaries-only","--message-format","json","--locked","--offline","-p","codex-hepta-agentd","-p","codex-hepta-intelligence-eval","--lib","--cargo-metadata",str(out/"cargo-metadata.json")]
 r["package_selection"]=["codex-hepta-agentd","codex-hepta-intelligence-eval"]
 r["metadata_strategy"]="Original scoped run-nextest.py cargo metadata --no-deps strategy; Cargo still resolves/builds both requested packages and default features"
 r["features_added"]=[]

 r["command"]=command;r["environment"]={k:env.get(k) for k in ("PATH","RUSTUP_HOME","CARGO_HOME","RUSTUP_TOOLCHAIN","CARGO_TARGET_DIR","CARGO_BUILD_JOBS","CARGO_INCREMENTAL","CARGO_PROFILE_DEV_DEBUG","CARGO_PROFILE_TEST_DEBUG","CARGO_NET_OFFLINE","RUST_MIN_STACK","NEXTEST_PROFILE","RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH","SOURCE_SHA","TESTED_SHA","HEPTA_CI_LANE","CODEX_REPO_ROOT",*helper_env.keys())}
 save(out/"PREPARATION_STARTED.json",r)
 os.chdir(repo/"codex-rs")
 version=subprocess.run(["cargo","nextest","--version"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 write(out/"NEXTEST_VERSION.txt",version.stdout+version.stderr)
 if version.returncode or b"0.9.103" not in version.stdout+version.stderr:raise RuntimeError("pinned nextest version differs")
 help_run=subprocess.run(["cargo","nextest","list","--help"],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 write(out/"NEXTEST_LIST_HELP.txt",help_run.stdout+help_run.stderr)
 if help_run.returncode or b"binaries-only" not in help_run.stdout+help_run.stderr or b"--cargo-metadata" not in help_run.stdout+help_run.stderr:raise RuntimeError("pinned list CLI unsupported")
 metadata_command=["cargo","metadata","--no-deps","--format-version=1","--locked","--offline"]
 metadata=subprocess.run(metadata_command,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 write(out/"cargo-metadata.stdout",metadata.stdout);write(out/"cargo-metadata.stderr",metadata.stderr)
 save(out/"CARGO_METADATA_RESULT.json",{"command":metadata_command,"cwd":str(Path.cwd()),"returncode":metadata.returncode,"stdout_bytes":len(metadata.stdout),"stdout_sha256":sha(metadata.stdout),"stderr_bytes":len(metadata.stderr),"stderr_sha256":sha(metadata.stderr)})
 if metadata.returncode:raise RuntimeError("scoped Cargo metadata failed")
 parsed=json.loads(metadata.stdout)
 if Path(parsed["workspace_root"])!=repo/"codex-rs" or Path(parsed["target_directory"])!=Path(env["CARGO_TARGET_DIR"]):raise RuntimeError("scoped Cargo metadata points at different workspace/target")
 names={p["name"] for p in parsed["packages"] if p["id"] in set(parsed["workspace_members"])}
 if not set(r["package_selection"]).issubset(names):raise RuntimeError("original packages missing from metadata")
 write(out/"cargo-metadata.json",metadata.stdout)
 r["build_started"]=True;save(out/"BUILD_STARTED.json",r)
 execution=execute_logged(command,out/"build.log",timeout_seconds=7200)
 r["execution"]=execution;raw=(out/"build.log").read_bytes();write(out/"build.log.gz",gzip.compress(raw,mtime=0))
 save(out/"BUILD_RESULT.json",execution)
 if execution["returncode"] or execution["timed_out"] or execution["output_limit_exceeded"]:raise RuntimeError("controlled build failed; exact raw retained")
 messages=[]
 for line in raw.splitlines():
  try:m=json.loads(line)
  except (ValueError,UnicodeDecodeError):continue
  if isinstance(m,dict):messages.append(m)
 listings=[m for m in messages if isinstance(m.get("rust-binaries"),dict) and isinstance(m.get("rust-build-meta"),dict)]
 if len(listings)!=1:raise RuntimeError("no unique successful nextest binary listing")
 listing=listings[0];save(out/"NEXTEST_BINARY_LIST.json",listing)
 if Path(listing["rust-build-meta"]["target-directory"])!=Path(env["CARGO_TARGET_DIR"]):raise RuntimeError("nextest reported different target")
 artifacts=[m for m in listing["rust-binaries"].values() if m.get("binary-name")=="codex_hepta_agentd" and m.get("kind")=="lib"]
 if len(artifacts)!=1:raise RuntimeError("no unique nextest-reported agentd lib executable")
 evals=[m for m in listing["rust-binaries"].values() if m.get("binary-name")=="codex_hepta_intelligence_eval" and m.get("kind")=="lib"]
 if len(evals)!=1:raise RuntimeError("original second eval lib binary missing")
 artifact=artifacts[0];compiler=Path(artifact["binary-path"])
 if not compiler.is_absolute() or not compiler.is_relative_to(Path(env["CARGO_TARGET_DIR"])) or compiler.is_symlink():raise RuntimeError("unexpected compiler-reported binary path")
 before_stat=compiler.stat();binary=compiler.read_bytes();after_stat=compiler.stat()
 if (before_stat.st_ino,before_stat.st_size,before_stat.st_mtime_ns)!=(after_stat.st_ino,after_stat.st_size,after_stat.st_mtime_ns) or not stat.S_ISREG(before_stat.st_mode) or not before_stat.st_mode&0o111 or binary[:4]!=b"\x7fELF":raise RuntimeError("new binary identity changed")
 (out/"bin").mkdir();pinned=out/"bin/codex_hepta_agentd-new-build";write(pinned,binary);pinned.chmod(0o500)
 identity={"label":"NEW_BUILD_DIAGNOSTIC","source_sha":source,"source_tree":tree,"compiler_executable":str(compiler),"pinned_executable":str(pinned),"bytes":len(binary),"sha256":sha(binary),"mtime_ns":after_stat.st_mtime_ns,"nextest_binary":artifact,"rust_build_meta":listing["rust-build-meta"],"second_original_package_binary":evals[0]}
 save(out/"BINARY.json",identity);r["binary"]=identity;r["status"]="new_build_diagnostic_ready"
except Exception as e:r.update(status="failed_new_build_diagnostic",error=type(e).__name__+": "+str(e))
finally:
 os.chdir(repo)
 try:
  after=snap("source-after");r["source_after"]=after
  if before and before!=after:r.update(status="failed_new_build_diagnostic",source_changed=True)
 except Exception as e:r.update(status="failed_new_build_diagnostic",final_source_error=str(e))
 r["source_before"]=before;r["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",r);print(json.dumps(r,sort_keys=True),flush=True)
raise SystemExit(0 if r["status"]=="new_build_diagnostic_ready" else 1)
