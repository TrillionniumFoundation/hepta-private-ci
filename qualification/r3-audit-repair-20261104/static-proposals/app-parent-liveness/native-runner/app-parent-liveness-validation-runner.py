import collections,datetime,hashlib,json,os,pathlib,re,shutil,subprocess,sys,time,traceback,errno,xml.etree.ElementTree as ET
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

def clean_ansi(s):
 s=re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",s)
 return re.sub(r"(?:\\x1b|\\u001b|\\u\{1b\})\[[0-?]*[ -/]*[@-~]","",s)

def require_pass(review):
 assert review["exit_code"]==0 and all(x["result"]=="PASS" for x in review["cases"]),"positive scope failed"

def read_proc_stat(pid):
 try:
  data=(pathlib.Path("/proc")/str(pid)/"stat").read_text()
  end=data.rfind(")");parts=data[end+2:].split()
  return {"pid":pid,"comm":data[data.find("(")+1:end],"state":parts[0],"ppid":int(parts[1]),"pgid":int(parts[2]),"sid":int(parts[3]),"starttime_ticks":int(parts[19])}
 except (FileNotFoundError,ProcessLookupError,PermissionError,ValueError,IndexError):return None

def observe_owned_command(argv,stream):
 proc=subprocess.Popen(argv,cwd=tree/"codex-rs",env=env,stdout=stream,stderr=subprocess.STDOUT)
 started=time.monotonic();owned={};previous={};markers=set();events=0;samples=0;errors=[];last=[]
 root_stat=read_proc_stat(proc.pid)
 root_identity=(proc.pid,root_stat["starttime_ticks"]) if root_stat is not None else None
 if root_identity is None:errors.append({"type":"RootIdentityUnavailable","message":"Initial owned command PID/starttime could not be observed."})
 log_path=out/"owned-process-observations.jsonl"
 # The dynamic marker is never inserted into any observer subprocess argv.
 # Read all structural /proc stat records, but read cmdline/exe only for this
 # command's observed descendants or the same already-owned PID/starttime pair.
 with log_path.open("w") as log:
  def emit(event):
   nonlocal events
   log.write(json.dumps({"observed_at":now(),"elapsed_seconds":time.monotonic()-started,**event})+"\n");log.flush();events+=1
  def sample():
   nonlocal previous,samples,last
   samples+=1;table={}
   for entry in pathlib.Path("/proc").iterdir():
    if not entry.name.isdigit():continue
    st=read_proc_stat(int(entry.name))
    if st is not None:table[st["pid"]]=st
   root_current=table.get(proc.pid)
   root_matches=root_identity is not None and root_current is not None and root_current["starttime_ticks"]==root_identity[1]
   descendants={proc.pid} if root_matches else set();changed=True
   while changed:
    changed=False
    for pid,st in table.items():
     if st["ppid"] in descendants and pid not in descendants:descendants.add(pid);changed=True
   for pid in descendants:
    if pid in table:owned[(pid,table[pid]["starttime_ticks"])]=True
   observed={}
   for identity in owned:
    pid,starttime=identity;st=table.get(pid)
    if st is None or st["starttime_ticks"]!=starttime:continue
    row=dict(st)
    row["scope"]="current-descendant" if pid in descendants else "previously-observed-owned-identity"
    path=pathlib.Path("/proc")/str(pid)
    try:
     with (path/"cmdline").open("rb") as f:cmd=f.read(16385)
     row["cmdline_truncated"]=len(cmd)>16384;cmd=cmd[:16384]
     row["cmdline_bytes_observed"]=len(cmd);row["cmdline_sha256"]=sha(cmd)
     row["cmdline"]=[arg.decode("utf-8","replace") for arg in cmd.rstrip(b"\0").split(b"\0")] if cmd else []
     found=sorted(set(re.findall(r"codex-command-exec-marker-[0-9]+",cmd.decode("utf-8","replace"))))
     row["exact_fixture_markers"]=found;markers.update(found)
    except (FileNotFoundError,ProcessLookupError,PermissionError) as e:row["cmdline_read_error"]=type(e).__name__
    try:row["exe"]=os.readlink(path/"exe")
    except (FileNotFoundError,ProcessLookupError,PermissionError) as e:row["exe_read_error"]=type(e).__name__
    observed[identity]=row
    if previous.get(identity)!=row:emit({"event":"owned-process-state","process":row})
   for identity in previous:
    if identity not in observed:emit({"event":"owned-identity-no-longer-observed","pid":identity[0],"starttime_ticks":identity[1]})
   previous=observed;last=list(observed.values())
  emit({"event":"observer-start","command_pid":proc.pid,"command_starttime_ticks":root_identity[1] if root_identity is not None else None,"observer_pid":os.getpid(),"sampling_interval_seconds":0.05,"no_observer_marker_subprocess":True})
  try:
   while proc.poll() is None:sample();time.sleep(0.05)
   sample()
  except Exception as e:
   errors.append({"type":type(e).__name__,"message":str(e)})
   emit({"event":"observer-error","error":errors[-1],"original_test_is_not_cancelled":True})
  returncode=proc.wait()
  emit({"event":"observer-terminal","original_command_exit":returncode,"samples":samples,"known_fixture_markers":sorted(markers)})
 save("owned-process-observation-summary.json",{"source":source,"command":argv,"command_pid":proc.pid,"command_starttime_ticks":root_identity[1] if root_identity is not None else None,"exit_code":returncode,"samples":samples,"events":events,"known_fixture_markers":sorted(markers),"observer_errors":errors,"last_observed_owned_processes":last,"trace":rec(log_path),"limit":"Only observed descendants and identical previously-owned PID/starttime pairs were read. A process that detached before the first observation can be missed. No global cmdline or environment dump, process signal, strace, test deadline change or source change was performed."})
 return subprocess.CompletedProcess(argv,returncode)


def phase(name, argv, streams=False, observe=False):
 assert shutil.disk_usage(tree).free >= 8_000_000_000, "disk below 8GB before " + name
 guard(name + "-before"); before = source; started = now(); clock = time.monotonic()
 stdout = out / (name + (".stdout" if streams else ".log")); stderr = out / (name + ".stderr")
 save(name + "-command.json", {"argv": argv, "cwd": str(tree / "codex-rs"), "source": source, "started_at": started, "attempt": 1, "cargo_profile": "dev-small", "nextest_profile": "local", "disk_before": dict(zip(("total", "used", "free"), shutil.disk_usage(tree)))})
 print(json.dumps({"phase_start": name, "source": source, "argv": argv}), flush=True)
 with stdout.open("xb") as so:
  if streams:
   with stderr.open("xb") as se: result = subprocess.run(argv, cwd=tree / "codex-rs", env=env, stdout=so, stderr=se)
  elif observe: result = observe_owned_command(argv, so)
  else: result = subprocess.run(argv, cwd=tree / "codex-rs", env=env, stdout=so, stderr=subprocess.STDOUT)
 record = {"name": name, "argv": argv, "source_before": before, "source_after": source, "source_unchanged": before == source, "exit_code": result.returncode, "started_at": started, "completed_at": now(), "duration_seconds": time.monotonic() - clock, "stdout": split(stdout, name + "-stdout"), "disk_after": dict(zip(("total", "used", "free"), shutil.disk_usage(tree)))}
 if streams: record["stderr"] = split(stderr, name + "-stderr")
 phases.append(record); save(name + "-status.json", record)
 guard(name + "-after")
 print(json.dumps({"phase_terminal": name, "source": source, "exit_code": result.returncode, "seconds": record["duration_seconds"], "disk_after": record["disk_after"]}), flush=True)
 assert record["disk_after"]["free"] >= 8_000_000_000, "disk below 8GB after " + name
 return record

def apply_stage(stage):
 global source
 assert source == stage["before_tree"]
 guard(stage["label"] + "-before"); changes = []; new_paths = []
 for f in stage["files"]:
  relative = pathlib.PurePosixPath(f["path"])
  assert not relative.is_absolute() and ".." not in relative.parts
  p = tree / f["path"]; b = request["sources"][f["after_blob"]].encode()
  assert p.resolve().is_relative_to(tree.resolve()) and not p.is_symlink()
  assert len(b) == f["bytes"] and sha(b) == f["sha256"] and oid(b) == f["after_blob"]
  if f["before_blob"] is None:
   assert not p.exists(), "new source path already exists: " + f["path"]
   assert p.parent.is_dir() and f["mode"] == "100644"
   new_paths.append(f["path"])
  else:
   assert p.is_file() and git(["hash-object", "--", f["path"]]).decode().strip() == f["before_blob"]
   assert ("100755" if p.stat().st_mode & 0o111 else "100644") == f["mode"]
  changes.append((p, b, f["before_blob"] is None))
 for p, b, is_new in changes:
  with p.open("xb" if is_new else "wb") as stream: assert stream.write(b) == len(b)
  assert p.read_bytes() == b
 e = dict(env); e["GIT_INDEX_FILE"] = str(out / (stage["label"] + "-apply.index"))
 git(["read-tree", source], e); git(["add", "-u", "--", "."], e)
 if new_paths: git(["add", "--"] + new_paths, e)
 actual = git(["write-tree"], e).decode().strip()
 assert actual == stage["after_tree"], "applied tree mismatch: " + actual
 source = actual; guard(stage["label"] + "-after"); save(stage["label"] + "-apply.json", stage)

def feature_graph(metadata):
 return {"workspace_members": sorted(metadata["workspace_members"]), "nodes": sorted(({"id": node["id"], "features": sorted(node["features"]), "deps": node.get("deps", [])} for node in metadata["resolve"]["nodes"]), key=lambda node: node["id"])}

def normal_helpers(name):
 argv = approved["normal_helper_build"]
 build = phase(name + "-normal-six-helper-build", argv, True)
 assert build["exit_code"] == 0, "normal source-bound helper build failed"
 wanted = {"test_arg0_preflight", "codex-code-mode-host", "codex-execve-wrapper", "test_stdio_server", "test_streamable_http_server", "codex-exec"}
 artifacts = []; finished = []; count = 0
 for line in (out / (name + "-normal-six-helper-build.stdout")).read_text().splitlines():
  if not line.strip(): continue
  message = json.loads(line); count += 1
  if message.get("reason") == "build-finished": finished.append(message)
  if message.get("reason") == "compiler-artifact" and message.get("executable") and message["target"]["name"] in wanted:
   p = pathlib.Path(message["executable"]); assert p.resolve().is_relative_to(target.resolve())
   artifacts.append({"package_id": message["package_id"], "target": message["target"], "profile": message["profile"], "features": message["features"], "fresh": message["fresh"], **rec(p)})
 assert finished == [{"reason": "build-finished", "success": True}]
 assert len(artifacts) == 6 and {a["target"]["name"] for a in artifacts} == wanted
 save(name + "-normal-six-helper-receipt.json", {"source": source, "argv": argv, "compiler_message_count": count, "artifacts": artifacts, "build_finished": finished, "stdout": rec(out / (name + "-normal-six-helper-build.stdout")), "stderr": rec(out / (name + "-normal-six-helper-build.stderr")), "limit": "Actual normal build at this source. Subsequent full catalogue may rebuild with workspace feature unification; actual after-catalogue identities are recorded independently."})
 return artifacts

def helper_records(catalog, normal):
 rows = []
 def visit(value):
  if isinstance(value, dict):
   if value.get("kind") == "bin-exe" and isinstance(value.get("path"), str):
    p = pathlib.Path(value["path"]); p = p if p.is_absolute() else pathlib.Path(catalog["rust-build-meta"]["target-directory"]) / p
    rows.append({"origin": "nextest-catalog", "catalog_entry": value, **rec(p)})
   for child in value.values(): visit(child)
  elif isinstance(value, list):
   for child in value: visit(child)
 visit(catalog["rust-build-meta"]["non-test-binaries"])
 for artifact in normal: rows.append({"origin": "normal-six-helper-build", "target_name": artifact["target"]["name"], **rec(artifact["path"])})
 paths = {}
 for row in rows: paths.setdefault(row["path"], []).append({k: v for k, v in row.items() if k not in ("path", "bytes", "sha256")})
 result = [{"origins": origins, **rec(path)} for path, origins in sorted(paths.items())]
 assert all(pathlib.Path(h["path"]).resolve().is_relative_to(target.resolve()) for h in result)
 assert sorted(pathlib.Path(h["path"]).name for h in result) == approved["historical_helper_basename_roster"]
 return result

def run_scope(scope):
 name = scope["label"]; expression = scope["expression"]; normal = normal_helpers(name)
 metadata = phase(name + "-metadata", ["cargo", "metadata", "--format-version=1", "--locked"], True)
 assert metadata["exit_code"] == 0
 current_metadata = json.loads((out / (name + "-metadata.stdout")).read_text()); current_graph = feature_graph(current_metadata)
 assert current_graph == baseline_graph, "full workspace feature graph differs from actual 7d source"
 assert len(current_graph["workspace_members"]) == 193 and len(current_graph["nodes"]) == 1501
 save(name + "-feature-graph-binding.json", {"source": source, "baseline_source": approved["initial_tree"], "baseline": approved["baseline_metadata"], "current": rec(out / (name + "-metadata.stdout")), "workspace_members": 193, "resolved_nodes": 1501, "full_resolve_and_features_equal": True, "package_filter": None, "default_members_not_used_to_limit_scope": True})
 catalog_command = ["cargo", "nextest", "list", "--locked", "--cargo-profile", "dev-small", "--message-format=json", "-E", expression]
 cat = phase(name + "-catalog", catalog_command, True); assert cat["exit_code"] == 0
 catalog = json.loads((out / (name + "-catalog.stdout")).read_text()); selected = []; ignored = []; unmatched = []; programs = []
 for sid, suite in catalog["rust-suites"].items():
  matched = False
  for case, item in suite["testcases"].items():
   row = {"classname": sid, "name": case, "package": suite["package-name"], "ignored": item["ignored"], "filter_match": item["filter-match"]}
   if item["filter-match"]["status"] == "matches" and not item["ignored"]: selected.append(row); matched = True
   elif item["ignored"]: ignored.append(row)
   else: unmatched.append(row)
  if matched:
   p = pathlib.Path(suite["binary-path"]); assert p.resolve().is_relative_to(target.resolve())
   programs.append({"binary_id": sid, **rec(p)})
 keys = lambda rows: collections.Counter((row["classname"], row["name"]) for row in rows)
 assert keys(selected) == keys(scope["expected_cases"]), "catalog selected roster mismatch"
 support = [r for r in ignored if r["classname"] == "codex-linux-sandbox" and r["name"] == "parent_lifecycle::tests::owned_liveness_scenario"]
 assert len(support) == 1, "ignored owned support catalogue identity missing"
 helpers = helper_records(catalog, normal)
 selection = {"source": source, "scope": scope, "selected": selected, "original_ignored": ignored, "filter_unmatched": unmatched, "ignored_owned_support_not_counted_as_pass": support, "programs_after_catalog_before_just": programs, "helpers_after_catalog_before_just": helpers, "normal_build_artifacts_before_catalog": normal, "normal_build_artifacts_after_catalog": [{"target_name": h["target"]["name"], **rec(h["path"])} for h in normal], "catalog_non_test_binaries": catalog["rust-build-meta"]["non-test-binaries"], "exact_full_workspace_graph": True}
 saved = save(name + "-selection.json", selection); save(name + "-selection.parts.json", split(saved, name + "-selection"))
 junit = tree / "codex-rs/target/nextest/local/junit.xml"; prior = rec(junit) if junit.is_file() else None; started = time.time_ns()
 argv = ["just", "test", "--locked", "--cargo-profile", "dev-small", "--no-tests", "fail", "--retries", "0", "--success-output", "immediate", "-E", expression]
 tested = phase(name, argv, observe=scope.get("observe_original_app", False))
 assert junit.is_file() and junit.stat().st_mtime_ns >= started - 2_000_000_000, "fresh JUnit missing"
 assert prior is None or rec(junit)["sha256"] != prior["sha256"], "stale JUnit"
 copied = out / (name + ".junit.xml")
 with copied.open("xb") as stream: stream.write(junit.read_bytes())
 cases = []
 for case in ET.parse(copied).getroot().iter("testcase"):
  result = "FAIL" if case.find("failure") is not None else "ERROR" if case.find("error") is not None else "SKIP" if case.find("skipped") is not None else "PASS"
  cases.append({"classname": case.attrib.get("classname"), "name": case.attrib.get("name"), "seconds": case.attrib.get("time"), "result": result, "failure": "\n".join(child.text or "" for child in case if child.tag in ("failure", "error"))})
 programs_after = [{"binary_id": p["binary_id"], **rec(p["path"])} for p in programs]
 helpers_after = [{"origins": h["origins"], **rec(h["path"])} for h in helpers]
 raw = (out / (name + ".log")).read_text(); clean = clean_ansi(raw)
 early = [line for line in clean.splitlines() if re.search(r"\bskipping\b|requires a remote test environment|requires remote test environment", line, re.I)]
 valid = keys(cases) == keys(selected) and programs == programs_after and helpers == helpers_after and not early and not any(c["result"] == "SKIP" for c in cases)
 review = {"label": name, "source": source, "selected_count": len(selected), "cases": cases, "counts": dict(collections.Counter(c["result"] for c in cases)), "exit_code": tested["exit_code"], "retries": 0, "original_ignored_count": len(ignored), "filter_unmatched_count": len(unmatched), "programs_before": programs, "programs_after": programs_after, "helpers_before": helpers, "helpers_after": helpers_after, "programs_stable": programs == programs_after, "helpers_stable": helpers == helpers_after, "exact_roster": keys(cases) == keys(selected), "early_return_notices": early, "selection_valid": valid, "source_unchanged": True, "full_workspace_graph_equal": True, "raw": rec(out / (name + ".log")), "fresh_junit": rec(copied), "nextest_summaries": [line for line in clean.splitlines() if "Starting " in line or "Summary" in line]}
 if scope.get("observe_original_app", False):
  observation = json.loads((out / "owned-process-observation-summary.json").read_text())
  review["supplemental_owned_process_observation"] = observation
  review["supplemental_observation_complete"] = not observation["observer_errors"] and len(observation["known_fixture_markers"]) == 1
  review["observation_limit"] = "Supplemental read-only evidence, separate from the unchanged original test oracle. A process shorter than the existing 50ms observation interval may be missed; missing observation is never asserted to show process termination."
 saved = save(name + "-review.json", review); save(name + "-review.parts.json", split(saved, name + "-review")); reviews.append(review)
 assert valid, "selected test identity or observation prerequisite incomplete"
 return review, clean

def qualify_negative(kind, review, raw):
 assert review["exit_code"] == 100 and len(review["cases"]) == 1 and review["cases"][0]["result"] == "FAIL"
 failure = clean_ansi(review["cases"][0]["failure"])
 text = clean_ansi(raw)
 proof = {"kind": kind, "source": source, "case": review["cases"][0], "raw": review["raw"], "exit_code": review["exit_code"], "test_source": approved["control_source"], "mechanical_source_order": approved["causal_source_anchors"][kind]}
 conditions = {"inherited_unread_parent_marker": "LIVENESS: inherited_unread_parent" in text, "not_outer_timeout": "TIMEOUT" not in text}
 if kind == "no_exit_rejection":
  conditions.update(actual_reparented_ok="actual reparented liveness result=Ok(())" in text, exact_child_assertion="exited original parent was admitted" in text, exact_assert_location="parent_lifecycle_tests.rs:258:" in text)
 elif kind == "no_rearm":
  conditions.update(armed_after_fd_close_and_exec="LIVENESS: armed_with_fd_closed_before_fork_and_exec" in text, exact_own_five_second_oracle="reaper survived original launcher exit" in text, exact_oracle_location="parent_lifecycle_tests.rs:111:" in text, no_launcher_waitid_timeout="original launcher did not exit" not in text)
 elif kind == "leaked_parent_fd":
  child_pattern = r"(?m)^[ \t]*thread 'parent_lifecycle::tests::owned_liveness_scenario'(?: \([0-9]+\))? panicked at [^\n]*parent_lifecycle_tests\.rs:268:\d+:\n"
  child_starts = list(re.finditer(child_pattern, text)); child_blocks = []
  for start in child_starts:
   following = text[start.end():]
   boundary = re.search(r"(?m)^[ \t]*(?:thread '[^']+'(?: \([0-9]+\))? panicked at|failures:|test result:)", following)
   end = start.end() + boundary.start() if boundary else len(text)
   child_blocks.append({"ansi_normalized_character_span": [start.start(), end], "stderr_block": text[start.start():end]})
  proof["exact_owned_child_panic_blocks"] = child_blocks
  child_text = child_blocks[0]["stderr_block"] if len(child_blocks) == 1 else ""
  diffs = re.findall(r"Diff < left / right >[ \t]*:?[ \t]*\n(.*?)(?:\n\s*\n|$)", child_text, flags=re.S)
  pairs = []
  for diff in diffs:
   left = "\n".join(line for line in diff.splitlines() if not line.lstrip().startswith(">"))
   right = "\n".join(line for line in diff.splitlines() if not line.lstrip().startswith("<"))
   pairs.append({"actual_left_numbers": [int(n) for n in re.findall(r"-?\d+", left)], "expected_right_numbers": [int(n) for n in re.findall(r"-?\d+", right)], "original_diff": diff})
  proof["tuple_diffs"] = pairs
  conditions.update(unique_exact_owned_child_pre_fork_panic=len(child_blocks) == 1, exact_pre_fork_tuple=any(p["expected_right_numbers"] == [-1, errno.EBADF] and len(p["actual_left_numbers"]) == 2 and p["actual_left_numbers"][0] >= 0 for p in pairs))
 else: raise AssertionError("unknown counterfactual")
 proof["conditions"] = conditions; proof["qualified"] = all(conditions.values()); save(kind + "-causal-negative.json", proof)
 assert proof["qualified"], "negative did not reach its specific physical causal oracle"
 return proof

def negative_with_finally(stage):
 apply_stage(stage["apply"])
 primary = None; proof = None; restored = False; original_exception = None; restore_exception = None
 try:
  review, raw = run_scope(stage["scope"]); proof = qualify_negative(stage["kind"], review, raw)
 except BaseException as error:
  primary = error; original_exception = {"type": type(error).__name__, "message": str(error), "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))}
 finally:
  try:
   assert source == stage["restore"]["before_tree"], "not the exact owned negative tree"
   guard(stage["kind"] + "-finally-restore-eligible"); apply_stage(stage["restore"]); restored = True
  except BaseException as error:
   restore_exception = {"type": type(error).__name__, "message": str(error), "traceback": "".join(traceback.format_exception(type(error), error, error.__traceback__))}
   if primary is None: primary = error
  save(stage["kind"] + "-finally-restore.json", {"negative_tree": stage["apply"]["after_tree"], "positive_tree": stage["restore"]["after_tree"], "actual_source_at_return": source, "restored_exact_positive": restored, "original_exception": original_exception, "restoration_exception": restore_exception, "negative_qualified": bool(proof and proof["qualified"]), "next_stage_allowed": bool(restored and primary is None and proof and proof["qualified"]), "contract": "Only the exact owned negative tree with unchanged ordinary index, locks and no unreviewed untracked input may be restored. Invalid negative evidence stops after restoration; external drift is never overwritten."})
 if primary is not None: raise primary
 assert restored and proof and proof["qualified"]
 return proof

def export_source(name):
 rows = []
 for raw_path in git(["diff", "--name-only", "-z", "b2d7f038d6d88156bc6a4cb29c8703f69b808f29", source]).split(b"\0"):
  if not raw_path: continue
  path = raw_path.decode(); mode, kind, blob = git(["ls-tree", source, "--", path]).decode().split("\t")[0].split()
  rows.append({"path": path, "mode": mode, "git_blob": blob, **{k: v for k, v in rec(tree / path).items() if k != "path"}})
 save(name, {"base_tree": "b2d7f038d6d88156bc6a4cb29c8703f69b808f29", "final_tree": source, "files": rows})

try:
 save("execution-request.json", request)
 guard("initial"); assert target.is_dir() and not target.is_symlink()
 baseline = pathlib.Path(approved["baseline_metadata"]["path"])
 assert all(rec(baseline)[k] == approved["baseline_metadata"][k] for k in ("bytes", "sha256"))
 baseline_graph = feature_graph(json.loads(baseline.read_text()))
 assert len(baseline_graph["workspace_members"]) == 193 and len(baseline_graph["nodes"]) == 1501
 save("native-host.json", {"host_alias": "rog", "uname": list(os.uname()), "rustc": subprocess.run(["rustc", "-vV"], env=env, capture_output=True, text=True, check=True).stdout, "target": str(target), "source": source, "initial_free_bytes": shutil.disk_usage(tree).free})
 apply_stage(approved["apply_fixed"])
 proofs = []
 for stage in approved["counterfactual_stages"]: proofs.append(negative_with_finally(stage))
 review, raw = run_scope(approved["positive_scope"]); require_pass(review)
 guard("final"); export_source("final-source-map.json")
 terminal = {"qualified": True, "source": source, "root_guard_blob": request["root_guard_blob"], "runner": request["runner"], "negative_proofs": proofs, "positive_review": review, "phases": phases, "scope": "Linux ROG, dev-small, full workspace graph with exact selected counterfactuals and final eight cases; all retries zero. No Windows or other-platform claim; no full-workspace test pass is implied.", "next_step": "Stop for root review. No Windows application, full gate, fix or fmt is performed by this runner."}
 saved = save("terminal.json", terminal); save("terminal.parts.json", split(saved, "terminal"))
 print(json.dumps({"terminal": True, "source": source, "positive_count": len(review["cases"]), "negative_qualified": len(proofs), "terminal_file": rec(saved)}), flush=True)
except BaseException as error:
 failure = {"source": source, "root_guard_blob": request.get("root_guard_blob"), "error_type": type(error).__name__, "error": str(error), "traceback": traceback.format_exc(), "phases": phases, "reviews": reviews, "source_not_automatically_changed_after_failure": True}
 saved = save("driver-error.json", failure); save("driver-error.parts.json", split(saved, "driver-error"))
 print(json.dumps({"terminal": False, "source": source, "driver_error": str(error), "file": rec(saved)}), flush=True)
 raise

