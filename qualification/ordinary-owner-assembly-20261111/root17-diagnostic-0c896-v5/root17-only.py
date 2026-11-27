"""Run only seventeen actual UID0 component diagnostics on one exact clean source.

This is not full qualification and cannot replace the final ordinary-plus-Root harness.
Maintenance, QA, caller verification and ordinary test dispatch are deliberately absent.
The original Root, source, helper, evidence, timeout and cleanup checks are unchanged.
Provide the complete reviewed CONFIG as argv[1]; placeholders fail before setup.
"""
import ast
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

CONFIG = json.loads(sys.argv[1])
REQUIRED_KEYS = {
    "head", "tree", "format_base", "work_root", "work_name", "attempt",
    "reference_repository", "operator_target", "root_target", "just_path",
    "rustc_path", "cargo_home", "rustup_home", "path",
    "ordinary_packages", "root_packages", "expected_root_parents",
    "overall_timeout_seconds", "full_caller_timeout_seconds",
}
if set(CONFIG) != REQUIRED_KEYS:
    raise ValueError("CONFIG must have exactly the reviewed explicit keys")
for field in ("head", "tree", "format_base"):
    if re.fullmatch(r"[0-9a-f]{40}", CONFIG[field]) is None:
        raise ValueError("replace and pin " + field + " before execution")
for field in ("work_name", "attempt"):
    if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,79}", CONFIG[field]) is None:
        raise ValueError("one bounded fresh task name is required")
SIX_PACKAGES = [
    "codex-hepta-agentd", "codex-hepta-learning-artifacts",
    "codex-hepta-intelligence-eval", "codex-hepta-contracts",
    "codex-hepta-neuron", "codex-hepta-learning-ledger",
]
if CONFIG["ordinary_packages"] != SIX_PACKAGES:
    raise ValueError("the six-package source workflow roster must remain exact")
if CONFIG["root_packages"] != ["codex-hepta-agentd", "codex-hepta-contracts"]:
    raise ValueError("the actual Root test packages are agentd and contracts")
PARENTS = CONFIG["expected_root_parents"]
if (not isinstance(PARENTS, list) or len(PARENTS) != 17 or len(set(PARENTS)) != 17
        or any(re.fullmatch(r"[A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)+", p) is None for p in PARENTS)):
    raise ValueError("exactly seventeen distinct fixed-source Root parents required")
if (type(CONFIG["overall_timeout_seconds"]) is not int
        or not 3600 <= CONFIG["overall_timeout_seconds"] <= 27000
        or type(CONFIG["full_caller_timeout_seconds"]) is not int
        or not 1800 <= CONFIG["full_caller_timeout_seconds"] <= 3600):
    raise ValueError("explicit bounded supervisor and full-caller budgets required")
if os.getuid() == 0 or os.geteuid() == 0:
    raise ValueError("the diagnostic harness and helper builder must start as the operator")
UID, GID = os.getuid(), os.getgid()
HEAD, TREE, BASE = (CONFIG[k] for k in ("head", "tree", "format_base"))
for field in ("work_root", "reference_repository", "operator_target", "root_target",
              "just_path", "rustc_path", "cargo_home", "rustup_home"):
    path = Path(CONFIG[field])
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("an exact absolute original path is required: " + field)
    if field != "rustc_path" and str(path) != str(path.resolve()):
        raise ValueError("a canonical original path is required: " + field)
ROOT = Path(CONFIG["work_root"])
WORK = ROOT / CONFIG["work_name"]
SOURCE, RECORDS = WORK / "source", WORK / "records"
REFERENCE = Path(CONFIG["reference_repository"])
TARGET, ROOT_TARGET = Path(CONFIG["operator_target"]), Path(CONFIG["root_target"])
JUST = Path(CONFIG["just_path"])
if REFERENCE == WORK or REFERENCE.is_relative_to(WORK):
    raise ValueError("the donor must be a separate read-only repository")
if TARGET == ROOT_TARGET or TARGET.is_relative_to(WORK) or ROOT_TARGET.is_relative_to(WORK):
    raise ValueError("explicit separate operator/Root caches required")
if not str(ROOT_TARGET).startswith("/var/tmp/hepta-af52-root-"):
    raise ValueError("only the assigned Root component target is permitted")
ROOT_FIXTURE = Path("/run") / ("hepta-af52-final-" + HEAD[:12] + "-" + CONFIG["attempt"])
if len(str(ROOT_FIXTURE)) > 120:
    raise ValueError("bounded original UDS fixture path required")
WORK.mkdir(mode=0o700)
RECORDS.mkdir(mode=0o700)
os.umask(0o022)
STARTED = time.monotonic()
DEADLINE = STARTED + CONFIG["overall_timeout_seconds"]
env = dict(os.environ)
# Preserve the actual operator HOME. Remove only competing test/source overrides.
for key in list(env):
    if key.startswith("CARGO_BIN_EXE_") or key.startswith("GIT_CONFIG_"):
        env.pop(key, None)
for key in ("NEXTEST_PROFILE", "NEXTEST_USER_CONFIG_FILE", "HEPTA_NEXTTEST_FULL_METADATA",
            "SOURCE_SHA", "TESTED_SHA", "BASE_SHA", "HEPTA_CI_LANE",
            "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
    env.pop(key, None)
env.update({
    "PATH": CONFIG["path"], "GIT_TERMINAL_PROMPT": "0",
    "CARGO_TARGET_DIR": str(TARGET), "RUSTUP_TOOLCHAIN": "1.96.0",
    "CARGO_HOME": CONFIG["cargo_home"], "RUSTUP_HOME": CONFIG["rustup_home"],
    "CARGO_INCREMENTAL": "0", "CARGO_BUILD_JOBS": "2",
    "CARGO_PROFILE_DEV_DEBUG": "0", "CARGO_PROFILE_TEST_DEBUG": "0",
    "CARGO_NET_OFFLINE": "true", "PYTHONDONTWRITEBYTECODE": "1",
    "BINDGEN_EXTRA_CLANG_ARGS": "-isystem/usr/lib/gcc/x86_64-linux-gnu/15/include",
    "SOURCE_SHA": HEAD, "TESTED_SHA": HEAD, "HEPTA_CI_LANE": "source-head",
})
result = {
    "schema": "hepta.root17-component-diagnostic.v1",
    "classification": "ROOT_COMPONENT_DIAGNOSTIC_NOT_FULL_QUALIFICATION",
    "full_qualification_accepted": False,
    "replaces_final_harness": False,
    "scheduled_test_suites": ["root"],
    "not_run": ["maintenance", "product-bins-check", "qa-four-folders",
                "caller-self-test", "caller-full-verify", "ordinary-six-crate-tests"],
    "source_sha": HEAD, "source_tree": TREE, "format_base": BASE,
    "operator_uid": UID, "operator_euid": os.geteuid(), "operator_gid": GID,
    "source_path": str(SOURCE), "reference_path": str(REFERENCE),
    "status": "running", "steps": [], "errors": [], "cleanup": [],
    "source_workflow_packages": SIX_PACKAGES, "root_packages": CONFIG["root_packages"],
    "expected_root_parents": PARENTS, "ordinary_complete_chains": 0,
    "positive_adoption_chains": 0, "ordinary_no_update_rollback_chains": 0,
    "independent_consumer_accepted": False, "physical_daemon_root_restart_accepted": False,
    "predecessor_results_used": False, "known_failure_exemptions": False,
}
source_ready = root_setup_started = root_touched_records = False
initial_snapshot = tool_before = root_binaries_before = None
pending_commands = []

def save(name, value):
    destination = RECORDS / name
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(destination)

def progress(stage=None):
    if stage is not None:
        result["current_stage"] = stage
    save("progress.json", result)
    print(json.dumps({"stage": result.get("current_stage"), "status": result["status"],
                      "source": HEAD, "records": str(RECORDS)}, sort_keys=True), flush=True)

def file_digest(path):
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise RuntimeError("expected original regular file: " + str(path))
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, f) != getattr(after, f) for f in fields) or size != before.st_size:
        raise RuntimeError("file changed while hashing: " + str(path))
    return {"path": str(path), "bytes": size, "sha256": digest.hexdigest()}

def remaining(limit):
    left = int(DEADLINE - time.monotonic() - 180)
    if left <= 0:
        raise RuntimeError("qualification budget exhausted; reserve cleanup time")
    return min(limit, left)

def raw(name, command, cwd=ROOT, environment=None, timeout=120, check=True):
    """Bound bootstrap/launcher commands; original CI recorder bounds test groups."""
    record = {"name": name, "command": command, "cwd": str(cwd), "state": "running"}
    result["steps"].append(record)
    progress(name)
    log = RECORDS / (name + ".launch.log")
    began = time.monotonic()
    timed_out = False
    with log.open("xb") as output:
        child = subprocess.Popen(command, cwd=cwd, env=environment or env,
                                 stdout=output, stderr=subprocess.STDOUT,
                                 start_new_session=True)
        record["launcher_pid"] = child.pid
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # The original source-bound recorder alone owns its Rust timeout.
            # Never signal it or its descendants from this outer supervisor.
            timed_out = True
            code = None
            record["completion_unknown"] = True
            record["nested_completion_unknown"] = True
            result["completion_unknown"] = True
            pending_commands.append((name, child))
        output.flush()
        os.fsync(output.fileno())
    record.update(state="completed" if code is not None else "unknown", exit_code=code,
                  timed_out=timed_out, elapsed_seconds=time.monotonic()-began,
                  log=({"path":str(log),"complete":False} if timed_out else file_digest(log)))
    progress(name)
    if check and (code != 0 or timed_out):
        raise RuntimeError(name + " failed; original launch log retained")
    return record

def git(*args, path=SOURCE):
    return subprocess.check_output(["git", "--no-optional-locks", "-C", str(path), *args],
                                   env=env, timeout=120)

def identity(path=SOURCE):
    return {"head": git("rev-parse", "HEAD", path=path).decode().strip(),
            "tree": git("rev-parse", "HEAD^{tree}", path=path).decode().strip(),
            "status": git("status", "--porcelain=v1", "--untracked-files=all", path=path).decode()}

def clean():
    observed = identity()
    if observed != {"head": HEAD, "tree": TREE, "status": ""}:
        raise RuntimeError("fixed source is not clean: " + json.dumps(observed, sort_keys=True))
    return observed

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

def tool_snapshot(label):
    paths = [
        "justfile", "scripts/just-shell.py", "scripts/run-nextest.py", "scripts/format.py",
        "scripts/hepta_ci_exec.py", "scripts/hepta_ci_junit.py",
        "scripts/hepta_cell_test_helpers.py", "scripts/verify_hepta_callers.py",
        "codex-rs/.config/nextest.toml", "codex-rs/rust-toolchain.toml",
        ".github/workflows/hepta-daemon-learning-native.yml", "CALLERS.toml",
    ]
    observed = {p: file_digest(SOURCE / p) for p in paths}
    save(label + ".json", observed)
    return observed

def workflow_contract():
    workflow = (SOURCE / ".github/workflows/hepta-daemon-learning-native.yml").read_text()
    block = workflow[workflow.index("          parents = ["):workflow.index("          helpers = ")]
    parsed = ast.parse("\n".join(line[10:] for line in block.splitlines()))
    values = {}
    for node in parsed.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    package_args = [x for p in SIX_PACKAGES for x in ("-p", p)]
    if values != {"parents": PARENTS, "packages": package_args}:
        raise RuntimeError("current-source workflow roster/package set differs from fixed CONFIG")
    save("workflow-contract.json", {"source": HEAD, "tree": TREE, **values,
                                   "workflow": file_digest(SOURCE / ".github/workflows/hepta-daemon-learning-native.yml")})

def read_execution(path, command, must_pass=True):
    record = json.loads(path.read_text())
    required = {"source_sha": HEAD, "tested_sha": HEAD, "lane": "source-head",
                "command": command}
    if any(record.get(k) != v for k, v in required.items()):
        raise RuntimeError("original executor record differs from requested source/command")
    before, after = record.get("before"), record.get("after")
    if (not isinstance(before, dict) or before != after or before.get("commit") != HEAD
            or before.get("tree") != TREE or before.get("dirty") is not False):
        raise RuntimeError("original executor did not retain equal clean source identity")
    raw_log = path.parent / record["log_file"]
    log = file_digest(raw_log)
    if log["sha256"] != record.get("log_sha256") or log["bytes"] != record.get("log_bytes"):
        raise RuntimeError("original raw execution log differs")
    passed = (record.get("status") == "passed" and record.get("exit_code") == 0
              and record.get("command_exit_code") == 0
              and record.get("timed_out") is False
              and record.get("output_limit_exceeded") is False)
    if must_pass and not passed:
        raise RuntimeError("original executor recorded failure: " + path.name)
    return record, passed, raw_log

def root_environment(helper_env):
    keys = ("PATH", "SOURCE_SHA", "TESTED_SHA", "HEPTA_CI_LANE", "PYTHONDONTWRITEBYTECODE",
            "CARGO_INCREMENTAL", "CARGO_BUILD_JOBS", "CARGO_PROFILE_TEST_DEBUG",
            "CARGO_PROFILE_DEV_DEBUG", "CARGO_NET_OFFLINE", "BINDGEN_EXTRA_CLANG_ARGS",
            "RUSTUP_TOOLCHAIN", "CARGO_HOME", "RUSTUP_HOME")
    selected = {k: env[k] for k in keys}
    for key in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH", "LIBCLANG_PATH"):
        if key in env:
            selected[key] = env[key]
    selected.update({
        "CARGO_TARGET_DIR": str(ROOT_TARGET), "NEXTEST_PROFILE": "local",
        "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
        "GIT_CONFIG_VALUE_0": str(SOURCE),
        "HEPTA_HOST_AUTHORITY_QUALIFICATION_STATE_PARENT": str(ROOT_FIXTURE / "bind"),
        "HEPTA_HOST_AUTHORITY_QUALIFICATION_SOURCE": str(ROOT_FIXTURE / "source"),
        "HEPTA_CHECKPOINT_TEST_ROOT": str(ROOT_FIXTURE / "checkpoints"),
        "HEPTA_Q24_FACTORY_WITNESS_BIND": str(ROOT_FIXTURE / "witness-bind"),
        "HEPTA_Q24_FACTORY_WITNESS_SOURCE": str(ROOT_FIXTURE / "witness-source"),
    })
    selected.update(helper_env)
    return selected

ROOT_WRAPPER = r"""
import json,os,runpy,sys
assert os.getuid()==os.geteuid()==0, 'actual UID0 required'
os.umask(0o022)
proof,entry=sys.argv.pop(1),sys.argv.pop(1)
with open(proof,'x') as stream:
    json.dump({'uid':os.getuid(),'euid':os.geteuid(),'gid':os.getgid(),'pid':os.getpid()},stream)
    stream.flush()
    os.fsync(stream.fileno())
print('Root test uid=0',flush=True)
sys.argv[0]=entry
runpy.run_path(entry,run_name='__main__')
"""


ROOT_EXECUTION_READ = r"""
import hashlib,json,os,stat,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
parent,path=Path(sys.argv[1]),Path(sys.argv[2])
uid,gid=int(sys.argv[3]),int(sys.argv[4])
assert uid>0 and gid>=0
assert parent.is_absolute() and parent.resolve()==parent and parent.name=='records'
assert path.parent==parent and path.name.endswith('.execution.json')
def identity(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_uid,s.st_gid,s.st_nlink,
            s.st_size,s.st_mtime_ns,s.st_ctime_ns)
p_before=parent.lstat()
assert stat.S_ISDIR(p_before.st_mode) and p_before.st_uid==uid and p_before.st_gid==gid
directory=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
    assert identity(os.fstat(directory))==identity(p_before)
    descriptor=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=directory)
    try:
        before=os.fstat(descriptor)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink==1 and before.st_uid==0
        assert 0<before.st_size<=65536
        data=bytearray()
        while len(data)<=65536:
            chunk=os.read(descriptor,min(8192,65537-len(data)))
            if not chunk:
                break
            data.extend(chunk)
        assert len(data)==before.st_size and len(data)<=65536
        assert identity(os.fstat(descriptor))==identity(before)
        assert identity(os.stat(path.name,dir_fd=directory,follow_symlinks=False))==identity(before)
        assert identity(os.fstat(directory))==identity(p_before)
        assert identity(parent.lstat())==identity(p_before) and parent.resolve()==parent
        print(json.dumps({'actual_uid':os.getuid(),'actual_euid':os.geteuid(),
            'original_path':str(path),'file_identity':list(identity(before)),
            'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
            'record':json.loads(data)},sort_keys=True),flush=True)
    finally:
        os.close(descriptor)
finally:
    os.close(directory)
"""

def read_root_execution_record(name, output):
    """Read only this completed launch's original Root record before any chown."""
    if result.get("completion_unknown"):
        raise RuntimeError("original launch completion unknown; Root record handoff stopped")
    if output != RECORDS / (name + ".execution.json"):
        result["completion_unknown"] = True
        raise RuntimeError("Root record must be this exact step in the fresh attempt")
    try:
        read = raw(name + "-root-record-read", ["sudo","-n","python3","-c",
                   ROOT_EXECUTION_READ,str(RECORDS),str(output),str(UID),str(GID)], timeout=60)
        proof = json.loads(Path(read["log"]["path"]).read_text())
        if (proof.get("actual_uid") != 0 or proof.get("actual_euid") != 0
                or proof.get("original_path") != str(output)
                or not isinstance(proof.get("record"),dict)):
            raise RuntimeError("original Root record read proof differs")
        save(name + ".root-record-read.json", proof)
        return proof["record"], proof
    except BaseException:
        result["completion_unknown"] = True
        raise

def recorded(name, command, timeout=3600, minimum=0, root=False, root_env=None, check=True, cwd=None):
    global root_touched_records
    if result.get("completion_unknown"):
        raise RuntimeError("original command completion unknown; no subsequent dispatch")
    clean()
    budget = remaining(timeout)
    output = RECORDS / (name + ".execution.json")
    launch = ["python3", str(SOURCE / "scripts/hepta_ci_exec.py"), "--timeout-seconds", str(budget),
              "--minimum-tests", str(minimum), "--output", str(output), "--", *command]
    if root:
        root_touched_records = True
        proof = RECORDS / (name + ".uid.json")
        launch = ["sudo", "-n", "env", "-i",
                  *(k+"="+v for k,v in sorted(root_env.items())),
                  "python3", "-c", ROOT_WRAPPER, str(proof), *launch[1:]]
    raw_record = raw(name, launch, cwd or SOURCE, timeout=budget+120, check=False)
    if root and (RECORDS / (name + ".uid.json")).exists():
        proof_data = json.loads((RECORDS / (name + ".uid.json")).read_text())
        if proof_data["uid"] != 0 or proof_data["euid"] != 0:
            raise RuntimeError("Root UID proof differs")
        result.setdefault("root_uid_proofs", []).append(file_digest(RECORDS / (name + ".uid.json")))
    elif root:
        raise RuntimeError("Root wrapper did not produce actual UID0 proof")
    if not output.is_file():
        result["completion_unknown"] = True
        raise RuntimeError("original executor has no terminal record for " + name)
    root_record_read = None
    if root:
        original_terminal, root_record_read = read_root_execution_record(name, output)
    else:
        original_terminal = json.loads(output.read_text())
    if (original_terminal.get("timed_out") is True
            or original_terminal.get("output_limit_exceeded") is True
            or original_terminal.get("status") in ("running","interrupted")):
        result["completion_unknown"] = True
        raise RuntimeError("original command timeout/truncation/interruption; no subsequent Cargo")
    if root:
        no_dispatch = (original_terminal.get("status") == "rejected"
                       and not original_terminal.get("log_file"))
        completed = (original_terminal.get("status") in ("passed","failed")
                     and type(original_terminal.get("command_exit_code")) is int
                     and original_terminal.get("timed_out") is False
                     and original_terminal.get("output_limit_exceeded") is False
                     and isinstance(original_terminal.get("after"),dict))
        result.setdefault("root_completion",[]).append({
            "name":name,"original_terminal":completed,"rejected_before_dispatch":no_dispatch,
        })
        if not (completed or no_dispatch):
            result["completion_unknown"] = True
            raise RuntimeError("original Root command did not prove terminal completion")
    if root:
        expected = {"source_sha":HEAD,"tested_sha":HEAD,"lane":"source-head","command":command}
        if any(original_terminal.get(k)!=v for k,v in expected.items()):
            result["completion_unknown"] = True
            raise RuntimeError("original Root terminal differs from this source/command")
        if completed:
            before,after=original_terminal.get("before"),original_terminal.get("after")
            if (not isinstance(before,dict) or before!=after or before.get("commit")!=HEAD
                    or before.get("tree")!=TREE or before.get("dirty") is not False):
                result["completion_unknown"] = True
                raise RuntimeError("original Root terminal lacks the same clean source")
        # The original recorder now proves terminal completion without timeout/truncation.
        # Only this task's records/reports are transferred; caches remain untouched.
        restore_record_ownership(name + "-terminal-record-ownership")
        transferred = file_digest(output)
        if (transferred["sha256"]!=root_record_read["sha256"]
                or transferred["bytes"]!=root_record_read["bytes"]):
            raise RuntimeError("original Root record bytes changed during evidence handoff")
    record, passed, log = read_execution(output, command, must_pass=False)
    passed = passed and raw_record["exit_code"] == 0 and not raw_record["timed_out"]
    result.setdefault("execution_records", []).append({
        "name": name, "record": file_digest(output), "passed": passed, "required_uid": 0 if root else UID,
    })
    clean()
    if check and not passed:
        raise RuntimeError(name + " failed; original execution and raw log retained")
    return record, passed, log

def package_args(packages):
    return [x for p in packages for x in ("-p", p)]

def json_from_raw_log(name, raw_log, required_keys):
    data = raw_log.read_bytes()
    text = data.decode("utf-8")
    decoder = json.JSONDecoder()
    matches = []
    for match in re.finditer(r"(?m)^[ \t]*\{", text):
        start = match.end()-1
        try:
            value, count = decoder.raw_decode(text[start:])
        except ValueError:
            continue
        if isinstance(value, dict) and all(k in value for k in required_keys):
            matches.append((value, text[start:start+count]))
    if len(matches) != 1:
        raise RuntimeError("exactly one original metadata document required: " + name)
    path = RECORDS / name
    path.write_bytes(matches[0][1].encode("utf-8"))
    save(name + ".provenance.json", {"raw_log": file_digest(raw_log),
                                    "retained_document": file_digest(path), "reformatted": False})
    return matches[0][0], path

def binary_bindings(metadata, cargo_metadata):
    binaries = metadata.get("rust-binaries", metadata.get("rust-suites"))
    if not isinstance(binaries, dict) or len(binaries) != 2:
        raise RuntimeError("Root list must compile exactly two library test binaries")
    bindings = []
    actual_packages = {p["name"]: p["id"] for p in cargo_metadata["packages"]
                       if p["name"] in CONFIG["root_packages"]}
    if set(actual_packages) != set(CONFIG["root_packages"]):
        raise RuntimeError("Root Cargo metadata omits a requested original package")
    expected_ids = {"codex-hepta-agentd", "codex-hepta-contracts"}
    if set(binaries) != expected_ids:
        raise RuntimeError("Root binary IDs differ from the two fixed packages")
    for name, binary in sorted(binaries.items()):
        if (binary.get("kind") != "lib" or binary.get("binary-id") != name
                or binary.get("package-id") != actual_packages[name]):
            raise RuntimeError("Root metadata selected a different package/library target")
        path = Path(binary["binary-path"])
        if not path.is_absolute() or not path.resolve().is_relative_to(ROOT_TARGET.resolve()):
            raise RuntimeError("Root binary lies outside its original dedicated target")
        bindings.append({"binary_id": name, **file_digest(path)})
    return bindings

def listed_root_parents(metadata):
    matched = []
    for package, suite in metadata["rust-suites"].items():
        if suite.get("package-name") != package or suite.get("status") != "listed":
            raise RuntimeError("Root test suite was not listed from its actual package")
        for name, case in suite["testcases"].items():
            observed = case["filter-match"]
            if observed["status"] == "matches":
                if case.get("ignored") is not True:
                    raise RuntimeError("selected Root parent is not an ignored test")
                matched.append(name)
            elif observed["status"] != "mismatch":
                raise RuntimeError("unknown original nextest filter observation")
    save("root-parent-list.json", {"expected":PARENTS,"observed":matched})
    if len(matched) != 17 or sorted(matched) != sorted(PARENTS):
        raise RuntimeError("actual fixed-source nextest list differs from seventeen parents")

def restore_record_ownership(name):
    owned = [RECORDS]
    reports = SOURCE / "codex-rs/target/nextest"
    if reports.exists():
        owned.append(reports)
    for path in owned:
        if path.is_symlink() or not path.resolve().is_relative_to(WORK.resolve()):
            raise RuntimeError("refuse ownership outside this task's records/reports")
    raw(name, ["sudo", "-n", "chown", "-R", "-P", "--no-dereference", f"{UID}:{GID}",
               *(str(p) for p in owned)], timeout=60)

def test_suite(name, arguments, root=False, root_env=None):
    report = SOURCE / "codex-rs/target/nextest/local/junit.xml"
    if report.exists():
        report.rename(RECORDS / (name + ".prior-junit-excluded.xml"))
    if report.exists():
        raise RuntimeError("old JUnit was not excluded")
    command = ["just", "test", "--locked", "--offline", *arguments,
               "--retries", "0", "--success-output", "final", "--failure-output", "final"]
    error = None
    observed = None
    try:
        observed = recorded(name, command, timeout=7200, minimum=17 if root else 1,
                            root=root, root_env=root_env, check=False)
    except BaseException as exc:
        error = exc
    finally:
        if root:
            try:
                if result.get("completion_unknown"):
                    raise RuntimeError("preserve live/unknown Root records without chown")
                restore_record_ownership(name + "-record-ownership")
            except BaseException as exc:
                result["errors"].append("Root evidence ownership: " + repr(exc))
                if error is None:
                    error = exc
    if result.get("completion_unknown"):
        # Preserve the recorder and live report in place for reconciliation.
        # Do not launch even the collector while the original may still write.
        raise RuntimeError("unknown original completion; JUnit collection and follow-up stopped")
    collection = raw(name + "-junit", [
        "python3", "scripts/hepta_ci_junit.py", "--execution",
        str(RECORDS / (name + ".execution.json")), "--junit", str(report),
        "--output", str(RECORDS / (name + ".junit.xml")),
    ], SOURCE, timeout=120, check=False)
    summary_path = RECORDS / (name + ".junit.summary.json")
    if summary_path.exists():
        summary = json.loads(summary_path.read_text())
        save(name + ".collection-binding.json", {
            "summary": file_digest(summary_path),
            "native_junit": file_digest(report) if report.is_file() else None,
            "collector_command_exit": collection["exit_code"],
        })
    else:
        summary = {}
    if collection["exit_code"] != 0 or summary.get("status") != "passed":
        result["errors"].append(name + " original JUnit collection failed")
    retained = RECORDS / (name + ".junit.xml")
    if retained.is_file():
        parsed = ET.parse(retained).getroot()
        cases = list(parsed.iter("testcase"))
        executed = [c for c in cases if c.find("skipped") is None]
        names = [c.attrib["name"] for c in executed]
        failed = sum(c.find("failure") is not None for c in cases)
        errors = sum(c.find("error") is not None for c in cases)
        counts = {"total": len(cases), "executed": len(executed),
                  "passed": len(executed)-failed-errors, "failed": failed, "errors": errors,
                  "skipped": len(cases)-len(executed)}
        save(name + ".counts.json", counts)
        result[name + "_counts"] = counts
        if root:
            save("root-parent-coverage.json", {"expected": PARENTS, "observed": names})
            if sorted(names) != sorted(PARENTS) or len(names) != 17:
                result["errors"].append("Root executed roster differs from exact seventeen parents")
    else:
        result["errors"].append(name + " lacks retained native JUnit")
    if observed is None or not observed[1]:
        result["errors"].append(name + " original test execution failed")
    if error is not None:
        raise error
    clean()

RUST_PREFLIGHT = r"""
import json,os,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
names={'cargo','rustc','rustdoc','rustfmt','clippy-driver','cargo-clippy','cargo-nextest'}
active=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():
        continue
    try:
        comm=(p/'comm').read_text().strip()
        if comm in names:
            try:
                cwd=os.readlink(p/'cwd')
            except OSError:
                cwd=None
            active.append({'pid':int(p.name),'comm':comm,'cwd':cwd})
    except FileNotFoundError:
        continue
print(json.dumps({'actual_preflight_uid':os.getuid(),'active_rust':active}),flush=True)
raise SystemExit(1 if active else 0)
"""

ROOT_SETUP = r"""
import json,os,stat,subprocess,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
p=Path(sys.argv[1])
assert p.parent==Path('/run') and p.name.startswith('hepta-af52-final-')
p.mkdir(mode=0o700)
created=p.stat()
with open(sys.argv[2],'x') as stream:
    json.dump({'path':str(p),'uid':os.getuid(),'euid':os.geteuid(),
               'device':created.st_dev,'inode':created.st_ino},stream)
    stream.flush()
    os.fsync(stream.fileno())
for n in ('source','bind','checkpoints','witness-source','witness-bind'):
    (p/n).mkdir(mode=0o700)
subprocess.run(['mount','--bind',str(p/'source'),str(p/'bind')],check=True,timeout=30)
subprocess.run(['mount','--bind',str(p/'witness-source'),str(p/'witness-bind')],check=True,timeout=30)
pairs={}
for n in ('source','bind','witness-source','witness-bind'):
    s=(p/n).stat()
    assert s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o700
    pairs[n]=[s.st_dev,s.st_ino]
assert pairs['source']==pairs['bind']
assert pairs['witness-source']==pairs['witness-bind']
assert pairs['source']!=pairs['witness-source']
s=p.stat()
print(json.dumps({'root_fixture_uid':os.getuid(),'root_fixture_euid':os.geteuid(),
 'path':str(p),'identity':[s.st_dev,s.st_ino],'pairs':pairs}),flush=True)
"""
ROOT_CACHE = r"""
import json,os,stat,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
p=Path(sys.argv[1])
assert p.parent==Path('/var/tmp') and p.name.startswith('hepta-af52-root-')
p.mkdir(mode=0o755,exist_ok=True)
s=p.lstat()
assert stat.S_ISDIR(s.st_mode) and s.st_uid==0 and stat.S_IMODE(s.st_mode)==0o755
print(json.dumps({'root_cache_uid':os.getuid(),'target':str(p)}),flush=True)
"""

try:
    save("configuration.json", CONFIG)
    raw("original-rust-idle-preflight",["sudo","-n","python3","-c",RUST_PREFLIGHT],timeout=60)
    result["reference_before"] = identity(REFERENCE)
    raw("isolated-clone", ["git", "clone", "--shared", "--no-checkout", "--no-hardlinks",
                           str(REFERENCE), str(SOURCE)], timeout=remaining(600))
    raw("fetch-exact-source", ["git", "-C", str(SOURCE), "fetch", "--no-tags",
                              "https://github.com/TrillionniumFoundation/hepta-private-ci.git", HEAD],
        timeout=remaining(600))
    if git("rev-parse", HEAD+"^{tree}").decode().strip() != TREE:
        raise RuntimeError("published fixed commit has different tree")
    raw("checkout-exact-source", ["git", "-C", str(SOURCE), "checkout", "--detach", HEAD],
        timeout=remaining(600))
    raw("format-base-ancestry", ["git", "-C", str(SOURCE), "merge-base", "--is-ancestor", BASE, HEAD],
        timeout=120)
    source_ready = True
    initial_snapshot = snapshot("source-before")
    tool_before = tool_snapshot("tools-before")
    workflow_contract()
    raw_commit = git("cat-file", "commit", HEAD)
    if hashlib.sha1(b"commit "+str(len(raw_commit)).encode()+b"\0"+raw_commit).hexdigest() != HEAD:
        raise RuntimeError("original commit object digest differs")
    save("source-commit-object.json", {"sha":HEAD,"tree":TREE,
        "base64":base64.b64encode(raw_commit).decode(),"bytes":len(raw_commit)})
    if Path(shutil.which("just", path=env["PATH"]) or "").resolve() != JUST:
        raise RuntimeError("just PATH resolution differs from its explicit original binary")
    tool_paths = [str(JUST), CONFIG["rustc_path"]]
    for tool in ("cargo", "cargo-nextest", "python3", "sudo", "mount", "mountpoint", "umount", "chown"):
        path = shutil.which(tool, path=env["PATH"])
        if not path:
            raise RuntimeError("required existing tool is unavailable: " + tool)
        tool_paths.append(path)
    result["external_tools_before"] = {p:file_digest(Path(p)) for p in tool_paths}
    _, _, operator_rust_log = recorded("operator-toolchain",
        [CONFIG["rustc_path"],"-Vv"],timeout=60,cwd=SOURCE/"codex-rs")
    toolchain = operator_rust_log.read_text()
    if "release: 1.96.0\n" not in toolchain:
        raise RuntimeError("actual operator rustc is not repository-pinned 1.96.0")
    save("toolchain.json", {"rustc":toolchain,"rustup_toolchain":env["RUSTUP_TOOLCHAIN"]})
    # Root-only diagnostic: the full harness exclusively owns all omitted gates.
    helper = ["python3","scripts/hepta_cell_test_helpers.py","--package",
              "codex-hepta-infer-worker-host","--output-dir",str(RECORDS/"helpers")]
    recorded("same-source-helper-build", helper, timeout=3600)
    recorded("same-source-helper-preverify", [*helper,"--verify-only"], timeout=120)
    helper_env = json.loads((RECORDS/"helpers/env.json").read_text())
    if set(helper_env) != {"CARGO_BIN_EXE_hepta-joint-propose","CARGO_BIN_EXE_hepta_joint_propose"}:
        raise RuntimeError("unexpected original helper capability set")
    env.update(helper_env)
    result["helper_manifest_before"] = file_digest(RECORDS/"helpers/manifest.json")
    result["before_tests"] = clean()
    if result["before_tests"] != {k:initial_snapshot[k] for k in ("head","tree","status")}:
        raise RuntimeError("diagnostic preparation changed the fixed source identity")
    root_env = root_environment(helper_env)
    save("root-environment.json", root_env)
    raw("root-cache", ["sudo","-n","python3","-c",ROOT_CACHE,str(ROOT_TARGET)], timeout=60)
    _, _, rust_log = recorded("root-toolchain", [CONFIG["rustc_path"],"-Vv"],
                             timeout=60,root=True,root_env=root_env,cwd=SOURCE/"codex-rs")
    if rust_log.read_text() != toolchain:
        raise RuntimeError("actual Root toolchain differs from operator's pinned toolchain")
    _, _, cargo_log = recorded("root-cargo-metadata",["cargo","metadata","--locked","--offline",
        "--no-deps","--format-version=1"],timeout=120,root=True,root_env=root_env,cwd=SOURCE/"codex-rs")
    cargo_metadata, metadata_path = json_from_raw_log("root-cargo-metadata.json",cargo_log,
                                                    ["workspace_root","target_directory","packages"])
    if Path(cargo_metadata["workspace_root"]).resolve() != (SOURCE/"codex-rs").resolve():
        raise RuntimeError("Root metadata has different workspace")
    if Path(cargo_metadata["target_directory"]).resolve() != ROOT_TARGET.resolve():
        raise RuntimeError("Root metadata points to the operator target")
    _, _, list_log = recorded("root-binary-list",["cargo","nextest","list","--locked","--offline",
        "--cargo-metadata",str(metadata_path),*package_args(CONFIG["root_packages"]),
        "--lib","--message-format","json","--run-ignored","only",
        "-E"," | ".join("test(="+p+")" for p in PARENTS)],
        timeout=7200,root=True,root_env=root_env,cwd=SOURCE/"codex-rs")
    binary_metadata, _ = json_from_raw_log("root-binaries-metadata.json",list_log,["rust-suites"])
    listed_root_parents(binary_metadata)
    root_binaries_before = binary_bindings(binary_metadata, cargo_metadata)
    save("root-binaries-before.json", {"source":HEAD,"tree":TREE,"builder_uid":0,
                                      "files":root_binaries_before})
    root_setup_started = True
    raw("root-fixture-setup",["sudo","-n","python3","-c",ROOT_SETUP,str(ROOT_FIXTURE),
        str(RECORDS/"root-fixture-created.json")],timeout=120)
    test_suite("root",[*package_args(CONFIG["root_packages"]),"--lib","--run-ignored","only",
        "-E"," | ".join("test(="+p+")" for p in PARENTS),"--test-threads","1"],
        root=True,root_env=root_env)
    root_binaries_after = binary_bindings(binary_metadata, cargo_metadata)
    save("root-binaries-after.json", {"source":HEAD,"tree":TREE,"builder_uid":0,
                                     "files":root_binaries_after})
    if root_binaries_after != root_binaries_before:
        raise RuntimeError("actual Root test binary changed across original just test")
    recorded("same-source-helper-postverify",[*helper,"--verify-only"],timeout=120)
    if file_digest(RECORDS/"helpers/manifest.json") != result["helper_manifest_before"]:
        raise RuntimeError("helper preparation evidence changed")
    result["after_tests"] = clean()
    if result["after_tests"] != result["before_tests"]:
        raise RuntimeError("source identity changed across native execution")
    result["status"] = "root-component-diagnostic-passed" if not result["errors"] else "root-component-diagnostic-failed"
except BaseException as error:
    result["status"] = "failed"
    result["failure"] = type(error).__name__+": "+str(error)
    result["traceback"] = traceback.format_exc()
finally:
    # Independent cleanup attempts: one failure must not skip the other bind or evidence.
    def cleanup(name, action, mutating=False):
        if mutating and result.get("completion_unknown"):
            result["cleanup"].append({"name":name,"status":"not-run-original-completion-unknown"})
            result["status"]="incomplete-original-completion-unknown"
            return
        try:
            action()
            result["cleanup"].append({"name":name,"status":"passed"})
        except BaseException as error:
            result["cleanup"].append({"name":name,"status":"failed","error":repr(error)})
            result["status"] = "failed"
            result["errors"].append("cleanup "+name+": "+repr(error))
    fixture_proof = RECORDS/"root-fixture-created.json"
    if root_setup_started and fixture_proof.is_file():
        # No proof means mkdir never succeeded: do not touch a pre-existing path.
        for name in ("witness-bind","bind"):
            def unmount(name=name):
                code = r"""
import json,os,stat,subprocess,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
proof=json.loads(Path(sys.argv[1]).read_text())
p=Path(proof['path'])
assert p.parent==Path('/run') and p.name.startswith('hepta-af52-final-')
s=p.lstat()
assert stat.S_ISDIR(s.st_mode) and s.st_uid==0
assert [s.st_dev,s.st_ino]==[proof['device'],proof['inode']]
assert proof['uid']==proof['euid']==0
name=sys.argv[2]
assert name in ('witness-bind','bind')
path=p/name
assert not path.is_symlink()
before=subprocess.run(['mountpoint','-q',str(path)],timeout=15).returncode
if before==0:
    subprocess.run(['umount',str(path)],check=True,timeout=30)
else:
    assert before in (1,32)
after=subprocess.run(['mountpoint','-q',str(path)],timeout=15).returncode
assert after in (1,32)
print(json.dumps({'unmounted':str(path),'before':before,'after':after}),flush=True)
"""
                raw("cleanup-unmount-"+name,["sudo","-n","python3","-c",code,
                    str(fixture_proof),name],timeout=90)
            cleanup("unmount-"+name,unmount,mutating=True)
        def remove_fixture():
            code = r"""
import json,os,shutil,stat,subprocess,sys
from pathlib import Path
assert os.getuid()==os.geteuid()==0
proof=json.loads(Path(sys.argv[1]).read_text())
p=Path(proof['path'])
assert p.parent==Path('/run') and p.name.startswith('hepta-af52-final-')
s=p.lstat()
assert stat.S_ISDIR(s.st_mode) and s.st_uid==0
assert [s.st_dev,s.st_ino]==[proof['device'],proof['inode']]
for name in ('witness-bind','bind'):
    assert not (p/name).is_symlink()
    assert subprocess.run(['mountpoint','-q',str(p/name)],timeout=15).returncode in (1,32)
shutil.rmtree(p)
assert not p.exists()
print(json.dumps({'removed_owned_fixture':str(p)}),flush=True)
"""
            if any(x["status"]!="passed" for x in result["cleanup"]
                   if x["name"].startswith("unmount-")):
                raise RuntimeError("preserve owned fixture after incomplete unmount")
            raw("cleanup-owned-fixture",["sudo","-n","python3","-c",code,
                str(fixture_proof)],timeout=90)
        cleanup("remove-owned-fixture",remove_fixture,mutating=True)
    elif root_setup_started:
        result["cleanup"].append({"name":"fixture-not-created","status":"not-owned-no-touch"})
    if root_touched_records:
        cleanup("record-ownership",lambda:restore_record_ownership("cleanup-record-ownership"),mutating=True)
    if source_ready:
        def retain_drift():
            observed=identity()
            save("final-source-identity.json",observed)
            patch=git("diff","--binary","--full-index",HEAD,"--")
            (RECORDS/"maintenance.patch").write_bytes(patch)
            result["maintenance_patch"]=file_digest(RECORDS/"maintenance.patch")
            if observed!={"head":HEAD,"tree":TREE,"status":""}:
                result["status"]="failed"
                outputs=[]
                for item in git("diff","--name-only","--no-renames","-z",HEAD,"--").split(b"\0"):
                    if not item:
                        continue
                    relative=os.fsdecode(item)
                    path=SOURCE/relative
                    if path.is_file() and not path.is_symlink():
                        data=path.read_bytes()
                        if len(data)>1024*1024 or len(outputs)>=128:
                            raise RuntimeError("drift postimage bound exceeded; raw patch retained")
                        outputs.append({"path":relative,"bytes":len(data),
                            "sha256":hashlib.sha256(data).hexdigest(),
                            "git_blob":hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest(),
                            "base64":base64.b64encode(data).decode()})
                save("maintenance-postimages.json",outputs)
        cleanup("retain-source-and-drift",retain_drift)
        if tool_before is not None:
            def verify_tools():
                after=tool_snapshot("tools-after")
                if after!=tool_before:
                    raise RuntimeError("original tool/checker source bytes changed")
            cleanup("original-tool-sources",verify_tools)
        def final_inventory():
            observed=snapshot("source-final")
            if initial_snapshot is not None and observed!=initial_snapshot:
                raise RuntimeError("final full source differs")
        cleanup("final-physical-source",final_inventory)
    def reference_unchanged():
        result["reference_after"]=identity(REFERENCE)
        if result.get("reference_before")!=result["reference_after"]:
            raise RuntimeError("read-only donor metadata changed during this attempt")
    cleanup("read-only-reference",reference_unchanged)
    if "external_tools_before" in result:
        def external_tools():
            after={p:file_digest(Path(p)) for p in result["external_tools_before"]}
            result["external_tools_after"]=after
            if after!=result["external_tools_before"]:
                raise RuntimeError("actual tool executables changed")
        cleanup("external-tools",external_tools)
    if result.get("completion_unknown"):
        result["status"]="incomplete-original-completion-unknown"
    progress("finished-or-awaiting-original")
# Keep the supervisor present while an observed original launcher is alive.
# No follow-up Cargo or mutating cleanup occurs, even if it later exits.
# The durable request/PID is available for the parent to reconcile.
for name, child in pending_commands:
    while child.poll() is None:
        result["awaiting_original"]={"name":name,"pid":child.pid}
        progress("awaiting-original-command")
        time.sleep(30)
    result.setdefault("pending_terminal_observations",[]).append({
        "name":name,"pid":child.pid,"exit_code":child.returncode,
        "followup_or_mutating_cleanup_performed":False,
    })
if pending_commands:
    result["status"]="failed-original-timeout-observed-no-cleanup"
    progress("original-launcher-finished-needs-reconciliation")
print(json.dumps({"status":result["status"],"progress":str(RECORDS/"progress.json")}),flush=True)
raise SystemExit(0 if result["status"]=="root-component-diagnostic-passed" else 1)
