TARGET_V3_RECEIPT_BINDING = None
if TARGET_V3_RECEIPT_BINDING is None:
    raise SystemExit("INERT: actual successful v3 creation receipt is not bound; no filesystem action is permitted")

from pathlib import Path
import collections,hashlib,json,os,re,subprocess,sys,tempfile,time,xml.etree.ElementTree as ET

if not isinstance(TARGET_V3_RECEIPT_BINDING,dict) or set(TARGET_V3_RECEIPT_BINDING)!={"bytes","sha256"}:raise RuntimeError("actual v3 receipt binding shape differs")
if type(TARGET_V3_RECEIPT_BINDING["bytes"]) is not int or not 0<TARGET_V3_RECEIPT_BINDING["bytes"]<=16384:raise RuntimeError("actual v3 receipt length is unbound or exceeds original bound")
if not isinstance(TARGET_V3_RECEIPT_BINDING["sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",TARGET_V3_RECEIPT_BINDING["sha256"]):raise RuntimeError("actual v3 receipt full hash is unbound")

if len(sys.argv)!=4: raise SystemExit("requires repository exact-source-sha evidence-output")
repo=Path(sys.argv[1]).resolve(strict=True)
source=sys.argv[2]
out=Path(sys.argv[3])
if not re.fullmatch(r"[0-9a-f]{40}",source): raise SystemExit("exact source SHA required")
if str(repo) != "/home/qian-qi/hepta-learn-positive-ce434-8bf3881afa8c-isolated-v1": raise SystemExit("unexpected qualification repository")
evidence=Path("/home/qian-qi/hepta-learn-ce434-evidence-20261111")
if out.parent!=evidence/"native" or not out.name.startswith("live-owners-full-"+source[:12]+"-"): raise SystemExit("unexpected evidence path")
out.mkdir(parents=True,exist_ok=False)
env=dict(os.environ)
env.update(CODEX_REPO_ROOT=str(repo),CARGO_TARGET_DIR="/data/hepta-learn-ce434-runtime-20261112-v3/target",CARGO_BUILD_JOBS="4",CARGO_INCREMENTAL="0",CARGO_PROFILE_TEST_DEBUG="0",CARGO_PROFILE_DEV_DEBUG="0",CARGO_NET_OFFLINE="true",PYTHONDONTWRITEBYTECODE="1",SOURCE_SHA=source,TESTED_SHA=source,BASE_SHA="be8adcbb5e9925f72e05330b8fb30509cba4544b",HEPTA_CI_LANE="source-head")
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
import stat
prior_pinroot=Path("/data/hepta-learn-ce434-runtime-20261112-v1/v8-private-pins")
recovery_path=evidence/"native/dependency-recovery-441de918-v1/result.json"
recovery_bytes=recovery_path.read_bytes()
if hashlib.sha256(recovery_bytes).hexdigest()!="8db2c096ff2c16b8e02f293a67c26939c5de6bf6e0dd69888179c4b0d31ca3fc":raise RuntimeError("original successful dependency recovery record differs")
recovered=json.loads(recovery_bytes)
if recovered["state"]!="original-assets-recovered-and-full-hash-verified" or recovered["source_sha"]!="441de918b863dd15b2faeae920017c1b4b08f59d" or recovered["environment"]["CARGO_TARGET_DIR"]!="/data/hepta-learn-ce434-runtime-20261112-v1/target":raise RuntimeError("original recovery identity differs")
target_root=Path(env["CARGO_TARGET_DIR"])
target_info=target_root.lstat()
if not stat.S_ISDIR(target_info.st_mode) or target_root.resolve(strict=True)!=target_root or target_info.st_uid!=os.getuid():raise RuntimeError("dedicated original owned build root differs")
target_recovery_path=evidence/"native/build-root-recovery-4537458b51b6-v3-attempt2/result.json"
recovery_stat=target_recovery_path.lstat()
if not stat.S_ISREG(recovery_stat.st_mode) or recovery_stat.st_uid!=os.getuid() or recovery_stat.st_nlink!=1 or recovery_stat.st_size!=TARGET_V3_RECEIPT_BINDING["bytes"]:raise RuntimeError("actual new target recovery record differs")
fd=os.open(target_recovery_path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC|os.O_NONBLOCK)
with os.fdopen(fd,"rb") as stream:
    first=os.fstat(stream.fileno());target_recovery_bytes=stream.read(16385);last=os.fstat(stream.fileno())
def stable_identity(s):return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_uid,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
if stable_identity(recovery_stat)!=stable_identity(first) or stable_identity(first)!=stable_identity(last) or stable_identity(last)!=stable_identity(target_recovery_path.lstat()) or len(target_recovery_bytes)!=last.st_size:raise RuntimeError("new target recovery record changed")
target_recovery=json.loads(target_recovery_bytes)
if hashlib.sha256(target_recovery_bytes).hexdigest()!=TARGET_V3_RECEIPT_BINDING["sha256"]:raise RuntimeError("actual target-v3 creation record differs")
if target_recovery["schema"]!="learn.original-build-root-recovery.v1" or target_recovery["state"]!="isolated-build-target-created-original-pins-retained" or target_recovery["source_sha"]!="4537458b51b6ca936264aecea7cfe384b941d0d1" or target_recovery["source_tree"]!="8cbd7b269c9c39df4ee3ffcefed8473060696184" or target_recovery["source_after"]!=target_recovery["source_sha"] or target_recovery["source_tree_after"]!=target_recovery["source_tree"] or target_recovery["source_status_after"] or target_recovery["runtime_root"]!=str(target_root.parent) or target_recovery["target"]!=str(target_root):raise RuntimeError("actual target-v3 creation provenance differs")
if target_recovery["original_manifest_sha256"]!=hashlib.sha256(pinbytes).hexdigest() or target_recovery["original_recovery_sha256"]!=hashlib.sha256(recovery_bytes).hexdigest():raise RuntimeError("original recovery preimage differs")
for path,field in [(target_root.parent,"root_identity"),(target_root,"target_identity")]:
    actual=path.lstat();prior=target_recovery[field]
    if not stat.S_ISDIR(actual.st_mode) or path.resolve(strict=True)!=path or actual.st_uid!=os.getuid() or stat.S_IMODE(actual.st_mode)!=0o700 or (actual.st_dev,actual.st_ino,actual.st_uid,oct(actual.st_mode))!=(prior["device"],prior["inode"],prior["uid"],prior["mode"]):raise RuntimeError("new original owned build target replaced")
with (out/"target-initialization-readback.json").open("xb") as stream:stream.write(target_recovery_bytes)
private_environment={}
private_artifacts=[]
for key,digest in expected.items():
    original_path=Path(pin["environment"][key])
    record=pin["artifacts"][key]
    if original_path.parent!=pinroot or record["path"]!=str(original_path) or record["sha256"]!=digest:
        raise RuntimeError("Original pinned input identity differs")
    target=prior_pinroot/original_path.name
    info=target.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_uid!=os.getuid() or info.st_size!=record["bytes"] or sha(target)!=digest:
        raise RuntimeError("Original verified private input identity differs")
    private_environment[key]=str(target)
    private_artifacts.append({"key":key,"path":str(target),"bytes":info.st_size,"sha256":digest,"acquisition":"read-only reuse of the exact original V8 pair recovered and full-hash-verified in dependency-recovery-441de918-v1"})
private_input_record={"original_manifest_sha256":hashlib.sha256(pinbytes).hexdigest(),"original_manifest_unchanged":True,"private_artifacts":private_artifacts,"copied_or_downloaded_during_this_native_invocation":False,"recovery_record_sha256":hashlib.sha256(recovery_bytes).hexdigest()}
with (out/"v8-private-input-readback.json").open("x") as stream:stream.write(json.dumps(private_input_record,indent=2)+"\n")
env.update(private_environment)
canonical=Path(tempfile.mkdtemp(prefix="hlca-",dir="/tmp")).resolve(strict=True)
if len(os.fsencode(canonical))>32 or canonical.is_symlink() or canonical.stat().st_uid!=os.getuid(): raise RuntimeError("short original owned temporary root required")
env["TMPDIR"]=str(canonical)
sys.dont_write_bytecode=True
report={"source_sha":source,"source_tree":git("rev-parse","HEAD^{tree}"),"canonical_tmpdir":str(canonical),"v8_manifest_sha256":hashlib.sha256(pinbytes).hexdigest(),"private_v8_inputs":private_input_record,"state":"starting","steps":[],"full_chain_acceptance":{"positive":0,"no_update":0,"daemon_root_cold_restart":0}}
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
if git("rev-parse","HEAD")!=source or git("status","--porcelain=v1","--untracked-files=all"):
    raise RuntimeError("fixed source must remain clean immediately before native tests")

if git("hash-object","scripts/hepta_c_observer_coverage.py")!="3ac2aab7e5b9fba93cd2371085a6cf66e2b84c87":
    raise RuntimeError("frozen combined inventory blob changed")
sys.path.insert(0,str(repo/"scripts"))
from hepta_c_observer_coverage import EXPECTED_CASES, OWNER_GROUPS, assess_retained_original_observer_coverage
if len(EXPECTED_CASES)!=201 or len(set(EXPECTED_CASES))!=201 or len(OWNER_GROUPS)!=43:
    raise RuntimeError("reviewed original-owner inventory changed")
report["purpose"]="actual original 190-case owner suite plus 11 existing V2 metadata cases on this fixed source; no ordinary-task acceptance"
report["expected_owner_cases"]=EXPECTED_CASES
report["expected_owner_groups"]=len(OWNER_GROUPS)
packages=sorted({package for package,_ in EXPECTED_CASES})
if packages!=["codex-hepta-agentd","codex-hepta-intelligence-eval","codex-hepta-learning-artifacts","codex-hepta-neuron"]:
    raise RuntimeError("reviewed original-owner packages changed")
expression=" | ".join("(package(="+package+") & test(="+name+"))" for package,name in EXPECTED_CASES)
junit=repo/"codex-rs/target/nextest/local/junit.xml"
junit.unlink(missing_ok=True)
command=["just","test","--locked","--offline",*[arg for package in packages for arg in ("-p",package)],"--lib","-E",expression,"--test-threads","2","--retries","0","--no-tests","fail","--status-level","pass","--success-output","final","--failure-output","final"]
execution=out/"focused-native.json"
native_exit=step("focused-native",v8+["/usr/bin/python3",str(repo/"scripts/hepta_ci_exec.py"),"--output",str(execution),"--minimum-tests","201","--timeout-seconds","3600","--",*command])
xmlpath=out/"focused-native.junit.xml"
collect_exit=step("focused-junit",["/usr/bin/python3",str(repo/"scripts/hepta_ci_junit.py"),"--execution",str(execution),"--junit",str(junit),"--output",str(xmlpath)])
record=json.loads(execution.read_bytes())
if record["source_sha"]!=source:raise RuntimeError("original execution has another source")
report["native_tests_executed"]=None
if xmlpath.exists():
    from hepta_ci_junit import NoDoctypeTreeBuilder
    document=ET.fromstring(xmlpath.read_bytes(),parser=ET.XMLParser(target=NoDoctypeTreeBuilder()))
    cases=list(document.iter("testcase"))
    actual=collections.Counter((c.get("classname"),c.get("name")) for c in cases)
    expected=collections.Counter(EXPECTED_CASES)
    failure_tags={"failure","error","skipped","flakyFailure","flakyError","rerunFailure","rerunError"}
    rejected=[{"package":c.get("classname"),"name":c.get("name"),"diagnostics":[n.text for n in c if n.tag in failure_tags]} for c in cases if any(n.tag in failure_tags for n in c)]
    report["owner_coverage"]={"total_cases":len(cases),"exact_selected_cases":actual==expected,"raw_junit_bytes":xmlpath.stat().st_size,"raw_junit_sha256":sha(xmlpath),"failed_or_skipped":rejected}
    if actual==expected:
        report["native_tests_executed"]=201
    if actual!=expected:raise RuntimeError("actual original owner case coverage changed")
report.update(native_exit_code=native_exit,collection_exit_code=collect_exit,source_after=git("rev-parse","HEAD"),source_status_after=git("status","--porcelain=v1","--untracked-files=all"),execution_log_file=record.get("log_file"),execution_log_bytes=record.get("log_bytes"),execution_log_sha256=record.get("log_sha256"))
report["original_observer_coverage"]={"state":"not-qualified-because-original-execution-failed","exact_pass_coverage":False}
if native_exit==0 and collect_exit==0:
    report["original_observer_coverage"]=assess_retained_original_observer_coverage(execution,xmlpath)
report["state"]="passed" if native_exit==0 and collect_exit==0 and report["native_tests_executed"]==201 and not report["owner_coverage"]["failed_or_skipped"] and report["original_observer_coverage"].get("exact_pass_coverage") is True and report["source_after"]==source and not report["source_status_after"] else "failed"
checkpoint()
raise SystemExit(0 if report["state"]=="passed" else 1)
