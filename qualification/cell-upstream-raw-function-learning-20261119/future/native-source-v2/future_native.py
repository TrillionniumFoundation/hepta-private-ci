"""Bound original upstream cases in the existing no-network bwrap envelope.

The original patch AST gate and complete-function parser are loaded byte-for-byte.
Only package/test paths and their frozen inventories are generalized here.
"""

import ast
import errno
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ANCESTOR = Path(
    "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/execution-code/native_sandbox.py"
)
ANCESTOR_SHA = "49cced4d3eb61ee86b1f55a11ca097be7618a0fc9b59e515f1b1d7676bec671c"
CODEC = Path(
    "/home/qian-qi/work/hepta-upstream-replacement-interface-20261119-2e9b/execution-source-2/replacement_codec.py"
)
CODEC_SHA = "e1147a8d02624ca87b4a1f2f3345b034664b11b074f29787cb4b34085d4058c3"
VENV = Path("/home/qian-qi/work/hepta-e5-upstream-20261118-2e9b/venv")
HOST_CANARY = Path(
    "/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/HOST_CANARY.txt"
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def write(path, value):
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)


def load_module(name, path, expected):
    if sha(Path(path).read_bytes()) != expected:
        raise ValueError("original helper bytes changed")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bound(path, expected=None):
    path = Path(path)
    raw = path.read_bytes()
    if expected is not None and sha(raw) != expected:
        raise ValueError("task specification changed")
    value = json.loads(raw)
    root = path.parent
    for row in value["files"]:
        rel = Path(row["path"])
        if rel.is_absolute() or ".." in rel.parts or (root / rel).is_symlink():
            raise ValueError("unsafe material path")
        data = (root / rel).read_bytes()
        if len(data) != row["bytes"] or sha(data) != row["sha256"]:
            raise ValueError("bound original material changed: " + str(rel))
    value["_root"] = str(root)
    value["_spec_sha256"] = sha(raw)
    return value


def before_oracle(spec):
    root = Path(spec["_root"])
    prior = (root / "before" / spec["source_path"]).read_bytes()
    oracle = (root / "oracle" / spec["source_path"]).read_bytes()
    if sha(prior) != spec["before_sha256"] or sha(oracle) != spec["after_sha256"]:
        raise ValueError("source binding differs")
    return prior, oracle


def convert(spec, answer):
    original = load_module("future_original_gate", ANCESTOR, ANCESTOR_SHA)
    parser = load_module("future_original_codec", CODEC, CODEC_SHA)
    project = spec["project_id"]
    original.TARGETS[project] = (
        spec["source_path"],
        spec["function"],
        spec.get("optional_constant"),
    )
    prior, oracle = before_oracle(spec)
    text = prior.decode("utf-8")
    tree = ast.parse(text)
    old = original.function(tree, spec["function"])
    left, right, old_text = parser.node_span(text, old)
    if text.count(old_text) != 1:
        raise ValueError("original function replacement span is not unique")
    new_text, extra_text = parser.parse_payload(project, answer, original)
    edits = [(left, right, new_text)]
    if extra_text is not None:
        name = spec.get("optional_constant")
        nodes = [node for node in tree.body if original.constant_name(node) == name]
        if len(nodes) == 1:
            a, b, old_extra = parser.node_span(text, nodes[0])
            if text.count(old_extra) != 1:
                raise ValueError("original constant span is not unique")
            edits.append((a, b, extra_text))
        elif not nodes and spec.get("constant_insert_before_original_name"):
            anchor = spec["constant_insert_before_original_name"]
            anchors = [
                node for node in tree.body if original.constant_name(node) == anchor
            ]
            if len(anchors) != 1:
                raise ValueError("original constant insertion anchor is not unique")
            a, b, old_extra = parser.node_span(text, anchors[0])
            if text.count(old_extra) != 1:
                raise ValueError("original constant anchor text is not unique")
            edits.append((a, b, extra_text + old_extra))
        else:
            raise ValueError("no frozen original constant slot")
    edits.sort()
    if any(a[1] > b[0] for a, b in zip(edits, edits[1:])):
        raise ValueError("overlapping original replacement spans")
    original_action = {
        "edits": [
            {"old": text[left:right], "new": replacement}
            for left, right, replacement in edits
        ]
    }
    action_raw = original.canonical(original_action)
    if not 0 < len(action_raw) <= 32768 or not 1 <= len(edits) <= 8:
        raise ValueError("original bounded raw JSON patch limit exceeded")
    if any(
        not row["old"] or len(row["old"]) + len(row["new"]) > 16384
        for row in original_action["edits"]
    ):
        raise ValueError("original bounded exact old/new strings required")
    changed = text
    for left, right, replacement in reversed(edits):
        changed = changed[:left] + replacement + changed[right:]
    candidate = changed.encode("utf-8")
    admission = original.check_ast(project, prior, oracle, candidate)
    return candidate, {
        **admission,
        "raw_answer_sha256": sha(answer.encode()),
        "converted_original_action_sha256": sha(action_raw),
        "original_source_sha256": sha(prior),
        "patched_source_sha256": sha(candidate),
        "task_spec_sha256": spec["_spec_sha256"],
        "replacement_text_from_model_only": True,
        "original_gate_sha256": ANCESTOR_SHA,
        "original_payload_parser_sha256": CODEC_SHA,
        "test_files_modified": False,
        "oracle_files_modified": False,
    }


def attest(case):
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    value = {
        "net_namespace": os.readlink("/proc/self/ns/net"),
        "pid_namespace": os.readlink("/proc/self/ns/pid"),
        "network_interfaces": socket.if_nameindex(),
        "env_keys": sorted(os.environ),
        "host_canary_visible": Path(case["host_canary"]).exists(),
        "effective_capabilities": status["CapEff"].strip(),
        "tests_readonly": bool(os.statvfs("/tests").f_flag & os.ST_RDONLY),
        "dependencies_readonly": bool(os.statvfs("/venv").f_flag & os.ST_RDONLY),
        "package_readonly": bool(os.statvfs("/package").f_flag & os.ST_RDONLY),
        "source_sha256": sha(Path("/package", case["source_path"]).read_bytes()),
        "test_files": {
            row["path"]: sha(Path("/tests", row["path"]).read_bytes())
            for row in case["test_files"]
        },
    }
    assert (
        value["net_namespace"] != case["host_net_namespace"]
        and value["pid_namespace"] != case["host_pid_namespace"]
    )
    assert (
        value["network_interfaces"] == [(1, "lo")] and not value["host_canary_visible"]
    )
    assert (
        value["tests_readonly"]
        and value["dependencies_readonly"]
        and value["package_readonly"]
    )
    assert int(value["effective_capabilities"], 16) == 0
    assert value["source_sha256"] == case["source_sha256"]
    assert value["test_files"] == {
        row["path"]: row["sha256"] for row in case["test_files"]
    }
    assert set(os.environ) <= {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "TZ",
        "PWD",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
        "PYTHONDONTWRITEBYTECODE",
        "OMP_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
    }
    sock = socket.socket()
    sock.settimeout(0.5)
    try:
        sock.connect(("192.0.2.1", 9))
    except OSError as error:
        value["network_connect_errno"] = error.errno
    else:
        raise AssertionError("unexpected external network")
    finally:
        sock.close()
    assert value["network_connect_errno"] in (
        errno.ENETUNREACH,
        errno.EHOSTUNREACH,
        errno.EPERM,
    )
    write("/out/SANDBOX_ATTESTATION.json", value)


def inside():
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    case = json.loads(Path("/case.json").read_bytes())
    attest(case)
    sys.path[:0] = ["/package/" + case["package_import_root"], "/"]
    for name in case["package_names"]:
        module = importlib.import_module(name)
        assert Path(module.__file__).resolve().is_relative_to("/package")
    import pytest

    args = [
        "-q",
        "-c",
        "/pytest.ini",
        "--confcutdir",
        "/tests",
        "-p",
        "no:cacheprovider",
        "-p",
        "pytest_timeout",
        "--timeout=3",
        "--timeout-method=signal",
        "--tb=short",
        "--junitxml",
        "/out/junit.xml",
        *["/tests/" + item for item in case["test_selectors"]],
    ]
    write(
        "/out/PYTEST_INTENT.json",
        {
            "argv": args,
            "original_test_files": case["test_files"],
            "tests_unchanged": True,
            "generated_packaging_stubs": [],
        },
    )
    start = time.perf_counter()
    code = int(pytest.main(args))
    write(
        "/out/PYTEST_RETURN.json",
        {"exit_code": code, "wall_seconds": time.perf_counter() - start},
    )
    return code


def run_native(spec, output, candidate=None, label="candidate", expected_cases=None):
    output = Path(output)
    output.mkdir(exist_ok=False)
    root = Path(spec["_root"])
    prior, _ = before_oracle(spec)
    chosen = root / "before" / spec["source_path"]
    if candidate is not None:
        chosen = output / "PATCHED_SOURCE.py"
        write(chosen, candidate)
    case = {
        key: spec[key]
        for key in (
            "project_id",
            "source_path",
            "package_import_root",
            "package_names",
            "test_selectors",
            "test_files",
        )
    }
    case.update(
        source_sha256=sha(chosen.read_bytes()),
        host_net_namespace=os.readlink("/proc/self/ns/net"),
        host_pid_namespace=os.readlink("/proc/self/ns/pid"),
        host_canary=str(HOST_CANARY),
        label=label,
    )
    assert HOST_CANARY.is_file() and sha(prior) == spec["before_sha256"]
    write(output / "CASE.json", case)
    write(output / "pytest.ini", b"[pytest]\n")
    inner = output / "sandbox-output"
    inner.mkdir()
    command = [
        "/usr/bin/bwrap",
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--cap-drop",
        "ALL",
    ]
    for path in ("/usr", "/lib", "/lib64"):
        command += ["--ro-bind", path, path]
    command += [
        "--ro-bind",
        "/etc/ld.so.cache",
        "/etc/ld.so.cache",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--dir",
        "/home",
        "--ro-bind",
        str(VENV),
        "/venv",
        "--ro-bind",
        str(root / "before"),
        "/package",
        "--ro-bind",
        str(chosen),
        "/package/" + spec["source_path"],
        "--ro-bind",
        str(root / "after-tests" / spec["test_root"]),
        "/tests",
        "--ro-bind",
        str(Path(__file__).resolve()),
        "/runner.py",
        "--ro-bind",
        str(output / "CASE.json"),
        "/case.json",
        "--ro-bind",
        str(output / "pytest.ini"),
        "/pytest.ini",
        "--bind",
        str(inner),
        "/out",
    ]
    env = {
        "PATH": "/venv/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1",
        "OPENBLAS_NUM_THREADS": "1",
    }
    for key, value in env.items():
        command += ["--setenv", key, value]
    command += [
        "--chdir",
        "/tmp",
        "/venv/bin/python",
        "-I",
        "-B",
        "/runner.py",
        "inside",
    ]
    write(
        output / "INTENT.json",
        {
            "argv": command,
            "environment": env,
            "sandbox_binary_sha256": sha(Path("/usr/bin/bwrap").read_bytes()),
            "native_runner_sha256": sha(Path(__file__).read_bytes()),
            "task_spec_sha256": spec["_spec_sha256"],
            "started_at_ns": str(time.time_ns()),
            "timeout_seconds": 120,
            "automatic_retry": False,
        },
    )
    start, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    timed_out = False
    with (
        (output / "STDOUT.txt").open("xb") as stdout,
        (output / "STDERR.txt").open("xb") as stderr,
    ):
        child = subprocess.Popen(
            command,
            stdout=stdout,
            stderr=stderr,
            env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True,
        )
        write(
            output / "STARTED.json", {"pid": child.pid, "process_group_id": child.pid}
        )
        try:
            code = child.wait(timeout=120)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGTERM)
            try:
                code = child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                code = child.wait(timeout=10)
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "project_id": spec["project_id"],
        "label": label,
        "actual_wait_returncode": code,
        "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - start,
        "completed_child_cpu_seconds": after.ru_utime
        + after.ru_stime
        - usage.ru_utime
        - usage.ru_stime,
        "case_sha256": sha((output / "CASE.json").read_bytes()),
        "stdout_sha256": sha((output / "STDOUT.txt").read_bytes()),
        "stderr_sha256": sha((output / "STDERR.txt").read_bytes()),
        "patched_source_sha256": case["source_sha256"],
        "actual_native_child": True,
        "model_calls": 0,
        "training_updates": 0,
    }
    junit = inner / "junit.xml"
    if junit.exists():
        cases = list(ET.parse(junit).getroot().iter("testcase"))
        result.update(
            tests=len(cases),
            failures=sum(node.find("failure") is not None for node in cases),
            errors=sum(node.find("error") is not None for node in cases),
            skipped=sum(node.find("skipped") is not None for node in cases),
            cases=[
                {
                    "name": node.attrib["name"],
                    "classname": node.attrib.get("classname", ""),
                    "failure": None
                    if node.find("failure") is None
                    else node.find("failure").attrib.get("message"),
                    "error": None
                    if node.find("error") is None
                    else node.find("error").attrib.get("message"),
                }
                for node in cases
            ],
            junit_sha256=sha(junit.read_bytes()),
        )
    identities = [(row["classname"], row["name"]) for row in result.get("cases", [])]
    result["same_original_case_set"] = (
        None
        if expected_cases is None
        else identities == [tuple(row) for row in expected_cases]
    )
    path = inner / "SANDBOX_ATTESTATION.json"
    result["sandbox_attestation_sha256"] = (
        sha(path.read_bytes()) if path.exists() else None
    )
    result["success"] = bool(
        code == 0
        and not timed_out
        and identities
        and (expected_cases is None or result["same_original_case_set"])
        and result.get("failures") == result.get("errors") == result.get("skipped") == 0
        and result["sandbox_attestation_sha256"]
    )
    write(output / "RESULT.json", result)
    return result


def verify(spec_path, spec_sha256, answer, output, expected_cases):
    output = Path(output)
    output.mkdir(exist_ok=False)
    started = time.perf_counter()
    write(output / "RAW_ANSWER.txt", answer.encode())
    spec = bound(spec_path, spec_sha256)
    try:
        candidate, admission = convert(spec, answer)
    except (ValueError, SyntaxError, TypeError, KeyError) as error:
        result = {
            "success": False,
            "stage": "replacement_or_patch_admission",
            "reason": str(error),
            "error_type": type(error).__name__,
            "actual_native_child": False,
        }
    else:
        write(output / "ADMISSION.json", admission)
        result = run_native(
            spec, output / "native", candidate, expected_cases=expected_cases
        )
        result["stage"] = "native_pytest"
    result.update(
        raw_answer_sha256=sha(answer.encode()),
        wall_seconds=time.perf_counter() - started,
        task_spec_sha256=spec_sha256,
        original_gate_sha256=ANCESTOR_SHA,
        original_payload_parser_sha256=CODEC_SHA,
        wrapper_source_sha256=sha(Path(__file__).read_bytes()),
    )
    write(output / "VERIFICATION.json", result)
    return result


def feedback(result):
    original = load_module("future_feedback_original", ANCESTOR, ANCESTOR_SHA)
    if result["stage"] == "native_pytest":
        return original.feedback(result)
    return canonical(
        {
            "success": False,
            "stage": result["stage"],
            "reason": result["reason"][:400],
            "verification_digest": sha(canonical(result)),
        }
    ).decode()


if __name__ == "__main__":
    if sys.argv[1:] != ["inside"]:
        raise SystemExit("only the sandbox inside entry is supported")
    raise SystemExit(inside())
