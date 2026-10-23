"""Registered v4 execution with byte-level source binding and retained failures."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import shutil
import subprocess
import sys
import time
import traceback

HERE = Path(__file__).resolve().parent
PARENT = HERE.parent
REPO = HERE.parents[2]
sys.path[:0] = [str(HERE), str(PARENT / "v3"), str(PARENT)]

import numpy as np
import torch

from allocation_control import AllocationPolicy
from allocation_evaluation import encoder_contract, prepare_worlds, rollout_arm, score_emitted, write_json
from allocation_model import AllocationModel
from allocation_reporting import allocation_report
from world import canonical


PREREGISTRATION = "f10589f3df5d2da88b2b5d92e3686441ce982461"
PROTOCOL_SHA256 = "4f90f435e3ce419a09f42412af1fc6fe3515f3c198e5e8555115b1996c1aab0b"


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def git(repo, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=repo,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, stderr=subprocess.PIPE, timeout=20)


def git_bindings(repo, paths):
    """Compare local bytes with committed blob IDs without fetching blob objects."""
    if git(repo, "rev-parse", "--show-object-format").strip() != b"sha1":
        raise RuntimeError("this source binding requires the repository's SHA1 Git format")
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    listing = git(repo, "ls-tree", "-r", "-z", commit, "--", *paths)
    committed = {}
    for entry in listing.split(b"\0"):
        if entry:
            header, name = entry.split(b"\t", 1)
            mode, kind, object_id = header.decode().split()
            if kind != "blob" or mode not in ("100644", "100755"):
                raise RuntimeError("regular committed source file required")
            committed[name.decode()] = object_id
    sha256, local = {}, {}
    for name in paths:
        path = Path(repo) / name
        if path.is_symlink():
            raise RuntimeError("source symlinks cannot satisfy byte binding")
        data = path.read_bytes()
        sha256[name] = hashlib.sha256(data).hexdigest()
        local[name] = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    dirty = [name for name in paths if committed.get(name) != local[name]]
    return {"implementation_commit": commit, "git_object_format": "sha1", "source_sha256": sha256,
            "committed_blob_sha1": committed, "local_blob_sha1": local,
            "all_source_bytes_committed": not dirty, "development_dirty_files": dirty}


def source_manifest():
    build_path = HERE / "evidence/native_build_final.json"
    build = json.loads(build_path.read_text())
    paths = {*HERE.glob("*.py"), *HERE.glob("evidence/*.py"), HERE / "protocol.json",
             HERE / "THEORY.md", build_path,
             *(PARENT / name for name in ("model.py", "world.py", "metrics.py", "controlled_model.py")),
             PARENT / "v3/feedback_model.py", PARENT / "v3/risk.py"}
    paths.update(REPO / name for name in (*build["source_sha256"], *build["dependency_source_sha256"]))
    result = git_bindings(REPO, sorted(str(path.relative_to(REPO)) for path in paths))
    ancestor = subprocess.run(["git", "merge-base", "--is-ancestor", PREREGISTRATION,
                              result["implementation_commit"]], cwd=REPO, capture_output=True,
                             env={**os.environ, "GIT_NO_LAZY_FETCH": "1"}, timeout=20)
    result.update(schema="hepta.modality-allocation.sources.v4", preregistration_commit=PREREGISTRATION,
                  preregistration_is_ancestor=ancestor.returncode == 0,
                  protocol_sha256=digest(HERE / "protocol.json"),
                  method="Git ls-tree blob ID versus SHA1(blob header + actual bytes), plus SHA256 file digests")
    return result


def storage_estimate(protocol, development):
    """Conservative uncompressed payload plus full archive headroom; no omission."""
    seeds = 1 if development else len(protocol["seeds"])
    worlds = 32 * protocol["development" if development else "confirmation"]["worlds_per_condition_initial_mode"]
    tree = (protocol["planning"]["joint_latent_float32_bytes_if_all_retained"]
            + protocol["planning"]["four_output_float32_bytes_if_all_retained"])
    online = 4 * worlds * ((40 + 1024 + 768 + 3072) * 4 + 3 * 4 * 64 * 4 + 16384)
    payload = seeds * (tree + online + 4 * 1024 * 1024)
    return {"uncompressed_payload_estimate_bytes": payload,
            "required_free_bytes_with_archive_headroom": 2 * payload + 128 * 1024 * 1024,
            "scope": "All trees, four outputs, all observed latents and transcripts; compression may reduce actual size."}


def storage_plan(estimate, output, archive):
    """Allocate the unchanged reservation across observed filesystem devices."""
    output, archive = dict(output), dict(archive)
    shared = output["st_dev"] == archive["st_dev"]
    total = estimate["required_free_bytes_with_archive_headroom"]
    if total != 2 * estimate["uncompressed_payload_estimate_bytes"] + 128 * 1024 * 1024:
        raise ValueError("complete payload and archive reservation must remain unchanged")
    required = total if shared else estimate["uncompressed_payload_estimate_bytes"] + 64 * 1024 * 1024
    output["required_free_bytes"] = archive["required_free_bytes"] = required
    archive["required_is_shared_with_output"] = shared
    return {**estimate, "strategy": "shared-filesystem" if shared else "split-filesystems",
            "distinct_filesystems": not shared, "output": output, "archive": archive,
            "free_bytes_at_start": output["free_bytes"],
            "total_required_unique_filesystem_bytes": required if shared else 2 * required,
            "passed": output["free_bytes"] >= required and archive["free_bytes"] >= required}


def execute(output, source_run, native_binary, development=False, archive_headroom_dir=None):
    output, source_run, native_binary = map(Path, (output, source_run, native_binary))
    if archive_headroom_dir is not None:
        archive_headroom_dir = Path(archive_headroom_dir).resolve(strict=True)
        if not archive_headroom_dir.is_dir():
            raise NotADirectoryError("archive headroom must refer to an existing directory")
    output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter(), time.process_time()
    receipt = {"schema": "hepta.modality-allocation.execution.v4", "status": "running",
               "attempt_kind": "development" if development else "confirmation", "development": development,
               "started_at_utc": datetime.now(timezone.utc).isoformat(), "output": str(output.resolve()),
               "preregistration_commit": PREREGISTRATION, "protocol_sha256": PROTOCOL_SHA256,
               "scientific_acceptance": "pending independent audits", "source_unchanged": None}
    write_json(output / "run-receipt.json", receipt)
    source, native, work, failures = None, None, [], []

    def progress(event, **values):
        row = {"event": event, "elapsed_seconds": time.perf_counter() - started, **values}
        with (output / "progress.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False) + "\n")
        print(json.dumps(row, allow_nan=False), flush=True)

    @contextmanager
    def meter(model, seed, phase):
        model.reset_work()
        mark, process = time.perf_counter(), time.process_time()
        try:
            yield
        finally:
            work.append({"seed": seed, "phase": phase, **model.work_receipt(),
                         "wall_seconds": time.perf_counter() - mark,
                         "python_process_cpu_seconds": time.process_time() - process})
            write_json(output / "model-work.json", work)

    try:
        protocol_bytes = (HERE / "protocol.json").read_bytes()
        (output / "protocol.json").write_bytes(protocol_bytes)
        if hashlib.sha256(protocol_bytes).hexdigest() != PROTOCOL_SHA256:
            raise RuntimeError("scientific protocol differs from preregistered bytes")
        protocol = json.loads(protocol_bytes)
        if (platform.python_version_tuple()[:2] != ("3", "12") or np.__version__ != "1.26.4"
                or torch.__version__ != "2.5.1+cpu" or torch.version.cuda is not None):
            raise RuntimeError("registered Python3.12 / NumPy1.26.4 / Torch2.5.1+cpu required")
        torch.set_num_threads(protocol["runtime"]["torch_threads"])
        observations = []
        for path in (output.resolve(), archive_headroom_dir or output.resolve()):
            observations.append({"directory": str(path), "st_dev": path.stat().st_dev,
                                 "free_bytes": shutil.disk_usage(path).free})
        budget = storage_plan(storage_estimate(protocol, development), *observations)
        budget["archive_headroom_requested"] = archive_headroom_dir is not None
        write_json(output / "storage.json", budget)
        if not budget["passed"]:
            raise RuntimeError("insufficient room for complete evidence and archive headroom")
        source = source_manifest()
        write_json(output / "source-manifest.json", source)
        if not source["preregistration_is_ancestor"]:
            raise RuntimeError("current implementation does not descend from preregistration")
        if not development and not source["all_source_bytes_committed"]:
            raise RuntimeError("confirmation requires byte-identical committed sources")
        for name in source["development_dirty_files"]:
            destination = output / "development-source-snapshot" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes((REPO / name).read_bytes())
        build_path = HERE / "evidence/native_build_final.json"
        build = json.loads(build_path.read_text())
        if digest(native_binary) != build["binary"]["sha256"]:
            raise RuntimeError("native binary differs from the reviewed build receipt")
        for name, expected in {**build["source_sha256"], **build["dependency_source_sha256"]}.items():
            if digest(REPO / name) != expected:
                raise RuntimeError("native build source binding changed: " + name)
        runtime = {"development": development, "attempt_kind": receipt["attempt_kind"],
                   "tier": "local-cpu", "dedicated_runner_verified": False, "device": "cpu",
                   "python": platform.python_version(), "numpy": np.__version__, "torch": torch.__version__,
                   "platform": platform.platform(), "threads": torch.get_num_threads(),
                   "native_binary": str(native_binary.resolve()), "native_binary_sha256": digest(native_binary),
                   "native_build_receipt_sha256": digest(build_path),
                   "implementation_commit": source["implementation_commit"]}
        write_json(output / "runtime-start.json", runtime)
        from allocation_bridge import NativeBridge
        seeds = [protocol["development"]["study_seed"]] if development else protocol["seeds"]
        replicates = protocol["development" if development else "confirmation"]["worlds_per_condition_initial_mode"]
        targets, seed_results = canonical(), {}
        with gzip.open(output / "native-transcript.tsv.gz", "wt", encoding="ascii") as transcript:
            native = NativeBridge(native_binary, transcript)
            try:
                with native:
                    for seed in seeds:
                        source_seed = protocol["development"]["source_checkpoint_seed"] if development else seed
                        frozen = protocol["source_checkpoints"][str(source_seed)]
                        checkpoint = source_run / frozen["path"]
                        if checkpoint.stat().st_size != frozen["bytes"] or digest(checkpoint) != frozen["sha256"]:
                            raise RuntimeError("frozen v3 checkpoint bytes differ")
                        directory = output / f"seed-{seed}"
                        directory.mkdir()
                        write_json(directory / "checkpoint.json", {"source_seed": source_seed, "study_seed": seed,
                            "path": str(checkpoint.resolve()), "bytes": frozen["bytes"], "sha256": frozen["sha256"]})
                        progress("seed_start", seed=seed, source_seed=source_seed)
                        model = AllocationModel(checkpoint, frozen["sha256"])
                        with meter(model, seed, "encoder_contract"):
                            contract = encoder_contract(model)
                            write_json(directory / "encoder-contract.json", {**contract, "actual_model_work": model.work_receipt()})
                        with meter(model, seed, "planning"):
                            policy = AllocationPolicy(model, targets, seed)
                            policy.save_tables(directory / "tree.npz", directory / "policy.npz")
                            planning = {**policy.receipt, "actual_model_work": model.work_receipt()}
                            write_json(directory / "planning.json", planning)
                        progress("policies_frozen_before_worlds", seed=seed)
                        worlds = prepare_worlds(seed, replicates)
                        np.savez_compressed(directory / "worlds.npz", **worlds)
                        seed_results[seed] = {"planning": planning, "arms": {}}
                        for arm in protocol["policies"]["arms"]:
                            with meter(model, seed, "arm:" + arm):
                                outputs, control, summary = rollout_arm(model, policy, worlds["raw_text"],
                                    worlds["initial_mode"], worlds["world_id"], arm, directory / arm, native)
                                scores = score_emitted(outputs, worlds["truth"], targets, control, directory / arm)
                            seed_results[seed]["arms"][arm] = scores
                            progress("arm_complete", seed=seed, arm=arm, worlds=summary["completed_worlds"],
                                     actual_linear_macs=summary["actual_model_work"]["linear_macs"])
                            del outputs
                        if digest(checkpoint) != frozen["sha256"]:
                            raise RuntimeError("source checkpoint changed during execution")
                        del model, policy
            finally:
                if native.receipt is not None:
                    write_json(output / "native-receipt.json", native.receipt)
        report = allocation_report(seed_results, protocol, development)
        write_json(output / "report.json", report)
        subtotal = report["costs"]["planning_and_online_linear_macs_subtotal"]
        actual = sum(row["linear_macs"] for row in work)
        checks = sum(row["linear_macs"] for row in work if row["phase"] == "encoder_contract")
        if actual != subtotal + checks:
            raise AssertionError("full actual hook total does not reconcile with report plus encoder checks")
        receipt.update(status="completed", completed_seeds=seeds,
                       planning_and_online_linear_macs_subtotal=subtotal,
                       separately_metered_encoder_contract_linear_macs=checks)
    except Exception:
        failures.append(traceback.format_exc())
    finally:
        if source is not None:
            try:
                end = source_manifest()
                write_json(output / "source-end.json", end)
                receipt["source_unchanged"] = end == source
                if end != source:
                    failures.append("Source commit or bytes changed during this attempt.")
                if native is not None and digest(native_binary) != native.binary_sha256:
                    failures.append("Native executable changed during this attempt.")
            except Exception:
                failures.append(traceback.format_exc())
        if failures:
            receipt.update(status="failed", traceback="\n".join(failures))
        receipt.update(full_actual_linear_macs=sum(row["linear_macs"] for row in work),
                       full_actual_model_work_phases=len(work), wall_seconds=time.perf_counter() - started,
                       python_process_cpu_seconds=time.process_time() - cpu,
                       peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                       completed_at_utc=datetime.now(timezone.utc).isoformat(),
                       cost_scope="All actual nn.Linear forwards in this attempt, including encoder checks; not total FLOPs, energy, development or independent replay work.")
        artifacts = {str(path.relative_to(output)): {"bytes": path.stat().st_size, "sha256": digest(path)}
                     for path in sorted(output.rglob("*")) if path.is_file()
                     and path.name not in ("run-receipt.json", "artifacts.json")}
        write_json(output / "artifacts.json", artifacts)
        receipt["artifact_manifest_sha256"] = digest(output / "artifacts.json")
        receipt["artifact_payload_bytes"] = sum(row["bytes"] for row in artifacts.values())
        write_json(output / "run-receipt.json", receipt)
    if receipt["status"] != "completed":
        raise RuntimeError("attempt failed; complete available evidence retained in " + str(output))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--native-binary", type=Path, required=True)
    parser.add_argument("--development", action="store_true")
    parser.add_argument("--archive-headroom-dir", type=Path,
                        help="existing archive directory; a different filesystem may hold the archive reservation")
    arguments = parser.parse_args()
    execute(arguments.output, arguments.source_run, arguments.native_binary, arguments.development,
            arguments.archive_headroom_dir)


if __name__ == "__main__":
    main()
