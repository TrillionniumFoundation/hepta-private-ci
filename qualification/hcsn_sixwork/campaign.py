"""Linux outer coordinator: one namespace/attempt, one phase, cumulative child wall."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

from .integrity import ARMS, SCHEMAS, TASKS, load, sha, validate

REGISTRY = Path("/home/qian-qi/hcsn-confirmatory-registry-v1")
SEEDS = [1907341, 4812467, 8629119]
SUFFIX = "20261121-e29f-independent-01"
PROFILES = {
    "readout": ("run", "hcsn-confirmatory-v1/", 180),
    "joint": ("joint", "hcsn-joint-confirmatory-v1/", 180),
    "architecture": ("architecture_run", "hcsn-architecture-confirmatory-v1/", 180),
    "feature": ("ablation", "hcsn-feature-confirmatory-v1/", 180),
    "boundary": ("boundary_control", "hcsn-boundary-confirmatory-v1/", 90),
}
DEPENDENCIES = ("hcsn_prepared/model.py", "hcsn_scale/model.py", "hcsn_adaptive/batched_flow.py",
                "hcsn_adaptive/finite_control.py", "hcsn_adaptive/impulse_execution.py",
                "hcsn_adaptive/budget.py", "hcsn_training/population_generator.py")


def exclusive(path, value):
    path = Path(path)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def append(path, value):
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def namespace(stage):
    return PROFILES[stage][1] + SUFFIX


def python_identity():
    return {"python": os.path.abspath(sys.executable), "python_realpath": str(Path(sys.executable).resolve())}


def key(stage):
    return hashlib.sha256(namespace(stage).encode()).hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True).stdout.strip()


def source_binding(root, expected):
    root = Path(root).resolve()
    if not re.fullmatch("[0-9a-f]{40}", expected) or git(root, "rev-parse", "HEAD") != expected:
        raise ValueError("formal source requires the exact declared Git HEAD")
    paths = ["qualification/hcsn_confirmatory_v1", "qualification/hcsn_sixwork"]
    paths += ["qualification/" + p for p in DEPENDENCIES]
    for name in ("qualification", *(str(Path(p).parent) for p in paths[2:])):
        init = root / name / "__init__.py"
        if init.is_file():
            paths.append(str(init.relative_to(root)))
    if git(root, "status", "--porcelain=v1", "--untracked-files=all", "--", *paths):
        raise ValueError("tracked or untracked relevant source is dirty")
    files = git(root, "ls-files", "-z", "--", *paths).split("\0")
    files = [p for p in files if p]
    required = ["qualification/hcsn_confirmatory_v1/" + p[0] + ".py" for p in PROFILES.values()]
    required += ["qualification/"+p for p in DEPENDENCIES]
    required += ["qualification/hcsn_sixwork/"+p for p in ("campaign.py", "integrity.py")]
    if not files or any(p not in files for p in required):
        raise ValueError("required coordinator/learning source is not tracked")
    binding = {p: sha(root / p) for p in sorted(files)}
    if any(binding["qualification/hcsn_sixwork/"+p] != sha(Path(__file__).with_name(p))
           for p in ("campaign.py", "integrity.py")):
        raise ValueError("executing coordinator differs from committed coordinator source")
    return binding


def register(plan_path):
    started = time.perf_counter()
    if sys.platform != "linux":
        raise ValueError("formal coordinator requires the declared Linux host")
    plan = load(plan_path)
    if plan["seeds"] != SEEDS or set(plan["stages"]) != set(PROFILES):
        raise ValueError("root predeclares exactly five stages and the three fixed seeds")
    root = Path(plan["source_root"]).resolve()
    binding = source_binding(root, plan["source_git_sha"])
    destinations = []
    for stage, spec in plan["stages"].items():
        if spec["namespace"] != namespace(stage):
            raise ValueError("namespace differs from root's preregistration")
        for name in ("manifest", "attempt"):
            value = Path(spec[name])
            if not value.is_absolute() or value.exists() or value.resolve().is_relative_to(root):
                raise ValueError("fresh absolute artifact paths outside source worktree required")
            destinations.append(value.resolve())
    if len(set(destinations)) != len(destinations) or any(
            a != b and (a.is_relative_to(b) or b.is_relative_to(a)) for a in destinations for b in destinations):
        raise ValueError("manifest/attempt paths overlap")
    REGISTRY.mkdir(parents=True, exist_ok=True)
    for stage, spec in plan["stages"].items():
        record = {"stage": stage, "namespace": namespace(stage), "seeds": SEEDS,
                  "source_root": str(root), "source_git_sha": plan["source_git_sha"], "source_files": binding,
                  "manifest": str(Path(spec["manifest"]).resolve()), "attempt": str(Path(spec["attempt"]).resolve()),
                  **python_identity(), "plan_sha256": sha(plan_path), "registered_at": stamp()}
        exclusive(REGISTRY / (key(stage) + ".json"), record)
        directory = REGISTRY / key(stage)
        directory.mkdir(exist_ok=False)
        Path(record["manifest"]).parent.mkdir(parents=True, exist_ok=True)
        Path(record["attempt"]).parent.mkdir(parents=True, exist_ok=True)
        append(directory / "events.jsonl", {"event": "registered", "time": stamp(), "record_sha256": sha(REGISTRY / (key(stage)+".json"))})
    setup = {"registered": list(PROFILES), "plan_sha256": sha(plan_path),
             "setup_wall_seconds": time.perf_counter()-started, "time": stamp()}
    exclusive(REGISTRY / ("registration-"+sha(plan_path)+".finished.json"), setup)
    print(json.dumps(setup))


def remaining(limit, prior):
    value = limit - prior
    if not 0 < value <= limit:
        raise ValueError("complete fit+final child-process budget is exhausted")
    return value


def admitted_selection(previous, path, supplied):
    if (not supplied or not re.fullmatch("[0-9a-f]{64}", supplied)
            or supplied != previous["validated_selection_sha256"]
            or supplied != previous["validation"]["receipt_sha256"] or supplied != sha(path)):
        raise ValueError("external selection must equal the originally validated fit bytes and current bytes")


def child_process(command, cwd, directory, phase, timeout):
    start = time.perf_counter()
    timed_out, usage = False, None
    parent = os.getpid()
    def guard_parent():
        import ctypes
        if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0:
            raise OSError("could not bind child lifetime to coordinator")
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGKILL)
    with (directory / (phase + ".stdout")).open("xb") as stdout, (directory / (phase + ".stderr")).open("xb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, stdout=stdout, stderr=stderr, start_new_session=True,
                                   preexec_fn=guard_parent if sys.platform == "linux" else None)
        append(directory / "events.jsonl", {"event": "child_spawned", "phase": phase,
                                           "pid": process.pid, "time": stamp()})
        while True:
            if hasattr(os, "wait4"):
                pid, status, measured = os.wait4(process.pid, os.WNOHANG)
                if pid:
                    process.returncode, usage = os.waitstatus_to_exitcode(status), measured
                    break
            elif process.poll() is not None:
                break
            if time.perf_counter()-start >= timeout and not timed_out:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
            time.sleep(.02)
    return {"pid": process.pid, "returncode": process.returncode, "timed_out": timed_out,
            "wall_seconds": time.perf_counter()-start,
            "peak_rss": usage.ru_maxrss if usage is not None else None,
            "peak_rss_unit": "bytes" if sys.platform == "darwin" else "KiB",
            "rss_scope": "wait4 child high-water mark; not a sampled whole-process-tree sum",
            "user_cpu_seconds": usage.ru_utime if usage is not None else None,
            "system_cpu_seconds": usage.ru_stime if usage is not None else None,
            "stdout": str(directory / (phase+".stdout")), "stderr": str(directory / (phase+".stderr"))}


def check_manifest(record, stage):
    cfg = load(record["manifest"])
    methods = cfg.get("architectures", cfg.get("methods"))
    if (cfg["schema"] != SCHEMAS[stage] or cfg["namespace"] != record["namespace"]
            or cfg["seeds"] != SEEDS or methods != list(ARMS[stage])
            or cfg["budget"]["wall_seconds"] != PROFILES[stage][2]
            or (stage != "boundary" and cfg["tasks"] != list(TASKS))):
        raise ValueError("child manifest differs from preregistered stage/seeds/budget")
    if not cfg.get("execution") or not cfg.get("runtime") or not cfg.get("sources"):
        raise ValueError("missing runtime/backend/source binding")
    if any(record["source_files"].get(p) != digest for p, digest in cfg["sources"].items()):
        raise ValueError("learning source hash is outside or differs from registered Git source")
    required = {p for p in record["source_files"]
                if p.startswith("qualification/hcsn_confirmatory_v1/") and Path(p).suffix in (".py", ".md")}
    if not required.issubset(cfg["sources"]):
        raise ValueError("freeze omits registered learning source")
    return cfg


def phase_run(stage, phase, selection_sha):
    setup_start = time.perf_counter()
    registry_path, directory = REGISTRY / (key(stage)+".json"), REGISTRY / key(stage)
    record = load(registry_path)
    registration = load(REGISTRY / ("registration-"+record["plan_sha256"]+".finished.json"))
    if registration["plan_sha256"] != record["plan_sha256"] or set(registration["registered"]) != set(PROFILES):
        raise ValueError("complete five-stage registration required")
    registered = json.loads((directory / "events.jsonl").read_text().splitlines()[0])
    if registered["event"] != "registered" or registered["record_sha256"] != sha(registry_path):
        raise ValueError("immutable registration changed")
    if record["namespace"] != namespace(stage) or record["stage"] != stage:
        raise ValueError("registry namespace/stage mismatch")
    if source_binding(record["source_root"], record["source_git_sha"]) != record["source_files"]:
        raise ValueError("registered source bytes changed")
    if any(record[k] != v for k, v in python_identity().items()):
        raise ValueError("coordinator interpreter changed")
    prior_wall, cfg, frozen = 0., None, None
    if phase != "freeze":
        frozen = load(directory / "frozen.json")
        freeze_end = load(directory / "freeze.finished.json")
        if (freeze_end["status"] != "complete" or sha(record["manifest"]) != frozen["manifest_sha256"]
                or frozen["registry_sha256"] != sha(registry_path) or frozen["attempt"] != record["attempt"]):
            raise ValueError("successful immutable freeze required")
        cfg = check_manifest(record, stage)
    if phase == "final":
        previous = load(directory / "fit.finished.json")
        if (previous["process"]["returncode"] != 0 or previous["process"]["timed_out"]
                or not previous["validation"]["integrity_ok"]):
            raise ValueError("failed/unknown/incomplete fit cannot advance to final")
        admitted_selection(previous, Path(record["attempt"])/"selection.json", selection_sha)
        prior_wall = previous["process"]["wall_seconds"]
    timeout = 90. if phase == "freeze" else remaining(PROFILES[stage][2], prior_wall)
    reservation = {"phase": phase, "time": stamp(), "registry_sha256": sha(registry_path),
                   "manifest_sha256": frozen["manifest_sha256"] if frozen else None,
                   "selection_sha256": selection_sha, "timeout_seconds": timeout}
    exclusive(directory / (phase+".reserved.json"), reservation)
    command = [record["python"], "-m", "qualification.hcsn_confirmatory_v1."+PROFILES[stage][0],
               phase, "--manifest", record["manifest"]]
    if phase == "freeze":
        command += ["--namespace", record["namespace"], "--seeds", *map(str, SEEDS)]
    else:
        command += ["--output", record["attempt"]]
        if phase == "final":
            command += ["--selection-sha256", selection_sha]
    append(directory / "events.jsonl", {"event": "phase_started", "phase": phase, "time": stamp(),
                                       "command": command, "timeout_seconds": timeout})
    process, validation, status, error = None, None, "failed", None
    try:
        process = child_process(command, record["source_root"], directory, phase, timeout)
        if process["returncode"] != 0 or process["timed_out"]:
            raise ValueError("child failed or timed out; reservation remains consumed")
        if phase != "freeze" and prior_wall + process["wall_seconds"] > PROFILES[stage][2]:
            raise ValueError("complete child-process cumulative wall exceeded stage limit")
        if source_binding(record["source_root"], record["source_git_sha"]) != record["source_files"]:
            raise ValueError("source changed during child execution")
        if phase == "freeze":
            cfg = check_manifest(record, stage)
            exclusive(directory / "frozen.json", {**reservation, "namespace": record["namespace"],
                      "manifest_sha256": sha(record["manifest"]), "attempt": record["attempt"]})
            status = "complete"
        else:
            validation = validate(record["attempt"], cfg, stage, phase, frozen["manifest_sha256"], selection_sha)
            if not validation["integrity_ok"]:
                raise ValueError("receipt grid/cost validation failed")
            status = "complete" if validation["passed"] else "unavailable"
    except Exception as caught:
        error = repr(caught)
    ending = {"phase": phase, "status": status, "error": error, "process": process, "validation": validation,
              "validated_selection_sha256": validation["receipt_sha256"] if phase == "fit" and validation else None,
              "source_git_sha": record["source_git_sha"], "manifest_sha256": sha(record["manifest"]) if Path(record["manifest"]).is_file() else None,
              "cumulative_fit_final_child_wall_seconds": prior_wall + process["wall_seconds"] if process and phase != "freeze" else None,
              "outer_attempt_wall_seconds": time.perf_counter()-setup_start, "time": stamp()}
    exclusive(directory / (phase+".finished.json"), ending)
    append(directory / "events.jsonl", {"event": "phase_finished", **ending})
    print(json.dumps({"stage": stage, "phase": phase, "status": status, "receipt": str(directory/(phase+".finished.json"))}))
    return 0 if status == "complete" else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "freeze", "fit", "final"))
    parser.add_argument("--plan")
    parser.add_argument("--stage", choices=tuple(PROFILES))
    parser.add_argument("--selection-sha256")
    args = parser.parse_args()
    if args.command == "register":
        if not args.plan:
            parser.error("register requires --plan")
        register(args.plan)
        return 0
    if not args.stage:
        parser.error("phase requires --stage")
    return phase_run(args.stage, args.command, args.selection_sha256)


if __name__ == "__main__":
    raise SystemExit(main())

