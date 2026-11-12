from pathlib import Path
from datetime import datetime,timezone
import base64,fcntl,gzip,hashlib,json,os,re,shutil,stat,subprocess,sys,xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
source="e8b6fe2aa55b4fdcfe8d9c15ea830e16f0144bbd"
tree="b607ff5f50812c5e0f932d7dae18d4c74f1269cb"
original=Path("/home/qian-qi/hepta-utility-36fa-review-19aa")
repo=Path("/home/qian-qi/hepta-utility-36fa-control-e8b6fe2a")
records=Path("/home/qian-qi/hepta-utility-36fa-evidence")
out=records/"countercontrol-e8b6fe2a-v1"
native=records/"native-e8b6fe2a-v1"
manifest=INPUT["manifest"];patch=INPUT["patch"].encode()
record={"status":"running","base_source_sha":source,"base_source_tree":tree,"started_at":datetime.now(timezone.utc).isoformat(),"qualification":"Isolated intentionally regressed causal control; not source-PR code or canonical source-head qualification","test_execution_status":"not_started"}
def sha(data):return hashlib.sha256(data).hexdigest()
def blob(data):return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
def write(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
def save(path,value):write(path,(json.dumps(value,indent=2,sort_keys=True)+"\n").encode())
def git(*args,at=None,data=None):return subprocess.check_output(["git",*args],cwd=at or repo,input=data)
def identity():return {"head":git("rev-parse","HEAD").decode().strip(),"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"status":git("status","--porcelain=v1","--untracked-files=all").decode()}
def verify_eval(control=False):
 expected={r["path"]:r for r in manifest["frozen_eval_crate_blobs"]}
 actual=[]
 for raw in git("ls-files","--stage","-z","codex-rs/hepta-intelligence-eval").split(b"\0"):
  if not raw:continue
  meta,path=raw.split(b"\t",1);mode,bid,stage=meta.decode().split();path=path.decode()
  if path not in expected or stage!="0" or mode!=expected[path]["mode"] or bid!=expected[path]["git_blob_sha1"]:raise RuntimeError("tracked eval input differs "+path)
  p=repo/path;data=p.read_bytes()
  wanted=expected[path]
  if control:
   row=next((r for r in manifest["production_files"] if r["path"]==path),None)
   if row:wanted={**row["postimage"],"mode":row["mode"]}
  actual_mode="100755" if p.stat().st_mode&0o111 else "100644"
  if actual_mode!=wanted["mode"] or len(data)!=wanted["bytes"] or blob(data)!=wanted["git_blob_sha1"] or ("sha256" in wanted and sha(data)!=wanted["sha256"]):raise RuntimeError("actual eval input differs "+path)
  actual.append({"path":path,"mode":actual_mode,"bytes":len(data),"blob":blob(data),"sha256":sha(data)})
 if len(actual)!=65 or {r["path"] for r in actual}!=set(expected):raise RuntimeError("eval source inventory differs")
 return actual
out.mkdir(exist_ok=False)
try:
 if os.geteuid()==0:raise RuntimeError("ordinary user required")
 lock=(records/"REVIEW_SOURCE.lock").open("a+")
 fcntl.flock(lock,fcntl.LOCK_SH|fcntl.LOCK_NB)
 terminal=json.loads((native/"RESULT.json").read_text())
 positive=json.loads((native/"eval-lib-coverage.json").read_text())
 if terminal["status"] not in ("passed","failed") or not terminal.get("finished_at") or terminal["source_sha"]!=source or terminal["source_before"]!=terminal["source_after"] or terminal["source_after"]["status"] or positive["source_sha"]!=source or positive["actual_count"]!=163 or positive["passed_count"]!=163:raise RuntimeError("known terminal clean canonical and independent positive eval prerequisite absent")
 record["canonical_native_terminal_status"]=terminal["status"]
 record["canonical_native_terminal_error"]=terminal.get("error")
 record["control_prerequisite"]="Fresh positive 163 eval cases; independent of owner-focused result. Native failure is retained and not overridden."
 save(out/"CANONICAL_NATIVE_TERMINAL.json",terminal)
 positive_execution=json.loads((native/"eval-lib.json").read_text())
 if positive_execution["status"]!="passed" or positive_execution["command_exit_code"]!=0 or positive_execution["timed_out"]:raise RuntimeError("positive eval original execution did not pass")
 save(out/"CANONICAL_EVAL_EXECUTION.json",positive_execution)
 expected_names=[r["full_name"] for r in manifest["planned_execution"]["cases"]]
 if positive["observed_four"]!=sorted(expected_names):raise RuntimeError("four positive cases absent")
 if git("rev-parse","HEAD",at=original).decode().strip()!=source or git("status","--porcelain=v1","--untracked-files=all",at=original):raise RuntimeError("canonical worktree no longer exact clean")
 if repo.exists() or repo.is_symlink():raise RuntimeError("control checkout already exists")
 subprocess.run(["git","clone","--no-checkout","--shared",str(original),str(repo)],check=True)
 git("checkout","--detach",source)
 before=identity()
 if before["head"]!=source or before["tree"]!=tree or before["status"]:raise RuntimeError("control base not exact clean canonical source")
 if git("rev-parse","HEAD:codex-rs/hepta-intelligence-eval").decode().strip()!="3a1254868e95319776765f776eec640df26329e5":raise RuntimeError("eval crate changed; reviewed control no longer applicable")
 baseline=verify_eval(False);save(out/"EVAL_SOURCE_BEFORE.json",baseline);save(out/"BASE_IDENTITY.json",before);save(out/"CONTROL_MANIFEST.json",manifest)
 if len(patch)!=1847 or sha(patch)!="b0f9b1cc0f1a03aa265a35ee48ae2e677a89a18a71d004ffc8e095184622ccc3" or blob(patch)!="7bad2fbdf7a4552fd84640413247576294c8be15":raise RuntimeError("control patch differs")
 write(out/"CONTROL.patch",patch)
 git("apply","--check",str(out/"CONTROL.patch"))
 git("apply",str(out/"CONTROL.patch"))
 allowed=sorted(manifest["modification_contract"]["allowed_paths"])
 if git("diff","--name-only").decode().splitlines()!=allowed or git("ls-files","--others","--exclude-standard"):raise RuntimeError("control changed unexpected source paths")
 controlled=verify_eval(True);save(out/"EVAL_CONTROL_INPUTS.json",controlled)
 for row in manifest["unchanged_test_inputs"]:
  data=(repo/row["path"]).read_bytes()
  if len(data)!=row["bytes"] or sha(data)!=row["sha256"] or blob(data)!=row["git_blob_sha1"]:raise RuntimeError("control changed retained test")
 control_identity=identity();record["control_identity_before"]=control_identity
 actual_patch=git("diff","--binary","--no-ext-diff");write(out/"ACTUAL_CONTROL.patch",actual_patch)
 env=dict(os.environ);env.update(json.loads((records/"MAINTENANCE_STARTED.json").read_text())["environment"])
 env.update(CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never")
 os.environ.update(env);sys.path.insert(0,str(repo/"scripts"));os.chdir(repo/"codex-rs")
 from hepta_ci_exec import execute_logged
 report=repo/"codex-rs/target/nextest/local/junit.xml"
 if report.exists():report.rename(out/"prior-junit-excluded.xml")
 command=manifest["planned_execution"]["command_argv"]
 started=datetime.now(timezone.utc);record.update(test_execution_status="running",test_started_at=started.isoformat(),command=command,cwd=str(repo/"codex-rs"))
 save(out/"TEST_STARTED.json",record)
 execution=execute_logged(command,out/"control.log",timeout_seconds=3600)
 finished=datetime.now(timezone.utc);record.update(execution=execution,test_finished_at=finished.isoformat(),test_execution_status="completed")
 save(out/"COMMAND_RESULT.json",{"started_at":started.isoformat(),"finished_at":finished.isoformat(),"command":command,**execution})
 if not report.exists():raise RuntimeError("control produced no fresh JUnit")
 with report.open("rb") as f:
  meta_before=os.fstat(f.fileno());data=f.read(64*1024*1024+1);meta_after=os.fstat(f.fileno())
 fields=("st_dev","st_ino","st_size","st_mtime_ns","st_ctime_ns")
 if len(data)>64*1024*1024 or not stat.S_ISREG(meta_before.st_mode) or any(getattr(meta_before,k)!=getattr(meta_after,k) for k in fields) or not started.timestamp()<=meta_after.st_mtime<=finished.timestamp():raise RuntimeError("control JUnit is not stable/fresh")
 write(out/"control.xml",data)
 if b"<!DOCTYPE" in data or b"<!ENTITY" in data:raise RuntimeError("unsupported JUnit declaration")
 cases=list(ET.fromstring(data).iter("testcase"));observed=[]
 for case in cases:
  failures=case.findall("failure");errors=case.findall("error");skipped=case.findall("skipped")
  text="\n".join((f.text or "") for f in failures)
  observed.append({"name":case.attrib.get("name"),"failures":len(failures),"errors":len(errors),"skipped":len(skipped),"failure_text":text,"actual_mismatch_mentions_both_dispositions":"Ineligible" in text and "InsufficientEvidence" in text})
 record["junit"]={"bytes":len(data),"sha256":sha(data),"mtime_ns":meta_after.st_mtime_ns,"cases":observed}
 save(out/"JUNIT_OBSERVATION.json",record["junit"])
 if len(observed)!=4 or sorted(r["name"] for r in observed)!=sorted(expected_names) or any(r["failures"]!=1 or r["errors"] or r["skipped"] or not r["actual_mismatch_mentions_both_dispositions"] for r in observed):raise RuntimeError("control failures are not the four intended disposition assertions")
 if execution["returncode"]==0 or execution["timed_out"] or execution["output_limit_exceeded"] or execution["observed_passed_tests"]!=0 or execution["observed_failed_tests"]!=4:raise RuntimeError("control terminal result differs from intended four failures")
 after=identity();save(out/"CONTROL_IDENTITY_AFTER.json",after);record["control_identity_after"]=after
 if after!=control_identity or verify_eval(True)!=controlled:raise RuntimeError("control source changed during tests")
 if git("rev-parse","HEAD",at=original).decode().strip()!=source or git("status","--porcelain=v1","--untracked-files=all",at=original):raise RuntimeError("canonical worktree changed during isolated control")
 record["status"]="expected_regression_observed"
except Exception as error:record.update(status="failed_control_verification",error=type(error).__name__+": "+str(error))
finally:
 archive=[]
 for p in sorted(out.iterdir()):
  if p.is_file() and p.suffix in (".log",".xml",".json",".patch"):
   data=p.read_bytes();packed=gzip.compress(data,compresslevel=9,mtime=0);write(p.with_name(p.name+".gz"),packed);archive.append({"path":str(p),"bytes":len(data),"sha256":sha(data),"gzip_bytes":len(packed),"gzip_sha256":sha(packed)})
 record["archive"]=archive;record["finished_at"]=datetime.now(timezone.utc).isoformat();save(out/"RESULT.json",record);print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(0 if record["status"]=="expected_regression_observed" else 1)
