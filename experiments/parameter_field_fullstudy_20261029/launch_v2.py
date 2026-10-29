"""Process-independent, memory-admitted controller for registered attempt02 jobs."""

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time

from .resource_v2 import StorageBudget, load_registration, memory_admission, memory_profile, pending_growth
from .run_v2 import verify_files

ROOT = Path(__file__).resolve().parents[2]
MODULES = {
    "experiments.parameter_field_fullstudy_20261029.run_v2",
    "experiments.parameter_field_fullstudy_20261029.architecture_run_v2",
    "experiments.parameter_field_fullstudy_20261029.endpoint_v2",
}


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


EXPECTED_IDS = {f"{stage}-{seed}" for stage in ("A", "B", "R") for seed in (17, 29, 43)} | {"C", "W", "A_endpoint", "B_endpoint", "C_endpoint"}


def arguments(argv):
    flags = [item for item in argv[3:] if item.startswith("--")]
    if len(flags) != len(set(flags)):
        raise ValueError("Duplicate worker flags")
    values = {}
    offset = 3
    while offset < len(argv):
        key = argv[offset]
        if not key.startswith("--"):
            raise ValueError("Unexpected positional worker argument")
        if key == "--execute":
            values[key] = True
            offset += 1
        else:
            if offset + 1 >= len(argv) or argv[offset + 1].startswith("--"):
                raise ValueError("Missing worker argument value")
            values[key] = argv[offset + 1]
            offset += 2
    return values


def validate_queue(value, root):
    jobs = value.get("jobs", [])
    identifiers = [job["id"] for job in jobs]
    if not jobs or len(set(identifiers)) != len(identifiers) or not set(identifiers) <= EXPECTED_IDS:
        raise ValueError("Empty, duplicate or unregistered job identifiers")
    if value.get("finalize") and set(identifiers) != EXPECTED_IDS:
        raise ValueError("Finalization requires the full fixed fourteen-job grid")
    for job in jobs:
        name, argv = job["id"], job["argv"]
        if (not isinstance(argv, list) or not 3 <= len(argv) <= 64
                or argv[:2] != ["-B", "-m"] or argv[2] not in MODULES
                or not all(isinstance(item, str) and "\x00" not in item for item in argv)):
            raise ValueError("Unregistered controller job form")
        flags = arguments(argv)
        phase, seed = job["phase"], job.get("seed")
        module = argv[2].rsplit(".", 1)[-1]
        if module == "run_v2":
            if phase not in ("A", "B", "R", "W") or flags.get("--phase") != phase:
                raise ValueError("Wrong legacy phase")
            expected_id = "W" if phase == "W" else f"{phase}-{seed}"
            if (phase == "W" and (seed is not None or "--seed" in flags)
                    or phase != "W" and (seed not in (17, 29, 43) or flags.get("--seed") != str(seed))):
                raise ValueError("Wrong legacy seed")
            expected_group = "training" if phase in ("A", "B") else "reconstruction" if phase == "R" else "singleton"
            expected_complete = "operations/W-all.COMPLETE.json" if phase == "W" else f"operations/{phase}-seed-{seed}.COMPLETE.json"
        elif module == "architecture_run_v2":
            if phase != "C" or seed is not None:
                raise ValueError("Wrong architecture training grid")
            expected_id, expected_group, expected_complete = "C", "training", "operations/C-all.COMPLETE.json"
        else:
            if phase not in ("A", "B", "C") or flags.get("--phase") != phase or seed is not None:
                raise ValueError("Wrong endpoint grid")
            expected_id, expected_group = phase + "_endpoint", "singleton"
            expected_complete = f"stage_{phase}/" + ("endpoint_evaluation" if phase == "C" else "endpoints") + "/ENDPOINTS.json"
        if name != expected_id or job["group"] != expected_group or job["completion"] != expected_complete:
            raise ValueError("Job identity, group or completion path differs from its fixed phase")
        frozen_sha = job.get("freeze_sha256", "")
        if len(frozen_sha) != 64 or any(c not in "0123456789abcdef" for c in frozen_sha):
            raise ValueError("Invalid expected source-freeze hash")
        if ("--root" not in flags or Path(flags["--root"]).resolve() != root
                or "--freeze" not in flags or not flags.get("--execute")):
            raise ValueError("Worker root, freeze or explicit execution differs")
        if not set(job.get("requires", [])) <= set(identifiers):
            raise ValueError("Unknown dependency")
    visiting, visited = set(), set()
    mapping = {job["id"]: job for job in jobs}
    def visit(name):
        if name in visiting:
            raise ValueError("Cyclic dependency")
        if name in visited:
            return
        visiting.add(name)
        for dependency in mapping[name].get("requires", []):
            visit(dependency)
        visiting.remove(name)
        visited.add(name)
    for name in identifiers:
        visit(name)
    return jobs


def verify_job(job, registration):
    flags = arguments(job["argv"])
    if (flags.get("--amendment-sha256") != registration["_sha256"]
            or digest(flags["--amendment"]) != registration["_sha256"]
            or digest(flags["--freeze"]) != job["freeze_sha256"]):
        raise ValueError("Job source/profile identity differs")
    freeze = json.loads(Path(flags["--freeze"]).read_text())
    if (job["phase"] not in freeze["allowed_phases"] or freeze.get("attempt_id") != "attempt02"
            or freeze.get("operational_amendment_sha256") != registration["_sha256"]):
        raise ValueError("Worker phase/attempt is not registered")
    verify_files(freeze, ROOT)
    protocol = flags.get("--protocolR") if job["phase"] == "R" else flags.get("--protocol", str(Path(__file__).with_name("PROTOCOL.json")))
    if not protocol or digest(protocol) != freeze["protocol_sha256"]:
        raise ValueError("Job protocol differs")


def completion_matches(job, seal, registration):
    provenance = seal.get("operations", seal)
    return (seal.get("complete") is True and seal.get("phase") == job["phase"]
            and seal.get("source_freeze_sha256") == job["freeze_sha256"]
            and provenance.get("operational_amendment_sha256") == registration["_sha256"]
            and provenance.get("attempt_id") == "attempt02"
            and (job["id"].endswith("_endpoint") or seal.get("seed") == job.get("seed"))
            and (job["id"].endswith("_endpoint") or seal.get("post_execution_storage_check") is True))


def proc_metrics(pid):
    result = {"rss_bytes": 0, "high_water_bytes": 0}
    try:
        with Path(f"/proc/{pid}/status").open() as stream:
            for line in stream:
                if line.startswith("VmRSS:"):
                    result["rss_bytes"] = int(line.split()[1]) * 1024
                elif line.startswith("VmHWM:"):
                    result["high_water_bytes"] = int(line.split()[1]) * 1024
    except OSError:
        pass
    return result


def verify_controller(args, registration):
    freeze = json.loads(Path(args.freeze).read_text())
    if ("OPS" not in freeze["allowed_phases"] or freeze.get("attempt_id") != "attempt02"
            or freeze.get("execution_kind") != "controller"
            or freeze.get("operational_amendment_sha256") != registration["_sha256"]
            or len(freeze["registered_commit"]) != 40
            or any(c not in "0123456789abcdef" for c in freeze["registered_commit"])):
        raise ValueError("Controller is not registered for this attempt/profile")
    verify_files(freeze, ROOT)
    for name in ("launch_v2.py", "resource_v2.py", "run_v2.py"):
        if str(Path(__file__).parent.relative_to(ROOT) / name) not in freeze["source_files"]:
            raise ValueError("Controller dependency missing from source freeze")
    return freeze


def run(args):
    registration = load_registration(args.amendment, args.amendment_sha256)
    freeze = verify_controller(args, registration)
    root = Path(args.root).resolve()
    storage = StorageBudget(root, registration)
    if Path(registration["raw_root"]).resolve() != root:
        raise ValueError("Controller raw root differs")
    state_dir = root / "controller"
    if state_dir.exists() and args.resume_admission:
        receipt = json.loads((state_dir / "ADMISSION_FAILED.json").read_text())
        if (receipt.get("status") != "ADMISSION_BLOCKED" or receipt.get("scientific_workers_started") != 0
                or receipt.get("source_freeze_sha256") != digest(args.freeze)
                or receipt.get("amendment_sha256") != registration["_sha256"]
                or receipt.get("initial_queue_sha256") != digest(args.queue)
                or list(state_dir.glob("*.START.json"))):
            raise ValueError("Only a pure, unchanged pre-science admission wait may be resumed automatically")
        active_path = root / "ACTIVE_WORKERS.json"
        if active_path.exists() and json.loads(active_path.read_text()).get("workers"):
            raise ValueError("A prior worker is still registered")
        index = 1
        while (root / f"controller_admission_{index:03d}").exists():
            index += 1
        with storage.writer_lock():
            state_dir.rename(root / f"controller_admission_{index:03d}")
    state_dir.mkdir(exist_ok=False)
    selector = selectors.DefaultSelector()
    running, results, submitted, accepted = {}, {}, set(), {}
    reservation = registration["concurrency"]["worker_reservation_bytes"]
    margin = registration["concurrency"]["memory_margin_bytes"]
    baseline = memory_profile()
    start = time.monotonic()
    last_status, paused_oom, admission_blocked_since = 0., False, None
    storage.write_json(state_dir / "START.json", {
        "attempt_id": "attempt02", "registered_commit": freeze["registered_commit"],
        "source_freeze_sha256": digest(args.freeze), "amendment_sha256": registration["_sha256"],
        "started_unix": time.time(), "memory_baseline": baseline,
        "max_workers": 2, "private_mount": False, "host_lifetime_durability_claim": False,
        "raw_external_uploads": 0,
    })

    def active_record():
        storage.write_json(root / "ACTIVE_WORKERS.json", {
            "workers": [{"id": name, "pid": item["process"].pid, "reservation_bytes": item["reservation"]}
                        for name, item in running.items()],
            "oom_baseline": {key: baseline[key] for key in ("oom", "oom_kill")},
        }, allow_replace=True)

    active_record()
    while True:
        queue = json.loads(Path(args.queue).read_text())
        jobs = validate_queue(queue, root)
        definitions = {job["id"]: json.dumps(job, sort_keys=True, separators=(",", ":")) for job in jobs}
        if any(name not in definitions or definitions[name] != content for name, content in accepted.items()):
            raise ValueError("An accepted job definition was changed or removed")
        accepted.update(definitions)
        profile = memory_profile()
        if profile["oom"] > baseline["oom"] or profile["oom_kill"] > baseline["oom_kill"]:
            paused_oom = True
        denied_profile = None
        for job in jobs:
            if job["id"] in submitted or paused_oom or len(running) >= 2:
                continue
            dependencies = job.get("requires", [])
            if not all(results.get(name, {}).get("complete") is True for name in dependencies):
                continue
            if running and (job["group"] == "singleton" or any(
                    item["job"]["group"] != job["group"] for item in running.values())):
                continue
            selected_reservation = reservation
            if job["phase"] in ("A", "B", "R") and not job["id"].endswith("_endpoint"):
                peaks = [result["process_peak_rss_bytes"] for name, result in results.items()
                         if name.startswith(("A-", "B-", "R-")) and result.get("complete")
                         and result.get("process_peak_rss_bytes", 0) > 0]
                if peaks:
                    grain = 64 * 1024 ** 2
                    selected_reservation = max(512 * 1024 ** 2, int((1.25 * max(peaks) + grain - 1) // grain) * grain)
            admission = memory_admission(selected_reservation, margin, pending_growth(root))
            if not admission["allowed"]:
                denied_profile = admission
                break
            verify_job(job, registration)
            storage.check()
            log = state_dir / (job["id"] + ".log")
            if log.exists():
                raise ValueError("Refusing to overwrite a prior job log")
            storage.write_bytes(log, b"")
            process = subprocess.Popen([sys.executable, *job["argv"]], cwd=ROOT,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            os.set_blocking(process.stdout.fileno(), False)
            running[job["id"]] = {"process": process, "job": job, "log": log,
                                  "started": time.monotonic(), "last_line": "", "partial_line": b"",
                                  "peak_rss_bytes": 0, "peak_high_water_bytes": 0,
                                  "admission": admission, "reservation": selected_reservation, "stream_closed": False}
            selector.register(process.stdout, selectors.EVENT_READ, job["id"])
            submitted.add(job["id"])
            active_record()
            storage.write_json(state_dir / (job["id"] + ".START.json"), {
                "id": job["id"], "pid": process.pid, "job": job, "admission": admission,
                "started_unix": time.time(), "worker_reservation_bytes": selected_reservation,
            })
            print(json.dumps({"started": job["id"], "pid": process.pid}), flush=True)
        if not running and denied_profile is not None:
            if admission_blocked_since is None:
                admission_blocked_since = time.monotonic()
            if time.monotonic() - admission_blocked_since >= 300:
                storage.write_json(state_dir / "ADMISSION_FAILED.json", {
                    "status": "ADMISSION_BLOCKED", "complete": False, "attempt_id": "attempt02",
                    "scientific_workers_started": len(submitted), "gradient_work_during_admission_wait": 0,
                    "pending": [job["id"] for job in jobs if job["id"] not in submitted],
                    "memory": denied_profile, "admission_wait_seconds": time.monotonic() - admission_blocked_since,
                    "source_freeze_sha256": digest(args.freeze), "amendment_sha256": registration["_sha256"],
                    "scientific_outcome_claim": False, "existing_evidence_preserved": True,
                    "initial_queue_sha256": digest(args.queue),
                }, failure_record=True)
                return 75
        else:
            admission_blocked_since = None
        for key, unused in selector.select(timeout=.2):
            name = key.data
            item = running[name]
            chunk = os.read(key.fileobj.fileno(), 65536)
            if not chunk:
                selector.unregister(key.fileobj)
                key.fileobj.close()
                item["stream_closed"] = True
                continue
            if item["log"].stat().st_size + len(chunk) > 4 * 1024 ** 2:
                raise RuntimeError("Bounded job log exceeded 4 MiB")
            storage.append_bytes(item["log"], chunk)
            lines = (item["partial_line"] + chunk).split(b"\n")
            item["partial_line"] = lines[-1][-65536:]
            if len(lines) > 1:
                item["last_line"] = lines[-2].decode(errors="replace")[-4096:]
        for name, item in list(running.items()):
            metrics = proc_metrics(item["process"].pid)
            item["peak_rss_bytes"] = max(item["peak_rss_bytes"], metrics["rss_bytes"])
            item["peak_high_water_bytes"] = max(item["peak_high_water_bytes"], metrics["high_water_bytes"])
            code = item["process"].poll()
            if code is None or not item["stream_closed"]:
                continue
            completion = root / item["job"]["completion"]
            valid = False
            if code == 0 and completion.is_file():
                seal = json.loads(completion.read_text())
                valid = completion_matches(item["job"], seal, registration)
                item["process_peak_rss_bytes"] = int(seal.get("process_peak_rss_bytes", 0))
                item["peak_high_water_bytes"] = max(item["peak_high_water_bytes"], item["process_peak_rss_bytes"])
            result = {"complete": valid, "exit_code": code,
                      "wall_seconds": time.monotonic() - item["started"],
                      "last_line": item["last_line"], "peak_rss_bytes": item["peak_rss_bytes"],
                      "peak_high_water_bytes": item["peak_high_water_bytes"],
                      "process_peak_rss_bytes": item.get("process_peak_rss_bytes", 0),
                      "completion": None if not valid else {
                          "path": completion.relative_to(root).as_posix(), "sha256": digest(completion),
                          "bytes": completion.stat().st_size},
                      "partial_evidence_preserved": True}
            results[name] = result
            del running[name]
            active_record()
            storage.write_json(state_dir / (name + ".RESULT.json"), result)
            print(json.dumps({"finished": name, **result}), flush=True)
        # An unreachable dependent or OOM-paused job is a recorded non-start, not an endless wait.
        for job in jobs:
            if job["id"] in submitted:
                continue
            failed_dependencies = [name for name in job.get("requires", [])
                                   if name in results and results[name].get("complete") is not True]
            if failed_dependencies or paused_oom:
                result = {"complete": False, "not_started": True, "exit_code": None,
                          "blocked_by": failed_dependencies, "oom_admission_paused": paused_oom,
                          "scheduled_gradient_microsteps": 0, "partial_evidence_preserved": True}
                results[job["id"]] = result
                submitted.add(job["id"])
                storage.write_json(state_dir / (job["id"] + ".RESULT.json"), result)
        if not running and any(result.get("complete") is not True for result in results.values()) and all(
                job["id"] in submitted for job in jobs):
            storage.write_json(state_dir / "EXECUTION_FAILED.json", {
                "complete": False, "jobs": results, "elapsed_seconds": time.monotonic() - start,
                "oom_admission_paused": paused_oom, "partial_evidence_preserved": True,
            }, failure_record=True)
            break
        if time.monotonic() - last_status >= 10:
            status = {"attempt_id": "attempt02", "elapsed_seconds": time.monotonic() - start,
                      "running": {name: {"pid": item["process"].pid, "last_line": item["last_line"],
                                         "peak_rss_bytes": item["peak_rss_bytes"],
                                         "group": item["job"]["group"]} for name, item in running.items()},
                      "pending": [job["id"] for job in jobs if job["id"] not in submitted],
                      "results": results, "memory": memory_profile(), "storage": storage.inventory(),
                      "oom_admission_paused": paused_oom}
            storage.write_json(root / "PROGRESS.json", status, allow_replace=True)
            print(json.dumps(status), flush=True)
            last_status = time.monotonic()
        if queue.get("finalize") and not running and all(job["id"] in results for job in jobs):
            storage.write_json(state_dir / "EXECUTION.json", {
                "complete": all(result["complete"] for result in results.values()),
                "jobs": results, "elapsed_seconds": time.monotonic() - start,
                "source_freeze_sha256": digest(args.freeze), "storage": storage.inventory(),
                "memory": memory_profile(), "oom_admission_paused": paused_oom,
                "raw_external_uploads": 0, "archive_finalized": False,
                "controller_cpu_seconds_total": time.process_time(),
            })
            break
        if time.monotonic() - start > 12 * 3600:
            raise RuntimeError("Registered outer 12 hour execution window exhausted")
        time.sleep(.3)


def main():
    parser = argparse.ArgumentParser()
    for name in ("root", "queue", "freeze", "amendment", "amendment-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--resume-admission", action="store_true")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".ops-controller.lock").open("a+b") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        raise SystemExit(run(args))


if __name__ == "__main__":
    main()
