"""Execute original upstream regression tests against exact parent and fixed package bytes."""
import argparse, hashlib, importlib, json, os, pathlib, resource, signal, subprocess, sys, time, types
import xml.etree.ElementTree as ET

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def write(path, value):
    with path.open("xb") as f:
        f.write(json.dumps(value, sort_keys=True, indent=2).encode() + b"\n")
        f.flush()
        os.fsync(f.fileno())

def checked_entry(root, project, variant):
    sources = json.loads((root / "SOURCES.json").read_bytes())
    entry = next(row for row in sources["sources"] if row["project_id"] == project)
    folder = root / "repositories" / project.split("/")[-1] / variant
    for item in entry["source_files"]:
        path = folder / item["path"]
        raw = path.read_bytes()
        assert len(raw) == item[variant]["bytes"]
        assert sha(path) == item[variant]["sha256"]
        assert hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest() == item[variant]["git_blob_sha1"]
    return entry, folder

def child(root, project, variant, output):
    entry, folder = checked_entry(root, project, variant)
    sys.path.insert(0, str(folder / entry["package_import_root"]))
    revision = entry[variant + "_commit"]
    generated = {}
    if project == "tox-dev/platformdirs":
        mod = types.ModuleType("platformdirs.version")
        mod.__version__ = "0+source." + revision[:12]
        mod.__version_tuple__ = (0, 0, 0)
        sys.modules[mod.__name__] = mod
        generated[mod.__name__] = {"__version__": mod.__version__, "__version_tuple__": [0, 0, 0]}
    if project == "python-humanize/humanize":
        mod = types.ModuleType("humanize._version")
        mod.__version__ = "0+source." + revision[:12]
        sys.modules[mod.__name__] = mod
        generated[mod.__name__] = {"__version__": mod.__version__}
    package = {"python-attrs/attrs": "attr", "Textualize/rich": "rich",
               "tox-dev/platformdirs": "platformdirs", "python-humanize/humanize": "humanize"}[project]
    imported = importlib.import_module(package)
    assert pathlib.Path(imported.__file__).resolve().is_relative_to(folder)
    import pytest
    test = root / "repositories" / project.split("/")[-1] / "after" / entry["selected_tests"]["path"]
    expected = next(row["after"]["sha256"] for row in entry["source_files"] if row["path"] == entry["selected_tests"]["path"])
    assert sha(test) == expected
    args = ["-q", "-c", str(root / "EMPTY.ini"), "--confcutdir", str(test.parent),
            "-p", "no:cacheprovider", "-p", "pytest_timeout", "--timeout=3", "--timeout-method=signal",
            "--tb=short", "--junitxml", str(output / "junit.xml"),
            *[str(test) + "::" + name for name in entry["selected_tests"]["names"]]]
    write(output / "PYTEST_INTENT.json", {"argv": args, "project_id": project, "variant": variant,
        "revision": revision, "original_test_sha256": expected, "original_test_file_unchanged": True,
        "generated_packaging_metadata_only": generated, "tests_outside_selected_functions": False,
        "new_model_calls": 0, "new_training_updates": 0, "started_at_ns": time.time_ns()})
    before = time.perf_counter()
    code = int(pytest.main(args))
    imported_files = {}
    for name, module in list(sys.modules.items()):
        path = getattr(module, "__file__", None)
        if path:
            resolved = pathlib.Path(path).resolve()
            if resolved.is_relative_to(folder):
                imported_files[name] = {"path": str(resolved.relative_to(folder)), "sha256": sha(resolved)}
    write(output / "PYTEST_RETURN.json", {"exit_code": code, "wall_seconds": time.perf_counter() - before,
        "imported_exact_package_files": imported_files, "generated_packaging_metadata_only": generated,
        "full_repository_suite_executed": False})
    return code

def owner(root, output, source_commit):
    before, usage = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
    sources = json.loads((root / "SOURCES.json").read_bytes())
    output.mkdir(exist_ok=False)
    write(output / "FREEZE.json", {"runner_source_commit": source_commit, "runner_sha256": sha(pathlib.Path(__file__)),
        "intent_commit": "04eea36b2ffe52a9e5105d0701880a0dedca9717",
        "sources_sha256": sha(root / "SOURCES.json"), "new_model_calls": 0, "new_training_updates": 0,
        "selected_project_order": [row["project_id"] for row in sources["sources"]],
        "variants": ["before", "after"], "test_file": "unchanged after-fix original upstream tests on both revisions",
        "per_test_timeout_seconds": 3, "child_timeout_seconds": 120, "automatic_retry": False,
        "started_at_ns": time.time_ns()})
    empty = root / "EMPTY.ini"
    if not empty.exists():
        empty.write_text("[pytest]\n")
    assert empty.read_text() == "[pytest]\n"
    rows = []
    for entry in sources["sources"]:
        for variant in ("before", "after"):
            checked_entry(root, entry["project_id"], variant)
            folder = output / (entry["project_id"].split("/")[-1] + "-" + variant)
            folder.mkdir()
            command = [str(root / "venv/bin/python"), "-I", "-B", str(pathlib.Path(__file__)),
                       "child", "--root", str(root), "--project", entry["project_id"],
                       "--variant", variant, "--output", str(folder)]
            then, cpu_before = time.perf_counter(), resource.getrusage(resource.RUSAGE_CHILDREN)
            env = {"PATH": str(root / "venv/bin") + ":/usr/bin:/bin", "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
                   "TZ": "UTC", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1", "PYTHONDONTWRITEBYTECODE": "1",
                   "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1"}
            timed_out = False
            with (folder / "STDOUT.txt").open("xb") as out, (folder / "STDERR.txt").open("xb") as err:
                process = subprocess.Popen(command, cwd=root, env=env, stdout=out, stderr=err, start_new_session=True)
                write(folder / "STARTED.json", {"pid": process.pid, "process_group_id": process.pid,
                    "argv": command, "started_at_ns": time.time_ns()})
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
            row = {"project_id": entry["project_id"], "variant": variant, "revision": entry[variant + "_commit"],
                "wait_returncode": code, "exit_source": "subprocess.Popen.wait", "timed_out": timed_out,
                "wall_seconds": time.perf_counter() - then,
                "completed_child_user_cpu_seconds": after.ru_utime - cpu_before.ru_utime,
                "completed_child_system_cpu_seconds": after.ru_stime - cpu_before.ru_stime,
                "stdout_sha256": sha(folder / "STDOUT.txt"), "stderr_sha256": sha(folder / "STDERR.txt"),
                "new_model_calls": 0, "new_training_updates": 0}
            junit = folder / "junit.xml"
            if junit.exists():
                xml = ET.parse(junit).getroot()
                tests = list(xml.iter("testcase"))
                row["tests"] = len(tests)
                row["failures"] = sum(test.find("failure") is not None for test in tests)
                row["errors"] = sum(test.find("error") is not None for test in tests)
                row["skipped"] = sum(test.find("skipped") is not None for test in tests)
                row["passed"] = row["tests"] - row["failures"] - row["errors"] - row["skipped"]
                row["cases"] = [{"name": test.attrib.get("name"), "class": test.attrib.get("classname"),
                    "failure_type": None if test.find("failure") is None else test.find("failure").attrib.get("message"),
                    "error_type": None if test.find("error") is None else test.find("error").attrib.get("message"),
                    "skipped": test.find("skipped") is not None} for test in tests]
                row["junit_sha256"] = sha(junit)
            write(folder / "EXIT.json", row)
            rows.append(row)
            print(json.dumps({key: row.get(key) for key in
                ("project_id", "variant", "wait_returncode", "timed_out", "tests", "passed", "failures", "errors")}),
                flush=True)
    by_source = []
    for entry in sources["sources"]:
        prior, fixed = [row for row in rows if row["project_id"] == entry["project_id"]]
        admitted = (prior["wait_returncode"] == 1 and prior.get("failures", 0) > 0 and prior.get("errors", 1) == 0
            and fixed["wait_returncode"] == 0 and fixed.get("passed", 0) > 0 and fixed.get("errors", 1) == 0
            and prior.get("tests") == fixed.get("tests") and not prior["timed_out"] and not fixed["timed_out"])
        by_source.append({"source_id": entry["source_id"], "project_id": entry["project_id"],
            "original_regression_demonstrated": admitted,
            "before_failed": prior.get("failures"), "after_passed": fixed.get("passed"),
            "lineage_count": 1, "authenticated_user_count": 0})
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {"schema": "hepta.upstream-native-regression-replay.v1", "status": "REPLAY_COMPLETE",
        "source_commit": source_commit, "sources_sha256": sha(root / "SOURCES.json"),
        "by_source": by_source, "stages": rows,
        "actual_owned_children": len(rows), "full_repository_suite_executed": False,
        "new_model_calls": 0, "new_training_updates": 0, "authenticated_user_count": 0,
        "new_test_human_trajectories": 0, "pretraining_overlap_known": False,
        "owner_wall_seconds": time.perf_counter() - before,
        "completed_child_cpu_seconds": after.ru_utime + after.ru_stime - usage.ru_utime - usage.ru_stime,
        "full_system_cost_known": False, "native_adoption": False,
        "scope": "original selected upstream test functions and complete parameter sets; no synthetic test assertions"}
    write(output / "RESULT.json", result)
    return 0 if all(row["original_regression_demonstrated"] for row in by_source) else 2

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("owner", "child"))
    parser.add_argument("--root", required=True, type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    parser.add_argument("--project")
    parser.add_argument("--variant", choices=("before", "after"))
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    code = (owner(args.root.resolve(strict=True), args.output, args.source_commit) if args.mode == "owner"
            else child(args.root.resolve(strict=True), args.project, args.variant, args.output))
    raise SystemExit(code)
