from pathlib import Path
import collections,hashlib,json,os,re,subprocess,sys,tempfile,time,xml.etree.ElementTree as ET

if len(sys.argv)!=4: raise SystemExit("requires repository exact-source-sha evidence-output")
repo=Path(sys.argv[1]).resolve(strict=True)
source=sys.argv[2]
out=Path(sys.argv[3])
if not re.fullmatch(r"[0-9a-f]{40}",source): raise SystemExit("exact source SHA required")
if not str(repo).startswith("/home/qian-qi/hepta-learn-all-owners-ce434-20261111-"): raise SystemExit("unexpected qualification repository")
evidence=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111")
if out.parent!=evidence/"native" or not out.name.startswith("owner-fixture-focus-"+source[:12]+"-"): raise SystemExit("unexpected evidence path")
out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ)
env.update(CODEX_REPO_ROOT=str(repo),CARGO_TARGET_DIR="/home/qian-qi/hepta-learn-ce434-target",CARGO_BUILD_JOBS="4",CARGO_INCREMENTAL="0",CARGO_PROFILE_TEST_DEBUG="0",CARGO_PROFILE_DEV_DEBUG="0",CARGO_NET_OFFLINE="true",PYTHONDONTWRITEBYTECODE="1",SOURCE_SHA=source,TESTED_SHA=source,BASE_SHA="73f20ed9a09bc5716484f497654640aedcec268d",HEPTA_CI_LANE="source-head")
env["PATH"]="/home/qian-qi/hepta-learn-ce434-tools/uv-venv/bin:/home/qian-qi/.local/bin:/home/qian-qi/.cargo/bin:"+env["PATH"]
def sha(path):
    with path.open("rb") as stream: return hashlib.file_digest(stream,"sha256").hexdigest()
def git(*args): return subprocess.check_output(["git",*args],cwd=repo,env=env,text=True).strip()
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):
    raise RuntimeError("fixed source must be clean before qualification")
pinroot=evidence/"native/v8-pinned-150-4-0-v2"
pinbytes=(pinroot/"manifest.json").read_bytes()
if hashlib.sha256(pinbytes).hexdigest()!="9969b385cfffaf8a16071033460b505fd98e7a8b6a7f8fd47762e526d78b5ff5": raise RuntimeError("V8 manifest changed")
pin=json.loads(pinbytes)
if pin["cargo_lock_sha256"]!=sha(repo/"codex-rs/Cargo.lock") or pin["resolver_sha256"]!=sha(repo/"scripts/codex_package/v8.py"): raise RuntimeError("V8 source changed")
expected={"RUSTY_V8_ARCHIVE":"a35c75d1f26e6a983885a45b33490a4ebe54f05050568b32b89cfb421b30b583","RUSTY_V8_SRC_BINDING_PATH":"7727826ae479bdb645e807239fb12d1f8e2e23de7a6cf16f5ee592690d1d8506"}
if set(pin["environment"])!=set(expected): raise RuntimeError("V8 pair incomplete")
for key,digest in expected.items():
    path=Path(pin["environment"][key])
    if path.parent!=pinroot or path.is_symlink() or sha(path)!=digest: raise RuntimeError("V8 artifact changed")
env.update(pin["environment"])
canonical=Path(tempfile.mkdtemp(prefix="hlca-",dir="/tmp")).resolve(strict=True)
if len(os.fsencode(canonical))>32 or canonical.is_symlink() or canonical.stat().st_uid!=os.getuid(): raise RuntimeError("short original owned temporary root required")
env["TMPDIR"]=str(canonical)
sys.dont_write_bytecode=True
report={"source_sha":source,"source_tree":git("rev-parse","HEAD^{tree}"),"canonical_tmpdir":str(canonical),"v8_manifest_sha256":hashlib.sha256(pinbytes).hexdigest(),"state":"starting","steps":[],"full_chain_acceptance":{"positive":0,"no_update":0,"daemon_root_cold_restart":0}}
def checkpoint():
    pending=out/"result.pending.json"
    pending.write_text(json.dumps(report,indent=2)+"\n")
    pending.replace(out/"result.json")
    print(json.dumps(report),flush=True)
def step(name,args):
    report["state"]=name
    checkpoint()
    log=out/(name+".driver.log")
    started=time.monotonic()
    with log.open("xb") as stream: result=subprocess.run(args,cwd=repo,env=env,stdout=stream,stderr=subprocess.STDOUT,check=False)
    report["steps"].append({"name":name,"exit_code":result.returncode,"seconds":time.monotonic()-started,"log_sha256":sha(log),"log_bytes":log.stat().st_size})
    checkpoint()
    return result.returncode

v8=["/usr/bin/python3",str(repo/"scripts/hepta_ci_v8.py"),"--run"]
helpers=out/"helpers"
code=step("helper-build",v8+["/usr/bin/python3",str(repo/"scripts/hepta_cell_test_helpers.py"),"--package","codex-hepta-infer-worker-host","--output-dir",str(helpers)])
if code:
    report["state"]="helper-failed"; checkpoint(); raise SystemExit(code)
code=step("helper-verify",["/usr/bin/python3",str(repo/"scripts/hepta_cell_test_helpers.py"),"--package","codex-hepta-infer-worker-host","--output-dir",str(helpers),"--verify-only"])
if code:
    report["state"]="helper-verification-failed"; checkpoint(); raise SystemExit(code)
env.update(json.loads((helpers/"env.json").read_text()))

junit=repo/"codex-rs/target/nextest/local/junit.xml"
prior=evidence/"native/all-owners-8f7cdf81c7e3-v1/failure-inventory.json"
inventory=json.loads(prior.read_bytes())
if inventory["source_sha"]!="8f7cdf81c7e3a4a0c8921b63e3b64e73657e19cc" or inventory["cases"]!=1330 or len(inventory["failed"])!=5 or not inventory["retained_73"]["all_passed"]:
    raise RuntimeError("original failed-case inventory mismatch")
names=[v["name"] for v in inventory["failed"]]
names.append("learning_iteration_evidence_client::tests::original_receipt_fixture_retains_peer_during_owner_work_between_frames")
if len(set(names))!=6: raise RuntimeError("focused test inventory duplicated")
expression=" | ".join("test(="+name+")" for name in names)
junit.unlink(missing_ok=True)
command=["just","test","--locked","--offline","-p","codex-hepta-agentd","--lib","-E",expression,"--test-threads","2","--retries","0","--no-tests","fail","--status-level","pass","--success-output","final","--failure-output","final"]
execution=out/"focused-native.json"
native_exit=step("focused-native",v8+["/usr/bin/python3",str(repo/"scripts/hepta_ci_exec.py"),"--output",str(execution),"--minimum-tests","6","--timeout-seconds","1800","--",*command])
xmlpath=out/"focused-native.junit.xml"
collect_exit=step("focused-junit",["/usr/bin/python3",str(repo/"scripts/hepta_ci_junit.py"),"--execution",str(execution),"--junit",str(junit),"--output",str(xmlpath)])
coverage_ok=False
if xmlpath.exists():
    sys.path.insert(0,str(repo/"scripts"))
    from hepta_ci_junit import NoDoctypeTreeBuilder
    from hepta_c_observer_coverage import ANSI, TERMINAL
    xml=ET.fromstring(xmlpath.read_bytes(),parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    cases=list(xml.iter("testcase"))
    wanted=collections.Counter(("codex-hepta-agentd",name) for name in names)
    observed=collections.Counter((c.get("classname"),c.get("name")) for c in cases)
    bad=[{"package":c.get("classname"),"name":c.get("name"),"diagnostics":[n.text for n in c.iter() if n.tag in ("failure","error","skipped","flakyFailure","flakyError","rerunFailure","rerunError")]} for c in cases if any(n.tag in ("failure","error","skipped","flakyFailure","flakyError","rerunFailure","rerunError") for n in c.iter())]
    suites=[s.get("name")==c.get("classname") for s in xml.iter("testsuite") for c in s.findall("testcase")]
    encoded=execution.read_bytes(); record=json.loads(encoded)
    logname=record["log_file"]
    if re.fullmatch(re.escape(execution.name)+r"\.[0-9a-f]{32}\.log",logname) is None: raise RuntimeError("unexpected original log name")
    logpath=out/logname
    if logpath.is_symlink(): raise RuntimeError("log replaced with alias")
    raw=logpath.read_bytes()
    if len(raw)!=record["log_bytes"] or hashlib.sha256(raw).hexdigest()!=record["log_sha256"] or record["source_sha"]!=source:
        raise RuntimeError("original retained execution identity mismatch")
    log=ANSI.sub("",raw.decode("utf-8",errors="replace"))
    summary=re.search(r"^\s*Summary\s+\[[^\]\n]+\]\s+",log,re.MULTILINE)
    rows=TERMINAL.findall(log[:summary.start()]) if summary is not None else []
    relevant=[row for row in rows if row[2] in names]
    raw_ok=collections.Counter((package,name) for _,package,name in relevant)==wanted and all(status=="PASS" for status,_,_ in relevant)
    coverage_ok=observed==wanted and not bad and len(suites)==6 and all(suites) and raw_ok
    report["required_coverage"]={"cases":len(cases),"expected":names,"failed_or_skipped":bad,"raw_log_rows":relevant,"log_file":logname,"log_bytes":len(raw),"log_sha256":record["log_sha256"],"junit_bytes":xmlpath.stat().st_size,"junit_sha256":sha(xmlpath),"exact_pass":coverage_ok}
report.update(native_exit_code=native_exit,collection_exit_code=collect_exit,source_after=git("rev-parse","HEAD"),source_status_after=git("status","--porcelain=v1","--untracked-files=all"))
report["state"]="passed" if native_exit==0 and collect_exit==0 and coverage_ok and report["source_after"]==source and not report["source_status_after"] else "failed"
checkpoint()
raise SystemExit(0 if report["state"]=="passed" else 1)
