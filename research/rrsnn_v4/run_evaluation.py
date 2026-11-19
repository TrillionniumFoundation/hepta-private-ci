"""Orchestration only: run the unchanged frozen evaluator after publication.

The publication receipt is evidence from the coordinator's immutable remote
read. This process verifies local bytes against that receipt; it does not claim
to perform an independent network or GitHub verification.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
import argparse
import fcntl
import gzip
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

from .aggregate import DATASETS, LATENT_REPLAYS, TRAINING_SEEDS, freeze_selection, selected_checkpoints
from .prepare_data import DATA_SPEC, sha, validate_freeze
from .train import atomic_json, check_disk, memory_snapshot, verify_protocol


ROOT = Path(__file__).resolve().parent
CPUS = (0, 1)


def validate_publication_receipt(selection_path, receipt_path):
    receipt = json.loads(Path(receipt_path).read_text())
    required = ("repository", "commit_sha", "repository_path", "selection_sha256",
                "git_blob_sha", "remote_bytes_verified", "recorded_at_utc")
    if any(key not in receipt for key in required):
        raise ValueError("Incomplete remote publication receipt")
    content = Path(selection_path).read_bytes()
    git_blob = hashlib.sha1(f"blob {len(content)}\0".encode()+content).hexdigest()
    if (receipt["remote_bytes_verified"] is not True
            or receipt["selection_sha256"] != hashlib.sha256(content).hexdigest()
            or receipt["git_blob_sha"] != git_blob
            or not re.fullmatch(r"[0-9a-f]{40}", receipt["commit_sha"])
            or not receipt["repository"] or not receipt["repository_path"]):
        raise ValueError("Selection bytes do not match the root-verified publication receipt")
    recorded = datetime.fromisoformat(receipt["recorded_at_utc"].replace("Z", "+00:00"))
    if recorded.tzinfo is None:
        raise ValueError("Publication receipt time must include its time zone")
    return {**receipt, "publication_receipt_sha256": sha(receipt_path),
            "verification_scope": "Coordinator verified immutable remote bytes; this runner verifies local SHA256 and Git blob SHA1 against the signed-off receipt, without network access."}


def validated_selection(freeze_path, selection_path, receipt_path):
    publication = validate_publication_receipt(selection_path, receipt_path)
    before_data = validate_freeze(freeze_path)
    for name, expected in before_data["source_sha256"].items():
        if sha(ROOT/name) != expected:
            raise ValueError(f"Pre-data frozen source changed: {name}")
    training, training_hash = verify_protocol()
    for key in ("variants", "seeds", "cpu_matched_variants"):
        if training[key] != before_data[key]:
            raise ValueError("Training matrix differs from the source/public protocol")
    if training["seeds"] != list(TRAINING_SEEDS):
        raise ValueError("Training seeds differ from the fixed evaluation allocation")
    selection = freeze_selection(freeze_path, selection_path)
    checkpoints = selected_checkpoints(selection)
    names = set(training["variants"]+list(training["cpu_matched_variants"]))
    if set(checkpoints) != names:
        raise ValueError("Published checkpoint selection is not the complete protocol matrix")
    manifest = json.loads((ROOT/"data"/"manifest.json").read_text())
    if manifest["protocol_sha256"] != sha(freeze_path):
        raise ValueError("Data provenance is not bound to the published pre-data freeze")
    identity = {"pre_data_protocol_sha256": sha(freeze_path),
                "training_protocol_sha256": training_hash, "selection_sha256": sha(selection_path),
                "runner_sha256": sha(__file__), "publication": publication,
                "evaluator_sha256": before_data["source_sha256"]["evaluate.py"],
                "data_manifest_sha256": sha(ROOT/"data"/"manifest.json")}
    return selection, checkpoints, manifest, identity


def verify_outputs(checkpoint, freeze_path, selection_path, manifest, require_complete):
    """Inspect every existing artifact before letting the frozen evaluator resume."""
    receipt = json.loads(checkpoint.with_name("training.json").read_text())
    completed, missing = [], []
    for dataset in DATASETS:
        for replay in range(LATENT_REPLAYS):
            path = checkpoint.parent/f"evaluation_{dataset}_rep{replay}.json.gz"
            if not path.exists():
                missing.append(str(path.relative_to(ROOT)))
                continue
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            expected = {"variant": receipt["variant"], "model_variant": receipt["model_variant"],
                "training_seed": receipt["seed"], "checkpoint_sha256": sha(checkpoint),
                "protocol_sha256": sha(freeze_path),
                "training_protocol_sha256": receipt["protocol_sha256"],
                "selection_sha256": sha(selection_path), "evaluator_sha256": sha(ROOT/"evaluate.py"),
                "task_sha256": sha(ROOT/"task.py"), "data_manifest_sha256": sha(ROOT/"data"/"manifest.json"),
                "source_files": next(row["files"] for row in manifest["splits"] if row["name"] == dataset),
                "dataset": dataset, "latent_replay": replay,
                "primary_comparator": "ctrnn_state_cpu", "real_future_window": False}
            if payload["identity"] != expected:
                raise ValueError(f"Existing evaluation has different identity: {path}")
            evaluation = payload["evaluation"]
            if (evaluation.get("all_resource_invariants_passed") is not True
                    or evaluation.get("episodes") != DATA_SPEC[dataset]["episodes"]
                    or len(evaluation["rows"]) != DATA_SPEC[dataset]["episodes"]
                    or evaluation.get("query_draws_per_scenario") != 4
                    or (dataset == "paired" and evaluation.get("paired_initial_state_equal") is not True)):
                raise ValueError(f"Existing evaluation is incomplete or violates a declared invariant: {path}")
            completed.append({"path": str(path.relative_to(ROOT)), "sha256": sha(path)})
    if require_complete and missing:
        raise RuntimeError(f"Completed child omitted {len(missing)} expected evaluation files")
    return completed, missing


def check_cpus():
    allowed = os.sched_getaffinity(0)
    if any(cpu not in allowed for cpu in CPUS):
        raise RuntimeError(f"Frozen worker CPUs {CPUS} are outside allowed affinity {sorted(allowed)}")
    return list(CPUS)


def run_matrix(freeze_path, selection_path, publication_receipt):
    cpus = check_cpus()
    selection, checkpoints, manifest, identity = validated_selection(freeze_path, selection_path, publication_receipt)
    initial_resources, begin = memory_snapshot(), time.perf_counter()
    check_disk()
    destination = ROOT/"results"
    destination.mkdir(exist_ok=True)
    lock = (destination/"evaluation_matrix.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError("Another evaluation orchestrator holds the matrix lock") from None
    jobs = [(name, seed, path) for name, seeds in sorted(checkpoints.items()) for seed, path in sorted(seeds.items())]
    free = Queue()
    for cpu in cpus:
        free.put(cpu)
    stopped, child_lock = threading.Event(), threading.Lock()
    children = set()
    completed, failed, not_started = [], [], []
    started = datetime.now(timezone.utc).isoformat()

    def execute(job):
        name, seed, checkpoint = job
        if stopped.is_set():
            return {"status": "not_started", "variant": name, "seed": seed}
        cpu = free.get()
        try:
            check_disk()
            previous, missing = verify_outputs(checkpoint, freeze_path, selection_path, manifest, False)
            start = time.perf_counter()
            if missing:
                environment = os.environ.copy()
                environment.update(OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
                command = ["taskset", "-c", str(cpu), sys.executable, "-m", "rrsnn_v4.evaluate",
                           "--checkpoint", str(checkpoint), "--freeze", str(Path(freeze_path).resolve()),
                           "--selection", str(Path(selection_path).resolve())]
                with checkpoint.with_name("evaluation.log").open("a") as log:
                    child = subprocess.Popen(command, cwd=ROOT.parent, env=environment,
                                             stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    with child_lock:
                        children.add(child)
                    try:
                        code = child.wait()
                    finally:
                        with child_lock:
                            children.discard(child)
                if code:
                    raise RuntimeError(f"Evaluation child exited {code}; see {checkpoint.with_name('evaluation.log')}")
            outputs, _ = verify_outputs(checkpoint, freeze_path, selection_path, manifest, True)
            check_disk()
            return {"status": "completed", "variant": name, "seed": seed, "cpu": cpu,
                    "checkpoint_sha256": sha(checkpoint), "resumed_verified_outputs": len(previous),
                    "new_outputs": len(missing), "elapsed_seconds": time.perf_counter()-start,
                    "outputs": outputs}
        except Exception as error:
            stopped.set()
            return {"status": "failed", "variant": name, "seed": seed,
                    "cpu": cpu, "error": str(error), "partial_files_preserved": True}
        finally:
            free.put(cpu)

    pool = ThreadPoolExecutor(max_workers=len(cpus))
    futures = []
    interrupted = None
    try:
        futures = [pool.submit(execute, job) for job in jobs]
        for future in as_completed(futures):
            record = future.result()
            {"completed": completed, "failed": failed, "not_started": not_started}[record["status"]].append(record)
            print(json.dumps({key: value for key, value in record.items() if key != "outputs"}), flush=True)
            atomic_json(destination/"evaluation_matrix_progress.json", {
                "identity": identity, "expected_jobs": len(jobs), "completed": completed,
                "failed": failed, "not_started": not_started, "elapsed_seconds": time.perf_counter()-begin})
        validated_selection(freeze_path, selection_path, publication_receipt)
    except BaseException as error:
        interrupted = f"{type(error).__name__}: {error}"
        stopped.set()
        for future in futures:
            future.cancel()
        with child_lock:
            for child in children:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        recorded = {(row["variant"], row["seed"]) for row in completed+failed+not_started}
        not_started.extend({"status": "not_collected_after_interruption", "variant": name,
                            "seed": seed, "partial_files_preserved": True}
                           for name, seed, _ in jobs if (name, seed) not in recorded)
        status = {"schema": "rrsnn-v4-evaluation-matrix-1", "identity": identity,
                  "started_at_utc": started, "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                  "all_completed": len(completed) == len(jobs) and not failed and interrupted is None,
                  "expected_checkpoint_jobs": len(jobs), "expected_evaluation_files": len(jobs)*len(DATASETS)*LATENT_REPLAYS,
                  "completed": completed, "failed": failed, "not_started": not_started,
                  "interruption": interrupted, "workers": len(cpus), "cpus": cpus,
                  "elapsed_seconds": time.perf_counter()-begin,
                  "resources_before": initial_resources, "resources_after": memory_snapshot(),
                  "resume_rule": "Only complete equal-identity files are reused; mismatched/corrupt artifacts cause failure and remain preserved."}
        atomic_json(destination/"evaluation_matrix_status.json", status)
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    if not status["all_completed"]:
        raise RuntimeError("Evaluation matrix incomplete; exact status and partial artifacts retained")
    return status


def validate_development():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="rrv4-runner-development-") as directory:
        root = Path(directory)
        selection, receipt_path = root/"selection.json", root/"publication.json"
        selection.write_bytes(b'{"scope":"DEVELOPMENT_ONLY_NO_CHECKPOINTS"}\n')
        content = selection.read_bytes()
        receipt = {"repository": "development/fixture", "commit_sha": "a"*40,
                   "repository_path": "rrsnn_v4/selection.json", "selection_sha256": sha(selection),
                   "git_blob_sha": hashlib.sha1(f"blob {len(content)}\0".encode()+content).hexdigest(),
                   "remote_bytes_verified": True, "recorded_at_utc": "2026-10-29T00:00:00+00:00"}
        receipt_path.write_text(json.dumps(receipt))
        validated = validate_publication_receipt(selection, receipt_path)
        assert validated["selection_sha256"] == sha(selection)
        rejected = []
        for key, value in (("remote_bytes_verified", False), ("git_blob_sha", "0"*40),
                           ("selection_sha256", "0"*64), ("commit_sha", "not-a-commit")):
            changed = {**receipt, key: value}
            receipt_path.write_text(json.dumps(changed))
            try:
                validate_publication_receipt(selection, receipt_path)
            except ValueError:
                rejected.append(key)
            else:
                raise AssertionError("Invalid publication receipt accepted")
        assert len(rejected) == 4
    cpus = check_cpus()
    affinities = []
    for cpu in cpus:
        output = subprocess.check_output(["taskset", "-c", str(cpu), sys.executable, "-c",
                                          "import os,json; print(json.dumps(sorted(os.sched_getaffinity(0))))"], text=True)
        affinity = json.loads(output)
        assert affinity == [cpu]
        affinities.append(affinity)
    result = {"schema": "rrsnn-v4-evaluation-runner-development-1", "all_passed": True,
              "invalid_receipt_rejections": rejected, "worker_affinities": affinities,
              "disk_free_bytes": check_disk(), "production_data_opened": False,
              "provenance_fixture_scope": "Synthetic temporary publication receipt only; no remote commit or trained checkpoint claimed.",
              "source_sha256": sha(__file__)}
    atomic_json(ROOT/"evaluation_runner_validation.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--freeze", type=Path)
    parser.add_argument("--selection", type=Path)
    parser.add_argument("--publication-receipt", type=Path)
    parser.add_argument("--validate-development", action="store_true")
    args = parser.parse_args()
    if args.validate_development:
        print(json.dumps(validate_development()))
    elif args.freeze and args.selection and args.publication_receipt:
        result = run_matrix(args.freeze, args.selection, args.publication_receipt)
        print(json.dumps({"all_completed": result["all_completed"], "jobs": len(result["completed"])}))
    else:
        parser.error("Provide --freeze, --selection and --publication-receipt, or --validate-development")
