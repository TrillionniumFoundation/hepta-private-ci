"""Replay unchanged B3 upstream tests against exact original parent/fix bytes."""

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


SOURCES_SHA256 = "38575e04211a2e4fc888456f4501de780e9acdb5f92f2f41fca42f66c6af219a"
SELECTION_SHA256 = "8bb2d80098639a649a1498d8190c800947f2ed287caf4ec44964c5b2ab03fb10"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    raw = value if isinstance(value, bytes) else (
        json.dumps(value, sort_keys=True, indent=2, allow_nan=False).encode() + b"\n"
    )
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def sources(root):
    if sha(root / "SOURCES.json") != SOURCES_SHA256:
        raise ValueError("acquired upstream inventory changed")
    if sha(root / "SOURCE_SELECTION.json") != SELECTION_SHA256:
        raise ValueError("prospective task/test selection changed")
    return json.loads((root / "SOURCES.json").read_bytes())


def verify_file(path, expected):
    raw = path.read_bytes()
    if len(raw) != expected["bytes"]:
        raise ValueError("original input size changed: " + str(path))
    if hashlib.sha256(raw).hexdigest() != expected["sha256"]:
        raise ValueError("original input SHA256 changed: " + str(path))
    if hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() != expected["git_blob_sha1"]:
        raise ValueError("original Git blob changed: " + str(path))


def check_material(root, entry):
    folder = root / "repositories" / entry["project_id"].split("/")[-1]
    for item in entry["source_files"]:
        for variant in ("before", "after"):
            verify_file(folder / variant / item["path"], item[variant])
    return folder


def make_case(root, entry, variant, folder):
    original = check_material(root, entry)
    case = folder / "case"
    case.mkdir()
    manifest = []
    test_path = entry["selected_tests"]["path"]
    for item in entry["source_files"]:
        actual_variant = "after" if item["path"] == test_path else variant
        expected = item[actual_variant]
        raw = (original / actual_variant / item["path"]).read_bytes()
        path = case / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        write(path, raw)
        os.chmod(path, int(item["mode"][-3:], 8))
        manifest.append({
            "path": item["path"], "original_variant": actual_variant,
            "original_commit": entry[actual_variant + "_commit"],
            "mode": item["mode"], **expected,
        })
    write(folder / "CASE_MANIFEST.json", manifest)
    return case


def check_case(case, manifest):
    expected_paths = {item["path"] for item in manifest}
    actual_paths = {
        str(path.relative_to(case)) for path in case.rglob("*") if path.is_file()
    }
    if actual_paths != expected_paths:
        raise ValueError("test case contains changed or unexpected regular files")
    for item in manifest:
        path = case / item["path"]
        if path.is_symlink():
            raise ValueError("test case input became a symlink")
        verify_file(path, item)
        if (path.stat().st_mode & 0o777) != int(item["mode"][-3:], 8):
            raise ValueError("test case input mode changed")


def child(args):
    material = sources(args.root)
    entry = next(row for row in material["sources"] if row["project_id"] == args.project)
    manifest = json.loads((args.output / "CASE_MANIFEST.json").read_bytes())
    case = args.output / "case"
    check_case(case, manifest)
    check_material(args.root, entry)
    for relative in reversed([entry["package_import_root"], *entry["extra_import_roots"]]):
        sys.path.insert(0, str(case / relative))
    package = importlib.import_module(entry["package_name"])
    if not Path(package.__file__).resolve().is_relative_to(case):
        raise ValueError("import did not resolve to the selected original package")
    import pytest

    test = case / entry["selected_tests"]["path"]
    test_expected = next(item["after"] for item in entry["source_files"]
                         if item["path"] == entry["selected_tests"]["path"])
    verify_file(test, test_expected)
    argv = [
        "-q", "-c", str(args.output.parent / "EMPTY.ini"),
        "--confcutdir", str(test.parent), "-p", "no:cacheprovider",
        "-p", "pytest_timeout", "--timeout=3", "--timeout-method=signal",
        "--tb=short", "--junitxml", str(args.output / "junit.xml"),
        *[str(test) + "::" + name for name in entry["selected_tests"]["names"]],
    ]
    write(args.output / "PYTEST_INTENT.json", {
        "project_id": args.project, "variant": args.variant,
        "original_package_commit": entry[args.variant + "_commit"],
        "original_test_commit": entry["after_commit"], "argv": argv,
        "original_test_sha256": test_expected["sha256"],
        "original_test_file_unchanged": True, "generated_behavior": False,
        "extra_original_import_roots": entry["extra_import_roots"],
        "python_version": platform.python_version(), "python_executable": sys.executable,
        "python_executable_sha256": sha(Path(sys.executable).resolve()),
        "pytest_version": pytest.__version__,
        "new_model_calls": 0, "new_training_updates": 0,
        "started_at_ns": time.time_ns(),
    })
    before = time.perf_counter()
    code = int(pytest.main(argv))
    elapsed = time.perf_counter() - before
    check_case(case, manifest)
    check_material(args.root, entry)
    imported = {}
    for name, module in list(sys.modules.items()):
        value = getattr(module, "__file__", None)
        if value:
            path = Path(value).resolve()
            if path.is_relative_to(case):
                imported[name] = {
                    "path": str(path.relative_to(case)), "sha256": sha(path)
                }
    write(args.output / "PYTEST_RETURN.json", {
        "exit_code": code, "wall_seconds": elapsed,
        "imported_exact_package_files": imported,
        "case_files_unchanged": True, "original_material_unchanged": True,
        "full_repository_suite_executed": False,
        "optional_semver_native_parser_loaded": any(
            name.startswith("fast_semver") for name in sys.modules
        ),
    })
    return code


def junit(path):
    cases = list(ET.parse(path).getroot().iter("testcase"))
    result = {
        "tests": len(cases),
        "failures": sum(case.find("failure") is not None for case in cases),
        "errors": sum(case.find("error") is not None for case in cases),
        "skipped": sum(case.find("skipped") is not None for case in cases),
        "cases": [],
        "junit_sha256": sha(path),
    }
    result["passed"] = (
        result["tests"] - result["failures"] - result["errors"] - result["skipped"]
    )
    for case in cases:
        failure, error = case.find("failure"), case.find("error")
        result["cases"].append({
            "name": case.get("name"), "class": case.get("classname"),
            "failure": None if failure is None else failure.get("message"),
            "error": None if error is None else error.get("message"),
            "skipped": case.find("skipped") is not None,
        })
    return result


def owner(args):
    started = time.perf_counter()
    cpu = resource.getrusage(resource.RUSAGE_CHILDREN)
    material = sources(args.root)
    args.output.mkdir(exist_ok=False)
    source_sha = sha(Path(__file__))
    write(args.output / "FREEZE.json", {
        "schema": "hepta.b3.original_replay_freeze.v1",
        "source_commit": args.source_commit, "runner_sha256": source_sha,
        "sources_sha256": SOURCES_SHA256, "selection_sha256": SELECTION_SHA256,
        "variants": ["before", "after"], "original_children_planned": 8,
        "projects": [row["project_id"] for row in material["sources"]],
        "per_case_timeout_seconds": 3, "outer_timeout_seconds": 120,
        "same_original_after_tests_on_both_revisions": True,
        "new_model_calls": 0, "new_training_updates": 0,
        "full_repository_suite_executed": False,
        "common_research_runtime_matches_current_A": True,
        "full_upstream_environment_reproduced": False,
        "started_at_ns": time.time_ns(), "automatic_retry": False,
    })
    write(args.output / "EMPTY.ini", b"[pytest]\n")
    rows, eligible, fatal = [], [], None
    try:
        for entry in material["sources"]:
            for variant in ("before", "after"):
                folder = args.output / (entry["project_id"].split("/")[-1] + "-" + variant)
                folder.mkdir()
                make_case(args.root, entry, variant, folder)
                command = [
                    str(args.root / "venv/bin/python"), "-I", "-B",
                    str(Path(__file__).resolve()), "child", "--root", str(args.root),
                    "--output", str(folder), "--project", entry["project_id"],
                    "--variant", variant,
                ]
                env = {
                    "PATH": str(args.root / "venv/bin") + ":/usr/bin:/bin",
                    "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC",
                    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
                    "OPENBLAS_NUM_THREADS": "1",
                }
                tick = time.perf_counter()
                before = resource.getrusage(resource.RUSAGE_CHILDREN)
                timed_out = False
                with (folder / "stdout.txt").open("xb") as out:
                    with (folder / "stderr.txt").open("xb") as err:
                        process = subprocess.Popen(
                            command, cwd=folder, env=env, stdout=out, stderr=err,
                            start_new_session=True,
                        )
                        write(folder / "STARTED.json", {
                            "pid": process.pid, "argv": command,
                            "started_at_ns": time.time_ns(),
                        })
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
                after = resource.getrusage(resource.RUSAGE_CHILDREN)
                row = {
                    "project_id": entry["project_id"], "variant": variant,
                    "original_package_commit": entry[variant + "_commit"],
                    "exit_code": code, "exit_source": "subprocess.Popen.wait",
                    "timed_out": timed_out, "wall_seconds": time.perf_counter() - tick,
                    "child_user_cpu_seconds": after.ru_utime - before.ru_utime,
                    "child_system_cpu_seconds": after.ru_stime - before.ru_stime,
                    "stdout_sha256": sha(folder / "stdout.txt"),
                    "stderr_sha256": sha(folder / "stderr.txt"),
                    "actual_pytest_return_present": (folder / "PYTEST_RETURN.json").is_file(),
                    "junit_present": (folder / "junit.xml").is_file(),
                    "new_model_calls": 0, "new_training_updates": 0,
                }
                if row["junit_present"]:
                    row.update(junit(folder / "junit.xml"))
                if row["actual_pytest_return_present"]:
                    returned = json.loads((folder / "PYTEST_RETURN.json").read_bytes())
                    row["case_files_unchanged"] = returned["case_files_unchanged"]
                    row["original_material_unchanged"] = returned["original_material_unchanged"]
                write(folder / "EXIT.json", row)
                rows.append(row)
                print(json.dumps({
                    key: row.get(key) for key in (
                        "project_id", "variant", "exit_code", "tests",
                        "passed", "failures", "errors", "timed_out"
                    )
                }, sort_keys=True), flush=True)
        for entry in material["sources"]:
            prior, fixed = [row for row in rows if row["project_id"] == entry["project_id"]]
            admitted = (
                prior["exit_code"] == 1 and prior.get("failures", 0) > 0
                and fixed["exit_code"] == 0 and fixed.get("passed", 0) > 0
                and prior.get("tests") == fixed.get("tests")
                and all(
                    row.get("errors", 1) == 0 and row.get("skipped", 1) == 0
                    and not row["timed_out"]
                    and row.get("case_files_unchanged", False)
                    and row.get("original_material_unchanged", False)
                    for row in (prior, fixed)
                )
            )
            eligible.append({
                "source_id": entry["source_id"], "project_id": entry["project_id"],
                "original_regression_demonstrated": admitted,
                "before_failed": prior.get("failures"),
                "after_passed": fixed.get("passed"),
                "test_case_count_per_revision": fixed.get("tests"),
                "lineage_count": 1, "authenticated_user_count": 0,
            })
        if sha(Path(__file__)) != source_sha:
            raise ValueError("frozen replay source changed")
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error)}
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    passed = fatal is None and len(eligible) == 4 and all(
        row["original_regression_demonstrated"] for row in eligible
    )
    result = {
        "schema": "hepta.b3.original_replay.v1", "passed": passed,
        "source_commit": args.source_commit, "runner_sha256": source_sha,
        "sources_sha256": SOURCES_SHA256, "selection_sha256": SELECTION_SHA256,
        "by_source": eligible, "stages": rows, "fatal_error": fatal,
        "actual_owned_children": len(rows), "new_model_calls": 0,
        "new_training_updates": 0, "authenticated_user_count": 0,
        "full_repository_suite_executed": False,
        "full_upstream_environment_reproduced": False,
        "independent_controller_authenticated": False,
        "pretraining_overlap_known": False, "native_adoption": False,
        "owner_wall_seconds": time.perf_counter() - started,
        "completed_child_cpu_seconds": (
            after.ru_utime + after.ru_stime - cpu.ru_utime - cpu.ru_stime
        ),
        "nested_windows_are_not_additive": True,
        "gpu_energy_joules": None, "network_energy_joules": None,
        "monetary_cost": None, "full_system_cost_known": False,
        "finished_at_ns": time.time_ns(),
    }
    write(args.output / "RESULT.json", result)
    return 0 if passed else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("owner", "child"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--source-commit")
    parser.add_argument("--project")
    parser.add_argument("--variant", choices=("before", "after"))
    args = parser.parse_args()
    if args.mode == "owner" and not args.source_commit:
        parser.error("owner requires an exact published source commit")
    raise SystemExit(owner(args) if args.mode == "owner" else child(args))
