import collections,datetime,hashlib,json,os,pathlib,re,shutil,subprocess,sys,time,traceback,urllib.request,xml.etree.ElementTree as ET
request=json.load(sys.stdin)
root=pathlib.Path("/home/qian-qi/work/hepta-audit-r3-fullgate-20261104")
tree=root/"source"; target=root/"target-app-epoch2-20261105"
out=root/"evidence"/request["evidence_name"];out.mkdir(exist_ok=False)
approved=request["guard"];source=approved["initial_tree"];counter=0;phases=[];reviews=[]
expected_locks=dict(approved["locks"]);temporary_config=None
env=dict(os.environ)
env["PATH"]=str(root/"tools/uv-venv/bin")+":"+str(root/"tools/bin")+":/home/qian-qi/.cargo/bin:/home/qian-qi/.local/bin:"+env.get("PATH","")
env.update(CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL="0",CARGO_BUILD_JOBS="4",RUSTUP_TOOLCHAIN="1.95.0",CARGO_NET_GIT_FETCH_WITH_CLI="true",PYTHONDONTWRITEBYTECODE="1",DOTSLASH_CACHE=str(root/"tools/dotslash-cache"),NEXTEST_PROFILE="local",UV_CACHE_DIR=str(out/"uv-cache"),UV_PYTHON_DOWNLOADS="never",RUSTY_V8_ARCHIVE=str(root/"tools/rusty-v8/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"),RUSTY_V8_SRC_BINDING_PATH=str(root/"tools/rusty-v8/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"))
def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def sha(b):return hashlib.sha256(b).hexdigest()
def oid(b):return hashlib.sha1(b"blob "+str(len(b)).encode()+b"\0"+b).hexdigest()
def rec(p):
 h=hashlib.sha256();size=0
 with pathlib.Path(p).open("rb") as f:
  while b:=f.read(1024*1024):h.update(b);size+=len(b)
 return {"path":str(p),"bytes":size,"sha256":h.hexdigest()}
def save(name,data):
 p=out/name;p.parent.mkdir(parents=True,exist_ok=True)
 b=(json.dumps(data,indent=2)+"\n").encode()
 with p.open("xb") as f:f.write(b)
 assert p.read_bytes()==b
 return p
def git(args,e=None):return subprocess.run(["git"]+args,cwd=tree,env=e or env,capture_output=True,check=True).stdout
def source_snapshot(label,check_locks=True):
 global counter
 counter+=1;e=dict(env);e["GIT_INDEX_FILE"]=str(out/(str(counter)+"-"+label+".index"))
 git(["read-tree",source],e);git(["add","-u","--","."],e)
 actual=git(["write-tree"],e).decode().strip()
 untracked=[os.fsdecode(p) for p in git(["ls-files","--others","--exclude-standard","-z"],e).split(b"\0") if p]
 allowed=list(approved["allowed_untracked_source_paths"])
 if temporary_config is not None:
  assert rec(tree/"user.bazelrc")["sha256"]==temporary_config["sha256"]
  allowed.append("user.bazelrc")
 ip=pathlib.Path(git(["rev-parse","--git-path","index"]).decode().strip());ip=ip if ip.is_absolute() else tree/ip
 result={"expected_source":source,"actual_source":actual,"head":git(["rev-parse","HEAD"]).decode().strip(),"ordinary_index":rec(ip),"locks":{p:rec(tree/p) for p in expected_locks},"untracked_source_paths":untracked,"allowed_untracked_source_paths":allowed}
 save(str(counter)+"-"+label+"-source-guard.json",result)
 assert result["head"]=="cabcb40d36e116beaa65750e1f674c52035da785"
 assert all(result["ordinary_index"][k]==approved["ordinary_index"][k] for k in ("bytes","sha256"))
 assert all(p in allowed for p in untracked),"unreviewed untracked source paths"
 if check_locks:
  assert all(result["locks"][p][k]==v[k] for p,v in expected_locks.items() for k in ("bytes","sha256")),"lock drift"
 return actual
def guard(label):assert source_snapshot(label)==source,"source drift at "+label
def split(p,label):
 data=pathlib.Path(p).read_bytes();directory=out/"parts"/label;directory.mkdir(parents=True,exist_ok=False);rows=[];offset=0
 while offset<len(data):
  end=min(offset+44000,len(data))
  while end<len(data) and data[end]&0xc0==0x80:end-=1
  q=directory/(str(len(rows)).zfill(4)+".txt")
  with q.open("xb") as f:f.write(data[offset:end])
  rows.append({"offset":offset,**rec(q)});offset=end
 return {"full":rec(p),"parts":rows}
def phase(name,argv,streams=False,cwd=None,allow_module_generation=False):
 global source,expected_locks
 assert shutil.disk_usage(tree).free>=8_000_000_000,"disk below 8GB before "+name
 guard(name+"-before");before=source;started=now();t=time.monotonic()
 stdout=out/(name+(".stdout" if streams else ".log"));stderr=out/(name+".stderr")
 save(name+"-command.json",{"argv":argv,"cwd":str(cwd or tree/"codex-rs"),"source":source,"started_at":started,"attempt":1,"cargo_profile":"dev-small","nextest_profile":"local","disk_before":dict(zip(("total","used","free"),shutil.disk_usage(tree)))})
 print(json.dumps({"phase_start":name,"source":source,"argv":argv}),flush=True)
 with stdout.open("xb") as so:
  if streams:
   with stderr.open("xb") as se:r=subprocess.run(argv,cwd=cwd or tree/"codex-rs",env=env,stdout=so,stderr=se)
  else:r=subprocess.run(argv,cwd=cwd or tree/"codex-rs",env=env,stdout=so,stderr=subprocess.STDOUT)
 result={"name":name,"argv":argv,"source_before":before,"exit_code":r.returncode,"started_at":started,"completed_at":now(),"duration_seconds":time.monotonic()-t,"stdout":split(stdout,name+"-stdout"),"disk_after":dict(zip(("total","used","free"),shutil.disk_usage(tree)))}
 if streams:result["stderr"]=split(stderr,name+"-stderr")
 if allow_module_generation:
  actual=source_snapshot(name+"-generator-result",False)
  paths=[p.decode() for p in git(["diff","--name-only","-z",before,actual]).split(b"\0") if p]
  result["generator_changed_paths"]=paths;result["generator_after_tree"]=actual
  assert set(paths).issubset({"MODULE.bazel.lock"}),"generator modified an unapproved source path"
  cargo=rec(tree/"codex-rs/Cargo.lock")
  assert all(cargo[k]==expected_locks["codex-rs/Cargo.lock"][k] for k in ("bytes","sha256"))
  patch=git(["diff",before,actual,"--","MODULE.bazel.lock"]);p=out/"actual-module-generator.patch";p.write_bytes(patch)
  result["actual_module_diff"]=rec(p);result["generated_module_lock"]={**rec(tree/"MODULE.bazel.lock"),"git_blob":git(["hash-object","--","MODULE.bazel.lock"]).decode().strip()}
  source=actual;expected_locks["MODULE.bazel.lock"]=rec(tree/"MODULE.bazel.lock")
  save("actual-lock-generation.json",result)
 result["source_after"]=source;result["source_unchanged"]=before==source
 phases.append(result);save(name+"-status.json",result)
 guard(name+"-after")
 print(json.dumps({"phase_terminal":name,"source":source,"exit_code":r.returncode,"seconds":result["duration_seconds"],"disk_after":result["disk_after"]}),flush=True)
 assert result["disk_after"]["free"]>=8_000_000_000,"disk below 8GB after "+name
 return result
def apply_stage(stage):
 global source
 assert source==stage["before_tree"]
 guard(stage["label"]+"-before")
 changes=[]
 for f in stage["files"]:
  p=tree/f["path"];b=request["sources"][f["after_blob"]].encode()
  assert not p.is_symlink() and p.is_file()
  assert git(["hash-object","--",f["path"]]).decode().strip()==f["before_blob"],"preimage mismatch "+f["path"]
  assert ("100755" if p.stat().st_mode&0o111 else "100644")==f["mode"]
  assert len(b)==f["bytes"] and sha(b)==f["sha256"] and oid(b)==f["after_blob"]
  changes.append((p,b))
 for p,b in changes:
  with p.open("wb") as stream:stream.write(b)
  assert p.read_bytes()==b
 e=dict(env);e["GIT_INDEX_FILE"]=str(out/(stage["label"]+"-apply.index"));git(["read-tree",source],e);git(["add","-u","--","."],e)
 actual=git(["write-tree"],e).decode().strip()
 assert actual==stage["after_tree"],"applied tree mismatch "+actual
 source=actual;guard(stage["label"]+"-after");save(stage["label"]+"-apply.json",stage)
def bin_records(catalog):
 rows=[]
 def visit(v):
  if isinstance(v,dict):
   if v.get("kind")=="bin-exe" and isinstance(v.get("path"),str):
    p=pathlib.Path(v["path"]);p=p if p.is_absolute() else pathlib.Path(catalog["rust-build-meta"]["target-directory"])/p
    assert p.resolve().is_relative_to(target.resolve())
    rows.append({"catalog_entry":v,**rec(p)})
   for c in v.values():visit(c)
  elif isinstance(v,list):
   for c in v:visit(c)
 visit(catalog["rust-build-meta"]["non-test-binaries"])
 return rows
def clean_ansi(s):
 s=re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",s)
 return re.sub(r"(?:\\x1b|\\u001b|\\u\{1b\})\[[0-?]*[ -/]*[@-~]","",s)
def run_scope(scope):
 name=scope["label"];args=scope["package_args"];expression=scope.get("expression");filter_args=["-E",expression] if expression else []
 metadata=phase(name+"-metadata",["cargo","metadata","--format-version=1","--locked"],True)
 assert metadata["exit_code"]==0
 cat=phase(name+"-catalog",["cargo","nextest","list","--locked","--cargo-profile","dev-small"]+args+filter_args+["--message-format=json"],True)
 assert cat["exit_code"]==0
 catalog=json.loads((out/(name+"-catalog.stdout")).read_text());selected=[];ignored=[];unmatched=[];programs=[]
 for sid,suite in catalog["rust-suites"].items():
  matched=False
  for case,item in suite["testcases"].items():
   row={"classname":sid,"name":case,"package":suite["package-name"],"ignored":item["ignored"],"filter_match":item["filter-match"]}
   if item["filter-match"]["status"]=="matches" and not item["ignored"]:selected.append(row);matched=True
   elif item["ignored"]:ignored.append(row)
   else:unmatched.append(row)
  if matched:
   p=pathlib.Path(suite["binary-path"]);assert p.resolve().is_relative_to(target.resolve())
   programs.append({"binary_id":sid,**rec(p)})
 keys=lambda rows:collections.Counter((x["classname"],x["name"]) for x in rows)
 assert keys(selected)==keys(scope["expected_cases"]),"catalog selected roster mismatch"
 helpers=bin_records(catalog)
 selection={"source":source,"scope":scope,"selected":selected,"original_ignored":ignored,"filter_unmatched":unmatched,"programs_after_catalog_before_just":programs,"catalog_helpers_after_catalog_before_just":helpers,"catalog_non_test_binaries":catalog["rust-build-meta"]["non-test-binaries"],"feature_scope":"Only the declared package selection is built for this iteration; the later original full-workspace graph remains a separate gate."}
 p=save(name+"-selection.json",selection);save(name+"-selection.parts.json",split(p,name+"-selection"))
 junit=tree/"codex-rs/target/nextest/local/junit.xml";prior=rec(junit) if junit.is_file() else None;started=time.time_ns()
 test=phase(name,["just","test","--locked","--cargo-profile","dev-small"]+args+filter_args+["--no-tests","fail","--retries","0","--success-output","immediate"])
 assert junit.is_file() and junit.stat().st_mtime_ns>=started-2_000_000_000,"fresh JUnit missing"
 assert prior is None or rec(junit)["sha256"]!=prior["sha256"],"stale JUnit"
 jp=out/(name+".junit.xml");jp.write_bytes(junit.read_bytes());cases=[]
 for c in ET.parse(jp).getroot().iter("testcase"):
  outcome="FAIL" if c.find("failure") is not None else "ERROR" if c.find("error") is not None else "SKIP" if c.find("skipped") is not None else "PASS"
  cases.append({"classname":c.attrib.get("classname"),"name":c.attrib.get("name"),"seconds":c.attrib.get("time"),"result":outcome,"failure":"\n".join(x.text or "" for x in c if x.tag in ("failure","error"))})
 programs_after=[{"binary_id":p["binary_id"],**rec(p["path"])} for p in programs]
 helpers_after=[{"catalog_entry":p["catalog_entry"],**rec(p["path"])} for p in helpers]
 raw=(out/(name+".log")).read_text();clean=clean_ansi(raw)
 early=[l for l in clean.splitlines() if re.search(r"\bskipping\b|requires a remote test environment|requires remote test environment",l,re.I)]
 valid=keys(selected)==keys(cases) and programs==programs_after and helpers==helpers_after and not early and not any(c["result"]=="SKIP" for c in cases)
 review={"label":name,"source":source,"packages":args,"selected_count":len(selected),"cases":cases,"counts":dict(collections.Counter(c["result"] for c in cases)),"exit_code":test["exit_code"],"retries":0,"original_ignored_count":len(ignored),"filter_unmatched_count":len(unmatched),"programs_before":programs,"programs_after":programs_after,"helpers_before":helpers,"helpers_after":helpers_after,"programs_stable":programs==programs_after,"helpers_stable":helpers==helpers_after,"exact_roster":keys(selected)==keys(cases),"early_return_notices":early,"selection_valid":valid,"source_unchanged":True,"raw":rec(out/(name+".log")),"fresh_junit":rec(jp),"nextest_summaries":[l for l in clean.splitlines() if "Starting " in l or "Summary" in l],"graph_limit":"Scoped iteration on the documented package argv; not whole-workspace qualification."}
 p=save(name+"-review.json",review);save(name+"-review.parts.json",split(p,name+"-review"));reviews.append(review)
 assert valid,"selected test identity/observation incomplete"
 return review,clean
def qualify_negative(kind,review,raw):
 assert review["exit_code"]==100 and len(review["cases"])==1 and review["cases"][0]["result"]=="FAIL"
 failure=clean_ansi(review["cases"][0]["failure"]);proof={"kind":kind,"source":source,"case":review["cases"][0],"original_exit":review["exit_code"],"raw_sha256":review["raw"]["sha256"]}
 if kind=="skills":
  diff=failure.split("Diff < left / right >",1)[1] if "Diff < left / right >" in failure else ""
  diff=diff.split("\n\n",1)[0]
  left_lines=[line for line in diff.splitlines() if not line.lstrip().startswith(">")]
  added_lines=[line for line in left_lines if line.lstrip().startswith("<")]
  left_paths=re.findall(r'"([^"\n]+/\.agents/skills)"',"\n".join(left_lines))
  added_paths=re.findall(r'"([^"\n]+/\.agents/skills)"',"\n".join(added_lines))
  outer=left_paths[0][:-len("/.agents/skills")] if left_paths and left_paths[0].endswith("/outer/.agents/skills") else None
  expected_paths=[outer+"/.agents/skills",outer+"/nested/inner/.agents/skills"] if outer else []
  proof["actual_left_vector_paths"]=left_paths;proof["added_left_paths"]=added_paths
  conditions={"original_assertion_location":"ext/skills/src/host_roots_tests.rs:441:" in failure,"exact_vector_assertion":"assertion failed:" in failure and "Diff < left / right >" in failure,"controlled_outer_added":bool(outer and expected_paths[0] in added_paths),"exact_actual_ordered_outer_and_cwd":bool(outer and left_paths==expected_paths),"not_timeout":"TIMEOUT" not in raw}
 elif kind=="migration":
  conditions={"child_original_assertion_location":"external-agent-migration/src/service_tests/plugins/marketplaces.rs:588:" in raw,"child_original_equality":"assertion failed:" in raw and "Diff < left / right >" in raw,"original_inferred_name":'"claude-plugins-official"' in raw,"child_one_failed":"test result: FAILED. 0 passed; 1 failed; 0 ignored;" in raw,"parent_reports_child_failure":"isolated import assertions failed" in raw,"not_timeout":"TIMEOUT" not in raw}
 else:raise AssertionError("unexpected negative kind")
 proof["conditions"]=conditions;proof["qualified"]=all(conditions.values());save(kind+"-causal-negative.json",proof)
 assert proof["qualified"],"negative failed before required causal oracle"
 return proof
def require_pass(review):
 assert review["exit_code"]==0 and all(x["result"]=="PASS" for x in review["cases"]),"positive scope failed"
def run_negative_and_restore(kind,scope,restore_stage):
 primary=None;proof=None;restored=False;original_exception=None;restore_exception=None
 try:
  review,raw=run_scope(scope);proof=qualify_negative(kind,review,raw)
 except BaseException as e:
  primary=e;original_exception={"type":type(e).__name__,"message":str(e),"traceback":"".join(traceback.format_exception(type(e),e,e.__traceback__))}
 finally:
  try:
   assert source==restore_stage["before_tree"],"not the owned negative tree; refusing restoration"
   guard(kind+"-negative-finally-restore-eligible")
   apply_stage(restore_stage);restored=True
  except BaseException as e:
   restore_exception={"type":type(e).__name__,"message":str(e),"traceback":"".join(traceback.format_exception(type(e),e,e.__traceback__))}
   if primary is None:primary=e
  save(kind+"-negative-finally-restore.json",{"negative_tree":restore_stage["before_tree"],"positive_tree":restore_stage["after_tree"],"actual_source_at_return":source,"restored_exact_positive":restored,"original_exception":original_exception,"restoration_exception":restore_exception,"negative_qualified":bool(proof and proof["qualified"]),"positive_tests_allowed":bool(restored and primary is None and proof and proof["qualified"]),"contract":"Restore only after exact owned-negative source, ordinary index, locks and untracked-input guards pass. An invalid negative remains invalid and stops after restoration; external drift is never overwritten."})
 if primary is not None:raise primary
 assert restored and proof and proof["qualified"]
 return proof
def install_bazel():
 pin=approved["bazel_bootstrap"];directory=out/"official-bazel";directory.mkdir(exist_ok=False)
 assert (tree/".bazelversion").read_text()=="9.3.0\n"
 installed=root/"tools/bin/bazel";assert not installed.exists() and not installed.is_symlink(),"Bazel appeared after reviewed preflight"
 rows=[]
 for a in pin["assets"]:
  assert a["url"].startswith("https://github.com/bazelbuild/bazel/releases/download/9.3.0/")
  p=directory/a["name"]
  with urllib.request.urlopen(a["url"],timeout=120) as response,p.open("xb") as f:
   while b:=response.read(1024*1024):f.write(b)
  observed=rec(p);assert observed["bytes"]==a["size"] and observed["sha256"]==a["sha256"],"official Bazel asset checksum mismatch"
  rows.append({"url":a["url"],"release_asset_id":a["id"],**observed})
 binary=directory/"bazel-9.3.0-linux-x86_64";checksum=(directory/"bazel-9.3.0-linux-x86_64.sha256").read_text().strip()
 parts=checksum.split();assert len(parts)==2 and parts[0]==rec(binary)["sha256"] and parts[1].lstrip("*")=="bazel-9.3.0-linux-x86_64"
 with installed.open("xb") as f:
  with binary.open("rb") as source_file:shutil.copyfileobj(source_file,f)
 installed.chmod(0o755);assert rec(installed)["sha256"]==rec(binary)["sha256"]
 save("official-bazel-bootstrap.json",{"pin":pin,"downloads":rows,"checksum_text":checksum,"installed":rec(installed),"system_paths_unchanged":True})
 version=phase("official-bazel-version",["bazel","--version"],True,cwd=tree)
 assert version["exit_code"]==0 and (out/"official-bazel-version.stdout").read_text().strip()=="bazel 9.3.0"
def generate_module_lock():
 global temporary_config
 cache=root/"v8-lock-cache-20261105";assert not cache.exists() and not cache.is_symlink()
 config=tree/"user.bazelrc";assert not config.exists() and not config.is_symlink()
 cache.mkdir(exist_ok=False)
 values={"output-user-root":"startup --output_user_root=","repo-contents-cache":"common --repo_contents_cache=","repository-cache":"common --repository_cache=","disk-cache":"common --disk_cache="}
 text="".join(prefix+str(cache/name)+"\n" for name,prefix in values.items())
 assert text==approved["temporary_bazel_config"]
 with config.open("xb") as f:f.write(text.encode())
 temporary_config=rec(config);save("temporary-task-user-bazelrc.json",{"content":text,"file":temporary_config,"cache_root":str(cache),"scope":"Only this previously absent task source override, through the original try-import; no original security or experimental flags removed."})
 primary=None
 try:
  update=phase("original-bazel-lock-update",["just","bazel-lock-update"],True,cwd=tree,allow_module_generation=True)
  assert update["exit_code"]==0,"original bazel lock update failed"
  check=phase("original-bazel-lock-check",["just","bazel-lock-check"],True,cwd=tree)
  assert check["exit_code"]==0,"original bazel lock check failed"
 except BaseException as e:primary=e
 finally:
  try:
   shutdown=phase("task-owned-bazel-server-shutdown",["bazel","shutdown"],True,cwd=tree)
   save("task-owned-bazel-shutdown-result.json",{"exit_code":shutdown["exit_code"],"only_cache_root":str(cache),"cache_preserved":True})
   if shutdown["exit_code"]!=0 and primary is None:primary=RuntimeError("task-owned Bazel shutdown failed")
  except BaseException as shutdown_error:
   save("task-owned-bazel-shutdown-error.json",{"error_type":type(shutdown_error).__name__,"error":str(shutdown_error),"traceback":traceback.format_exc(),"original_primary_error":str(primary) if primary is not None else None})
   if primary is None:primary=shutdown_error
  finally:
   assert rec(config)["sha256"]==temporary_config["sha256"],"temporary config was changed externally; do not remove it"
   config.unlink();temporary_config=None
   save("temporary-task-user-bazelrc-restored.json",{"path":str(config),"exists":config.exists(),"cache_preserved":True})
 if primary is not None:raise primary
 guard("after-original-lock-gates")
def export_source():
 rows=[]
 for path in [p.decode() for p in git(["diff","--name-only","-z","f8251e1d14fa8524ab469281296cd4cf708f173c",source]).split(b"\0") if p]:
  mode,kind,blob=git(["ls-tree",source,"--",path]).decode().split("\t")[0].split()
  rows.append({"path":path,"mode":mode,"git_blob":blob,**{k:v for k,v in rec(tree/path).items() if k!="path"}})
 save("final-source-map.json",{"before_tree":approved["initial_tree"],"final_tree":source,"paths":rows})
try:
 assert approved["initial_tree"]=="f8251e1d14fa8524ab469281296cd4cf708f173c"
 assert re.fullmatch("[0-9a-f]{40}",request["root_guard_blob"])
 assert target.is_dir() and not target.is_symlink()
 assert not any(k in os.environ for k in ("CODEX_SANDBOX_NETWORK_DISABLED","CODEX_SANDBOX"))
 (out/"runner.py").write_text(request["runner_source"]);save("root-guard.json",approved)
 guard("initial")
 git_program=pathlib.Path(shutil.which("git",path=env["PATH"]));save("native-host-and-tools.json",{"observed_at":now(),"uname":subprocess.run(["uname","-srm"],capture_output=True,text=True,check=True).stdout,"rustc_vv":subprocess.run(["rustc","-vV"],env=env,capture_output=True,text=True,check=True).stdout,"git_program":rec(git_program),"target":str(target),"old_target_untouched":str(root/"target"),"disk":dict(zip(("total","used","free"),shutil.disk_usage(tree)))})
 stages=approved["stages"];scopes=approved["scopes"]
 apply_stage(stages[0]);skills_proof=run_negative_and_restore("skills",scopes[0],stages[1])
 r,raw=run_scope(scopes[1]);require_pass(r)
 apply_stage(stages[2]);migration_proof=run_negative_and_restore("migration",scopes[2],stages[3])
 r,raw=run_scope(scopes[3]);require_pass(r)
 assert "test result: ok. 1 passed; 0 failed; 0 ignored;" in raw,"original migration child output missing"
 apply_stage(stages[4])
 install_bazel();generate_module_lock()
 r,raw=run_scope(scopes[4]);require_pass(r)
 guard("final");export_source()
 result={"source":source,"root_guard_blob":request["root_guard_blob"],"target":str(target),"host":"rog","cargo_profile":"dev-small","nextest_profile":"local","retries":0,"skills_causal_negative":skills_proof,"migration_causal_negative":migration_proof,"reviews":reviews,"locks":expected_locks,"phases":phases,"source_and_ordinary_index_guards_passed":True,"next_step":"Stop for root review. No final hygiene or whole-workspace rerun in this stage."}
 p=save("terminal.json",result);save("terminal.parts.json",split(p,"terminal"))
 print(json.dumps({"terminal":True,"source":source,"scopes":[{"label":r["label"],"counts":r["counts"],"exit_code":r["exit_code"]} for r in reviews],"lock_generator_actual":True}),flush=True)
except BaseException as e:
 save("driver-error.json",{"source":source,"error_type":type(e).__name__,"error":str(e),"traceback":traceback.format_exc(),"phases":phases,"review_count":len(reviews),"temporary_config_active":temporary_config})
 print(json.dumps({"terminal":False,"source":source,"driver_error":str(e)}),flush=True)
 raise
