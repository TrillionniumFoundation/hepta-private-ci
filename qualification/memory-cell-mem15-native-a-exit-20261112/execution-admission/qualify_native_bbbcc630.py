"""One frozen native A-exit capture qualification; never calls model.generate.

This is an executor evidence script, not a product runner or scientific cohort.
Every arm is attempted at most once. Its child/HTTP originals remain authoritative.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time
import traceback
import uuid
import xml.etree.ElementTree as ET

ROOT = Path("/home/qq/work/mem15-native-qualification-20261112-ef0c")
OLD = Path("/home/qq/work/mem12-native-qualification-20261112-ef0c")
CACHE = Path("/home/qq/work/mem13-native-qualification-20261112-ef0c/source")
SOURCE = ROOT / "source-final-bbbcc630"
OUT = ROOT / "capture-bbbcc630-01"
COMMIT = "bbbcc63003a88d0396a9694222dc98dc8c0d59d6"
TREE = "fe00b2618f39e942ec6b1a8af2d63ec585e5f892"
CODEX_TREE = "ed240f298fa2cbb104c65054596e64e7d1e9bca8"
BASE = "7f6b5b80cf4528aabd44ad2df1a93d7f70e7590d"
PROFILE = CACHE.parent / "frozen-profile.json"
PROFILE_SHA = "dfba6d23b9ceee986773c74bd3d39eeb81a41f93476a891c342dec9944b8dedd"
PYTHON = "/usr/bin/python3.14"
PREFIX = "production_composition::tests::episodic_control::provider::process::"
CAPTURE_CASE = PREFIX + "episodic_native_a_exit_capture"
ACK_CASES = {
    PREFIX + "child::tests::imported_ack_requires_successful_original_process_exit_and_exact_input",
    PREFIX + "child::tests::missing_or_repeated_ack_cannot_start_c",
}
CLI_CASE = "context_delivery_tests::delivery_rejects_ambiguous_modes_before_authority_or_journal_open"
ARMS = [
    {"arm": arm, "request_id": "mem15-bbbcc630-" + arm + "-ef0c-v1"}
    for arm in ("attach", "reader-off", "withhold", "tombstone")
]
ENV = dict(os.environ)
ENV.update({
    "PATH": str(ROOT / "format-recovery01/bin") + ":/home/qq/.cargo/bin:/home/qq/work/hepta-cell-s0-ai395-20261108-898e/tools/just-1.58.0:/home/qq/work/hepta-cell-s0-ai395-20261108-898e/tools/uv-0.13.5:" + ENV.get("PATH", "/usr/bin:/bin"),
    "XDG_CACHE_HOME": str(ROOT / "format-recovery01/tool-cache"),
    "RUSTUP_TOOLCHAIN": "1.96.0", "CARGO_BUILD_JOBS": "2", "CARGO_INCREMENTAL": "0",
    "CARGO_PROFILE_TEST_DEBUG": "0", "CARGO_PROFILE_DEV_DEBUG": "0",
    "CARGO_TARGET_DIR": str(OLD / "cargo-target"), "CODEX_REPO_ROOT": str(SOURCE),
    "PYTHONPATH": str(SOURCE / "scripts") + ":" + str(SOURCE),
    "PYTHONDONTWRITEBYTECODE": "1", "GIT_TERMINAL_PROMPT": "0",
    "SOURCE_SHA": COMMIT, "TESTED_SHA": COMMIT, "BASE_SHA": BASE,
    "HEPTA_CI_LANE": "source-head",
})
JUNIT = SOURCE / "codex-rs/target/nextest/local/junit.xml"
RESULT = {
    "schema": "hepta.mem15.native-capture-qualification.v1", "source_commit": COMMIT,
    "source_tree": TREE, "codex_rs_tree": CODEX_TREE, "started_unix_ns": time.time_ns(),
    "status": "running", "phases": [], "arms": [], "model_generation_count": None,
    "physical_native_http_count": None, "scored_memory_benefit_episodes": 0,
    "scientific_acceptance": "HOLD", "fixture_only": True, "observer_authenticated": False,
    "resource_settings": {"cargo_build_jobs": 2, "outer_nice": 10},
    "scope": "new three software controls and four independent capture-only native fixtures; no prior811 reruns; no benefit cohort; no C namespace-isolation claim",
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return {"bytes": path.stat().st_size, "sha256": h.hexdigest()}


def write(path, value):
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def save():
    temporary = OUT / "RESULT.pending.json"
    temporary.write_bytes(canonical(RESULT) + b"\n")
    temporary.replace(OUT / "RESULT.json")


def document(path):
    return json.loads(path.read_bytes())


def git(*args):
    return subprocess.check_output(["git", "-C", str(SOURCE), *args], env=ENV).decode().strip()


def identity():
    return {"commit": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
            "codex_rs_tree": git("rev-parse", "HEAD:codex-rs"), "status": git("status", "--porcelain")}


def require_source():
    value = identity()
    if value != {"commit": COMMIT, "tree": TREE, "codex_rs_tree": CODEX_TREE, "status": ""}:
        raise RuntimeError("frozen source mismatch: " + json.dumps(value))
    return value


def command(label, args, *, expected=None, timeout=6600, env=None, setup=False, final=False):
    if not setup and not final:
        require_source()
    old_uuid = None
    if expected is not None and JUNIT.exists():
        if JUNIT.is_symlink():
            raise RuntimeError("symlink JUnit refused")
        old_uuid = ET.parse(JUNIT).getroot().get("uuid")
        JUNIT.rename(OUT / (label + ".previous.junit.xml"))
    receipt_path = OUT / (label + ".receipt.json")
    wrapped = args if setup else [PYTHON, str(SOURCE / "scripts/hepta_ci_exec.py"),
        "--timeout-seconds", str(timeout), "--output", str(receipt_path),
        *(["--minimum-tests", str(len(expected))] if expected is not None else []), "--", *args]
    entry = {"name": label, "command": args, "started_unix_ns": time.time_ns(), "status": "running"}
    RESULT["phases"].append(entry)
    save()
    with (OUT / (label + ".console.log")).open("xb") as stream:
        completed = subprocess.run(wrapped, cwd=ROOT if setup else SOURCE, env=env or ENV,
            stdout=stream, stderr=subprocess.STDOUT, timeout=timeout if setup else None)
    entry.update(exit_code=completed.returncode, finished_unix_ns=time.time_ns(),
                 status="passed" if completed.returncode == 0 else "failed")
    if receipt_path.exists():
        entry["receipt"] = document(receipt_path)
    if expected is not None:
        try:
            if JUNIT.is_symlink() or not JUNIT.is_file():
                raise ValueError("missing fresh workspace JUnit")
            copy = OUT / (label + ".junit.xml")
            shutil.copyfile(JUNIT, copy)
            report = ET.parse(copy).getroot()
            cases = report.findall(".//testcase")
            names = [item.get("name") for item in cases]
            run_uuid = str(uuid.UUID(report.attrib["uuid"]))
            receipt = entry["receipt"]
            log = OUT / receipt["log_file"]
            if digest(log)["sha256"] != receipt["log_sha256"] or run_uuid not in log.read_text():
                raise ValueError("original nextest log/UUID mismatch")
            start, finish = (datetime.fromisoformat(receipt[key]) for key in ("started_at", "finished_at"))
            if (run_uuid == old_uuid or len(names) != len(expected) or set(names) != expected
                    or report.get("tests") != str(len(expected)) or report.get("failures") != "0"
                    or report.get("errors") != "0" or any(item.find(tag) is not None for item in cases for tag in ("failure", "error", "skipped"))
                    or not all(start <= datetime.fromisoformat(item.attrib["timestamp"]) <= finish for item in cases)
                    or any(receipt[side]["commit"] != COMMIT or receipt[side]["tree"] != TREE or receipt[side]["dirty"] for side in ("before", "after"))):
                raise ValueError("JUnit does not bind exact required cases, source and execution time")
            entry["junit"] = {**digest(copy), "uuid": run_uuid, "case_names": names, "fresh_source_time_binding": True}
        except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
            entry.update(status="failed", collection_error=str(error))
    save()
    return entry["status"] == "passed"


def join_arm(arm, directory, adapter, server, server_returncode, test_ok):
    """Only original joined records can replace unknown counts with zero."""
    native = directory / "native"
    result = document(native / "RESULT.json")
    intent = document(native / "INTENT.json")
    plan = document(adapter / "PLAN.json")
    stopped = document(adapter / "STOPPED.json")
    a, c = document(native / "A/EXIT.json"), document(native / "C/EXIT.json")
    dispatch = document(native / "DISPATCH_INPUT.json")
    a_intent, c_intent = document(native / "A/INTENT.json"), document(native / "C/INTENT.json")
    snapshot_raw = (native / "A/stdin.bin").read_bytes()
    snapshot = json.loads(snapshot_raw)
    fact = snapshot["body"]["records"][0]["text"]
    nonce = fact.removeprefix("fixture nonce: ")
    ack = document(native / "A_ACK.json")
    expected_mode = arm["arm"].replace("-", "_")
    if (not test_ok or server_returncode != 0 or plan["native_source_sha"] != COMMIT
            or plan["request_id"] != arm["request_id"] or plan["mode"] != "capture"
            or plan["profile"] != PROFILE_VALUE or plan["source_pins"] != ADAPTER_PINS
            or server["plan"] != pin(canonical(plan))
            or intent["outer_source_sha"] != COMMIT or intent["request_id"] != arm["request_id"]
            or intent["requested_model"] != PROFILE_VALUE["model_name"]
            or intent["provider_base_url"] != f"http://127.0.0.1:{server['address'][1]}/v1"
            or result["request_id"] != arm["request_id"] or result["mode"] != expected_mode
            or result["A_exit"] != a or result["C_exit"] != c or dispatch["A_exit"] != a
            or dispatch["A_ack"] != ack or a["exit_code"] != 0 or a["timed_out"]
            or c["exit_code"] in (None, 0) or c["timed_out"] or result["terminal_observed"]
            or not result["A_exit_precedes_C_start"] or not result["A_importer_process_exits_before_C"]
            or not a["exited_at_unix_ns"] <= c["started_at_unix_ns"]
            or a["pid"] in (a["parent_pid"], c["pid"]) or c["pid"] == c["parent_pid"]
            or server["started_at_unix_ns"] > c["started_at_unix_ns"]
            or stopped["ended_at_unix_ns"] < c["started_at_unix_ns"]
            or c_intent["extra_environment"] != [] or not c_intent["environment_cleared"]
            or nonce in json.dumps(c_intent) or nonce.encode() in (native / "C/stdin.bin").read_bytes()
            or ack["pid"] != a["pid"] or ack["snapshot_sha256"] != pin(snapshot_raw)["sha256"]
            or snapshot["sha256"] != pin(canonical(snapshot["body"]))["sha256"]
            or ack["imported"]["snapshot_sha256"] != snapshot["sha256"]):
        raise ValueError("native A/C, source, server, fixture or acknowledgement binding failed")
    for key in ("authority_id", "namespace", "generation"):
        if ack["imported"][key] != snapshot["body"][key]:
            raise ValueError("owner receipt identity differs from exact A envelope")
    for child, child_intent in ((a, a_intent), (c, c_intent)):
        if child["executable_before"] != child["executable_after"] or child["stdin"] != child_intent["stdin"]:
            raise ValueError("child executable/input bytes changed")
    if c["executable_before"] != BINARIES["hepta-infer-worker"]["pin"]:
        raise ValueError("C executable differs from compiled candidate binary")
    if not (native / "C.journal").is_file() or not result["durable_record"]:
        raise ValueError("original native journal/record missing")
    source_delta = result["source_reads_after"] - result["source_reads_before"]
    joined = {"status": "joined", "arm": arm["arm"], "request_id": arm["request_id"],
        "native_result": digest(native / "RESULT.json"), "native_journal": digest(native / "C.journal"),
        "adapter_plan": digest(adapter / "PLAN.json"), "adapter_server": digest(adapter / "SERVER.json"),
        "adapter_stopped": digest(adapter / "STOPPED.json"), "A_exit_precedes_C_start": True,
        "A_pid": a["pid"], "C_pid": c["pid"], "source_read_delta": source_delta,
        "physical_native_http_count": None, "model_generation_count": None,
        "fixture_nonce": nonce, "C_namespace_isolated": False, "full_memory_off_demonstrated": False}
    http_dirs = sorted(p for p in adapter.glob("http-*") if p.is_dir())
    if arm["arm"] == "tombstone":
        if (stopped["http_connections_observed"] != 0 or http_dirs or (adapter / "ATTEMPT.json").exists()
                or not result["native_revocation_rejected"] or source_delta != 3
                or result["owner_cut_after"] == result["owner_cut_before"]
                or "canonical episodic head changed outside the bridge" not in (native / "C/stderr.bin").read_text()
                or stopped["ended_at_unix_ns"] < c["exited_at_unix_ns"]
                or stopped["ended_at_unix_ns"] - server["started_at_unix_ns"] < 119 * 10**9):
            raise ValueError("tombstone did not bind original native rejection and no-request server termination")
        joined.update(physical_native_http_count=0, model_generation_count=0, nonce_in_http_body=None)
    else:
        if len(http_dirs) != 1 or stopped["http_connections_observed"] != 1:
            raise ValueError("exactly one captured HTTP request required")
        http = http_dirs[0]
        observed, mapping, attempt = (document(p) for p in (http / "OBSERVED.json", http / "MAPPING.json", adapter / "ATTEMPT.json"))
        wire, body, provider_raw = ((http / name).read_bytes() for name in ("request.http.bin", "body.bin", "provider-request.bin"))
        provider = json.loads(provider_raw)
        present = nonce.encode() in body
        if (observed["status"] != "CAPTURED_WITHOUT_GENERATION" or observed["physical_model_calls"] != 0
                or not observed["capture_complete"] or not observed["socket_write_succeeded"]
                or not c["started_at_unix_ns"] <= observed["started_at_unix_ns"] <= observed["ended_at_unix_ns"] <= c["exited_at_unix_ns"]
                or server["started_at_unix_ns"] > observed["started_at_unix_ns"]
                or stopped["ended_at_unix_ns"] < observed["ended_at_unix_ns"]
                or observed["advertised_body_bytes"] != len(body) or observed["observed_body_bytes"] != len(body)
                or wire.split(b"\r\n\r\n", 1)[1] != body or observed["native_http"] != pin(wire)
                or observed["native_body"] != pin(body) or attempt["native_http"] != pin(wire)
                or attempt["native_body"] != pin(body) or attempt["provider_request"] != pin(provider_raw)
                or attempt["request_id"] != arm["request_id"] or attempt["mode"] != "capture"
                or mapping["native_body"] != pin(body) or mapping["provider_request"] != pin(provider_raw)
                or mapping["discarded_fields"] != [] or not mapping["source_utf8_equals_destination_utf8"]
                or provider["input"].encode() != body or provider["model"] != PROFILE_VALUE["model_name"]
                or provider["max_output_tokens"] != 32 or provider["temperature"] != 0 or provider["store"] is not False
                or source_delta != (0 if arm["arm"] == "reader-off" else 4)
                or result["owner_cut_after"] != result["owner_cut_before"]
                or present != (arm["arm"] == "attach") or (adapter / "provider").exists()):
            raise ValueError("complete HTTP/mapping/no-generation/source-count/nonce binding failed")
        joined.update(physical_native_http_count=1, model_generation_count=0, nonce_in_http_body=present,
                      native_body=pin(body), provider_request=pin(provider_raw), body_fields=sorted(json.loads(body)))
    write(directory / "JOINED.json", joined)
    return joined


def run_arm(arm):
    require_source()
    directory = OUT / arm["arm"]
    directory.mkdir()
    adapter = directory / "adapter"
    entry = {**arm, "status": "running", "physical_native_http_count": None, "model_generation_count": None}
    RESULT["arms"].append(entry)
    save()
    server_process = None
    try:
        prepare = [PYTHON, "-B", "-m", "ndu_real_runtime.episodic_native_adapter", "--prepare", str(adapter),
            "--profile", str(PROFILE), "--request-id", arm["request_id"], "--native-source-sha", COMMIT, "--mode", "capture"]
        if not command(arm["arm"] + "-prepare", prepare, timeout=60):
            raise ValueError("capture adapter admission failed")
        serving = [PYTHON, "-B", "-m", "ndu_real_runtime.episodic_native_adapter", "--serve", str(adapter)]
        write(directory / "LISTENER_INTENT.json", {"command": serving, "source": require_source(),
            "precompile_completed_at_unix_ns": RESULT["precompile_completed_at_unix_ns"], "listener_seconds": 120})
        with (directory / "listener.stdout.bin").open("xb") as stdout, (directory / "listener.stderr.bin").open("xb") as stderr:
            started = time.time_ns()
            server_process = subprocess.Popen(serving, cwd=SOURCE, env=ENV, stdout=stdout, stderr=stderr)
            write(directory / "LISTENER_STARTED.json", {"pid": server_process.pid, "started_unix_ns": started})
            deadline = time.monotonic() + 10
            while not (adapter / "SERVER.json").exists():
                if server_process.poll() is not None or time.monotonic() >= deadline:
                    raise ValueError("original listener did not publish readiness; no relaunch")
                time.sleep(0.05)
            server = document(adapter / "SERVER.json")
            plan = document(adapter / "PLAN.json")
            if (server["address"][0] != "127.0.0.1" or type(server["address"][1]) is not int
                    or not 0 < server["address"][1] < 65536 or server["plan"] != pin(canonical(plan))
                    or server["started_at_unix_ns"] < RESULT["precompile_completed_at_unix_ns"]
                    or plan["mode"] != "capture" or plan["native_source_sha"] != COMMIT
                    or plan["request_id"] != arm["request_id"] or plan["profile"] != PROFILE_VALUE
                    or plan["source_pins"] != ADAPTER_PINS or plan["max_input_tokens"] != 1024):
                raise ValueError("listener does not bind frozen source/profile/plan")
            native_env = dict(ENV, HEPTA_LOCAL_PROVIDER_BASE_URL=f"http://127.0.0.1:{server['address'][1]}/v1",
                HEPTA_LOCAL_PROVIDER_MODEL=PROFILE_VALUE["model_name"], HEPTA_MEM_NATIVE_SOURCE_SHA=COMMIT,
                HEPTA_MEM_CONTEXT_REQUEST_ID=arm["request_id"], HEPTA_MEM_CONTEXT_RUN_ROOT=str(directory / "native"),
                HEPTA_MEM_NATIVE_PHASE="capture", HEPTA_MEM_NATIVE_INTERVENTION=arm["arm"])
            write(directory / "BOUND_NATIVE_ENVIRONMENT.json", {key: value for key, value in native_env.items()
                if key.startswith(("HEPTA_LOCAL_PROVIDER_", "HEPTA_MEM_", "CARGO_BIN_EXE_"))})
            test_ok = command(arm["arm"] + "-capture", ["just", "test", "--locked", "-p", "codex-hepta-agentd",
                "--lib", "-E", "test(=" + CAPTURE_CASE + ")", "--run-ignored", "only", "--no-capture", "--retries", "0"],
                expected={CAPTURE_CASE}, timeout=240, env=native_env)
            # Wait for the original one-shot listener, including the full no-request tombstone window.
            server_returncode = server_process.wait(timeout=150)
            write(directory / "LISTENER_EXIT.json", {"pid": server_process.pid, "exit_code": server_returncode,
                  "finished_unix_ns": time.time_ns(), "timed_out": False})
        entry.update(join_arm(arm, directory, adapter, server, server_returncode, test_ok))
    except BaseException as error:
        entry.update(status="incomplete", error=type(error).__name__ + ": " + str(error))
        (directory / "exception.txt").write_text(traceback.format_exc())
    finally:
        if server_process is not None and server_process.poll() is None:
            # Only this owned listener is stopped. An interrupted server is never called zero-request.
            server_process.terminate()
            try:
                server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server_process.kill()
                server_process.wait(timeout=5)
            write(directory / "LISTENER_INTERRUPTED.json", {"pid": server_process.pid,
                "exit_code": server_process.returncode, "finished_unix_ns": time.time_ns(), "observation_complete": False})
        save()


# Token-only uses the frozen tokenizer/template and exact retained provider input.
# No AutoModel class, model weights loader, or generation method is invoked.
TOKEN_WORKER = r'''
import hashlib,json,os,sys
from pathlib import Path
profile=json.loads(Path(sys.argv[1]).read_bytes())
sys.path.insert(0,profile["site_packages"])
import torch
from transformers import AutoTokenizer
torch.set_num_threads(2)
raw=Path(sys.argv[2]).read_bytes(); request=json.loads(raw)
tokenizer=AutoTokenizer.from_pretrained(profile["model_dir"],local_files_only=True,trust_remote_code=False)
prompt=tokenizer.apply_chat_template([{"role":"user","content":request["input"]}],tokenize=False,add_generation_prompt=True)
inputs=tokenizer(prompt,return_tensors="pt",truncation=False)
count=int(inputs["input_ids"].shape[1])
result={"schema":"hepta.mem15.token-only.v1","request_sha256":hashlib.sha256(raw).hexdigest(),
 "rendered_prompt":prompt,"tensors":{name:{"dtype":str(value.dtype),"shape":list(value.shape),"values":value.tolist()} for name,value in inputs.items()},
 "prompt_tokens":count,"input_limit":1024,"truncation":False,"budget_admitted":count<=1024,
 "status":"ADMITTED_WITHOUT_GENERATION" if count<=1024 else "REJECTED_INPUT_TOKEN_BUDGET",
 "model_weights_loaded":False,"model_generation_count":0,"namespace_isolated":False}
Path(sys.argv[3]).write_bytes(json.dumps(result,sort_keys=True,separators=(",",":"),allow_nan=False).encode()+b"\n")
print(json.dumps({key:value for key,value in result.items() if key not in ("rendered_prompt","tensors")},sort_keys=True))
'''


def token_only():
    sys.path.insert(0, str(SOURCE / "scripts"))
    from ndu_real_runtime.episodic_local_provider import runtime_inventory
    before = runtime_inventory(PROFILE_VALUE["site_packages"])
    assets_before = {name: digest(Path(PROFILE_VALUE["model_dir"]) / name) for name in PROFILE_VALUE["model_assets"]}
    if (before["sha256"] != PROFILE_VALUE["runtime_sha256"] or assets_before != PROFILE_VALUE["model_assets"]
            or digest(Path(PYTHON))["sha256"] != PROFILE_VALUE["python_sha256"]):
        raise ValueError("token-only runtime or frozen assets changed")
    worker = OUT / "token_only.py"
    worker.write_text(TOKEN_WORKER)
    token_home = OUT / "token-home"
    token_home.mkdir()
    token_env = {"HOME": str(token_home), "XDG_CACHE_HOME": str(token_home / "cache"), "PATH": "/usr/bin:/bin",
        "PYTHONDONTWRITEBYTECODE": "1", "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "TOKENIZERS_PARALLELISM": "false"}
    entries = []
    for arm in ARMS:
        request = OUT / arm["arm"] / "adapter/http-0001/provider-request.bin"
        if not request.is_file():
            entries.append({"arm": arm["arm"], "status": "NOT_EXECUTED_NO_MAPPED_REQUEST"})
            continue
        output = OUT / arm["arm"] / "TOKEN_ONLY.json"
        args = [PYTHON, "-B", str(worker), str(PROFILE), str(request), str(output)]
        ok = command(arm["arm"] + "-token-only", args, timeout=60, env={**ENV, **token_env})
        entry = {"arm": arm["arm"], "execution_passed": ok, "request": digest(request), "worker": digest(worker)}
        if output.exists():
            value = document(output)
            if value["request_sha256"] != entry["request"]["sha256"] or value["model_generation_count"] != 0:
                raise ValueError("token-only exact input binding failed")
            entry.update({key: value[key] for key in ("status", "prompt_tokens", "input_limit", "budget_admitted", "model_generation_count")})
            entry["original_output"] = digest(output)
        entries.append(entry)
    after = runtime_inventory(PROFILE_VALUE["site_packages"])
    assets_after = {name: digest(Path(PROFILE_VALUE["model_dir"]) / name) for name in PROFILE_VALUE["model_assets"]}
    value = {"runtime_before": before, "runtime_after": after, "assets_before": assets_before, "assets_after": assets_after,
             "same_frozen_assets": before == after and assets_before == assets_after, "entries": entries,
             "scope": "tokenizer-only admission; not actual generation or namespace-isolated model delivery"}
    write(OUT / "TOKEN_PREFLIGHT.json", value)
    if not value["same_frozen_assets"]:
        raise ValueError("token-only asset/runtime postimages changed")
    RESULT["token_preflight"] = value


OUT.mkdir(mode=0o700, exist_ok=False)
try:
    write(OUT / "PLAN.json", {"source_commit": COMMIT, "source_tree": TREE, "codex_rs_tree": CODEX_TREE,
        "arms": ARMS, "phase": "capture", "maximum_attempts_per_arm": 1, "model_generation_authorized": False,
        "controls": sorted(ACK_CASES | {CLI_CASE}), "capture_case": CAPTURE_CASE,
        "nextest_retries": 0, "nextest_timeout_policy_changed": False, "listener_timeout_seconds": 120,
        "max_input_tokens": 1024, "max_output_tokens": 32, "post_capture_token_only_predeclared": True})
    # Preserve the exact submitted -c payload without depending on local executor files.
    import __main__
    payload = getattr(__main__, "SUBMITTED_PAYLOAD", None)
    if payload is not None:
        (OUT / "submitted.py").write_text(payload)
    save()
    if not command("fetch-final", ["git", "-C", str(CACHE), "fetch", "--no-tags", "--depth=1",
            "https://github.com/TrillionniumFoundation/hepta-private-ci.git", COMMIT], timeout=300, setup=True):
        raise RuntimeError("exact source fetch failed")
    if not command("new-worktree", ["git", "-C", str(CACHE), "worktree", "add", "--detach", str(SOURCE), COMMIT], timeout=300, setup=True):
        raise RuntimeError("new worktree failed")
    RESULT["source_before"] = require_source()
    if digest(PROFILE)["sha256"] != PROFILE_SHA:
        raise ValueError("frozen profile differs")
    PROFILE_VALUE = document(PROFILE)
    shutil.copyfile(PROFILE, OUT / "frozen-profile.json")
    repair_path, deps_path = OLD / "clang-resources-v1/REPAIR.json", OLD / "build-dependencies/DEPENDENCIES.json"
    repair, deps = document(repair_path), document(deps_path)
    if repair["status"] != "prepared" or repair["system_packages_modified"] or not deps["protoc_usable"]:
        raise ValueError("known task-local build prerequisites unavailable")
    if digest(Path(repair["stddef_header"]["path"]))["sha256"] != repair["stddef_header"]["sha256"]:
        raise ValueError("task-local stddef header changed")
    ENV.update(repair["build_environment"], PROTOC=deps["protoc_path"], LD_LIBRARY_PATH=deps["protoc_libraries"])
    RESULT["build_environment"] = {key: ENV[key] for key in ("PATH", "XDG_CACHE_HOME", "RUSTUP_TOOLCHAIN", "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL",
        "CARGO_PROFILE_TEST_DEBUG", "CARGO_PROFILE_DEV_DEBUG", "CARGO_TARGET_DIR", "BINDGEN_EXTRA_CLANG_ARGS", "PROTOC", "LD_LIBRARY_PATH")}
    RESULT["prerequisites"] = {"clang": digest(repair_path), "protoc": digest(deps_path)}
    postimages = document(ROOT / "format-recovery01/RESULT.json")["formatted_postimages"]
    for path, expected in postimages.items():
        if digest(SOURCE / path) != {key: expected[key] for key in ("bytes", "sha256")}:
            raise ValueError("formatted final postimage differs: " + path)
    RESULT["formatted_postimages"] = postimages
    ADAPTER_PINS = {name: digest(SOURCE / "scripts" / name) for name in (
        "ndu_real_runtime/episodic_native_adapter.py", "ndu_real_runtime/episodic_local_provider.py",
        "ndu_real_runtime/episodic_local_worker.py", "ndu_real_runtime/episodic_provider_handoff.py", "hepta_ci_exec.py")}
    RESULT["adapter_source_pins"] = ADAPTER_PINS
    envfile = OUT / "v8.env"
    ENV["GITHUB_ENV"] = str(envfile)
    ok = command("verified-v8", [PYTHON, str(SOURCE / "scripts/hepta_ci_v8.py")], timeout=900)
    if ok:
        for line in envfile.read_text().splitlines():
            key, value = line.split("=", 1)
            if key not in {"RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"}:
                raise ValueError("unexpected V8 export")
            ENV[key] = value
        ok = command("native-binaries", ["cargo", "build", "--locked", "--manifest-path", str(SOURCE / "codex-rs/Cargo.toml"),
            "-p", "codex-cli", "--bin", "codex", "-p", "codex-hepta-infer-worker-host", "--bin", "hepta-infer-worker"])
    BINARIES = {}
    if ok:
        for name in ("codex", "hepta-infer-worker"):
            path = Path(ENV["CARGO_TARGET_DIR"]) / "debug" / name
            BINARIES[name] = {"path": str(path), "pin": digest(path)}
            ENV["CARGO_BIN_EXE_" + name] = str(path)
        RESULT["binaries_before"] = BINARIES
        ok = command("capture-precompile", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib",
            "-E", "test(=" + CAPTURE_CASE + ")", "--run-ignored", "only", "--no-run", "--retries", "0"])
    if ok:
        ok = command("ack-controls", ["just", "test", "--locked", "-p", "codex-hepta-agentd", "--lib", "-E",
            " | ".join("test(=" + name + ")" for name in sorted(ACK_CASES)), "--no-capture", "--retries", "0"], expected=ACK_CASES)
    if ok:
        ok = command("cli-control", ["just", "test", "--locked", "-p", "codex-hepta-infer-worker-host", "--bin", "hepta-infer-worker",
            "-E", "test(=" + CLI_CASE + ")", "--no-capture", "--retries", "0"], expected={CLI_CASE})
    RESULT["new_controls_passed"] = ok
    if ok:
        RESULT["precompile_completed_at_unix_ns"] = time.time_ns()
        save()
        for arm in ARMS:
            run_arm(arm)
        if all(entry["status"] == "joined" for entry in RESULT["arms"]):
            RESULT["model_generation_count"] = sum(entry["model_generation_count"] for entry in RESULT["arms"])
            RESULT["physical_native_http_count"] = sum(entry["physical_native_http_count"] for entry in RESULT["arms"])
        left = OUT / "reader-off/adapter/http-0001/body.bin"
        right = OUT / "withhold/adapter/http-0001/body.bin"
        if left.is_file() and right.is_file():
            a, b = left.read_bytes(), right.read_bytes()
            ja, jb = json.loads(a), json.loads(b)
            RESULT["reader_off_vs_withhold"] = {"raw_body_equal": a == b, "parsed_json_equal": ja == jb,
                "left": pin(a), "right": pin(b), "differing_top_level_fields": sorted(key for key in set(ja) | set(jb) if ja.get(key) != jb.get(key)),
                "no_normalization_or_dynamic_field_removal": True}
        try:
            token_only()
        except BaseException as error:
            RESULT["token_preflight_error"] = type(error).__name__ + ": " + str(error)
            (OUT / "token-preflight-exception.txt").write_text(traceback.format_exc())
        RESULT["scoped_fix_passed"] = command("scoped-fix", ["just", "fix", "--locked", "-p", "codex-hepta-agentd", "-p", "codex-hepta-infer-worker-host"], final=True)
    RESULT["format_passed"] = command("final-format", ["just", "fmt", "--base", BASE], timeout=900, final=True)
    RESULT["source_after"] = identity()
    (OUT / "source-rewrites.patch").write_text(git("diff", "--binary", "HEAD"))
    RESULT["source_unchanged"] = RESULT["source_before"] == RESULT["source_after"]
    RESULT["binaries_after"] = {name: {"path": value["path"], "pin": digest(Path(value["path"]))} for name, value in BINARIES.items()}
    RESULT["binary_bytes_unchanged"] = RESULT["binaries_after"] == BINARIES
    RESULT["status"] = "capture_controls_passed" if (ok and len(RESULT["arms"]) == 4
        and all(entry["status"] == "joined" for entry in RESULT["arms"])
        and RESULT.get("scoped_fix_passed") and RESULT["format_passed"] and RESULT["source_unchanged"]
        and RESULT["binary_bytes_unchanged"]) else "incomplete"
except BaseException as error:
    RESULT.update(status="incomplete", error=type(error).__name__ + ": " + str(error))
    (OUT / "exception.txt").write_text(traceback.format_exc())
finally:
    RESULT["finished_unix_ns"] = time.time_ns()
    save()
    # Copy formatter originals and source postimages only. Retained private owner roots stay remote.
    formatting = OUT / "pretest-format-originals"
    formatting.mkdir()
    for name in ("FORMAT.json", "just-format.log"):
        if (ROOT / name).is_file():
            shutil.copyfile(ROOT / name, formatting / ("initial-" + name))
    for name in ("RESULT.json", "FORMAT.patch", "just-format.log", "dotslash-help.log", "pinned-buildifier-version.log"):
        path = ROOT / "format-recovery01" / name
        if path.is_file():
            shutil.copyfile(path, formatting / ("recovery-" + name))
    originals = OUT / "source-postimages"
    if SOURCE.exists():
        for name in list(RESULT.get("formatted_postimages", {})) + ["scripts/" + name for name in RESULT.get("adapter_source_pins", {})]:
            path = SOURCE / name
            if path.is_file():
                target = originals / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
    # Exclude C home/cache: the controlled public A/C input/output and native journal are retained.
    selected = [path for path in OUT.rglob("*") if path.is_file() and not path.is_symlink()
        and not any(part in {"home", "cache", "work", "token-home", "__pycache__"} for part in path.relative_to(OUT).parts)]
    write(OUT / "MEMBER_MANIFEST.json", {str(path.relative_to(OUT)): digest(path) for path in selected})
    archive = ROOT / "capture-bbbcc630-01.tar.xz"
    with tarfile.open(archive, "x:xz") as stream:
        for path in selected + [OUT / "MEMBER_MANIFEST.json"]:
            stream.add(path, arcname=str(path.relative_to(OUT)), recursive=False)
    publication = {"archive": str(archive), **digest(archive), "result": str(OUT / "RESULT.json"), "status": RESULT["status"]}
    write(ROOT / "CAPTURE_BBBCC630_01_PUBLICATION.json", publication)
    print(json.dumps(publication, indent=2))
if RESULT["status"] != "capture_controls_passed":
    raise SystemExit(1)
