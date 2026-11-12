import hashlib,json,os,signal,stat,subprocess,sys,time,traceback,urllib.parse
from pathlib import Path

PLAN=json.loads(sys.stdin.buffer.read(1048577))
ROOT=Path(PLAN["output_root"])
REPO=ROOT/"source"
RECORDS=ROOT/"evidence"/"act2-notes-seed"
PYTHON=PLAN["python"]
SOURCE=PLAN["source_sha"]
TREE=PLAN["source_tree"]
BEFORE=None
STAGES=[]
env=dict(os.environ)
def hash_file(path):
 h=hashlib.sha256()
 with Path(path).open("rb") as stream:
  for part in iter(lambda:stream.read(1048576),b""):h.update(part)
 return h.hexdigest()
def save(name,value):
 path=RECORDS/name
 with path.open("x") as stream:
  json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
  stream.write("\n");stream.flush();os.fsync(stream.fileno())
 return hash_file(path)
def capture(argv,cwd=None,timeout=60):
 p=subprocess.run(argv,cwd=cwd,env=env,stdin=subprocess.DEVNULL,
                  stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
 if p.returncode:
  raise RuntimeError("Metadata command failed: "+argv[0]+" exit "+str(p.returncode))
 return p.stdout.decode()
def snapshot():
 head=capture(["git","rev-parse","HEAD"],REPO).strip()
 tree=capture(["git","rev-parse","HEAD^{tree}"],REPO).strip()
 dirty=capture(["git","status","--porcelain=v1","--untracked-files=all"],REPO)
 if head!=SOURCE or tree!=TREE or dirty:
  raise RuntimeError("Exact clean source identity required")
 entries=[]
 raw=subprocess.check_output(["git","ls-files","--stage","-z"],cwd=REPO,env=env)
 for item in raw.split(b"\0"):
  if not item:continue
  meta,path_bytes=item.split(b"\t",1)
  mode,blob,stage=meta.decode().split()
  if stage!="0":raise RuntimeError("Unmerged source entry")
  rel=os.fsdecode(path_bytes);path=REPO/rel
  if mode=="120000":
   data=os.fsencode(os.readlink(path))
   sha256=hashlib.sha256(data).hexdigest()
   actual=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
   size=len(data)
  elif mode in ("100644","100755") and path.is_file() and not path.is_symlink():
   size=path.stat().st_size
   gh=hashlib.sha1(b"blob "+str(size).encode()+b"\0");sh=hashlib.sha256()
   with path.open("rb") as stream:
    for part in iter(lambda:stream.read(1048576),b""):gh.update(part);sh.update(part)
   actual=gh.hexdigest();sha256=sh.hexdigest()
  else:raise RuntimeError("Unsupported tracked input type: "+mode)
  if actual!=blob:raise RuntimeError("Tracked bytes differ from index: "+rel)
  entries.append([rel,mode,blob,size,sha256])
 return {"commit":head,"tree":tree,"dirty":False,"files":entries}
def stage(name,argv,timeout,redact=False):
 save(name+"-START.json",{"stage":name,"argv":"validated exact-source fetch" if redact else argv,
                         "source_sha":SOURCE,"started_unix_ns":time.time_ns()})
 began=time.monotonic()
 with (RECORDS/(name+"-stdout-stderr.log")).open("xb") as log:
  result=subprocess.run(argv,cwd=REPO if REPO.is_dir() else ROOT,env=env,
                        stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
                        timeout=timeout)
 record={"stage":name,"exit_code":result.returncode,"elapsed_seconds":time.monotonic()-began,
         "log_sha256":hash_file(RECORDS/(name+"-stdout-stderr.log"))}
 STAGES.append(record);save(name+"-TERMINAL.json",record)
 print(json.dumps(record,sort_keys=True),flush=True)
 if result.returncode:raise RuntimeError(name+" failed")
def ci(name,argv,timeout,minimum=0):
 command=[PYTHON,"-B",str(REPO/"scripts/hepta_ci_exec.py"),
          "--timeout-seconds",str(timeout),"--output",str(RECORDS/(name+".json"))]
 if minimum:command+=["--minimum-tests",str(minimum)]
 stage(name,command+["--"]+argv,timeout+120)
def preserve_junit(name,before_sha256):
 path=REPO/"codex-rs/target/nextest/local/junit.xml"
 record={"expected_path":str(path),"present":path.is_file(),"before_sha256":before_sha256,"role":"raw auxiliary runner output; named-case gate is the original workflow receipt"}
 if path.is_file():
  raw=path.read_bytes()
  with (RECORDS/(name+"-junit.xml")).open("xb") as stream:
   stream.write(raw);stream.flush();os.fsync(stream.fileno())
  current=hashlib.sha256(raw).hexdigest()
  record.update(bytes=len(raw),sha256=current,changed_since_command=current!=before_sha256)
 save(name+"-JUNIT.json",record)
def test_ci(name,argv,minimum):
 junit=REPO/"codex-rs/target/nextest/local/junit.xml"
 before=hash_file(junit) if junit.is_file() else None
 try:
  ci(name,argv,1800,minimum)
 finally:
  preserve_junit(name,before)
def verify_tools():
 values={}
 for name,spec in PLAN["tools"].items():
  path=Path(spec["path"])
  if not path.is_file() or not os.access(path,os.X_OK):
   raise RuntimeError("Required existing tool unavailable: "+name)
  actual=hash_file(path)
  if spec.get("sha256") is not None and actual!=spec["sha256"]:
   raise RuntimeError("Existing tool pin differs: "+name)
  version=capture([str(path),"--version"]).strip()
  if spec["version_fragment"] not in version:
   raise RuntimeError("Existing tool version differs: "+name)
  values[name]={"path":str(path),"sha256":actual,"version":version}
 return values
if os.getuid()!=1000 or os.geteuid()!=1000:
 raise RuntimeError("This request requires the original ordinary uid/euid 1000")
os.umask(0o077)
ROOT.mkdir(parents=True,exist_ok=False)
RECORDS.mkdir(parents=True,exist_ok=False)
(ROOT/"tmp").mkdir()
terminal={"source_sha":SOURCE,"source_tree":TREE,"status":"FAILED",
          "execution_environment":"ai395 ordinary uid1000; not hosted CI",
          "owner_decision":None,"production_authority":False,
          "full_dynamic_tool_handler_qualified":False,"final_use_qualified":False,
          "learning_gain_qualified":False,"research_B_C_actor_calls":0}
try:
 for name in ("RUSTFLAGS","CARGO_ENCODED_RUSTFLAGS","RUSTC_WRAPPER","RUSTC_WORKSPACE_WRAPPER"):
  if env.get(name):raise RuntimeError("Unregistered compiler override: "+name)
 env.update(PLAN["environment"])
 env.update(SOURCE_SHA=SOURCE,TESTED_SHA=SOURCE,HEPTA_CI_LANE="source-head",
            CODEX_REPO_ROOT=str(REPO),PYTHONPATH=str(REPO/"scripts")+":"+str(REPO),
            PYTHONDONTWRITEBYTECODE="1",RUNNER_TEMP=str(ROOT/"evidence"),
            TMPDIR=str(ROOT/"tmp"),CARGO_TARGET_DIR=str(REPO/"codex-rs/target"),
            GITHUB_ENV=str(RECORDS/"v8-environment.txt"))
 for name in ("RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH"):env.pop(name,None)
 save("REQUEST_PLAN.json",PLAN)
 memory={}
 for line in Path("/proc/meminfo").read_text().splitlines():
  key,value=line.split(":",1)
  if key in ("MemAvailable","MemTotal"):memory[key]=int(value.split()[0])*1024
 disk=os.statvfs(ROOT)
 if memory["MemAvailable"]<PLAN["minimum_available_memory_bytes"] or disk.f_bavail*disk.f_frsize<PLAN["minimum_available_disk_bytes"]:
  raise RuntimeError("Declared native resource floor is not met")
 save("RESOURCE_AT_START.json",{"uid":os.getuid(),"euid":os.geteuid(),"memory":memory,
      "disk_available_bytes":disk.f_bavail*disk.f_frsize,"loadavg":os.getloadavg(),
      "cargo_build_jobs":2,"requested_memory_max_bytes":34359738368,
      "requested_cpu_quota_percent":200,"native_build_started":False})
 save("TOOLS.json",verify_tools())
 origin=capture(["git","-C",PLAN["existing_source_repository"],"remote","get-url","origin"]).strip()
 parsed=urllib.parse.urlparse(origin)
 if (parsed.scheme!="https" or parsed.username is not None or parsed.password is not None
     or parsed.hostname!="github.com" or parsed.path.rstrip("/") not in
        ("/TrillionniumFoundation/hepta-private-ci","/TrillionniumFoundation/hepta-private-ci.git")):
  raise RuntimeError("Expected a credential-free GitHub origin; no remote changed")
 stage("source-clone",["git","clone","--no-checkout","--no-hardlinks","--no-tags",
       PLAN["existing_source_repository"],str(REPO)],600)
 stage("source-fetch",["git","-C",str(REPO),"fetch","--no-tags","--depth=1",origin,
       SOURCE,PLAN["format_base"]],600,redact=True)
 stage("source-checkout",["git","-C",str(REPO),"checkout","--detach",SOURCE],120)
 BEFORE=snapshot();save("SOURCE_BEFORE.json",BEFORE)
 workflow=REPO/PLAN["workflow_path"]
 if hash_file(workflow)!=PLAN["workflow_sha256"]:
  raise RuntimeError("Exact reviewed workflow bytes differ")
 text=workflow.read_text()
 prefix="          python3 - <<'PY'\n";suffix="\n          PY\n"
 if text.count(prefix)!=1:raise RuntimeError("Expected one original named-case receipt program")
 receipt=text.split(prefix,1)[1].split(suffix,1)[0]
 receipt="\n".join(line[10:] if line.startswith("          ") else line for line in receipt.splitlines())+"\n"
 compile(receipt,"original-workflow-receipt","exec")
 (RECORDS/"source.txt").write_text(SOURCE+"\n"+TREE+"\n")
 save("LOCK_BEFORE.json",{"path":"codex-rs/Cargo.lock","sha256":hash_file(REPO/"codex-rs/Cargo.lock")})
 for relative,pin in PLAN["reviewed_source_inputs"].items():
  if hash_file(REPO/relative)!=pin["sha256"]:raise RuntimeError("Reviewed source input differs: "+relative)
 save("REVIEWED_SOURCE_INPUTS.json",PLAN["reviewed_source_inputs"])
 stage("v8-prepare",[PYTHON,"-B",str(REPO/"scripts/hepta_ci_v8.py")],1200)
 vf=RECORDS/"v8-environment.txt"
 pairs={}
 if vf.exists():
  for line in vf.read_text().splitlines():
   key,value=line.split("=",1)
   if key in pairs or key not in {"RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH"} or not value:
    raise RuntimeError("Unexpected original V8 environment result")
   pairs[key]=value
 if pairs and set(pairs)!={"RUSTY_V8_ARCHIVE","RUSTY_V8_SRC_BINDING_PATH"}:
  raise RuntimeError("Original V8 resolver did not return a complete pair")
 env.update(pairs)
 v8={key:{"path":value,"bytes":Path(value).stat().st_size,"sha256":hash_file(value)} for key,value in pairs.items()}
 save("V8_ARTIFACTS.json",v8)
 stage("rustc-version",[PLAN["tools"]["rustup"]["path"],"run","1.96.0","rustc","--version","--verbose"],60)
 ci("caller-proof",[PYTHON,"-B",str(REPO/"scripts/verify_hepta_callers.py"),"verify"],4800)
 ci("build",["env","--chdir=codex-rs",PLAN["tools"]["rustup"]["path"],"run","1.96.0",
            "cargo","build","--locked","-p","codex-hepta-agentd",
            "--bin","codex-hepta-agentd","--bin","hepta-notes-thread-seed"],3000)
 save("BINARIES.json",{name:{"path":str(REPO/"codex-rs/target/debug"/name),
      "sha256":hash_file(REPO/"codex-rs/target/debug"/name)}
      for name in ("codex-hepta-agentd","hepta-notes-thread-seed")})
 just=PLAN["tools"]["just"]["path"]
 test_ci("seed",[just,"test","--locked","-p","codex-hepta-agentd","--test","notes_thread_seed_product",
            "-E","test(launcher_seeds_one_unused_original_thread_without_model_contact)",
            "--status-level","all","--retries","0"],1)
 test_ci("seed-regressions",[just,"test","--locked","-p","codex-hepta-agentd","--lib",
      "--test","notes_thread_seed_product","-E",
      "test(original_notes_seed_profile_) | test(seed_embedding_keeps_the_store_but_removes_general_cognitive_tool_state) | test(standard_profile_rejects_original_notes_seed_before_model_contact)",
      "--status-level","all","--retries","0"],5)
 stage("named-case-receipts",[PYTHON,"-B","-c",receipt],60)
 stage("format",[just,"fmt","--base",PLAN["format_base"],"--check"],600)
 for value in v8.values():
  if hash_file(value["path"])!=value["sha256"]:raise RuntimeError("Resolved V8 input changed")
 terminal["status"]="NATIVE_SIX_METHOD_VALIDATION_PASSED"
except BaseException as error:
 terminal["error"]={"type":type(error).__name__,"message":str(error)}
 traceback.print_exc()
finally:
 try:
  if BEFORE is not None:
   after=snapshot();save("SOURCE_AFTER.json",after)
   terminal["source_inventory_unchanged"]=(after==BEFORE)
   terminal["tracked_file_count"]=len(after["files"])
   if after!=BEFORE:terminal["status"]="FAILED"
  else:terminal["source_inventory_unchanged"]=False
 except BaseException as error:
  terminal["status"]="FAILED"
  terminal["final_source_error"]={"type":type(error).__name__,"message":str(error)}
 terminal["stages"]=STAGES
 terminal["finished_unix_ns"]=time.time_ns()
 save("TERMINAL.json",terminal)
 print(json.dumps(terminal,sort_keys=True),flush=True)
if terminal["status"]!="NATIVE_SIX_METHOD_VALIDATION_PASSED":raise SystemExit(1)
