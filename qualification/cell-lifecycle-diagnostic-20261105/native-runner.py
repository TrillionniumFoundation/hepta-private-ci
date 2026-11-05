import os,subprocess,json,time,hashlib,gzip,difflib,shutil,datetime
from pathlib import Path
root=Path("/home/qian-qi/work/hepta-cell-admission-r2-20261105");repo=root/"source";ev=root/"evidence"
base="3419b6ac8adf5b47b140e553f5fff9e74c98d352";head="3247636513f4cddaede6e9b45110925e9065d507";tree="99cc2b503f5e9825457066c0d7e2b935a795d234"
expected={"codex-rs/hepta-runtime/src/lib.rs":"2f9d7865417dc8db620dcd149c99e624310dd33a743d6545e94fa79c8b48bbd5","codex-rs/hepta-runtime/src/organs_tests.rs":"8100a42fd789269b2444a443f3869592c575ebfb94946417c99a47e9d12f0733","codex-rs/hepta-runtime/src/topology_execution.rs":"f1baa6c08cc72dabec84715a6a627cc0a8ca5dcc18f8f11081dd55f0ce7484db"}
env={**os.environ,"GIT_OPTIONAL_LOCKS":"0","GIT_TERMINAL_PROMPT":"0","RUSTUP_TOOLCHAIN":"1.96.0-x86_64-unknown-linux-gnu","CARGO_TARGET_DIR":str(root/"target"),"CARGO_BUILD_JOBS":"2"}
records=[]
def emit(r):
 print(json.dumps(r),flush=True)
 with (ev/"native-session.jsonl").open("a") as f:f.write(json.dumps(r)+"\n")
def run(name,args,cwd=repo,timeout=None):
 start=time.time();emit({"phase":name,"command":args,"cwd":str(cwd),"started_at":datetime.datetime.now(datetime.timezone.utc).isoformat()})
 with (ev/(name+".stdout")).open("wb") as out,(ev/(name+".stderr")).open("wb") as err:
  p=subprocess.run(args,cwd=cwd,env=env,stdout=out,stderr=err,timeout=timeout)
 r={"name":name,"command":args,"cwd":str(cwd),"exit_code":p.returncode,"elapsed_seconds":time.time()-start,"completed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),"logs":{}}
 for stream in ["stdout","stderr"]:
  q=ev/(name+"."+stream);b=q.read_bytes();gz=q.with_name(q.name+".gz");gz.write_bytes(gzip.compress(b,mtime=0))
  r["logs"][stream]={"path":str(q),"bytes":len(b),"sha256":hashlib.sha256(b).hexdigest(),"gzip_bytes":gz.stat().st_size,"gzip_sha256":hashlib.sha256(gz.read_bytes()).hexdigest()}
 records.append(r);(ev/"native-results.json").write_text(json.dumps({"head":head,"tree":tree,"records":records},indent=2)+"\n")
 emit({**r,"stdout_tail":(ev/(name+".stdout")).read_text(errors="replace")[-5000:],"stderr_tail":(ev/(name+".stderr")).read_text(errors="replace")[-5000:]})
 return p.returncode
def source_hashes():return {name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in expected}
def clean():
 assert source_hashes()==expected,"candidate source digest changed"
 assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=repo,text=True).strip()==head
 assert subprocess.check_output(["git","rev-parse","HEAD^{tree}"],cwd=repo,text=True).strip()==tree
 assert subprocess.check_output(["git","status","--porcelain=v1","--untracked-files=no"],cwd=repo,env=env)==b"","tracked source changed"
live=[]
for p in Path("/proc").iterdir():
 if not p.name.isdigit():continue
 try:
  cwd=(p/"cwd").resolve()
  if cwd==repo or cwd.is_relative_to(repo):live.append({"pid":int(p.name),"cwd":str(cwd),"comm":(p/"comm").read_text().strip()})
 except (OSError,RuntimeError):pass
emit({"prior_isolated_cwd_processes":live,"disk_free_bytes":shutil.disk_usage(root).free})
assert not live,"prior isolated source process still active"
assert shutil.disk_usage(root).free>8*1024**3
clean()
if run("fetch-format-base",["git","fetch","--no-tags","--depth=1","--filter=blob:none","origin",base],timeout=120):raise RuntimeError("base fetch failed")
clean()
inputs={"head":head,"tree":tree,"source_sha256":source_hashes(),"compiler":subprocess.check_output(["/home/qian-qi/.rustup/toolchains/1.96.0-x86_64-unknown-linux-gnu/bin/rustc","-Vv"],text=True),"just":subprocess.check_output(["/home/qian-qi/.cargo/bin/just","--version"],text=True),"nextest":subprocess.check_output(["/home/qian-qi/.cargo/bin/cargo-nextest","--version"],text=True),"environment_overrides":{"RUSTUP_TOOLCHAIN":env["RUSTUP_TOOLCHAIN"],"CARGO_TARGET_DIR":env["CARGO_TARGET_DIR"],"CARGO_BUILD_JOBS":env["CARGO_BUILD_JOBS"]},"materialization_manifest_sha256":hashlib.sha256((ev/"materialization.json").read_bytes()).hexdigest()}
(ev/"native-inputs.json").write_text(json.dumps(inputs,indent=2)+"\n");emit(inputs)
lib=repo/"codex-rs/hepta-runtime/src/lib.rs";original=lib.read_bytes();line=b"        topology_execution::require_control_lifecycle_admission_v1()?;\n";assert original.count(line)==2
negative=original.replace(line,b"")
(ev/"negative-control.patch").write_text("".join(difflib.unified_diff(original.decode().splitlines(keepends=True),negative.decode().splitlines(keepends=True),fromfile="a/codex-rs/hepta-runtime/src/lib.rs",tofile="b/codex-rs/hepta-runtime/src/lib.rs")))
red_rc=None
try:
 lib.write_bytes(negative)
 emit({"negative_control":"remove only the two public admission calls; helper, error variant, test fixture and all other candidate files retained","red_source_sha256":source_hashes(),"patch_sha256":hashlib.sha256((ev/"negative-control.patch").read_bytes()).hexdigest()})
 expr="test(public_governed_topology_denies_before_grant_consumption_or_callbacks) | test(public_topology_recovery_denies_before_grant_consumption_or_callbacks)"
 red_rc=run("native-red",["/home/qian-qi/.cargo/bin/just","test","--locked","-p","codex-hepta-runtime","-E",expr,"--retries","0"],repo/"codex-rs")
finally:
 lib.write_bytes(original)
 clean();emit({"candidate_restored":True,"source_sha256":source_hashes()})
red_text=(ev/"native-red.stdout").read_text(errors="replace")+(ev/"native-red.stderr").read_text(errors="replace")
red_valid=(red_rc==100 and "2 tests run" in red_text and "2 failed" in red_text)
emit({"negative_control_valid_behavioral_failure":red_valid,"red_exit_code":red_rc})
if not red_valid:raise RuntimeError("negative control did not establish two executed regression failures")
green_rc=run("native-green",["/home/qian-qi/.cargo/bin/just","test","--locked","-p","codex-hepta-runtime","--retries","0"],repo/"codex-rs")
clean()
fmt_rc=run("native-fmt",["/home/qian-qi/.cargo/bin/just","fmt","--base",base],repo/"codex-rs")
clean()
final={"head":head,"tree":tree,"red_behavioral_failure":red_valid,"green_exit_code":green_rc,"fmt_exit_code":fmt_rc,"source_unchanged":True,"source_sha256":source_hashes(),"scope":"native Unix runtime package; sparse source materialization, local fixture behavior only, no physical lifecycle activation"}
(ev/"native-final.json").write_text(json.dumps(final,indent=2)+"\n");emit(final)
if green_rc or fmt_rc:raise RuntimeError("green or formatter failed")

