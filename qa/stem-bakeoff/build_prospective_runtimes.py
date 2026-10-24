"""Build predeclared isolated legacy dependencies; never execute benchmark tests."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import signal
import subprocess
import time

from operational_cohort_plan import canonical
from prospective_runtime_plan import sha


def command(args, directory, name, timeout=600):
    """Preserve stdout/stderr and actual disjoint child CPU for each attempt."""
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    started, parent_cpu = time.perf_counter_ns(), time.process_time_ns()
    with (directory / (name + ".log")).open("wb") as stream:
        child = subprocess.Popen(args, stdout=stream, stderr=subprocess.STDOUT,
                                 cwd=directory, start_new_session=True)
        timed_out = False
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(child.pid, signal.SIGKILL)
            code = child.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    report = {"args": list(map(str, args)), "cwd": str(directory), "exit_code": code,
        "timed_out": timed_out, "wall_ns": time.perf_counter_ns() - started,
        "parent_cpu_ns": time.process_time_ns() - parent_cpu,
        "child_user_cpu_ns": round((after.ru_utime - before.ru_utime) * 1e9),
        "child_system_cpu_ns": round((after.ru_stime - before.ru_stime) * 1e9),
        "log_sha256": sha(directory / (name + ".log")),
        "timing_scope": "Process launch through reaped exit and closed output; excludes receipt serialization."}
    (directory / (name + ".command.json")).write_bytes(canonical(report))
    return report


def inventory(root):
    return [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
        for p in sorted(root.rglob("*")) if p.is_file()
        and "__pycache__" not in p.parts]


def verify_pins(pins):
    for path, expected in pins.items():
        if sha(path) != expected:
            raise ValueError("pinned input changed: " + path)


def build(plan_path, output, only=None, uv=None):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    plan_path, output = Path(plan_path).resolve(), Path(output).resolve()
    plan_raw = plan_path.read_bytes()
    plan, plan_sha = json.loads(plan_raw), hashlib.sha256(plan_raw).hexdigest()
    verify_pins(plan["file_pins"])
    if sha(plan["interpreter"]) != plan["interpreter_sha256"]:
        raise ValueError("shared interpreter executable changed")
    output.mkdir(parents=True, exist_ok=True)
    pins = dict(plan["file_pins"], **{str(plan_path): plan_sha})
    pins[str(Path(__file__).resolve())] = sha(__file__)
    uv = str(Path(uv or shutil.which("uv")).resolve())
    pins[uv] = sha(uv)
    profiles, inventories, failures = {}, {}, {}
    for name, profile in plan["profiles"].items():
        if only and not name.startswith(only):
            continue
        root, receipts = output / "environments" / name, output / "receipts" / name
        receipts.mkdir(parents=True, exist_ok=True)
        complete = receipts / "complete.json"
        if complete.exists():
            previous = json.loads(complete.read_bytes())
            if previous["plan_sha256"] != plan_sha or sha(receipts / "inventory.json") != previous["inventory_sha256"]:
                raise ValueError("completed runtime plan/inventory binding changed")
            records = json.loads((receipts / "inventory.json").read_bytes())
            if inventory(root) != records:
                raise ValueError("completed immutable runtime changed")
        else:
            if root.exists():
                failures[name] = "Prior incomplete environment retained; use a new output root for another attempt."
                continue
            if shutil.disk_usage(output).free < plan["builder_policy"]["minimum_free_disk_bytes"]:
                raise OSError("reserved free disk would be exhausted before profile construction")
            root.parent.mkdir(parents=True, exist_ok=True)
            steps = []
            steps.append(command([plan["interpreter"], "-m", "venv", "--without-pip", str(root)], receipts, "01-venv"))
            python = str(root / "bin/python")
            common = ["--python", python, "--no-build-isolation", "--default-index", "https://pypi.org/simple",
                      "--cache-dir", str(output / "uv-cache"), "--no-python-downloads"]
            common.extend(profile.get("build_settings", []))
            bootstrap = [uv, "pip", "install", "--link-mode", "hardlink"] + common
            if steps[-1]["exit_code"] == 0:
                steps.append(command(bootstrap + plan["bootstrap"], receipts, "02-bootstrap"))
            requirements = receipts / "direct-requirements.txt"
            requirements.write_text("\n".join(profile["requirements"]) + "\n")
            if steps[-1]["exit_code"] == 0:
                resolve = [uv, "pip", "compile"] + common + ["--generate-hashes", "--output-file",
                    str(receipts / "resolved-requirements.txt"), str(requirements)]
                steps.append(command(resolve, receipts, "03-resolve"))
            if steps[-1]["exit_code"] == 0:
                install = [uv, "pip", "install"] + common + ["--link-mode", "hardlink", "--require-hashes",
                    "-r", str(receipts / "resolved-requirements.txt")]
                steps.append(command(install, receipts, "04-install"))
            if steps[-1]["exit_code"] == 0:
                smoke = "import importlib,json; names=" + repr(profile["smoke_imports"]) + "; print(json.dumps({n: str(getattr(importlib.import_module(n),'__file__',None)) for n in names},sort_keys=True))"
                steps.append(command([python, "-I", "-B", "-c", smoke], receipts, "05-import-smoke", 60))
            if steps[-1]["exit_code"] == 0:
                steps.append(command([python, "-m", "pip", "check"], receipts, "06-pip-check", 60))
            if steps[-1]["exit_code"] == 0:
                steps.append(command([python, "-m", "pip", "freeze", "--all"], receipts, "07-freeze", 60))
            passed = steps[-1]["exit_code"] == 0 and len(steps) == 7
            if passed:
                freeze = (receipts / "07-freeze.log").read_text()
                installed = {line.split("==", 1)[0].lower().replace("_", "-") for line in freeze.splitlines()}
                if installed.intersection(plan["builder_policy"]["target_packages_forbidden"]):
                    raise ValueError("installed target package would shadow checkout")
                (receipts / "resolved-lock.txt").write_text(freeze)
                (receipts / "inventory.json").write_bytes(canonical(inventory(root)))
                verify_pins(pins)
                complete.write_bytes(canonical({"plan_sha256": plan_sha, "profile": name,
                    "inventory_sha256": sha(receipts / "inventory.json"), "resolved_lock_sha256": sha(receipts / "resolved-lock.txt"),
                    "direct_requirements_sha256": sha(requirements), "commands": len(steps),
                    "benchmark_commands_run": 0, "same_runtime_both_revisions": True,
                    "wall_ns": sum(r["wall_ns"] for r in steps),
                    "child_cpu_ns": sum(r["child_user_cpu_ns"] + r["child_system_cpu_ns"] for r in steps),
                    "parent_cpu_ns": sum(r["parent_cpu_ns"] for r in steps),
                    "scope": "Sum of seven disjoint install/import/freeze subprocess observations; file inventory work is outside these observations."}))
            else:
                failures[name] = {"last_step": steps[-1], "attempt_preserved": str(receipts)}
                (receipts / "failed-attempt.json").write_bytes(canonical(failures[name]))
            print(json.dumps({"profile": name, "completed": passed, "free_disk_bytes": shutil.disk_usage(output).free}), flush=True)
        if complete.exists():
            profiles[name] = {"python": str(root / "bin/python"), "python_sha256": sha(root / "bin/python"),
                "plain_pytest": profile["plain_pytest"], "source_paths": profile["source_paths"]}
            inventories[name] = {"root": str(root), "manifest": str(receipts / "inventory.json"),
                                 "sha256": sha(receipts / "inventory.json")}
            for filename in ("complete.json", "resolved-lock.txt", "resolved-requirements.txt", "direct-requirements.txt", "inventory.json"):
                pins[str(receipts / filename)] = sha(receipts / filename)
    result = {"schema": "hepta.prospective-runtime-config.v1", "profiles": profiles,
        "group_profiles": {k: v for k, v in plan["group_profiles"].items() if v in profiles},
        "inventories": inventories, "file_pins": pins, "failures": failures,
        "shared_base_inventory_required": str(Path(plan["interpreter"]).parent.parent),
        "benchmark_commands_run": 0, "all_profiles_completed": not failures and len(profiles) == len(plan["profiles"]),
        "acquisition_transport": "uv with public PyPI, immutable shared hardlink cache, hash-required resolved packages; pip remains installed only for local check/freeze.",
        "inclusive_builder_wall_ns": time.perf_counter_ns() - started,
        "inclusive_builder_parent_cpu_ns": time.process_time_ns() - cpu,
        "scope": "Builder startup after imports through final inventory/pin checks; child installation CPU is separately retained per attempt. Excludes final config write."}
    verify_pins(pins)
    target = output / ("runtime-config-" + only + ".json" if only else "runtime-config.json")
    if target.exists():
        raise FileExistsError(target)
    target.write_bytes(canonical(result))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--only")
    parser.add_argument("--uv")
    args = parser.parse_args()
    report = build(args.plan, args.output, args.only, args.uv)
    print(json.dumps({"completed": len(report["profiles"]), "failed": len(report["failures"])}))
