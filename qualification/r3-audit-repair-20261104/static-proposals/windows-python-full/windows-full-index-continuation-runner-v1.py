import tomllib,collections,datetime,hashlib,json,os,pathlib,re,shutil,subprocess,sys,time,traceback,errno,xml.etree.ElementTree as ET
request=json.load(sys.stdin)
root=pathlib.Path("/home/qian-qi/work/hepta-audit-r3-fullgate-20261104")
tree=root/"source"; target=root/"target-app-epoch2-20261105"
out=root/"evidence"/request["evidence_name"];out.mkdir(exist_ok=False)
approved=request["guard"];source=approved["initial_tree"];counter=0;phases=[];reviews=[]
expected_locks=dict(approved["locks"]);temporary_config=None
env=dict(os.environ)
env["PATH"]=str(root/"tools/uv-venv/bin")+":"+str(root/"tools/bin")+":/home/qian-qi/.cargo/bin:/home/qian-qi/.local/bin:"+env.get("PATH","")
env.update(PYTHONPYCACHEPREFIX=str(out/"python-pycache"),CARGO_TARGET_DIR=str(target),CARGO_INCREMENTAL="0",CARGO_BUILD_JOBS="4",RUSTUP_TOOLCHAIN="1.95.0",CARGO_NET_GIT_FETCH_WITH_CLI="true",PYTHONDONTWRITEBYTECODE="1",DOTSLASH_CACHE=str(root/"tools/dotslash-cache"),NEXTEST_PROFILE="local",UV_CACHE_DIR=str(out/"uv-cache"),UV_PYTHON_DOWNLOADS="never",RUSTY_V8_ARCHIVE=str(root/"tools/rusty-v8/librusty_v8_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.a.gz"),RUSTY_V8_SRC_BINDING_PATH=str(root/"tools/rusty-v8/src_binding_ptrcomp_sandbox_release_x86_64-unknown-linux-gnu.rs"))


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

def export_source(name):
 rows = []
 for raw_path in git(["diff", "--name-only", "-z", "b2d7f038d6d88156bc6a4cb29c8703f69b808f29", source]).split(b"\0"):
  if not raw_path: continue
  path = raw_path.decode(); mode, kind, blob = git(["ls-tree", source, "--", path]).decode().split("\t")[0].split()
  rows.append({"path": path, "mode": mode, "git_blob": blob, **{k: v for k, v in rec(tree / path).items() if k != "path"}})
 save(name, {"base_tree": "b2d7f038d6d88156bc6a4cb29c8703f69b808f29", "final_tree": source, "files": rows})

def phase(name, argv, streams=False, cwd=None):
 workdir = pathlib.Path(cwd) if cwd is not None else tree / "codex-rs"
 assert workdir in (tree, tree / "codex-rs")
 assert shutil.disk_usage(tree).free >= 8_000_000_000, "disk below 8GB before " + name
 guard(name + "-before"); before = source; started = now(); clock = time.monotonic()
 stdout = out / (name + (".stdout" if streams else ".log")); stderr = out / (name + ".stderr")
 save(name + "-command.json", {"argv": argv, "cwd": str(workdir), "source": source, "started_at": started, "attempt": 1, "cargo_profile": "dev-small", "nextest_profile": "local", "disk_before": dict(zip(("total", "used", "free"), shutil.disk_usage(tree)))})
 print(json.dumps({"phase_start": name, "source": source, "argv": argv}), flush=True)
 with stdout.open("xb") as so:
  if streams:
   with stderr.open("xb") as se: result = subprocess.run(argv, cwd=workdir, env=env, stdout=so, stderr=se)
  else: result = subprocess.run(argv, cwd=workdir, env=env, stdout=so, stderr=subprocess.STDOUT)
 record = {"name": name, "argv": argv, "source_before": before, "source_after": source, "source_unchanged": before == source, "exit_code": result.returncode, "started_at": started, "completed_at": now(), "duration_seconds": time.monotonic() - clock, "stdout": split(stdout, name + "-stdout"), "disk_after": dict(zip(("total", "used", "free"), shutil.disk_usage(tree)))}
 if streams: record["stderr"] = split(stderr, name + "-stderr")
 phases.append(record); save(name + "-status.json", record); guard(name + "-after")
 print(json.dumps({"phase_terminal": name, "source": source, "exit_code": result.returncode, "seconds": record["duration_seconds"], "disk_after": record["disk_after"]}), flush=True)
 assert record["disk_after"]["free"] >= 8_000_000_000, "disk below 8GB after " + name
 return record

def run_python_scope():
 for label, key in (("wrapper-shell-syntax", "bash_argv"), ("collector-python-compile", "python_compile_argv")):
  result = phase(label, approved["original_gates"][key], cwd=tree)
  assert result["exit_code"] == 0, label + " failed"
 catalog_script = "import json,unittest; s=unittest.defaultTestLoader.discover('.github/scripts',pattern='test_run_bazel*.py'); ids=[]\ndef walk(x):\n if isinstance(x,unittest.TestSuite):\n  for y in x:walk(y)\n else:ids.append(x.id())\nwalk(s); print(json.dumps(sorted(ids)))"
 result = phase("wrapper-python-catalog", ["python3", "-c", catalog_script], True, tree)
 assert result["exit_code"] == 0
 ids = json.loads((out / "wrapper-python-catalog.stdout").read_text())
 assert len(ids) == len(set(ids)) == approved["original_gates"]["python_roster_count"]
 assert not any("_FailedTest" in name for name in ids)
 result = phase("wrapper-python-original-suite", approved["original_gates"]["python_test_argv"], cwd=tree)
 raw = (out / "wrapper-python-original-suite.log").read_text()
 count = re.findall(r"(?m)^Ran ([0-9]+) tests? in [0-9.]+s$", raw)
 ok = result["exit_code"] == 0 and count == [str(len(ids))] and re.search(r"(?m)^OK$", raw) is not None
 receipt = {"source": source, "catalog_ids": ids, "catalog": rec(out / "wrapper-python-catalog.stdout"), "original_argv": approved["original_gates"]["python_test_argv"], "actual_summary_counts": count, "original_raw": rec(out / "wrapper-python-original-suite.log"), "exit_code": result["exit_code"], "passed": ok, "limit": "Original unittest discovery and whole suite, not a replacement test runner. Exact catalog names and original reported executed count are bound; original log remains authoritative."}
 save("wrapper-python-original-review.json", receipt)
 assert ok, "original wrapper Python suite did not pass complete expected roster"
 return receipt

def run_full():
 normal=normal_helpers("full-workspace")
 packages=[]
 workspace_manifest=tomllib.loads((tree/"codex-rs/Cargo.toml").read_text())
 if "package" in workspace_manifest or "workspace" not in workspace_manifest or "default-members" in workspace_manifest["workspace"]:raise RuntimeError("full workspace default selection contract changed")
 if shutil.disk_usage(tree).free<24_000_000_000:raise RuntimeError("resource guard below 24GB before full owning catalog")
 metadata_argv=["cargo","metadata","--format-version=1","--locked"]
 if metadata_argv!=approved["original_gates"]["full_metadata_argv"]:raise RuntimeError("original full metadata argv mismatch")
 meta=phase("workspace-metadata",metadata_argv,True)
 if meta["exit_code"]!=0:raise RuntimeError("full workspace metadata failed")
 workspace_metadata=json.loads((out/"workspace-metadata.stdout").read_text())
 current_graph=feature_graph(workspace_metadata)
 assert current_graph == baseline_graph, "full dependency graph differs from actual 7d source"
 assert len(current_graph["workspace_members"]) == 193 and len(current_graph["nodes"]) == 1501
 save("full-feature-graph-binding.json", {"source":source,"baseline":approved["baseline_metadata"],"current":rec(out/"workspace-metadata.stdout"),"workspace_members":193,"resolved_nodes":1501,"full_resolve_and_features_equal":True,"package_filter":None,"expression_filter":None})
 # Record the naturally resolved registry identity without extra fetch or mutation.
 sqlx_rows=[{k:p.get(k) for k in ("id","name","version","source","manifest_path","links")} for p in workspace_metadata["packages"] if p["name"]=="sqlx-sqlite" and p["version"]=="0.9.0"]
 save("sqlx-sqlite-natural-metadata.json",{"source":source,"metadata":rec(out/"workspace-metadata.stdout"),"packages":sqlx_rows,"additional_fetch_or_dependency_mutation":False})

 workspace_ids=set(workspace_metadata["workspace_members"])
 workspace_names={p["name"] for p in workspace_metadata["packages"] if p["id"] in workspace_ids}
 save("workspace-members.json",{"source":source,"members":sorted(workspace_names),"member_ids":sorted(workspace_ids),"normal_metadata":rec(out/"workspace-metadata.stdout")})
 package_args=[]
 # Keep the original no-package workspace recipe's normal full metadata path.
 catalog_argv=["cargo","nextest","list","--locked","--cargo-profile","dev-small","--message-format=json"]
 if catalog_argv!=approved["original_gates"]["full_catalog_argv"]:raise RuntimeError("original full catalog argv mismatch")
 cat=phase("full-workspace-catalog",catalog_argv,True)
 if cat["exit_code"]!=0:raise RuntimeError("full-workspace catalog/build failed")
 parsed=json.loads((out/"full-workspace-catalog.stdout").read_text());expected=[];ignored=[];unmatched=[];binaries=[];actual_packages=set()
 for sid,suite in parsed["rust-suites"].items():
  matched=False
  for name,item in suite["testcases"].items():
   row={"classname":sid,"name":name,"package":suite["package-name"],"ignored":item["ignored"],"filter_match":item["filter-match"]}
   if item["filter-match"]["status"]=="matches" and not item["ignored"]:expected.append(row);matched=True
   elif item["ignored"]:ignored.append(row)
   else:unmatched.append(row)
  if matched:
   actual_packages.add(suite["package-name"]);binaries.append({"binary_id":sid,**rec(pathlib.Path(suite["binary-path"]))})
 if not expected:raise RuntimeError("empty full-workspace roster")
 if unmatched:raise RuntimeError("full-workspace catalog has unexpected unmatched cases")
 reference=request["full_roster_reference"];reference_path=pathlib.Path(reference["path"])
 assert reference["source"]==approved["initial_tree"], "frozen App roster source mismatch"
 assert reference_path.resolve().is_relative_to((root/"evidence").resolve()) and reference_path.is_file() and not reference_path.is_symlink()
 assert all(rec(reference_path)[k]==reference[k] for k in ("bytes","sha256")), "frozen App catalog bytes changed"
 reference_catalog=json.loads(reference_path.read_text());reference_eligible=[];reference_ignored=[]
 for sid,suite in reference_catalog["rust-suites"].items():
  for name,item in suite["testcases"].items():
   row={"classname":sid,"name":name,"ignored":item["ignored"]}
   (reference_ignored if item["ignored"] else reference_eligible).append(row)
 roster_keys=lambda rows:collections.Counter((x["classname"],x["name"],x["ignored"]) for x in rows)
 assert roster_keys(expected)==roster_keys(reference_eligible), "full eligible roster differs from frozen App catalog"
 assert roster_keys(ignored)==roster_keys(reference_ignored), "full ignored roster differs from frozen App catalog"
 save("full-frozen-App-roster-binding.json",{"reference":reference,"actual_reference":rec(reference_path),"full_catalog":rec(out/"full-workspace-catalog.stdout"),"source":source,"eligible_count":len(expected),"ignored_count":len(ignored),"unmatched_count":len(unmatched),"exact_counter_equality":True,"reference_selection_filter_match_ignored":True,"case_keys":"(classname,name,ignored) with multiplicity; no deduplication or count-only acceptance"})
 if not actual_packages.issubset(workspace_names):raise RuntimeError("non-workspace package in full catalog")
 empty_packages=sorted(workspace_names-actual_packages)
 packages=sorted(workspace_names)
 helpers=helper_records(parsed,normal)
 selection={"source":source,"packages":packages,"actual_packages":sorted(actual_packages),"packages_without_testcases":empty_packages,"cargo_profile":"dev-small","nextest_profile":"local","expected_selected":expected,"existing_ignored":ignored,"existing_unmatched":unmatched,"test_binaries_after_catalog_before_just":binaries,"helpers_after_catalog_before_just":helpers,"catalog_non_test_binaries":parsed["rust-build-meta"]["non-test-binaries"],"catalog":rec(out/"full-workspace-catalog.stdout")}
 sp=save("full-workspace-selection.json",selection);save("full-workspace-selection-index.json",split(sp,"selection"))
 junit=tree/"codex-rs/target/nextest/local/junit.xml";prior=rec(junit) if junit.exists() else None;started=time.time_ns()
 print(json.dumps({"catalog_roster":{"selected":len(expected),"existing_ignored":len(ignored),"existing_unmatched":len(unmatched),"binaries":len(binaries),"helpers":len(helpers),"packages":sorted(actual_packages),"empty_packages":empty_packages}}),flush=True)
 test_argv=["just","test","--locked","--cargo-profile","dev-small"]+package_args+["--no-tests","fail","--retries","0","--success-output","immediate"]
 if test_argv!=approved["original_gates"]["full_workspace_argv"]:raise RuntimeError("original full workspace argv mismatch")
 test=phase("full-workspace",test_argv)
 if not junit.is_file() or junit.stat().st_mtime_ns<started-2_000_000_000:raise RuntimeError("missing or stale owning JUnit")
 if prior and rec(junit)["sha256"]==prior["sha256"]:raise RuntimeError("unchanged owning JUnit")
 copy=out/"full-workspace.junit.xml";copy.write_bytes(junit.read_bytes());cases=[]
 for c in ET.parse(copy).getroot().iter("testcase"):
  result="FAIL" if c.find("failure") is not None else "ERROR" if c.find("error") is not None else "SKIP" if c.find("skipped") is not None else "PASS"
  cases.append({"name":c.attrib.get("name"),"classname":c.attrib.get("classname"),"seconds":c.attrib.get("time"),"result":result,"failure":"\n".join(x.text or "" for x in c if x.tag in ("failure","error"))})
 expected_keys=collections.Counter((x["classname"],x["name"]) for x in expected)
 actual_keys=collections.Counter((x["classname"],x["name"]) for x in cases if x["result"]!="SKIP")
 ignored_keys={(x["classname"],x["name"]) for x in ignored}
 unexpected_skips=[x for x in cases if x["result"]=="SKIP" and (x["classname"],x["name"]) not in ignored_keys]
 after=[{"binary_id":b["binary_id"],**rec(pathlib.Path(b["path"]))} for b in binaries];ha=[{"origins":h["origins"],**rec(pathlib.Path(h["path"]))} for h in helpers]
 raw=(out/"full-workspace.log").read_text();clean=re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",raw)
 early=[l for l in clean.splitlines() if "Skipping test because it cannot execute when network is disabled" in l or "python not found; skipping" in l or "setsid not available; skipping" in l or "skipping zsh-fork test:" in l or "unable to resolve \u0060codex-execve-wrapper\u0060 binary" in l or "failed to fetch zsh via dotslash" in l]
 skip_observations=[l for l in clean.splitlines() if re.search(r"\bskipping\b",l,re.I)]
 # Bind early-return notices to actual nextest case blocks; PASS JUnit can omit output.
 raw_lines=raw.splitlines(keepends=True);plain_lines=[re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]","",line) for line in raw_lines];byte_offsets=[0]
 for line in raw_lines:byte_offsets.append(byte_offsets[-1]+len(line.encode()))
 case_by_key={(c["classname"],c["name"]):c for c in cases}
 summary_line=max((i for i,line in enumerate(plain_lines) if re.match(r"^\s*Summary\s+\[",line)),default=len(raw_lines))
 headers=[]
 for i,line in enumerate(plain_lines[:summary_line]):
  match=re.match(r"^\s*(PASS|FAIL|TIMEOUT|LEAK|SKIP)\s+\[\s*[0-9.]+s\]\s+(\S+)\s+(.+?)\s*$",line)
  if match:headers.append({"line":i,"result":match.group(1),"classname":match.group(2),"name":match.group(3)})
 early_patterns=("requires a remote test environment","Skipping test because it cannot execute when network is disabled","python not found; skipping","setsid not available; skipping","skipping zsh-fork test:","unable to resolve \u0060codex-execve-wrapper\u0060 binary","failed to fetch zsh via dotslash","skipping sandbox test:","skipping capability test:")
 notice_lines={i for i,line in enumerate(plain_lines) if any(marker in line for marker in early_patterns)}
 early_case_observations=[];associated_lines=set()
 for i,header in enumerate(headers):
  stop=headers[i+1]["line"] if i+1<len(headers) else summary_line
  notices=[line for line in sorted(notice_lines) if header["line"]<=line<stop]
  if not notices:continue
  key=(header["classname"],header["name"]);junit_case=case_by_key.get(key)
  block="".join(raw_lines[header["line"]:stop]);encoded=block.encode()
  item={"classname":key[0],"name":key[1],"nextest_header_result":header["result"],"junit_result":junit_case["result"] if junit_case else None,"exact_junit_key_bound":junit_case is not None,"messages":[{"line":n+1,"original_line":raw_lines[n],"plain_line":plain_lines[n]} for n in notices],"original_raw_block":{"start_line":header["line"]+1,"end_line":stop,"byte_offset":byte_offsets[header["line"]],"bytes":len(encoded),"sha256":sha(encoded),"content":block},"limit":"Original explicit early-return notice is preserved. JUnit PASS does not establish execution of the omitted remote or prerequisite-dependent behavior."}
  early_case_observations.append(item);associated_lines.update(notices)
 unbound_early_notices=[{"line":i+1,"original_line":raw_lines[i],"plain_line":plain_lines[i]} for i in sorted(notice_lines-associated_lines)]
 observations={"source":source,"original_raw":rec(out/"full-workspace.log"),"original_junit":rec(copy),"cases":early_case_observations,"unbound_notices":unbound_early_notices,"full_raw_test_early_return_notice_count":len(notice_lines),"legacy_missing_binary_network_pattern_list":early,"limits":"Derived observation only; original full test command/status/roster remain unchanged. Other skipping analytics messages are retained separately without labeling them test early returns."}
 save("early-return-case-observations.json",observations)
 counts=dict(collections.Counter(c["result"] for c in cases));roster=expected_keys==actual_keys
 all_pass=all(c["result"] in ("PASS","SKIP") for c in cases) and not unexpected_skips
 review={"source":source,"host":"rog","cargo_profile":"dev-small","nextest_profile":"local","retries":0,"cases":cases,"counts":counts,"selected_catalog_count":len(expected),"existing_ignored_catalog_count":len(ignored),"existing_unmatched_catalog_count":len(unmatched),"exact_executed_roster":roster,"missing_roster":[{"classname":k[0],"name":k[1],"count":v} for k,v in (expected_keys-actual_keys).items()],"unexpected_roster":[{"classname":k[0],"name":k[1],"count":v} for k,v in (actual_keys-expected_keys).items()],"unexpected_skips":unexpected_skips,"known_missing_prerequisite_early_returns":early,"all_skip_observations":skip_observations,"early_return_case_observations":early_case_observations,"unbound_early_return_notices":unbound_early_notices,"all_selected_cases_without_observed_early_return":not early_case_observations and not unbound_early_notices,"binary_before":binaries,"binary_after":after,"binary_stable":binaries==after,"helpers_before":helpers,"helpers_after":ha,"helpers_stable":helpers==ha,"source_unchanged":True,"junit":split(copy,"junit"),"prior_junit":prior,"exit_code":test["exit_code"],"nextest_summaries":[l for l in clean.splitlines() if "Starting " in l or "Summary" in l],"passed":test["exit_code"]==0 and roster and all_pass and binaries==after and helpers==ha and not early}
 rp=save("full-workspace-review.json",review);save("full-workspace-review-index.json",split(rp,"review"))
 reviews.append(review)
 return review

def read_completed_python_scope():
 reference = request["completed_python_reference"]; original_files = {}
 for name, expected in reference["files"].items():
  path = pathlib.Path(expected["path"])
  assert path.is_relative_to(root / "evidence") and not path.is_symlink()
  assert all(rec(path)[key] == expected[key] for key in ("bytes", "sha256")), "completed Python evidence changed: " + name
  original_files[name] = path.read_text()
 ids = json.loads(original_files["catalog"])
 assert len(ids) == len(set(ids)) == approved["original_gates"]["python_roster_count"]
 assert not any("_FailedTest" in name for name in ids)
 status = json.loads(original_files["status"]); command = json.loads(original_files["command"])
 assert status["source_before"] == status["source_after"] == command["source"] == source
 assert status["argv"] == command["argv"] == approved["original_gates"]["python_test_argv"]
 before = json.loads(original_files["before_guard"]); after = json.loads(original_files["after_guard"])
 assert before["actual_source"] == after["actual_source"] == source
 assert before["head"] == after["head"] == approved["ordinary_head"]
 assert before["locks"] == after["locks"] and not before["untracked_source_paths"] and not after["untracked_source_paths"]
 assert all(after["ordinary_index"][key] == approved["ordinary_index"][key] for key in ("bytes", "sha256"))
 reconciliation = json.loads(original_files["index_reconciliation"])
 assert reconciliation["source"] == source and reconciliation["ordinary_head"] == approved["ordinary_head"]
 assert reconciliation["index_semantics_exact_head"] and reconciliation["parsed_index_matches_git_ls_files"]
 assert reconciliation["private_source_index_exact_candidate"] and reconciliation["working_tree_raw_diff_empty"]
 assert reconciliation["ordinary_index_bytes_stable_during_read"] and not reconciliation["untracked_source_paths"]
 assert all(reconciliation["actual_ordinary_index"][key] == approved["ordinary_index"][key] for key in ("bytes", "sha256"))
 assert all(reconciliation["flags"][key] == 0 for key in ("stage_nonzero", "assume_valid", "extended_nonzero", "skip_worktree", "intent_to_add"))
 raw = original_files["raw"]
 count = re.findall(r"(?m)^Ran ([0-9]+) tests? in [0-9.]+s$", raw)
 ok = status["exit_code"] == 0 and count == [str(len(ids))] and re.search(r"(?m)^OK$", raw) is not None
 receipt = {"source": source, "catalog_ids": ids, "catalog": reference["files"]["catalog"], "original_argv": approved["original_gates"]["python_test_argv"], "actual_summary_counts": count, "original_raw": reference["files"]["raw"], "exit_code": status["exit_code"], "passed": ok, "original_attempt_job": reference["job_id"], "original_controller_exit_code": 1, "original_guard_failure_retained": reference["failure_originals_blob"], "readonly_index_reconciliation": reference["files"]["index_reconciliation"], "not_reexecuted": True, "limit": "Previously completed original 57-test suite is read and hash-verified, not rerun. The prior controller failed on ordinary-index bytes; semantic reconciliation and the new snapshot require an explicit root continuation guard. No claim is made about the unavailable prior index stat or extension bytes."}
 save("wrapper-python-original-review.json", receipt)
 assert ok, "completed original Python evidence does not qualify"
 return receipt

try:
 save("execution-request.json", request); guard("initial")
 assert target.is_dir() and not target.is_symlink()
 baseline = pathlib.Path(approved["baseline_metadata"]["path"])
 assert all(rec(baseline)[k] == approved["baseline_metadata"][k] for k in ("bytes", "sha256"))
 baseline_graph = feature_graph(json.loads(baseline.read_text()))
 assert len(baseline_graph["workspace_members"]) == 193 and len(baseline_graph["nodes"]) == 1501
 save("native-host.json", {"host_alias":"rog","uname":list(os.uname()),"rustc":subprocess.run(["rustc","-vV"],env=env,capture_output=True,text=True,check=True).stdout,"target":str(target),"source":source,"initial_free_bytes":shutil.disk_usage(tree).free,"cargo_profile":"dev-small","nextest_profile":"local","environment_policy_changed":False})
 assert approved["stages"] == [] and source == approved["final_tree"], "continuation must not reapply source"
 python_review = read_completed_python_scope()
 full_review = run_full()
 guard("final"); export_source("final-source-map.json")
 terminal = {"source":source,"root_guard_blob":request["root_guard_blob"],"runner":request["runner"],"python_passed":python_review["passed"],"full_original_command_exit_code":full_review["exit_code"],"full_review":rec(out/"full-workspace-review.json"),"full_counts":full_review["counts"],"full_passed":full_review["passed"],"exact_executed_roster":full_review["exact_executed_roster"],"binary_stable":full_review["binary_stable"],"helpers_stable":full_review["helpers_stable"],"observed_early_return_cases":len(full_review["early_return_case_observations"]),"unbound_early_return_notices":full_review["unbound_early_return_notices"],"phases":phases,"limits":approved["limits"],"next_step":"Stop for root review of every actual full-suite outcome. No hygiene, additional tests or publication is performed."}
 p=save("terminal.json",terminal);save("terminal.parts.json",split(p,"terminal"))
 print(json.dumps({"terminal":True,"source":source,"python_passed":python_review["passed"],"full_exit":full_review["exit_code"],"counts":full_review["counts"],"full_passed":full_review["passed"],"roster":full_review["exact_executed_roster"],"programs_stable":full_review["binary_stable"],"helpers_stable":full_review["helpers_stable"],"observed_early_returns":len(full_review["early_return_case_observations"]),"terminal_file":rec(p)}),flush=True)
 if not full_review["passed"]: raise SystemExit(1)
except Exception as error:
 failure={"source":source,"root_guard_blob":request.get("root_guard_blob"),"error_type":type(error).__name__,"error":str(error),"traceback":traceback.format_exc(),"phases":phases,"source_not_automatically_changed_after_failure":True}
 p=save("driver-error.json",failure);save("driver-error.parts.json",split(p,"driver-error"))
 print(json.dumps({"terminal":False,"source":source,"error":str(error),"driver_error":rec(p)}),flush=True)
 raise
