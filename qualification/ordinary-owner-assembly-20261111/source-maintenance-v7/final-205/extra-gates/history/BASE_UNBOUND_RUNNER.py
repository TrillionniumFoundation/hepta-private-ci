"""Separate operator-only additional test gate proposal. UNBOUND: DO NOT LAUNCH.

The original 096b seven-package / Root17 harness is neither changed nor invoked.
This runner reports its own observed executions; it is not hepta_ci_exec.
"""
import gzip
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

FIXED_CONFIG = json.loads(r'''{"schema_version":1,"binding_state":"UNBOUND_DO_NOT_LAUNCH","head":"UNBOUND_FINAL_SOURCE_HEAD","tree":"UNBOUND_FINAL_SOURCE_TREE","source_manifest_blob":"UNBOUND_FINAL_SOURCE_MANIFEST_BLOB","source_manifest_path":"UNBOUND_FINAL_SOURCE_MANIFEST_PATH","source_file_count":"UNBOUND_FINAL_SOURCE_FILE_COUNT","work_root":"/home/qq/af52-learning-local-decision-20261111","work_name":"UNBOUND_FRESH_EXTRA_GATE_WORK_NAME","attempt":"UNBOUND_FRESH_EXTRA_GATE_ATTEMPT","reference_repository":"/home/qq/af52-learning-local-decision-20261111/ordinary-control-completion-maintenance-v2/source","reference_head":"UNBOUND_FRESH_READONLY_REFERENCE_HEAD","reference_tree":"UNBOUND_FRESH_READONLY_REFERENCE_TREE","operator_target":"/home/qq/af52-learning-20261111/target","just_path":"/home/qq/hepta-learning-native-4f559bf-d9fb-20261108/transfer/just","rustc_path":"/home/qq/.cargo/bin/rustc","cargo_home":"/home/qq/.cargo","rustup_home":"/home/qq/.rustup","path":"/home/qq/hepta-learning-native-4f559bf-d9fb-20261108/transfer:/home/qq/.cargo/bin:/usr/local/bin:/usr/bin:/bin","overall_timeout_seconds":27000,"evidence_reserve_seconds":120,"fixture_binding_state":"UNBOUND_REVIEWED_SAME_SOURCE_FIXTURES","fixture_evidence_blob":"UNBOUND_REVIEWED_FIXTURE_EVIDENCE_BLOB"}''')
TEST_SUITES = json.loads(r'''[{"id":"targeted-core","stage":"targeted","command":["just","test","--locked","--offline","-p","codex-core","--lib","-E","test(session::original_shutdown::tests::) | test(thread_manager::original_shutdown::tests::) | test(codex_delegate::tests::) | test(thread_manager::tests::shutdown_all_threads_bounded_submits_shutdown_to_every_thread) | test(thread_manager::tests::cancelled_unclaimed_new_startup_removes_runtime_and_materialized_store)","--retries","0","--success-output","final","--failure-output","final"],"required_families":["session::original_shutdown::tests::","thread_manager::original_shutdown::tests::","codex_delegate::tests::"],"required_exact_tests":["thread_manager::tests::shutdown_all_threads_bounded_submits_shutdown_to_every_thread","thread_manager::tests::cancelled_unclaimed_new_startup_removes_runtime_and_materialized_store"]},{"id":"targeted-app-server","stage":"targeted","command":["just","test","--locked","--offline","-p","codex-app-server","--lib","-E","test(original_owned_shutdown::tests::) | test(request_serialization::tests::) | test(configured_mcp_runtime::tests::) | test(models_refresh_worker::tests::) | test(turn_cost_worker::tests::)","--retries","0","--success-output","final","--failure-output","final"],"required_families":["original_owned_shutdown::tests::","request_serialization::tests::","configured_mcp_runtime::tests::","models_refresh_worker::tests::","turn_cost_worker::tests::"],"required_exact_tests":[]},{"id":"targeted-rmcp-client","stage":"targeted","command":["just","test","--locked","--offline","-p","codex-rmcp-client","--lib","-E","test(stdio_server_launcher::owned_shutdown::tests::)","--retries","0","--success-output","final","--failure-output","final"],"required_families":["stdio_server_launcher::owned_shutdown::tests::"],"required_exact_tests":[]},{"id":"targeted-mcp","stage":"targeted","command":["just","test","--locked","--offline","-p","codex-mcp","--lib","-E","test(connection_manager::tests::shutdown_) | test(connection_manager::tests::cancelling_startup_does_not_disable_a_ready_client) | test(runtime::tests::) | test(rmcp_client::tests::)","--retries","0","--success-output","final","--failure-output","final"],"required_families":["connection_manager::tests::shutdown_","runtime::tests::","rmcp_client::tests::"],"required_exact_tests":["connection_manager::tests::cancelling_startup_does_not_disable_a_ready_client"]},{"id":"full-codex-core","stage":"full-crate","command":["just","test","--locked","--offline","-p","codex-core","--retries","0","--success-output","final","--failure-output","final"],"required_families":[],"required_exact_tests":[]},{"id":"full-codex-app-server","stage":"full-crate","command":["just","test","--locked","--offline","-p","codex-app-server","--retries","0","--success-output","final","--failure-output","final"],"required_families":[],"required_exact_tests":[]},{"id":"full-codex-rmcp-client","stage":"full-crate","command":["just","test","--locked","--offline","-p","codex-rmcp-client","--retries","0","--success-output","final","--failure-output","final"],"required_families":[],"required_exact_tests":[]},{"id":"full-codex-mcp","stage":"full-crate","command":["just","test","--locked","--offline","-p","codex-mcp","--retries","0","--success-output","final","--failure-output","final"],"required_families":[],"required_exact_tests":[]},{"id":"full-workspace","stage":"full-workspace","command":["just","test","--locked","--offline","--retries","0","--success-output","final","--failure-output","final"],"required_families":[],"required_exact_tests":[]}]''')
# Root must review and freeze any actual current-source fixture inputs here.
# An empty table still requires a real fixed evidence blob explaining why no
# externally injected binary is required. Never inherit arbitrary binary paths.
FIXTURE_BINDINGS = []
ORIGINAL_HARNESS = "096b5b69c1295560f3a6c9e0da51e2708a0c996c"
SUPERVISOR_ORIGIN = "447e5720c40d069d549e32ab00e886f2ab0ffb0c"
URL = "https://github.com/TrillionniumFoundation/hepta-private-ci.git"

# Refuse BEFORE filesystem mutation, Git commands or any child creation.
if len(sys.argv) != 2:
    raise ValueError("one exact reviewed CONFIG argument is required")
C = json.loads(sys.argv[1])
if C != FIXED_CONFIG:
    raise ValueError("CONFIG differs from the embedded reviewed exact binding")
if C["binding_state"] != "BOUND_REVIEWED_EXTRA_GATES":
    raise ValueError("unbound additional-gate proposal must not launch")
if C["fixture_binding_state"] != "BOUND_REVIEWED_SAME_SOURCE_FIXTURES":
    raise ValueError("current-source fixture dependency evidence is unbound")
if any(isinstance(v, str) and "UNBOUND" in v for v in C.values()):
    raise ValueError("replace and review every fixed binding before launch")
for key in ("head", "tree", "source_manifest_blob", "reference_head",
            "reference_tree", "fixture_evidence_blob"):
    if re.fullmatch(r"[0-9a-f]{40}", C[key]) is None:
        raise ValueError("invalid fixed Git identity: " + key)
if type(C["source_file_count"]) is not int or C["source_file_count"] <= 0:
    raise ValueError("an exact positive reviewed source file count is required")
if (type(C["overall_timeout_seconds"]) is not int
        or not 600 <= C["overall_timeout_seconds"] <= 27000
        or C["evidence_reserve_seconds"] != 120):
    raise ValueError("one bounded total budget including evidence is required")
if os.name != "posix" or not sys.platform.startswith("linux"):
    raise ValueError("the actual required Linux custody tests must be selectable")
if os.getuid() == 0 or os.geteuid() == 0:
    raise ValueError("this gate must run only as the original operator")
for key in ("work_name", "attempt"):
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", C[key]) is None:
        raise ValueError("fresh bounded exact work identity required")

START = time.monotonic()
DEADLINE = START + C["overall_timeout_seconds"]
EVIDENCE_RESERVE_SECONDS = C["evidence_reserve_seconds"]
FINALIZING = False
EVIDENCE_DEADLINE = DEADLINE
WORK = Path(C["work_root"]) / C["work_name"]
SOURCE = WORK / "source"
RECORDS = WORK / "records"
REFERENCE = Path(C["reference_repository"])
TARGET = Path(C["operator_target"])
for path in [WORK.parent, REFERENCE, TARGET, Path(C["just_path"]),
             Path(C["cargo_home"]), Path(C["rustup_home"])]:
    if not path.is_absolute() or path.resolve() != path or ".." in path.parts:
        raise ValueError("exact canonical existing operator path required: " + str(path))
if (REFERENCE == WORK or REFERENCE.is_relative_to(WORK)
        or TARGET == WORK or TARGET.is_relative_to(WORK)
        or WORK.is_relative_to(REFERENCE)):
    raise ValueError("source, read-only donor and shared operator target must be separate")
mp = Path(C["source_manifest_path"])
if mp.is_absolute() or ".." in mp.parts or not mp.parts:
    raise ValueError("fixed manifest must be a safe repository-relative path")
WORK.mkdir(mode=0o700)
RECORDS.mkdir(mode=0o700)
os.umask(0o022)

env = dict(os.environ)
# Keep the operator HOME and original platform/environment skip behavior.
for key in list(env):
    if (key.startswith("CARGO_BIN_EXE_") or key.startswith("NEXTEST_BIN_EXE_")
            or key.startswith("GIT_CONFIG_")):
        env.pop(key, None)
for key in ["NEXTEST_PROFILE", "NEXTEST_USER_CONFIG_FILE", "HEPTA_NEXTTEST_FULL_METADATA",
            "SOURCE_SHA", "TESTED_SHA", "BASE_SHA", "HEPTA_CI_LANE",
            "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"]:
    env.pop(key, None)
env.update({
    "PATH": C["path"], "GIT_TERMINAL_PROMPT": "0",
    "CARGO_TARGET_DIR": str(TARGET), "RUSTUP_TOOLCHAIN": "1.96.0",
    "CARGO_HOME": C["cargo_home"], "RUSTUP_HOME": C["rustup_home"],
    "CARGO_INCREMENTAL": "0", "CARGO_BUILD_JOBS": "2",
    "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0",
    "CARGO_NET_OFFLINE": "true", "PYTHONDONTWRITEBYTECODE": "1",
    "BINDGEN_EXTRA_CLANG_ARGS": "-isystem/usr/lib/gcc/x86_64-linux-gnu/15/include",
    "SOURCE_SHA": C["head"], "TESTED_SHA": C["head"], "HEPTA_CI_LANE": "source-head",
})
R = {
    "schema_version": 1,
    "classification": "ADDITIONAL_FOUR_CRATE_AND_WORKSPACE_TEST_GATES",
    "producer": "hepta-extra-gates-reviewed-supervisor",
    "original_harness_blob_unchanged": ORIGINAL_HARNESS,
    "supervisor_origin": SUPERVISOR_ORIGIN,
    "input": C, "status": "running", "steps": [], "errors": [],
    "source_ready": False, "completion_unknown": False, "all_nine_passed": False,
    "ordinary_business_counts": [0, 0, 0], "original_qualification_run": False,
    "suite_results": {s["id"]: {"status": "not-run", "command": s["command"]} for s in TEST_SUITES},
    "immutable_artifacts": [],
}

def supervisor_interrupt(signum,frame):
    R["external_interruption_signal"]=signum
    raise InterruptedError("source maintenance supervisor interrupted by signal "+str(signum))

def sha(data): return hashlib.sha256(data).hexdigest()

def blob(data): return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def read_bytes(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        a=os.fstat(fd)
        assert stat.S_ISREG(a.st_mode),"regular file required"
        with os.fdopen(fd,"rb",closefd=False) as f: data=f.read()
        b=os.fstat(fd)
        ident=lambda x:(x.st_dev,x.st_ino,x.st_mode,x.st_size,x.st_mtime_ns,x.st_ctime_ns)
        assert ident(a)==ident(b) and len(data)==a.st_size,"changed original file"
        return data
    finally: os.close(fd)

def save(name,value):
    raw=(json.dumps(value,indent=2,sort_keys=True)+"\n").encode()
    tmp=RECORDS/(name+".tmp"); destination=RECORDS/name
    with open(tmp,"wb") as f: f.write(raw);f.flush();os.fsync(f.fileno())
    tmp.replace(destination)
    return {"path":str(destination),"bytes":len(raw),"sha256":sha(raw),"git_blob":blob(raw)}

def progress(stage):
    R["stage"]=stage;save("progress.json",R)
    print(json.dumps({"stage":stage,"status":R["status"],"records":str(RECORDS)},sort_keys=True),flush=True)

def kill_owned_group_before_reap(p):
    # The exact session/group was just created by us. Kill before reaping its leader.
    # A timeout remains fatal and completion-unknown; this does not certify every descendant's exit.
    try: os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    reap_budget = min(10, max(0, DEADLINE - time.monotonic()))
    try: p.wait(timeout=reap_budget)
    except subprocess.TimeoutExpired: pass

def command(label,args,timeout,cwd=None,required=True):
    if FINALIZING: raise RuntimeError("new work is forbidden during evidence cleanup")
    start=time.monotonic(); log=RECORDS/(label+".log")
    progress(label);budget=remaining(timeout)
    with open(log,"xb") as output:
        try: p=subprocess.Popen(args,cwd=cwd or SOURCE,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
        except BaseException as error:
            R["completion_unknown"]=True
            R.setdefault("child_creation_unknown",[]).append({"label":label,"command":args,"error_type":type(error).__name__,"error":str(error)})
            save("progress.json",R)
            raise
        timeout_hit=False
        try: code=p.wait(timeout=budget)
        except subprocess.TimeoutExpired:
            timeout_hit=True;R["completion_unknown"]=True
            R.setdefault("timed_out_commands",[]).append(label)
            kill_owned_group_before_reap(p);code=p.returncode
        except BaseException as error:
            R["completion_unknown"]=True
            aborted={"label":label,"command":args,"cwd":str(cwd or SOURCE),"log_path":str(log),"error_type":type(error).__name__,"error":str(error),"leader_returncode":p.returncode}
            if p.returncode is None:
                kill_owned_group_before_reap(p)
                aborted["owned_group_kill_requested_before_reap"]=True
            else:
                aborted["group_cleanup_not_attempted_after_leader_reap"]=True
            R.setdefault("aborted_commands",[]).append(aborted)
            save(label+".aborted.json",aborted);save("progress.json",R)
            raise
    step={"label":label,"command":args,"cwd":str(cwd or SOURCE),"owned_leader_pid":p.pid,"created_pgid":p.pid,"leader_reaped":p.returncode is not None,"exit_code":code,"timed_out":timeout_hit,"elapsed_seconds":time.monotonic()-start,"log_path":str(log),"log_may_be_incomplete":timeout_hit}
    R["steps"].append(step);save(label+".execution.json",step);save("progress.json",R)
    data=read_bytes(log)
    step["log"]={"path":str(log),"bytes":len(data),"sha256":sha(data),"git_blob":blob(data)}
    save(label+".execution.json",step);save("progress.json",R)
    print(json.dumps({"completed":label,"exit_code":code,"timed_out":timeout_hit,"log_bytes":len(data)},sort_keys=True),flush=True)
    if timeout_hit: raise TimeoutError("owned command timed out; no subsequent work/capture/publication may assume completion: "+label)
    if required and code!=0: raise RuntimeError("source maintenance command failed: "+label)
    return code,data

def retain_git_read_failure(argv,directory,kind,output,error,returncode=None):
    number=R.get("git_read_failure_counter",0);R["git_read_failure_counter"]=number+1
    item={"command":argv,"cwd":str(directory),"kind":kind,"returncode":returncode,"during_evidence_cleanup":FINALIZING}
    for stream_name,data in [("stdout",output),("stderr",error)]:
        if data is None:
            item[stream_name]={"captured":False,"reason":"no bytes supplied by the original operation"}
            continue
        if not isinstance(data,bytes):
            item[stream_name]={"captured":False,"reason":"unexpected non-byte operation result","type":type(data).__name__}
            continue
        path=RECORDS/("git-read-failure-%03d.%s.bin"%(number,stream_name))
        with open(path,"xb") as f: f.write(data);f.flush();os.fsync(f.fileno())
        item[stream_name]={"captured":True,"path":str(path),"bytes":len(data),"sha256":sha(data),"git_blob":blob(data)}
    pin=save("git-read-failure-%03d.json"%number,item)
    R.setdefault("git_read_failure_evidence",[]).append(pin);save("progress.json",R)

def git_read(*args,cwd=None):
    if FINALIZING:
        budget=min(30,EVIDENCE_DEADLINE-time.monotonic())
        if budget<=0: raise TimeoutError("separate evidence cleanup budget exhausted")
    else: budget=remaining(120)
    argv=["git","--no-optional-locks",*args]
    try: p=subprocess.Popen(argv,cwd=cwd or SOURCE,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    except BaseException as error:
        R["completion_unknown"]=True
        R.setdefault("child_creation_unknown",[]).append({"command":argv,"cwd":str(cwd or SOURCE),"error_type":type(error).__name__,"error":str(error),"during_evidence_cleanup":FINALIZING})
        save("progress.json",R)
        raise
    try: output,error=p.communicate(timeout=budget)
    except subprocess.TimeoutExpired as exc:
        R["completion_unknown"]=True
        R.setdefault("timed_out_reads",[]).append({"command":argv,"cwd":str(cwd or SOURCE),"during_evidence_cleanup":FINALIZING})
        if p.returncode is None: kill_owned_group_before_reap(p)
        else: R.setdefault("reaped_group_cleanup_unknown",[]).append({"command":argv,"pid":p.pid})
        if p.stdout is not None: p.stdout.close()
        if p.stderr is not None: p.stderr.close()
        retain_git_read_failure(argv,cwd or SOURCE,"timeout",exc.output,exc.stderr,p.returncode)
        raise TimeoutError("bounded owned Git read timed out") from exc
    except BaseException as exc:
        R["completion_unknown"]=True
        if p.returncode is None: kill_owned_group_before_reap(p)
        else: R.setdefault("reaped_group_cleanup_unknown",[]).append({"command":argv,"pid":p.pid})
        if p.stdout is not None: p.stdout.close()
        if p.stderr is not None: p.stderr.close()
        retain_git_read_failure(argv,cwd or SOURCE,"aborted",getattr(exc,"output",None),getattr(exc,"stderr",None),p.returncode)
        raise
    if p.returncode!=0:
        retain_git_read_failure(argv,cwd or SOURCE,"nonzero-exit",output,error,p.returncode)
        raise subprocess.CalledProcessError(p.returncode,argv,output=output,stderr=error)
    return output

def identity(directory):
    return {"head":git_read("rev-parse","HEAD",cwd=directory).decode().strip(),"tree":git_read("rev-parse","HEAD^{tree}",cwd=directory).decode().strip(),"status":git_read("status","--porcelain",cwd=directory).decode()}


def remaining(maximum):
    reserve = 0 if FINALIZING else EVIDENCE_RESERVE_SECONDS
    value = min(maximum, DEADLINE - time.monotonic() - reserve)
    if value <= 0:
        raise TimeoutError("single additional-gate absolute budget exhausted")
    return value


signal.signal(signal.SIGTERM, supervisor_interrupt)
signal.signal(signal.SIGHUP, supervisor_interrupt)

def git(*args, path=SOURCE):
    return git_read(*args, cwd=path)

def file_digest(path):
    data = read_bytes(path)
    return {"path": str(path), "bytes": len(data),
            "sha256": sha(data), "git_blob": blob(data)}

def retain_immutable(path):
    item = file_digest(path)
    R["immutable_artifacts"].append(item)
    return item

def physical_file_observation(path, maximum=64 * 1024 * 1024):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            raise RuntimeError("native report is not a bounded regular file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(maximum + 1)
        after = os.fstat(fd)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid",
                  "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(data) > maximum or len(data) != before.st_size
                or any(getattr(before, f) != getattr(after, f) for f in fields)):
            raise RuntimeError("native report changed while reading")
        return data, {
            "path": str(path), "identity": {f: getattr(after, f) for f in fields},
            "bytes": len(data), "sha256": sha(data), "git_blob": blob(data),
        }
    finally:
        os.close(fd)

def clean():
    observed = identity(SOURCE)
    if observed != {"head": C["head"], "tree": C["tree"], "status": ""}:
        raise RuntimeError("fixed source identity or clean state changed")
    return observed

TOOLS = {
    "justfile": "a215a76cf407ace9715bca39c20497014e7dd4dc",
    "scripts/just-shell.py": "bb2db6ebc4312a301ee39d2793fde16289d046d8",
    "scripts/run-nextest.py": "1ed63abe84267b320cbfb0123a70aac5507f4595",
    "scripts/hepta_ci_exec.py": "c9434b3a4afb31f80e323d543936386a2fa738de",
    "scripts/hepta_ci_junit.py": "683626df091bdfe160a8965fdc92bf40f5783cf8",
    "scripts/verify_hepta_callers.py": "7a6709691c372504ca11b5d2a74e14ba819fca8f",
    "scripts/hepta_typed_callers.py": "e23bb8aa42241b429ef5dbce5a4660853b66eb2f",
    "codex-rs/.config/nextest.toml": "0904c42a41594d3ae4dc6f196e64f35f0b85bd2c",
    "codex-rs/rust-toolchain.toml": "917d2492264a35bc9c0feaef41878d8825870866",
}

def check_tools():
    for path, expected in TOOLS.items():
        if blob(read_bytes(SOURCE / path)) != expected:
            raise RuntimeError("fixed tool/profile/checker source differs: " + path)

def external_tools():
    result = {}
    for name in ("just", "cargo", "cargo-nextest", "python3"):
        selected = shutil.which(name, path=env["PATH"])
        if not selected:
            raise RuntimeError("required existing operator tool unavailable: " + name)
        resolved = Path(selected).resolve(strict=True)
        if name == "just" and resolved != Path(C["just_path"]).resolve(strict=True):
            raise RuntimeError("just PATH resolution differs from the exact operator binary")
        result[name] = {"selected": selected, "resolved": str(resolved),
                        "file": file_digest(resolved)}
    resolved = Path(C["rustc_path"]).resolve(strict=True)
    result["rustc"] = {"selected": C["rustc_path"], "resolved": str(resolved),
                       "file": file_digest(resolved)}
    return result

def check_fixture_bindings():
    observations = []
    keys = set()
    for item in FIXTURE_BINDINGS:
        if set(item) != {"source_head", "source_tree", "path", "sha256",
                         "evidence_path", "evidence_git_blob", "environment_keys"}:
            raise RuntimeError("fixture binding schema differs")
        if item["source_head"] != C["head"] or item["source_tree"] != C["tree"]:
            raise RuntimeError("fixture binding belongs to a different source")
        path = Path(item["path"])
        evidence = Path(item["evidence_path"])
        for current in (path, evidence):
            if not current.is_absolute() or current.resolve(strict=True) != current:
                raise RuntimeError("fixture evidence must use a reviewed actual canonical path")
        actual = file_digest(path)
        original = file_digest(evidence)
        if (actual["sha256"] != item["sha256"]
                or original["git_blob"] != item["evidence_git_blob"]):
            raise RuntimeError("actual fixture binary or its reviewed source evidence differs")
        if not os.access(path, os.X_OK):
            raise RuntimeError("fixture input is not an existing executable")
        for key in item["environment_keys"]:
            if (not re.fullmatch(r"(?:CARGO_BIN_EXE_|NEXTEST_BIN_EXE_)[A-Za-z0-9_-]+", key)
                    or key in keys):
                raise RuntimeError("duplicate or invalid fixed fixture environment key")
            keys.add(key)
            env[key] = str(path)
        observations.append({"binding": item, "actual": actual, "evidence": original})
    return observations

def collector_identity(observation):
    return {"commit": observation["head"], "tree": observation["tree"],
            "dirty": observation["status"] != ""}

def test_suite(spec):
    name = spec["id"]
    command_args = spec["command"]
    if R["completion_unknown"] or FINALIZING:
        raise RuntimeError("new test dispatch forbidden after unknown completion or finalization")
    before = clean()
    check_tools()
    R["suite_results"][name]["status"] = "preparing"
    progress(name + "-prepare")
    report = SOURCE / "codex-rs/target/nextest/local/junit.xml"
    if report.resolve(strict=False) != report:
        raise RuntimeError("native local JUnit path was redirected")
    if os.path.lexists(report):
        prior_data, prior_identity = physical_file_observation(report)
        prior = RECORDS / (name + ".prior-junit-excluded.xml")
        if os.path.lexists(prior):
            raise RuntimeError("prior report archive already exists")
        report.rename(prior)
        retained = retain_immutable(prior)
        if retained["sha256"] != prior_identity["sha256"]:
            raise RuntimeError("prior report changed while being excluded")
        save(name + ".prior-junit-excluded.json", prior_identity)
    if os.path.lexists(report):
        raise RuntimeError("old or dangling native JUnit was not excluded")

    suite_started = time.monotonic()
    record = {
        "schema_version": 1, "producer": "hepta-extra-gates-reviewed-supervisor",
        "status_scope": "actual process plus terminal summary; JUnit gate is separate",
        "source_sha": C["head"], "tested_sha": C["head"], "lane": "source-head",
        "extra_attempt": C["attempt"], "suite_id": name,
        "command": command_args, "working_directory": str(SOURCE),
        "before": collector_identity(before), "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running", "command_exit_code": None,
    }
    execution_path = RECORDS / (name + ".execution.json")
    if os.path.lexists(execution_path):
        raise RuntimeError("execution record already belongs to another invocation")
    save(name + ".execution.json", record)
    R["suite_results"][name]["status"] = "running"
    try:
        code, data = command(name + "-command", command_args,
                             C["overall_timeout_seconds"], required=False)
    except BaseException as error:
        record.update(status="incomplete", elapsed_seconds=time.monotonic() - suite_started,
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      error_type=type(error).__name__, error=str(error),
                      completion_unknown=R["completion_unknown"])
        save(name + ".execution.json", record)
        R["suite_results"][name].update(status="incomplete", error=str(error))
        raise
    after = identity(SOURCE)
    passed, failed = observed_test_counts(data.decode("utf-8", errors="replace"))
    normalized_exit = code if code >= 0 else 128 - code
    process_passed = (code == 0 and passed > 0 and failed == 0
                      and before == after and not R["completion_unknown"])
    record.update(
        status="passed" if process_passed else "failed",
        exit_code=normalized_exit if not process_passed and normalized_exit else (0 if process_passed else 1),
        command_exit_code=code, after=collector_identity(after),
        elapsed_seconds=time.monotonic() - suite_started,
        timed_out=False, output_limit_exceeded=False, minimum_tests=1,
        observed_passed_tests=passed, observed_failed_tests=failed,
        finished_at=datetime.now(timezone.utc).isoformat(),
        log_file=name + "-command.log", log_bytes=len(data), log_sha256=sha(data),
        direct_supervisor_record=name + "-command.execution.json",
    )
    save(name + ".execution.json", record)
    raw_log = retain_immutable(RECORDS / record["log_file"])
    if raw_log["sha256"] != record["log_sha256"] or raw_log["bytes"] != record["log_bytes"]:
        raise RuntimeError("original command log changed after observation")
    if before != after:
        raise RuntimeError("source changed during the actual additional test command")
    if R["completion_unknown"]:
        raise RuntimeError("unknown completion forbids even the JUnit collector")

    native = None
    native_error = None
    try:
        _, native = physical_file_observation(report)
    except (OSError, RuntimeError) as error:
        native_error = str(error)
    collect_args = ["python3", "scripts/hepta_ci_junit.py", "--execution",
                    str(execution_path), "--junit", str(report), "--output",
                    str(RECORDS / (name + ".junit.xml"))]
    collection_code, _ = command(name + "-junit", collect_args, 120, required=False)
    summary_path = RECORDS / (name + ".junit.summary.json")
    summary = json.loads(read_bytes(summary_path)) if summary_path.is_file() else {}
    retained_path = RECORDS / (name + ".junit.xml")
    counts = None
    coverage = {"missing_families": [], "missing_exact_tests": []}
    retained_pin = None
    if retained_path.is_file():
        retained_bytes = read_bytes(retained_path)
        retained_pin = retain_immutable(retained_path)
        if native is None or retained_pin["sha256"] != native["sha256"]:
            raise RuntimeError("retained JUnit differs from this actual native report")
        # The unchanged collector rejects declarations and invalid XML before
        # retaining it. Only its checked statuses permit interpretation here.
        if summary.get("status") in ("passed", "retained-failed"):
            parsed = ET.fromstring(retained_bytes)
            cases = list(parsed.iter("testcase"))
            executed = [c for c in cases if c.find("skipped") is None]
            names = [c.attrib["name"] for c in executed]
            failures = sum(c.find("failure") is not None for c in cases)
            errors = sum(c.find("error") is not None for c in cases)
            counts = {"total": len(cases), "executed": len(executed),
                      "passed": len(executed) - failures - errors,
                      "failed": failures, "errors": errors,
                      "skipped": len(cases) - len(executed)}
            coverage["missing_families"] = [
                family for family in spec["required_families"]
                if not any(n.startswith(family) for n in names)
            ]
            coverage["missing_exact_tests"] = [
                required for required in spec["required_exact_tests"] if required not in names
            ]
            save(name + ".roster.json", {
                "executed_names": names,
                "cases": [{"name": c.attrib.get("name"), "classname": c.attrib.get("classname"),
                           "skipped": c.find("skipped") is not None,
                           "failure": c.find("failure") is not None,
                           "error": c.find("error") is not None} for c in cases],
                "coverage": coverage,
                "skip_limit": "Keep original ignored/platform filters and printed environment early returns; executed test return is not business execution proof.",
            })
    if native is not None:
        _, native_after = physical_file_observation(report)
        if native_after != native:
            raise RuntimeError("native report changed during original collection")
    if summary_path.is_file():
        retain_immutable(summary_path)
    binding = {"native": native, "native_error": native_error,
               "execution": retain_immutable(execution_path),
               "retained": retained_pin, "collection_exit_code": collection_code,
               "summary_status": summary.get("status"), "counts": counts,
               "coverage": coverage}
    save(name + ".collection-binding.json", binding)
    if counts is not None:
        save(name + ".counts.json", counts)
    clean()
    check_tools()
    gate_passed = (process_passed and collection_code == 0
                   and summary.get("status") == "passed"
                   and counts is not None and counts["executed"] > 0
                   and not coverage["missing_families"]
                   and not coverage["missing_exact_tests"])
    R["suite_results"][name].update(
        status="passed" if gate_passed else "failed",
        command_exit_code=code, collection_exit_code=collection_code,
        counts=counts, coverage=coverage, execution=str(execution_path),
    )
    if not gate_passed:
        R["errors"].append({"suite": name, "actual_test_or_collection_failed": True})
    save("progress.json", R)
    return gate_passed

def observed_test_counts(text: str) -> tuple[int, int]:
    """Parse terminal runner summaries, never compile messages or ignored tests.

    Output is diagnostic evidence of the named command, not authentication of an
    arbitrary command's claims. A nextest summary supersedes nested libtest text.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)
    nextest = re.findall(r"Summary[^\n]*?\d+ tests? run: ([^\n]+)", text)
    if nextest:
        summary = nextest[-1]
        passed = re.search(r"(\d+) passed", summary)
        failed = sum(
            int(value)
            for value in re.findall(r"(\d+) (?:failed|timed out|leaked)", summary)
        )
        return int(passed[1]) if passed else 0, failed
    passed = failed = 0
    for match in re.finditer(
        r"test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed;", text
    ):
        passed += int(match[1])
        failed += int(match[2])
    for match in re.finditer(
        r"Ran (\d+) tests? in [^\n]+\n\s*\n?(OK|FAILED)(?: \(([^\n]*)\))?(?:\n|$)", text
    ):
        total = int(match[1])
        fields = dict(
            (key.strip(), int(value))
            for key, value in re.findall(r"([a-z ]+)=(\d+)", match[3] or "")
        )
        failures = sum(
            fields.get(key, 0) for key in ("failures", "errors", "unexpected successes")
        )
        failed += failures or (1 if match[2] == "FAILED" else 0)
        excluded = failures + sum(
            fields.get(key, 0) for key in ("skipped", "expected failures")
        )
        passed += max(0, total - excluded)
    return passed, failed



def snapshot(label):
    observed = clean()
    flags = git("ls-files", "-v", "-z").split(b"\0")
    if any(value and not value.startswith(b"H ") for value in flags):
        raise RuntimeError("source has skip/assume-unchanged/unmerged index entries")
    if git("ls-files", "--others", "--exclude-standard", "-z"):
        raise RuntimeError("unexpected untracked source")
    rows = []
    for entry in git("ls-tree", "-r", "-z", "HEAD").split(b"\0"):
        if not entry:
            continue
        header, rawpath = entry.split(b"\t", 1)
        mode, kind, blob = header.decode().split(" ")
        path = SOURCE / os.fsdecode(rawpath)
        if kind != "blob":
            raise RuntimeError("unsupported source entry: " + os.fsdecode(rawpath))
        header_sha = hashlib.sha1()
        sha = hashlib.sha256()
        if mode == "120000":
            if not path.is_symlink():
                raise RuntimeError("tracked symlink changed type")
            data = os.fsencode(os.readlink(path))
            header_sha.update(b"blob " + str(len(data)).encode() + b"\0" + data)
            sha.update(data)
            size = len(data)
        else:
            metadata = path.lstat()
            actual_mode = "100755" if metadata.st_mode & 0o111 else "100644"
            if not stat.S_ISREG(metadata.st_mode) or actual_mode != mode:
                raise RuntimeError("source file kind/mode differs: " + str(path))
            size = metadata.st_size
            header_sha.update(b"blob " + str(size).encode() + b"\0")
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    header_sha.update(block)
                    sha.update(block)
            if path.stat().st_size != size:
                raise RuntimeError("source size changed while hashing")
        if header_sha.hexdigest() != blob:
            raise RuntimeError("physical source bytes differ from HEAD: " + str(path))
        rows.append({"path": os.fsdecode(rawpath), "mode": mode, "bytes": size,
                     "git_blob": blob, "sha256": sha.hexdigest()})
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
    archive = RECORDS / (label + ".inventory.json.gz")
    with archive.open("xb") as stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=stream, mtime=0) as output:
            output.write(encoded)
    summary = {**observed, "files": len(rows), "inventory_sha256": hashlib.sha256(encoded).hexdigest()}
    save(label + ".json", {**summary, "inventory": file_digest(archive)})
    return summary



try:
    save("CONFIG.json", C)
    save("TEST_SUITES.json", TEST_SUITES)
    save("FIXTURE_BINDINGS.json", {
        "review_evidence_blob": C["fixture_evidence_blob"],
        "bindings": FIXTURE_BINDINGS,
    })
    R["reference_before"] = identity(REFERENCE)
    if R["reference_before"] != {"head": C["reference_head"], "tree": C["reference_tree"], "status": ""}:
        raise RuntimeError("read-only reference differs from the exact reviewed binding")
    command("isolated-clone", ["git", "clone", "--shared", "--no-checkout", "--no-hardlinks",
                              str(REFERENCE), str(SOURCE)], 600, cwd=WORK)
    command("fetch-exact-source", ["git", "-C", str(SOURCE), "fetch", "--no-tags", URL, C["head"]],
            600, cwd=WORK)
    if git_read("rev-parse", C["head"] + "^{tree}").decode().strip() != C["tree"]:
        raise RuntimeError("exact commit tree differs")
    command("checkout-exact-source", ["git", "-C", str(SOURCE), "checkout", "--detach", C["head"]],
            600, cwd=WORK)
    R["source_ready"] = True
    clean()
    raw_commit = git_read("cat-file", "commit", C["head"])
    if hashlib.sha1(b"commit " + str(len(raw_commit)).encode() + b"\0" + raw_commit).hexdigest() != C["head"]:
        raise RuntimeError("actual Git commit object differs")
    check_tools()
    raw_manifest = read_bytes(SOURCE / C["source_manifest_path"])
    if blob(raw_manifest) != C["source_manifest_blob"]:
        raise RuntimeError("fixed reviewed source manifest differs")
    original = json.loads(raw_manifest)
    if len(original["files"]) != C["source_file_count"]:
        raise RuntimeError("reviewed source manifest count differs")
    seen = set()
    for item in original["files"]:
        relative = Path(item["path"])
        if relative.is_absolute() or ".." in relative.parts or str(relative) in seen:
            raise RuntimeError("invalid or duplicate source manifest path")
        seen.add(str(relative))
        if blob(read_bytes(SOURCE / relative)) != item["post"]:
            raise RuntimeError("physical manifest source differs: " + str(relative))
    R["source_before"] = snapshot("source-before")
    R["external_tools_before"] = external_tools()
    R["fixture_bindings_before"] = check_fixture_bindings()
    _, rustc = command("operator-rustc", [C["rustc_path"], "-Vv"], 60, cwd=SOURCE / "codex-rs")
    if b"release: 1.96.0\n" not in rustc:
        raise RuntimeError("original repository-pinned Rust toolchain differs")
    for label, argv in [
        ("operator-just", ["just", "--version"]),
        ("operator-cargo", ["cargo", "--version"]),
        ("operator-nextest", ["cargo", "nextest", "--version"]),
        ("operator-python", ["python3", "--version"]),
    ]:
        command(label, argv, 60, cwd=SOURCE / "codex-rs")
    for stage in ("targeted", "full-crate", "full-workspace"):
        stage_ok = True
        for suite in [s for s in TEST_SUITES if s["stage"] == stage]:
            stage_ok = test_suite(suite) and stage_ok
        if not stage_ok:
            raise RuntimeError("a required stage failed; wider gates were not dispatched: " + stage)
    R["all_nine_passed"] = (
        len(R["suite_results"]) == 9
        and all(v["status"] == "passed" for v in R["suite_results"].values())
        and not R["errors"] and not R["completion_unknown"]
    )
    R["status"] = "additional-gates-passed" if R["all_nine_passed"] else "additional-gates-failed"
except BaseException as error:
    R["status"] = "additional-gates-failed"
    R["errors"].append({"type": type(error).__name__, "message": str(error),
                        "traceback": traceback.format_exc()})
    traceback.print_exc()
finally:
    FINALIZING = True
    # This is the SAME original deadline, not another cleanup allowance.
    EVIDENCE_DEADLINE = DEADLINE
    R["single_absolute_budget_seconds"] = C["overall_timeout_seconds"]
    R["evidence_reserve_inside_total_seconds"] = EVIDENCE_RESERVE_SECONDS
    if R["source_ready"] and not R["completion_unknown"]:
        try:
            R["source_after"] = snapshot("source-final")
            check_tools()
            if R.get("source_before") != R["source_after"]:
                raise RuntimeError("final actual physical source differs")
            R["external_tools_after"] = external_tools()
            if R["external_tools_after"] != R.get("external_tools_before"):
                raise RuntimeError("operator executables changed")
            R["fixture_bindings_after"] = check_fixture_bindings()
            if R["fixture_bindings_after"] != R.get("fixture_bindings_before"):
                raise RuntimeError("actual source-bound fixture inputs changed")
            for step in R["steps"]:
                if "log" in step:
                    actual = file_digest(Path(step["log"]["path"]))
                    if (actual["bytes"] != step["log"]["bytes"]
                            or actual["sha256"] != step["log"]["sha256"]):
                        raise RuntimeError("original direct-command log changed")
            for item in R["immutable_artifacts"]:
                if file_digest(Path(item["path"])) != item:
                    raise RuntimeError("original per-command evidence changed: " + item["path"])
        except BaseException as error:
            R["errors"].append({"final_source_or_evidence_check": str(error)})
    if R["completion_unknown"]:
        R["source_after"] = "not_certified_after_unknown_completion"
    try:
        R["reference_after"] = identity(REFERENCE)
        if R.get("reference_before") != R["reference_after"]:
            raise RuntimeError("read-only reference changed")
    except BaseException as error:
        R["errors"].append({"reference_check": str(error)})
    for entry in R["suite_results"].values():
        if entry["status"] == "not-run":
            entry["not_run_reason"] = "prior-stage failure, interruption or fixed budget; never PASS"
    R["elapsed_seconds"] = time.monotonic() - START
    if R["elapsed_seconds"] > C["overall_timeout_seconds"]:
        R["errors"].append({"original_total_budget_exceeded": True})
    if R["completion_unknown"]:
        R["status"] = "additional-gates-incomplete-unknown"
    elif not R["all_nine_passed"] or R["errors"]:
        R["status"] = "additional-gates-failed"
    result_pin = save("RESULT.json", R)
    progress("finished")
    print(json.dumps({"result": result_pin, "status": R["status"],
                      "original_harness_unchanged": ORIGINAL_HARNESS}, sort_keys=True), flush=True)
sys.exit(0 if R["status"] == "additional-gates-passed" else 1)
