from pathlib import Path
from datetime import datetime,timezone
import fcntl,gzip,hashlib,json,os,re,signal,stat,subprocess,sys,types,xml.etree.ElementTree as ET
sys.dont_write_bytecode=True
if INPUT.get("state")!="READY_FOR_FINAL_SOURCE_QUALIFICATION" or INPUT.get("root_execution_approved") is not True:raise RuntimeError("qualification input remains HOLD")
repo=Path(INPUT["repo"])
source=INPUT["source"]
tree=INPUT["tree"]
records=Path(INPUT["records_parent"])
out=Path(INPUT["records"])
driver=Path(INPUT["native_driver_path"])
record={"source_sha":source,"source_tree":tree,"status":"running","started_at":datetime.now(timezone.utc).isoformat(),"stages":[],"behavioral_tests_started":False,"qualification":"Native tests only; no real authorized ordinary A/B/C iteration qualification"}
def git(*args):return subprocess.check_output(["git",*args],cwd=repo)
def sha(data):return hashlib.sha256(data).hexdigest()
def write(p,data):
 p.parent.mkdir(parents=True,exist_ok=True)
 fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o400)
 with os.fdopen(fd,"wb") as f:f.write(data);f.flush();os.fsync(f.fileno())
def save(p,value):write(p,(json.dumps(value,indent=2,sort_keys=True)+"\n").encode())
def state(stage):
 record["stage"]=stage;p=out/"STATE.pending.json";p.write_text(json.dumps(record,indent=2,sort_keys=True)+"\n");p.replace(out/"STATE.json")
def snapshot(label):
 names=sorted(set(git("ls-files","-z").split(b"\0")+git("ls-files","--others","--exclude-standard","-z").split(b"\0"))-{b""})
 rows=[]
 for raw in names:
  path=os.fsdecode(raw);p=repo/path
  if not p.exists() and not p.is_symlink():rows.append({"path":path,"missing":True});continue
  meta=p.lstat()
  if stat.S_ISLNK(meta.st_mode):data=os.fsencode(os.readlink(p));mode="120000"
  elif stat.S_ISREG(meta.st_mode):data=p.read_bytes();mode="100755" if meta.st_mode&0o111 else "100644"
  else:raise RuntimeError("unsupported source file type")
  rows.append({"path":path,"mode":mode,"bytes":len(data),"sha256":sha(data),"blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()})
 raw=json.dumps(rows,sort_keys=True,separators=(",",":")).encode();packed=gzip.compress(raw,mtime=0);write(out/(label+".files.json.gz"),packed)
 value={"commit":git("rev-parse","HEAD").decode().strip(),"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"status":git("status","--porcelain=v1","--untracked-files=all").decode(),"files":len(rows),"inventory_sha256":sha(raw)}
 save(out/(label+".json"),value);return value
def verify_clean(value):
 if value["commit"]!=source or value["tree"]!=tree or value["status"] or value["files"]!=INPUT["expected_file_count"] or value["inventory_sha256"]!=INPUT["expected_inventory_sha256"]:raise RuntimeError("source is not the exact clean canonical source and full frozen inventory")
def archive_stage(name,paths):
 rows=[]
 for path in paths:
  if path.is_file() and not path.is_symlink():
   data=path.read_bytes();packed=gzip.compress(data,compresslevel=9,mtime=0);destination=path.with_name(path.name+".gz");write(destination,packed)
   rows.append({"path":str(path),"bytes":len(data),"sha256":sha(data),"gzip_path":str(destination),"gzip_bytes":len(packed),"gzip_sha256":sha(packed)})
 save(out/(name+"-archive.json"),{"source_sha":source,"files":rows})
if not out.is_absolute() or out.is_relative_to(repo) or repo.is_relative_to(out) or out.is_relative_to(Path(INPUT["target"])) or Path(INPUT["target"]).is_relative_to(out):raise RuntimeError("fresh external records required")
out.mkdir(parents=True,exist_ok=False)
guard=None
before=None
try:
 if re.fullmatch("[0-9a-f]{40}",source) is None or re.fullmatch("[0-9a-f]{40}",tree) is None or os.geteuid()==0:raise RuntimeError("exact source and ordinary user required")
 required_input=INPUT.get("positive_eval_cases")
 frozen_four=["closure::tests::incomplete_evidence::known_failure_does_not_replace_longitudinal_retention_or_unlearning","closure::tests::incomplete_evidence::known_failure_keeps_missing_evidence_unknown_under_both_claim_scopes","closure::tests::incomplete_evidence::legacy_negative_evaluation_also_requires_complete_evidence","tests::incomplete_evidence::known_regression_with_unknown_metric_support_is_not_complete_ineligible"]
 if not isinstance(required_input,list) or len(required_input)!=4 or not all(isinstance(name,str) for name in required_input) or sorted(required_input)!=sorted(frozen_four):raise RuntimeError("positive eval cases must be exactly the four frozen regression names")
 admission_path=Path(INPUT["admission_path"]);admission_raw=admission_path.read_bytes()
 admission_pin={"bytes":len(admission_raw),"sha256":sha(admission_raw),"git_blob":hashlib.sha1(b"blob "+str(len(admission_raw)).encode()+b"\0"+admission_raw).hexdigest()}
 if admission_pin!=INPUT["admission_pin"]:raise RuntimeError("exact admission module differs")
 admission=types.ModuleType("final_qualification_admission");admission.__file__=str(admission_path)
 exec(compile(admission_raw,str(admission_path),"exec"),admission.__dict__)
 guard=admission.Admission(INPUT,out/"admission",True)
 signal.signal(signal.SIGALRM,guard.m.alarm_handler);guard.m.set_alarm(600)
 try:guard.acquire_and_validate()
 finally:signal.alarm(0)
 if sha(driver.read_bytes())!="3c318e8d028afd0039325a531215c4add411dc5a1a0ec5016fd3448dfbf2d231":raise RuntimeError("original driver differs")
 env=dict(os.environ) # The unchanged V5 environment_preflight has validated and installed only its restored explicit environment.
 env.update(CODEX_REPO_ROOT=str(repo),PYTHONPATH=str(repo/"scripts"),PYTHONDONTWRITEBYTECODE="1",CARGO_NET_OFFLINE="true",CARGO_TERM_COLOR="never",SOURCE_SHA=source,TESTED_SHA=source,HEPTA_CI_LANE="source-head",CARGO_TARGET_DIR=INPUT["target"])
 os.environ.update(env);sys.path.insert(0,str(repo/"scripts"));os.chdir(repo/"codex-rs")
 from hepta_ci_exec import run,execute_logged
 from hepta_ci_junit import collect
 before=snapshot("source-before");verify_clean(before)
 st=os.statvfs(os.environ["CARGO_TARGET_DIR"]);save(out/"RUNTIME.json",{"uid":os.geteuid(),"target":os.environ["CARGO_TARGET_DIR"],"free_bytes":st.f_bavail*st.f_frsize,"total_memory_bytes":os.sysconf("SC_PHYS_PAGES")*os.sysconf("SC_PAGE_SIZE"),"source_sha":source,"qualification":record["qualification"]})
 def command(name,cmd,budget,minimum=0):
  state(name);result=run(out/(name+".json"),cmd,timeout_seconds=budget,minimum_tests=minimum)
  payload=json.loads((out/(name+".json")).read_text());record["stages"].append({"name":name,"result":result,"record":str(out/(name+".json")),"command_exit_code":payload.get("command_exit_code")})
  paths=[out/(name+".json")]
  if payload.get("log_file"):paths.append(out/payload["log_file"])
  archive_stage(name,paths)
  if result:raise RuntimeError(name+" failed; original command retained")
  return payload
 # Final format and canonical alignment are actual pinned prerequisites;
 # qualification never repeats fix/fmt. Original b92 retains its own toolchain
 # and helper phases on each focused/all invocation.
 save(out/"EXACT_SOURCE_ADMISSION.json",{"status":"actual_clean_final_source_admitted","source_sha":source,"source_tree":tree,"repo":str(repo),"source_snapshot":before,"actual_prerequisites":INPUT["canonical_alignment"],"qualification":False,"at":datetime.now(timezone.utc).isoformat()})
 guard.before_native_stage("eval-lib")
 report=repo/"codex-rs/target/nextest/local/junit.xml"
 if report.exists():report.rename(out/"eval-lib-prior-junit-excluded.xml")
 record["behavioral_tests_started"]=True;record["attempted"]= ["eval-lib"];state("eval-lib")
 save(out/"eval-lib-execution-start.json",{"source_sha":source,"at":datetime.now(timezone.utc).isoformat(),"entrypoint":"original hepta_ci_exec.run","timeout_seconds":3600})
 result=run(out/"eval-lib.json",["just","test","--locked","--offline","-p","codex-hepta-intelligence-eval","--lib","--retries","0","--status-level","pass","--success-output","final","--failure-output","final","--test-threads","2"],minimum_tests=1,timeout_seconds=3600)
 execution=json.loads((out/"eval-lib.json").read_text());record["stages"].append({"name":"eval-lib","result":result,"collection":None,"record":str(out/"eval-lib.json")})
 retained=collect(out/"eval-lib.json",report,out/"eval-lib.xml");record["stages"][-1]["collection"]=retained
 archive_stage("eval-lib",[out/"eval-lib.json",*([out/execution["log_file"]] if execution.get("log_file") else []),out/"eval-lib.xml",out/"eval-lib.summary.json"])
 if result or retained:raise RuntimeError("full eval lib failed")
 cases=list(ET.parse(out/"eval-lib.xml").iter("testcase"))
 required=set(INPUT["positive_eval_cases"])
 actual=[c.attrib.get("name") for c in cases if c.find("skipped") is None]
 passed=[c.attrib.get("name") for c in cases if c.find("skipped") is None and c.find("failure") is None and c.find("error") is None]
 all_names=[c.attrib.get("name") for c in cases]
 save(out/"eval-lib-coverage.json",{"source_sha":source,"count_policy":"actual final-source complete unfiltered library; no historical-count gate","actual_count":len(actual),"passed_count":len(passed),"required_four":sorted(required),"observed_four":sorted(required&set(passed)),"names":actual,"all_fresh_junit_names":all_names,"skipped_names":[c.attrib.get("name") for c in cases if c.find("skipped") is not None]})
 if not actual or len(passed)!=len(actual) or len(set(actual))!=len(actual) or len(set(all_names))!=len(all_names) or not all(isinstance(name,str) and name for name in all_names) or not required.issubset(set(passed)):raise RuntimeError("full eval lib inventory or four regression cases differ")
 check=snapshot("source-after-eval");verify_clean(check)
 if check!=before:raise RuntimeError("source changed during eval")
 for suite,budget in [("focused",12000),("all",21000)]:
  guard.before_native_stage(suite)
  record["attempted"].append(suite);state(suite);destination=out/suite
  cmd=["python3",str(driver),"--repo",str(repo),"--records",str(destination),"--source",source,"--suite",suite]
  if suite=="all":cmd+=["--root-parent",INPUT["root_parent"]]
  save(out/(suite+"-launch.json"),{"command":cmd,"source_sha":source,"at":datetime.now(timezone.utc).isoformat()})
  os.chdir(repo);execution=execute_logged(cmd,out/(suite+"-driver.log"),timeout_seconds=budget);os.chdir(repo/"codex-rs")
  record["stages"].append({"name":suite,**execution,"records":str(destination)})
  save(out/(suite+"-driver-result.json"),execution)
  files=[out/(suite+"-driver.log"),out/(suite+"-driver-result.json")]
  if destination.exists():files += [p for p in destination.iterdir() if p.is_file() and p.suffix in (".json",".xml",".log")]
  archive_stage(suite,files)
  if execution["returncode"] or execution["timed_out"] or execution["output_limit_exceeded"]:raise RuntimeError("original native "+suite+" driver failed")
  native=json.loads((destination/"driver-result.json").read_text())
  if native["status"]!="passed" or native["failures"]:raise RuntimeError("native driver did not pass")
  if suite=="focused":
   rows=list(ET.parse(destination/"focused.xml").iter("testcase"))
   selected=[c for c in rows if c.attrib.get("name")=="neuron_cell_evaluation::tests::learning::insufficient_evidence_keeps_the_original_training_cut"]
   if len(selected)!=1 or any(c.find(t) is not None for c in selected for t in ("failure","error","skipped")):raise RuntimeError("required mixed-evidence agentd case did not pass exactly once")
   save(out/"focused-mixed-evidence-coverage.json",{"source_sha":source,"actual_passed_case":selected[0].attrib["name"],"count":1})
  check=snapshot("source-after-"+suite);verify_clean(check)
  if check!=before:raise RuntimeError("source changed during native "+suite)
 record["status"]="passed"
except Exception as error:
 known=any(row.get("result") not in (None,0) or row.get("returncode") not in (None,0) or row.get("timed_out") is True or row.get("output_limit_exceeded") is True for row in record["stages"])
 status="failed" if known else "unknown" if isinstance(error,(OSError,ET.ParseError,json.JSONDecodeError)) else "failed"
 record.update(status=status,error=type(error).__name__+": "+str(error))
finally:
 os.chdir(repo)
 try:
  after=snapshot("source-after");record["source_after"]=after
  if before is None:record.update(source_change=None,source_comparison="unknown_missing_before")
  elif before!=after:record.update(status="failed",source_change=True,source_comparison="different")
  else:record.update(source_change=False,source_comparison="equal")
 except Exception as error:record.update(status="unknown" if record["status"]=="passed" else record["status"],final_snapshot_error=str(error),source_change=None,source_comparison="unknown_missing_after")
 if guard is not None:
  try:
   signal.signal(signal.SIGALRM,guard.m.alarm_handler);guard.m.set_alarm(300)
   record["actual_full_physical_observation"]=guard.finish()
  except Exception as error:record.update(status="failed" if isinstance(error,admission.SourceChanged) else "unknown" if record["status"]=="passed" else record["status"],full_physical_evidence_error=type(error).__name__+": "+str(error))
  finally:signal.alarm(0);guard.close()
 record["source_before"]=before;record["finished_at"]=datetime.now(timezone.utc).isoformat()
 save(out/"RESULT.json",record);state("finished");print(json.dumps(record,sort_keys=True),flush=True)
raise SystemExit(0 if record["status"]=="passed" else 1)
