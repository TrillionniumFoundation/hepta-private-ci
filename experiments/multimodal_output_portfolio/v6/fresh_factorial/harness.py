"""One fresh bounded process chain; no resumes, retries, alternate cohort owners."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import resource
import signal
import subprocess
import sys
import time


PREFIX = "experiments.multimodal_output_portfolio.v6.fresh_factorial."


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
        stream.write("\n")


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def exact_owner(protocol, output):
    owner, actual = Path(protocol["source_owner_directory"]), Path(output)
    if (not owner.is_absolute() or owner.resolve() != owner or not actual.is_absolute()
            or str(actual) != os.path.normpath(str(output)) or actual != owner or actual.resolve() != actual):
        raise ValueError("only the published absolute source owner may run this new cohort")
    return owner


def evidence_bytes(root):
    total = 0
    for directory, names, leaves in os.walk(root, followlinks=False, onerror=lambda e: (_ for _ in ()).throw(e)):
        for name in names + leaves:
            path = Path(directory) / name
            if path.is_symlink():
                raise ValueError("evidence symlink is outside the single-owner resource boundary")
            if path.is_file():
                total += path.stat().st_size
    return total


def child_rss(pid):
    try:
        lines = Path(f"/proc/{pid}/status").read_text().splitlines()
    except FileNotFoundError:
        return 0
    return next((int(line.split()[1]) * 1024 for line in lines if line.startswith("VmRSS:")), 0)


def stop_owned_process(proc):
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            proc.wait(timeout=10)
            return
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)


def interrupt(signum, frame):
    raise InterruptedError("harness received signal " + str(signum))


def launch(stage, command, cwd, root, environment, deadline, budget):
    started = time.perf_counter_ns()
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    log = root / (stage + ".log")
    failure, returncode, proc = None, None, None
    peak_rss, maximum_bytes, last_progress = 0, evidence_bytes(root), time.monotonic()
    try:
        if time.monotonic() >= deadline:
            raise TimeoutError("total fresh compute budget exhausted before stage launch")
        with log.open("xb") as stream:
            proc = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stream, stderr=subprocess.STDOUT,
                                    stdin=subprocess.DEVNULL, start_new_session=True)
            while True:
                peak_rss = max(peak_rss, child_rss(proc.pid))
                maximum_bytes = max(maximum_bytes, evidence_bytes(root))
                if time.monotonic() >= deadline:
                    raise TimeoutError("total 1800-second fresh compute budget exhausted")
                if peak_rss > budget["maximum_child_rss_bytes"]:
                    raise MemoryError("fresh child exceeded registered resident-memory budget")
                if maximum_bytes > budget["maximum_new_evidence_bytes"]:
                    raise OSError("fresh evidence exceeded registered byte budget")
                try:
                    returncode = proc.wait(timeout=min(.5, max(.001, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - last_progress >= 30:
                        print(json.dumps({"stage": stage, "running_seconds": round((time.perf_counter_ns() - started) / 1e9),
                                          "peak_sampled_rss_bytes": peak_rss, "evidence_bytes": maximum_bytes}), flush=True)
                        last_progress = time.monotonic()
            if returncode:
                raise RuntimeError("stage exited with code " + str(returncode))
            if resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024 > budget["maximum_child_rss_bytes"]:
                raise MemoryError("completed child peak exceeded registered memory budget")
            maximum_bytes = max(maximum_bytes, evidence_bytes(root))
            if maximum_bytes > budget["maximum_new_evidence_bytes"]:
                raise OSError("completed stage exceeded registered evidence byte budget")
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error)}
        if proc is not None:
            stop_owned_process(proc)
            returncode = proc.returncode
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"stage": stage, "command": command, "cwd": str(cwd), "returncode": returncode,
        "failure": failure, "wall_ns_including_import_and_exit": time.perf_counter_ns() - started,
        "cpu_ns_including_import_and_exit": round(1e9 * (after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime)),
        "cumulative_completed_child_peak_rss_bytes": after.ru_maxrss * 1024,
        "maximum_sampled_child_rss_bytes": peak_rss, "maximum_sampled_evidence_bytes": maximum_bytes,
        "log_sha256": sha(log) if log.exists() else None, "automatic_retries": 0,
        "resource_guard": "half-second child RSS/evidence polling plus completed-child peak; not a kernel allocation cap",
        "energy_measured": False}
    save(root / (stage + "-process.json"), receipt)
    return receipt


def main(cache, protocol, source_commit, output):
    signal.signal(signal.SIGTERM, interrupt)
    protocol, cache = Path(protocol).resolve(), Path(cache).resolve()
    source_dir = Path(__file__).resolve().parent
    if protocol.parent != source_dir or protocol.name != "protocol.json":
        raise ValueError("execute the published protocol beside its exact source")
    plan = json.loads(protocol.read_bytes())
    budget = plan["resource_budget"]
    if (budget["total_compute_seconds"] != 1800 or budget["maximum_child_rss_bytes"] != 2 << 30
            or budget["maximum_new_evidence_bytes"] != 1 << 30 or budget["threads"] != 2
            or plan["status"] != "frozen_after_exposure_review_requires_publication_before_data"):
        raise ValueError("registered total compute/memory/evidence budget or protocol status differs")
    root = exact_owner(plan, output)
    root.mkdir(parents=True, exist_ok=False)
    cwd = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=source_dir,
               text=True, capture_output=True, check=True, timeout=10).stdout.strip())
    environment = os.environ.copy()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        environment[name] = "2"
    environment.update(PYTHONHASHSEED="0", PYTHONUNBUFFERED="1", PYTHONDONTWRITEBYTECODE="1")
    common = ["--protocol", str(protocol), "--source-commit", source_commit]
    data = root / "data"
    fitted, runs, replay = (root / name for name in ("training", "inference", "replay"))
    commands = [
        ("prepare", "data_prepare", ["--cache", str(cache), "--output", str(data)]),
        ("bootstrap", "models", ["--data", str(data), "--output", str(root / "bootstrap")]),
        ("gates", "gates", ["--data", str(data), "--output", str(fitted)]),
        ("inference", "infer", ["--data", str(data), "--training", str(fitted), "--output", str(runs)]),
        ("replay", "infer", ["--data", str(data), "--training", str(fitted), "--runs", str(runs), "--output", str(replay)]),
        ("evaluate", "evaluate", ["--data", str(data), "--training", str(fitted), "--runs", str(runs),
                                 "--replay", str(replay), "--output", str(root / "evaluation")]),
    ]
    began, deadline = time.perf_counter_ns(), time.monotonic() + budget["total_compute_seconds"]
    save(root / "harness-start.json", {"schema": "hepta.ndu-fresh-factorial.harness.v1", "source_commit": source_commit,
        "protocol_file_sha256": sha(protocol), "executable": sys.executable, "at_utc": datetime.now(timezone.utc).isoformat(),
        "budget": budget, "no_resumes_or_retries": True, "authority": "DENY_ALL"})
    receipts = []
    for name, module, options in commands:
        receipt = launch(name, [sys.executable, "-m", PREFIX + module, *common, *options], cwd, root,
                         environment, deadline, budget)
        receipts.append(receipt)
        print(json.dumps({"stage": name, "returncode": receipt["returncode"], "failure": receipt["failure"]}), flush=True)
        if receipt["failure"]:
            break
    summary = {"schema": "hepta.ndu-fresh-factorial.harness.v1", "stages": receipts,
        "complete": len(receipts) == 6 and all(row["failure"] is None for row in receipts),
        "total_wall_ns": time.perf_counter_ns() - began,
        "total_stage_cpu_ns": sum(row["cpu_ns_including_import_and_exit"] for row in receipts),
        "harness_peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
        "final_cohort_consumed": (data / "final-access-ndu-fresh-factorial.json").exists(),
        "model_generation_sealed": (root / "model-seal.json").exists(), "new_evidence_bytes": evidence_bytes(root),
        "automatic_retries": 0, "all_partial_artifacts_and_failed_costs_preserved": True,
        "cost_scope": "all six stages, fresh observers/bases/gates, inference/replay/scoring and imports; setup separately recorded",
        "not_measured": ["electrical energy", "operator/network setup", "joint process-tree peak RSS"],
        "authority": "DENY_ALL", "production_authority": False}
    save(root / "harness-summary.json", summary)
    print(json.dumps({key: summary[key] for key in ("complete", "final_cohort_consumed", "total_wall_ns")}), flush=True)
    return 0 if summary["complete"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("cache", "protocol", "source-commit", "output"):
        parser.add_argument("--" + name, required=True)
    raise SystemExit(main(**vars(parser.parse_args())))
