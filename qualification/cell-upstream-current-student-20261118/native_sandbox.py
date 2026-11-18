"""Restricted upstream source edits, evaluated by unchanged tests in real bwrap."""
import ast
import copy
import errno
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import socket
import subprocess
import sys
import time
import types
import xml.etree.ElementTree as ET

MATERIAL_ROOT = Path("/home/qian-qi/work/hepta-e5-upstream-20261118-2e9b")
HOST_CANARY = Path("/home/qian-qi/work/hepta-upstream-current-policy-20261118-2e9b/HOST_CANARY.txt")
SOURCES_SHA = "686f1d77e274486034044ead9ec1b5db25c98c87b530264e1128766da785d0fa"
TARGETS = {
    "python-attrs/attrs": ("src/attr/_make.py", "_is_class_var", None),
    "Textualize/rich": ("rich/cells.py", "split_graphemes", None),
    "tox-dev/platformdirs": ("src/platformdirs/unix.py", "_get_user_dirs_folder", "_LINE_END_CR"),
    "python-humanize/humanize": ("src/humanize/time.py", "_abs_timedelta", None),
}
SAFE_BUILTINS = {"abs", "all", "any", "bool", "chr", "dict", "enumerate", "float",
    "getattr", "int", "isinstance", "len", "list", "max", "min", "ord", "range",
    "reversed", "round", "set", "sorted", "str", "sum", "tuple", "zip",
    "Exception", "TypeError", "ValueError", "RuntimeError"}
BANNED_NODES = (ast.Import, ast.ImportFrom, ast.Global, ast.Nonlocal, ast.ClassDef,
    ast.AsyncFunctionDef, ast.Await, ast.Yield, ast.YieldFrom)
BANNED_NAMES = {"eval", "exec", "compile", "globals", "locals", "vars", "dir",
    "__import__", "__builtins__", "breakpoint", "input", "print", "open", "exit", "quit"}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def write(path, value):
    path = Path(path)
    raw = value if isinstance(value, bytes) else canonical(value) + b"\n"
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha(raw)

def read(path):
    return json.loads(Path(path).read_bytes())

def source(project):
    raw = (MATERIAL_ROOT / "SOURCES.json").read_bytes()
    if sha(raw) != SOURCES_SHA:
        raise ValueError("source inventory changed")
    row = next(row for row in json.loads(raw)["sources"] if row["project_id"] == project)
    folder = MATERIAL_ROOT / "repositories" / project.split("/")[-1]
    for item in row["source_files"]:
        for variant in ("before", "after"):
            raw = (folder / variant / item["path"]).read_bytes()
            if len(raw) != item[variant]["bytes"] or sha(raw) != item[variant]["sha256"]:
                raise ValueError("bound upstream bytes changed")
    return row, folder

def function(tree, name):
    rows = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
    if len(rows) != 1:
        raise ValueError("exactly one permitted source function required")
    return rows[0]

def constant_name(node):
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    return None

def signature(node):
    return ast.dump(ast.FunctionDef(name=node.name, args=node.args, body=[], decorator_list=node.decorator_list,
        returns=node.returns, type_comment=node.type_comment, type_params=getattr(node, "type_params", [])),
        include_attributes=False)

def check_ast(project, prior, oracle, candidate):
    allowed_path, target, extra = TARGETS[project]
    before_tree, oracle_tree, after_tree = [ast.parse(raw) for raw in (prior, oracle, candidate)]
    old_fn, oracle_fn, new_fn = [function(tree, target) for tree in (before_tree, oracle_tree, after_tree)]
    if signature(old_fn) != signature(new_fn):
        raise ValueError("permitted function signature/decorators changed")
    def fixed_nodes(tree):
        return [ast.dump(node, include_attributes=False) for node in tree.body
                if not (isinstance(node, ast.FunctionDef) and node.name == target)
                and not (extra and constant_name(node) == extra)]
    if fixed_nodes(before_tree) != fixed_nodes(after_tree):
        raise ValueError("edit changes code outside the named function or permitted regex constant")
    extras = [node for node in after_tree.body if extra and constant_name(node) == extra]
    if len(extras) > 1:
        raise ValueError("duplicate permitted module constant")
    if extras:
        oracle_extra = next(node for node in oracle_tree.body if constant_name(node) == extra)
        if isinstance(extras[0], ast.AnnAssign) and ast.dump(extras[0].annotation) != ast.dump(oracle_extra.annotation):
            raise ValueError("permitted constant annotation changed")
        value = extras[0].value
        if not (isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
                and isinstance(value.func.value, ast.Name) and value.func.value.id == "re"
                and value.func.attr == "compile" and len(value.args) == 1 and not value.keywords
                and isinstance(value.args[0], ast.Constant) and isinstance(value.args[0].value, str)
                and len(value.args[0].value) <= 256):
            raise ValueError("module addition must be a bounded literal re.compile constant")
    references = [*ast.walk(old_fn), *ast.walk(oracle_fn)]
    allowed_globals = {node.id for node in references if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)}
    allowed_globals.update(SAFE_BUILTINS | {"re"})
    if extra:
        allowed_globals.add(extra)
    attributes = {node.attr for node in references if isinstance(node, ast.Attribute)} | {"sub", "compile"}
    local_names = {node.id for node in ast.walk(new_fn) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))}
    local_names.update(arg.arg for arg in ast.walk(new_fn) if isinstance(arg, ast.arg))
    if sum(isinstance(node, ast.FunctionDef) for node in ast.walk(new_fn)) != 1:
        raise ValueError("nested function definitions are outside the patch interface")
    parents = {child: parent for parent in ast.walk(new_fn) for child in ast.iter_child_nodes(parent)}
    for node in ast.walk(new_fn):
        if isinstance(node, BANNED_NODES):
            raise ValueError("unsupported executable construct: " + type(node).__name__)
        if isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                raise ValueError("unsafe name in patch")
            if isinstance(node.ctx, ast.Load) and node.id not in allowed_globals | local_names:
                raise ValueError("new external name is not admitted: " + node.id)
        if isinstance(node, ast.Attribute):
            if node.attr == "open" and not (isinstance(parents.get(node), ast.Call) and parents[node].func is node):
                raise ValueError("file open cannot be aliased")
            if isinstance(node.ctx, (ast.Store, ast.Del)) or node.attr not in attributes or node.attr.startswith("__"):
                raise ValueError("unsupported attribute access or mutation: " + node.attr)
            if isinstance(node.value, ast.Name) and node.value.id == "sys" and node.attr != "getfilesystemencoding":
                raise ValueError("sys access outside original filesystem-encoding query")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            if not (len(node.args) in (2, 3) and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "__forward_arg__"):
                raise ValueError("getattr limited to the original ForwardRef data field")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "open":
            if any(isinstance(arg, ast.Starred) for arg in node.args) or any(kw.arg is None for kw in node.keywords):
                raise ValueError("dynamic file open arguments are not admitted")
            mode = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "mode"), None)
            if mode is not None and not (isinstance(mode, ast.Constant) and mode.value in ("r", "rt", "rb")):
                raise ValueError("candidate file access is read-only")
    return {"path": allowed_path, "function": target, "optional_constant": extra,
            "outside_function_ast_unchanged": True, "no_import_or_test_mutation": True}

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result

def admit(project, answer):
    row, folder = source(project)
    path, _, _ = TARGETS[project]
    before = (folder / "before" / path).read_bytes()
    oracle = (folder / "after" / path).read_bytes()
    if not isinstance(answer, str) or not 0 < len(answer.encode()) <= 32768:
        raise ValueError("bounded raw JSON patch required")
    action = json.loads(answer, object_pairs_hook=unique_object)
    if not isinstance(action, dict) or set(action) != {"edits"} or not isinstance(action["edits"], list) or not 1 <= len(action["edits"]) <= 8:
        raise ValueError('expected exactly {"edits":[{"old":"exact original text","new":"replacement"}]}')
    text = before.decode()
    replacements = []
    for edit in action["edits"]:
        if not isinstance(edit, dict) or set(edit) != {"old", "new"}:
            raise ValueError("each edit needs only old and new")
        old, new = edit["old"], edit["new"]
        if not isinstance(old, str) or not old or not isinstance(new, str) or len(old) + len(new) > 16384:
            raise ValueError("bounded exact old/new strings required")
        if text.count(old) != 1:
            raise ValueError("old text must occur exactly once in the original file")
        start = text.index(old)
        replacements.append((start, start + len(old), new))
    replacements.sort()
    if any(left[1] > right[0] for left, right in zip(replacements, replacements[1:])):
        raise ValueError("overlapping original edits")
    result = text
    for start, end, replacement in reversed(replacements):
        result = result[:start] + replacement + result[end:]
    modified = result.encode()
    declaration = check_ast(project, before, oracle, modified)
    return modified, {**declaration, "original_source_sha256": sha(before),
        "patched_source_sha256": sha(modified), "answer_sha256": sha(answer.encode()),
        "edits": len(replacements), "test_files_modified": False, "oracle_files_modified": False}

def attest(case):
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    value = {"net_namespace": os.readlink("/proc/self/ns/net"), "pid_namespace": os.readlink("/proc/self/ns/pid"),
        "network_interfaces": socket.if_nameindex(), "env_keys": sorted(os.environ),
        "host_canary_visible": Path(case["host_canary"]).exists(),
        "tests_readonly": bool(os.statvfs("/tests").f_flag & os.ST_RDONLY),
        "dependencies_readonly": bool(os.statvfs("/venv").f_flag & os.ST_RDONLY),
        "package_readonly": bool(os.statvfs("/package").f_flag & os.ST_RDONLY),
        "effective_capabilities": status["CapEff"].strip(),
        "test_sha256": sha(Path("/tests/" + Path(case["test_path"]).name).read_bytes()),
        "source_sha256": sha(Path("/package/" + case["source_path"]).read_bytes())}
    assert value["net_namespace"] != case["host_net_namespace"] and value["pid_namespace"] != case["host_pid_namespace"]
    assert value["network_interfaces"] == [(1, "lo")] and not value["host_canary_visible"]
    assert value["tests_readonly"] and value["dependencies_readonly"] and value["package_readonly"]
    assert int(value["effective_capabilities"], 16) == 0
    assert value["test_sha256"] == case["test_sha256"] and value["source_sha256"] == case["source_sha256"]
    assert not any(key not in {"PATH", "HOME", "LANG", "LC_ALL", "TZ", "PWD",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD", "PYTHONDONTWRITEBYTECODE", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"} for key in os.environ)
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
    assert value["network_connect_errno"] in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.EPERM)
    write("/out/SANDBOX_ATTESTATION.json", value)

def inside():
    resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (60, 65))
    resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    case = read("/case.json")
    attest(case)
    sys.path.insert(0, "/package/" + case["package_import_root"])
    generated = {}
    if case["project_id"] == "tox-dev/platformdirs":
        module = types.ModuleType("platformdirs.version")
        module.__version__, module.__version_tuple__ = "0+source", (0, 0, 0)
        sys.modules[module.__name__] = module
        generated[module.__name__] = {"__version__": module.__version__, "__version_tuple__": [0, 0, 0]}
    if case["project_id"] == "python-humanize/humanize":
        module = types.ModuleType("humanize._version")
        module.__version__ = "0+source"
        sys.modules[module.__name__] = module
        generated[module.__name__] = {"__version__": module.__version__}
    package = {"python-attrs/attrs": "attr", "Textualize/rich": "rich", "tox-dev/platformdirs": "platformdirs",
               "python-humanize/humanize": "humanize"}[case["project_id"]]
    imported = importlib.import_module(package)
    assert Path(imported.__file__).resolve().is_relative_to("/package")
    import pytest
    test = "/tests/" + Path(case["test_path"]).name
    args = ["-q", "-c", "/pytest.ini", "--confcutdir", "/tests", "-p", "no:cacheprovider",
        "-p", "pytest_timeout", "--timeout=3", "--timeout-method=signal", "--tb=short",
        "--junitxml", "/out/junit.xml", *[test + "::" + name for name in case["test_functions"]]]
    write("/out/PYTEST_INTENT.json", {"argv": args, "original_test_sha256": case["test_sha256"],
        "generated_packaging_metadata_only": generated, "tests_unchanged": True})
    started = time.perf_counter()
    code = int(pytest.main(args))
    write("/out/PYTEST_RETURN.json", {"exit_code": code, "wall_seconds": time.perf_counter() - started,
        "generated_packaging_metadata_only": generated})
    return code

def run_native(project, output, candidate=None, label="candidate"):
    started, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    output = Path(output)
    output.mkdir(exist_ok=False)
    row, folder = source(project)
    source_path, _, _ = TARGETS[project]
    test = folder / "after" / row["selected_tests"]["path"]
    original = folder / "before" / source_path
    chosen = original
    if candidate is not None:
        chosen = output / "PATCHED_SOURCE.py"
        write(chosen, candidate)
    case = {"project_id": project, "source_path": source_path, "source_sha256": sha(chosen.read_bytes()),
        "test_path": row["selected_tests"]["path"], "test_sha256": sha(test.read_bytes()),
        "test_functions": row["selected_tests"]["names"], "package_import_root": row["package_import_root"],
        "host_net_namespace": os.readlink("/proc/self/ns/net"), "host_pid_namespace": os.readlink("/proc/self/ns/pid"),
        "host_canary": str(HOST_CANARY), "label": label}
    assert HOST_CANARY.is_file()
    write(output / "CASE.json", case)
    write(output / "pytest.ini", b"[pytest]\n")
    inner_output = output / "sandbox-output"
    inner_output.mkdir()
    command = ["/usr/bin/bwrap", "--unshare-all", "--die-with-parent", "--new-session",
        "--clearenv", "--cap-drop", "ALL"]
    for path in ("/usr", "/lib", "/lib64"):
        command += ["--ro-bind", path, path]
    command += ["--ro-bind", "/etc/ld.so.cache", "/etc/ld.so.cache", "--proc", "/proc",
        "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/home",
        "--ro-bind", str(MATERIAL_ROOT / "venv"), "/venv",
        "--ro-bind", str(folder / "before"), "/package",
        "--ro-bind", str(chosen), "/package/" + source_path,
        "--ro-bind", str(test.parent), "/tests",
        "--ro-bind", str(Path(__file__).resolve()), "/runner.py",
        "--ro-bind", str(output / "CASE.json"), "/case.json",
        "--ro-bind", str(output / "pytest.ini"), "/pytest.ini",
        "--bind", str(inner_output), "/out"]
    env = {"PATH": "/venv/bin:/usr/bin:/bin", "HOME": "/tmp", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
        "TZ": "UTC", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
    for key, value in env.items():
        command += ["--setenv", key, value]
    command += ["--chdir", "/tmp", "/venv/bin/python", "-I", "-B", "/runner.py", "inside"]
    write(output / "INTENT.json", {"argv": command, "environment": env,
        "sandbox_binary_sha256": sha(Path("/usr/bin/bwrap").read_bytes()),
        "native_verifier_source_sha256": sha(Path(__file__).read_bytes()),
        "started_at_ns": time.time_ns(), "timeout_seconds": 120, "automatic_retry": False})
    timed_out = False
    with (output / "STDOUT.txt").open("xb") as stdout, (output / "STDERR.txt").open("xb") as stderr:
        child = subprocess.Popen(command, stdout=stdout, stderr=stderr, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
            start_new_session=True)
        write(output / "STARTED.json", {"pid": child.pid, "process_group_id": child.pid})
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
    result = {"project_id": project, "label": label, "actual_wait_returncode": code, "timed_out": timed_out,
        "wall_seconds": time.perf_counter() - started, "completed_child_cpu_seconds":
        after.ru_utime + after.ru_stime - usage.ru_utime - usage.ru_stime,
        "case_sha256": sha((output / "CASE.json").read_bytes()),
        "stdout_sha256": sha((output / "STDOUT.txt").read_bytes()),
        "stderr_sha256": sha((output / "STDERR.txt").read_bytes()),
        "original_test_sha256": case["test_sha256"], "patched_source_sha256": case["source_sha256"],
        "actual_native_child": True, "model_calls": 0, "training_updates": 0}
    junit = inner_output / "junit.xml"
    if junit.exists():
        tests = list(ET.parse(junit).getroot().iter("testcase"))
        result.update(tests=len(tests), failures=sum(node.find("failure") is not None for node in tests),
            errors=sum(node.find("error") is not None for node in tests),
            skipped=sum(node.find("skipped") is not None for node in tests),
            cases=[{"name": node.attrib["name"], "failure": None if node.find("failure") is None else node.find("failure").attrib.get("message"),
                    "error": None if node.find("error") is None else node.find("error").attrib.get("message")}
                   for node in tests], junit_sha256=sha(junit.read_bytes()))
    old_result = read(MATERIAL_ROOT / "replay-1/RESULT.json")
    expected = next(row for row in old_result["stages"] if row["project_id"] == project and row["variant"] == "after")
    result["same_original_case_set"] = [row["name"] for row in result.get("cases", [])] == [row["name"] for row in expected["cases"]]
    attest_path = inner_output / "SANDBOX_ATTESTATION.json"
    result["sandbox_attestation_sha256"] = sha(attest_path.read_bytes()) if attest_path.exists() else None
    result["success"] = bool(code == 0 and not timed_out and result["same_original_case_set"]
        and result.get("failures") == result.get("errors") == result.get("skipped") == 0
        and result["sandbox_attestation_sha256"])
    write(output / "RESULT.json", result)
    return result

def verify(project, answer, output):
    output = Path(output)
    output.mkdir(exist_ok=False)
    write(output / "ANSWER.txt", answer.encode())
    started = time.perf_counter()
    try:
        candidate, admission = admit(project, answer)
    except (ValueError, SyntaxError, TypeError, KeyError) as error:
        result = {"success": False, "stage": "patch_admission", "reason": str(error),
            "error_type": type(error).__name__, "answer_sha256": sha(answer.encode()),
            "actual_native_child": False, "wall_seconds": time.perf_counter() - started}
    else:
        write(output / "ADMISSION.json", admission)
        result = run_native(project, output / "native", candidate)
        result.update(stage="native_pytest", answer_sha256=sha(answer.encode()),
            verification_wall_seconds=time.perf_counter() - started)
    write(output / "VERIFICATION.json", result)
    return result

def feedback(result):
    value = {"success": result["success"], "stage": result["stage"],
        "verification_digest": sha(canonical(result))}
    if result["stage"] == "patch_admission":
        value["reason"] = result["reason"][:400]
    else:
        value.update(test_cases=result.get("tests"), failures=result.get("failures"), errors=result.get("errors"),
            skipped=result.get("skipped"), same_original_case_set=result["same_original_case_set"],
            outer_timeout=result["timed_out"], child_exit=result["actual_wait_returncode"],
            failures_detail=[{"name": row["name"][:160], "message": (row["failure"] or row["error"] or "")[:240]}
                for row in result.get("cases", []) if row["failure"] or row["error"]][:3])
    return canonical(value).decode()

if __name__ == "__main__":
    if sys.argv[1:] != ["inside"]:
        raise SystemExit("only the sandbox inside entry is supported as a script")
    raise SystemExit(inside())
