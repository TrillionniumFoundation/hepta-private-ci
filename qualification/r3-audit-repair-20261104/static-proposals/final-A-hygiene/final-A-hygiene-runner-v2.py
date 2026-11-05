import datetime,hashlib,json,os,pathlib,shutil,subprocess,sys,time,traceback
request=json.load(sys.stdin)
root=pathlib.Path("/home/qian-qi/work/hepta-audit-r3-fullgate-20261104");tree=root/"source";target=root/"target-app-epoch2-20261105"
approved=request["guard"];source=approved["initial_tree"];counter=0;phases=[]
out=root/"evidence"/request["evidence_name"];out.mkdir(exist_ok=False)
owners=["codex-apply-patch","codex-arg0","codex-cli","codex-core","core_test_support","codex-exec-server","codex-skills-extension","codex-external-agent-migration","codex-hepta-agentd","codex-hepta-contracts","codex-hepta-supervisor","codex-linux-sandbox","codex-uds","codex-utils-pty","codex-v8-poc","codex-windows-sandbox"]
fix_argv=["just","fix","--locked","--profile","dev-small"]+[x for owner in owners for x in ("-p",owner)]
env=dict(os.environ)
env["PATH"]=str(root/"tools/uv-venv/bin")+":"+str(root/"tools/bin")+":/home/qian-qi/.cargo/bin:/home/qian-qi/.local/bin:"+env.get("PATH","")
env.update(PYTHONPYCACHEPREFIX=str(out/"python-pycache"),CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL="0",CARGO_BUILD_JOBS="4",RUSTUP_TOOLCHAIN="1.95.0",CARGO_NET_GIT_FETCH_WITH_CLI="true",PYTHONDONTWRITEBYTECODE="1",DOTSLASH_CACHE=str(root/"tools/dotslash-cache"),NEXTEST_PROFILE="local",UV_CACHE_DIR=str(out/"uv-cache"),UV_PYTHON_DOWNLOADS="never",RUSTY_V8_ARCHIVE=str(root/"tools/rusty-v8/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"),RUSTY_V8_SRC_BINDING_PATH=str(root/"tools/rusty-v8/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"))
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def rec(path):
 path=pathlib.Path(path);h=hashlib.sha256();size=0
 with path.open("rb") as f:
  while b:=f.read(1024*1024):h.update(b);size+=len(b)
 return {"path":str(path),"bytes":size,"sha256":h.hexdigest()}
def write(name,b):
 p=out/name;p.parent.mkdir(parents=True,exist_ok=True)
 with p.open("xb") as f:assert f.write(b)==len(b)
 assert p.read_bytes()==b
 return rec(p)
def save(name,value):return write(name,(json.dumps(value,indent=2)+"\n").encode())
def split(path,label):
 path=pathlib.Path(path);b=path.read_bytes();parts=[];offset=0;directory=out/"parts"/label;directory.mkdir(parents=True,exist_ok=False)
 while offset<len(b):
  end=min(offset+44000,len(b))
  while end<len(b) and b[end]&0xc0==0x80:end-=1
  p=directory/(str(len(parts)).zfill(4)+".txt")
  with p.open("xb") as f:f.write(b[offset:end])
  parts.append({"offset":offset,**rec(p)});offset=end
 return {"full":rec(path),"parts":parts}
def git(args,extra=None):
 e=dict(env);e.update(extra or {})
 return subprocess.run(["git"]+args,cwd=tree,env=e,capture_output=True,check=True).stdout
def frozen_full_reference():
 result={}
 for name,expected in approved["full_result_files"].items():
  p=pathlib.Path(expected["path"]);assert p.resolve().is_relative_to((root/"evidence").resolve()) and p.is_file() and not p.is_symlink()
  actual=rec(p);assert all(actual[k]==expected[k] for k in ("bytes","sha256")),"full evidence changed: "+name
  result[name]=actual
 review=json.loads(pathlib.Path(result["review"]["path"]).read_text());terminal=json.loads(pathlib.Path(result["terminal"]["path"]).read_text())
 assert review["source"]==terminal["source"]==approved["tested_tree"]
 assert review["exact_executed_roster"] and review["binary_stable"] and review["helpers_stable"]
 assert review["selected_catalog_count"]==approved["full_selected_count"] and review["counts"]==approved["full_actual_counts"]
 assert terminal["full_counts"]==review["counts"] and terminal["full_original_command_exit_code"]==review["exit_code"]
 return result
def snapshot(label,basis):
 global counter
 counter+=1;private=out/(str(counter)+"-"+label+".index");e={"GIT_INDEX_FILE":str(private)}
 git(["read-tree",basis],e);git(["add","-u","--","."],e);actual=git(["write-tree"],e).decode().strip()
 untracked=[os.fsdecode(p) for p in git(["ls-files","--others","--exclude-standard","-z"],e).split(b"\0") if p]
 ip=pathlib.Path(git(["rev-parse","--git-path","index"]).decode().strip());ip=ip if ip.is_absolute() else tree/ip
 result={"basis_tree":basis,"actual_tree":actual,"head":git(["rev-parse","HEAD"]).decode().strip(),"ordinary_index":rec(ip),"private_index":rec(private),"locks":{p:rec(tree/p) for p in approved["locks"]},"untracked_source_paths":untracked,"full_result_files":frozen_full_reference(),"recipe_files":{r["relative_path"]:rec(tree/r["relative_path"]) for r in approved["recipe_files"]}}
 failures=[]
 if result["head"]!=approved["ordinary_head"]:failures.append("ordinary HEAD changed")
 if any(result["ordinary_index"][k]!=approved["ordinary_index"][k] for k in ("bytes","sha256")):failures.append("ordinary index bytes changed; no reset or automatic acceptance")
 for p,expected in approved["locks"].items():
  if any(result["locks"][p][k]!=expected[k] for k in ("bytes","sha256")):failures.append("lock changed: "+p)
 if untracked!=approved["allowed_untracked_source_paths"]:failures.append("unexpected untracked source paths")
 result["guard_failures"]=failures;save(str(counter)+"-"+label+"-source-guard.json",result)
 return result
def require(snapshot):
 assert not snapshot["guard_failures"],"; ".join(snapshot["guard_failures"])
def delta(label,before,after):
 patch=git(["diff","--binary","--full-index","--no-ext-diff","--no-textconv","--no-renames",before,after,"--"])
 patch_ref=write(label+".patch",patch)
 raw=git(["diff","--name-status","-z","--no-renames",before,after,"--"]);tokens=raw.split(b"\0");rows=[];i=0
 while i<len(tokens) and tokens[i]:
  status=tokens[i].decode();path=os.fsdecode(tokens[i+1]);i+=2
  relative=pathlib.PurePosixPath(path);assert not relative.is_absolute() and ".." not in relative.parts
  entry=git(["ls-tree","-z",after,"--",path]);row={"path":path,"status":status}
  if entry:
   header,name=entry.rstrip(b"\0").split(b"\t",1);mode,kind,blob=header.decode().split()
   assert os.fsdecode(name)==path and kind=="blob" and mode in ("100644","100755"),"unexpected changed source type"
   b=git(["cat-file","blob",blob]);assert oid(b)==blob
   saved=write("postimages/"+label+"/"+path,b)
   row.update(mode=mode,git_blob=blob,bytes=len(b),sha256=sha(b),complete_postimage=saved)
  else:assert status=="D"
  rows.append(row)
 result={"before_tree":before,"after_tree":after,"patch":patch_ref,"changed_paths":rows}
 save(label+"-changes.json",result);return result
def terminal(state,next_stage,exit_code,detail):
 candidate=delta("candidate-at-terminal",approved["publication_base_tree"],source)
 result={"state":state,"source":source,"tested_tree":approved["tested_tree"],"root_execution_guard":request["root_guard_blob"],"root_triage_review":approved["root_full_triage_review"],"runner":request["runner"],"phases":phases,"candidate":candidate,"remaining_stage":next_stage,"ordinary_index_expected":approved["ordinary_index"],"original_full_counts":approved["full_actual_counts"],"full_result_files":approved["full_result_files"],"detail":detail,"all_hygiene_gates_passed":state=="HYGIENE_COMPLETE_AWAITING_ROOT_REVIEW","no_tests_after_hygiene":True,"no_refs_changed":True,"limits":approved["limits"]}
 p=save("terminal.json",result);save("terminal-parts.json",split(pathlib.Path(p["path"]),"terminal"))
 print(json.dumps({"terminal":True,"state":state,"source":source,"remaining_stage":next_stage,"receipt":p}),flush=True)
 raise SystemExit(exit_code)
def phase(label,argv,cwd):
 global source
 if shutil.disk_usage(tree).free<8_000_000_000:raise RuntimeError("resource guard below 8GB before "+label)
 before=snapshot(label+"-before",source);require(before);assert before["actual_tree"]==source,"unreviewed source drift"
 started=now();clock=time.monotonic();save(label+"-command.json",{"argv":argv,"cwd":str(cwd),"source":source,"started_at":started,"cargo_profile":"dev-small","owners":owners,"attempt":1,"disk_before":dict(zip(("total","used","free"),shutil.disk_usage(tree)))})
 so=out/(label+".stdout");se=out/(label+".stderr")
 print(json.dumps({"phase_start":label,"source":source,"argv":argv}),flush=True)
 with so.open("xb") as sout,se.open("xb") as serr:p=subprocess.run(argv,cwd=cwd,env=env,stdout=sout,stderr=serr)
 after=snapshot(label+"-after",source);old=source;source=after["actual_tree"]
 changes=delta(label,old,source)
 result={"name":label,"argv":argv,"source_before":old,"source_after":source,"exit_code":p.returncode,"started_at":started,"completed_at":now(),"duration_seconds":time.monotonic()-clock,"stdout":split(so,label+"-stdout"),"stderr":split(se,label+"-stderr"),"changes":changes,"after_guard_failures":after["guard_failures"],"metadata_identity":after["full_result_files"],"disk_after":dict(zip(("total","used","free"),shutil.disk_usage(tree)))}
 phases.append(result);save(label+"-status.json",result)
 print(json.dumps({"phase_terminal":label,"source_before":old,"source_after":source,"exit_code":p.returncode,"changed_paths":len(changes["changed_paths"]),"guard_failures":after["guard_failures"]}),flush=True)
 return result
try:
 save("execution-request.json",request)
 assert approved["authorized_after_full_triage"] is True and len(approved["root_full_triage_review"])==40
 assert approved["owners"]==owners and approved["commands"][0]==fix_argv and approved["commands"][1]==["just","fmt"] and approved["commands"][2]==["git","diff","--check"]
 assert approved["ordinary_head"]=="cabcb40d36e116beaa65750e1f674c52035da785" and approved["allowed_untracked_source_paths"]==[]
 assert target.is_dir() and not target.is_symlink()
 assert approved["start_stage"]==0 and source==approved["tested_tree"], "first hygiene run must bind the actual complete-test source"
 for item in approved["recipe_files"]:
  p=tree/item["relative_path"];assert all(rec(p)[k]==item[k] for k in ("bytes","sha256")),"original recipe identity changed"
 initial=snapshot("initial",source);require(initial);assert initial["actual_tree"]==source
 save("native-host.json",{"host_alias":"rog","uname":list(os.uname()),"rustc":subprocess.run(["rustc","-vV"],env=env,capture_output=True,text=True,check=True).stdout,"target":str(target),"source":source,"cargo_profile":"dev-small","initial_free_bytes":shutil.disk_usage(tree).free,"no_environment_policy_change":True})
 for index,label in enumerate(("scoped-fix","original-fmt","original-diff-check","full-candidate-diff-check")):
  argv=approved["commands"][index] if index<3 else ["git","diff","--check",approved["publication_base_tree"],source,"--"]
  cwd=tree/"codex-rs" if index<2 else tree
  result=phase(label,argv,cwd)
  if result["after_guard_failures"]:terminal("GUARD_CHANGED_STOP_FOR_ROOT",index+1,1,"No index reset, source restoration or next command is attempted.")
  if result["exit_code"]!=0:terminal("ORIGINAL_COMMAND_FAILED",index+1,1,"The original failure and all automatic source changes are retained; later commands were not run.")
  if result["disk_after"]["free"]<8_000_000_000:terminal("RESOURCE_GUARD_STOP",index+1,1,"No source or cache cleanup is attempted.")
  if result["changes"]["changed_paths"]:terminal("AUTOMATIC_SOURCE_CHANGES_REQUIRE_ROOT_REVIEW",index+1,3,"Original command succeeded, but all automatic postimages and exact patch require root review before the next hygiene stage. No A tests follow.")
 final=snapshot("final",source);require(final);assert final["actual_tree"]==source
 terminal("HYGIENE_COMPLETE_AWAITING_ROOT_REVIEW",None,0,"Original scoped fix, formatter and diff gates completed. Actual source and full patch are retained for root review. No A tests or publication follow.")
except Exception as error:
 failure={"source":source,"root_execution_guard":request.get("root_guard_blob"),"error_type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc(),"phases":phases,"no_source_or_index_reset":True,"no_automatic_retry":True}
 p=save("driver-error.json",failure);save("driver-error-parts.json",split(pathlib.Path(p["path"]),"driver-error"))
 print(json.dumps({"terminal":False,"source":source,"error":str(error),"receipt":p}),flush=True)
 raise
