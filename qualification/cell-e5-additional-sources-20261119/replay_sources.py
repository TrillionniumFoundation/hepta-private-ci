"""Replay complete selected upstream test functions under unchanged original E5 limits."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open("xb") as stream:
        stream.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def checked_snapshot(root, index, variant):
    folder = root / "repositories" / str(index) / variant
    manifest = json.loads((root / "snapshots" / f"{index}-{variant}.json").read_bytes())
    for row in manifest["files"]:
        file = folder / row["path"]
        assert not file.is_symlink() and sha(file) == row["sha256"], row["path"]
    return folder, manifest


def product_file(entry, path):
    parts = Path(path).parts
    return "tests" not in parts and "test" not in parts and any(path == prefix or path.startswith(prefix + "/") for prefix in entry["product_roots"])


def materialize(root, entry, variant, output):
    original, before = checked_snapshot(root, entry["index"], variant)
    tests, after = checked_snapshot(root, entry["index"], "after")
    work = output / "work"
    shutil.copytree(tests, work)
    originals = {row["path"]: row for row in before["files"]}
    fixed = {row["path"]: row for row in after["files"]}
    for path in sorted(set(originals) | set(fixed)):
        if not product_file(entry, path):
            continue
        target = work / path
        if path in originals:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original / path, target)
        elif target.exists():
            target.unlink()
    bound = []
    for path, row in fixed.items():
        if product_file(entry, path):
            if path not in originals:
                continue
            row = originals[path]
        assert sha(work / path) == row["sha256"], path
        bound.append({"path": path, "sha256": row["sha256"], "role": "runtime" if product_file(entry, path) else "original_after_fixture"})
    for path, row in originals.items():
        if path not in fixed and product_file(entry, path):
            assert sha(work / path) == row["sha256"]
            bound.append({"path": path, "sha256": row["sha256"], "role": "runtime"})
    write(output / "EXECUTION_MANIFEST.json", bound)
    return work


def child(root, entry, variant, output):
    work = output / "work"
    expected = json.loads((output / "EXECUTION_MANIFEST.json").read_bytes())
    assert all(sha(work / row["path"]) == row["sha256"] for row in expected)
    sys.path.insert(0, str(work))
    sys.path.insert(0, str(work / entry["import_root"]))
    os.chdir(work)
    if entry.get("suite_environment"):
        os.environ[entry["suite_environment"]] = str(work / "json")
    package = importlib.import_module(entry["package"])
    assert Path(package.__file__).resolve().is_relative_to(work)
    import pytest
    argv = ["-q", "-c", str(root / "EMPTY.ini"), "--confcutdir", str(work), "-p", "no:cacheprovider", "-p", "pytest_timeout", "--timeout=3", "--timeout-method=signal", "--tb=short", "--junitxml", str(output / "junit.xml"), "-k", entry["keyword"]]
    for plugin in entry.get("plugins", []):
        argv += ["-p", plugin]
    argv.extend(str(work / path) for path in entry["test_files"])
    write(output / "PYTEST_INTENT.json", {"argv": argv, "project_id": entry["project_id"], "variant": variant, "revision": entry[variant + "_commit"], "runtime_import": package.__file__, "test_files": [{"path": path, "sha256": sha(work / path)} for path in entry["test_files"]], "after_tests_and_fixtures_unchanged": True, "full_selected_function_parameter_sets": True, "model_calls": 0, "training_updates": 0})
    began = time.perf_counter()
    code = int(pytest.main(argv))
    imported = {}
    for name, module in list(sys.modules.items()):
        filename = getattr(module, "__file__", None)
        if filename and Path(filename).resolve().is_relative_to(work):
            imported[name] = {"path": str(Path(filename).resolve().relative_to(work)), "sha256": sha(Path(filename))}
    unchanged = all((work / row["path"]).exists() and sha(work / row["path"]) == row["sha256"] for row in expected)
    write(output / "PYTEST_RETURN.json", {"exit_code": code, "wall_seconds": time.perf_counter() - began, "imported_exact_files": imported, "execution_inputs_unchanged": unchanged})
    assert unchanged, "upstream tests mutated an input"
    return code


def parse_junit(path):
    if not path.exists():
        return {}
    cases = list(ET.parse(path).getroot().iter("testcase"))
    failed = sum(case.find("failure") is not None for case in cases)
    errors = sum(case.find("error") is not None for case in cases)
    skipped = sum(case.find("skipped") is not None for case in cases)
    return {"tests": len(cases), "failures": failed, "errors": errors, "skipped": skipped, "passed": len(cases) - failed - errors - skipped, "cases": [{"name": case.get("name"), "class": case.get("classname"), "failure": None if case.find("failure") is None else case.find("failure").get("message"), "error": None if case.find("error") is None else case.find("error").get("message"), "skipped": case.find("skipped") is not None} for case in cases], "junit_sha256": sha(path)}


def owner(root, output, source_commit):
    output.mkdir(exist_ok=False)
    plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
    assert json.loads((root / "ACQUISITION.json").read_bytes())["status"] == "ACQUIRED"
    started = time.perf_counter()
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    write(output / "FREEZE.json", {"source_commit": source_commit, "plan_sha256": sha(root / "ACQUISITION_PLAN.json"), "runner_sha256": sha(Path(__file__)), "native_limits": plan["native"], "variants": ["before", "after"], "new_model_calls": 0, "new_training_updates": 0, "started_at_ns": time.time_ns()})
    (root / "EMPTY.ini").write_text("[pytest]\n")
    stages, sources = [], []
    for entry in plan["projects"]:
        if entry.get("python_requires") and sys.version_info >= (3, 11):
            sources.append({"project_id": entry["project_id"], "source_id": entry["source_id"], "original_regression_demonstrated": False, "status": "MISSING_COMPATIBLE_INTERPRETER", "reason": entry["python_requires"], "native_children": 0})
            continue
        pair = []
        for variant in ("before", "after"):
            folder = output / f"{entry['index']}-{variant}"
            folder.mkdir()
            work = materialize(root, entry, variant, folder)
            argv = [str(root / "venv/bin/python"), "-I", "-B", str(Path(__file__)), "child", "--root", str(root), "--output", str(folder), "--index", str(entry["index"]), "--variant", variant]
            env = {"PATH": str(root / "venv/bin") + ":/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
            before_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
            began, timed_out = time.perf_counter(), False
            with (folder / "STDOUT.txt").open("xb") as out, (folder / "STDERR.txt").open("xb") as err:
                process = subprocess.Popen(argv, cwd=work, env=env, stdout=out, stderr=err, start_new_session=True)
                write(folder / "STARTED.json", {"pid": process.pid, "process_group_id": process.pid, "argv": argv, "started_at_ns": time.time_ns()})
                try:
                    code = process.wait(timeout=120)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        code = process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        code = process.wait(timeout=10)
            after_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
            row = {"project_id": entry["project_id"], "variant": variant, "revision": entry[variant + "_commit"], "wait_returncode": code, "timed_out": timed_out, "wall_seconds": time.perf_counter() - began, "completed_child_cpu_seconds": after_cpu.ru_utime + after_cpu.ru_stime - before_cpu.ru_utime - before_cpu.ru_stime, "stdout_sha256": sha(folder / "STDOUT.txt"), "stderr_sha256": sha(folder / "STDERR.txt"), **parse_junit(folder / "junit.xml")}
            write(folder / "EXIT.json", row)
            pair.append(row)
            stages.append(row)
            print(json.dumps({key: row.get(key) for key in ("project_id", "variant", "wait_returncode", "tests", "passed", "failures", "errors", "skipped", "timed_out")}), flush=True)
            checked_snapshot(root, entry["index"], variant)
        prior, fixed = pair
        cases = lambda row: [(case["class"], case["name"]) for case in row.get("cases", [])]
        admitted = prior["wait_returncode"] == 1 and prior.get("failures", 0) > 0 and prior.get("errors", 1) == 0 and fixed["wait_returncode"] == 0 and fixed.get("passed", 0) > 0 and fixed.get("errors", 1) == 0 and prior.get("tests") == fixed.get("tests") and cases(prior) == cases(fixed) and not prior["timed_out"] and not fixed["timed_out"]
        sources.append({"project_id": entry["project_id"], "source_id": entry["source_id"], "original_regression_demonstrated": admitted, "before_failed": prior.get("failures"), "after_passed": fixed.get("passed"), "case_identity_equal": cases(prior) == cases(fixed), "native_children": 2, "authenticated_user_count": 0})
    final_cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta.upstream-native-regression-replay.v1", "status": "REPLAY_COMPLETE", "source_commit": source_commit, "by_source": sources, "stages": stages, "actual_owned_children": len(stages), "new_admitted_sources": sum(row["original_regression_demonstrated"] for row in sources), "new_model_calls": 0, "new_training_updates": 0, "authenticated_user_count": 0, "source_growth_qualified": False, "owner_wall_seconds": time.perf_counter() - started, "completed_child_cpu_seconds": final_cpu.ru_utime + final_cpu.ru_stime - usage.ru_utime - usage.ru_stime, "full_system_cost_known": False, "pretraining_overlap_known": False, "native_adoption": False}
    write(output / "RESULT.json", result)
    print(json.dumps({key: value for key, value in result.items() if key != "stages"}), flush=True)
    return 0 if all(row["original_regression_demonstrated"] for row in sources) else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("owner", "child"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--index", type=int)
    parser.add_argument("--variant", choices=("before", "after"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if args.mode == "owner":
        code = owner(root, args.output, args.source_commit)
    else:
        plan = json.loads((root / "ACQUISITION_PLAN.json").read_bytes())
        entry = next(row for row in plan["projects"] if row["index"] == args.index)
        code = child(root, entry, args.variant, args.output)
    raise SystemExit(code)
