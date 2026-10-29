"""Execute all structure arms, retain raw outputs, then score fresh checkpoints."""

import argparse
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "memory-cell-adapters"))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    import hashlib
    return hashlib.sha256(value).hexdigest()


def run_child(command, log, *, timeout=180):
    before = resource.getrusage(resource.RUSAGE_CHILDREN)
    began, last = time.monotonic(), time.monotonic()
    coordinator_cpu = time.process_time()
    resident_integral, coordinator_integral, peak, samples = 0.0, 0.0, 0, 0
    with log.with_suffix(".stdout").open("wb") as stdout, log.with_suffix(".stderr").open("wb") as stderr:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                   env={**os.environ, "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                                        "OPENBLAS_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"})
        while process.poll() is None:
            now = time.monotonic()
            try:
                fields = Path(f"/proc/{process.pid}/statm").read_text().split()
                resident = int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
                resident_integral += resident * (now - last)
                coordinator_rss = int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
                coordinator_integral += coordinator_rss * (now - last)
                peak = max(peak, resident)
                samples += 1
            except (OSError, ValueError, IndexError):
                pass
            last = now
            if now - began > timeout:
                process.kill()
                process.wait()
                raise TimeoutError(f"owned experiment exceeded {timeout} seconds: {log}")
            time.sleep(0.02)
        code = process.wait()
    after = resource.getrusage(resource.RUSAGE_CHILDREN)
    receipt = {"command": command, "exit_code": code, "pid": process.pid,
               "wall_seconds": time.monotonic() - began,
               "cpu_seconds": after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime,
               "coordinator_cpu_seconds": time.process_time() - coordinator_cpu,
               "rss_byte_seconds_sampled": resident_integral, "sampled_peak_rss_bytes": peak,
               "coordinator_rss_byte_seconds_sampled": coordinator_integral,
               "rss_samples": samples, "sampling_interval_seconds": 0.02,
               "stdout_sha256": sha(log.with_suffix(".stdout").read_bytes()),
               "stderr_sha256": sha(log.with_suffix(".stderr").read_bytes())}
    log.with_suffix(".process.json").write_bytes(canonical(receipt))
    if code:
        raise RuntimeError(f"experiment failed; retained process logs: {log}")
    return receipt


def score(args, protocol, executions):
    import torch
    from corpus import bits
    from structure_models import Structure
    from structure_train import phases

    torch.set_num_threads(1)
    identity = json.loads((args.fixture / "development-encoder.json").read_bytes())["base_encoder_sha"]
    # This is the first parse of held expressions in the experiment coordinator.
    held_opened_ns = time.monotonic_ns()
    held = json.loads((args.fixture / "held-evaluator-rows.json").read_bytes())
    indexes = [i for i, row in enumerate(held) if row["role"] == "semantic"]
    addresses = torch.tensor([held[i]["entity"] for i in indexes])
    with np.load(args.fixture / "held-encoded.npz", allow_pickle=False) as archive:
        held_features = torch.from_numpy(archive["features"][indexes].copy())
    with np.load(args.fixture / "canonical.npz", allow_pickle=False) as archive:
        canonical_features = torch.from_numpy(archive["semantic"].copy())
    records = []
    for execution in executions:
        location = args.output / execution["name"]
        training = json.loads((location / "TRAINING.json").read_bytes())
        phases_results = []
        prior_changes = set()
        for phase in phases():
            began, cpu = time.perf_counter(), time.process_time()
            model = Structure.load(location / f"phase-{phase['phase']}", identity)
            with torch.no_grad():
                canonical_bits = (model(canonical_features, torch.arange(8)).sigmoid() >= 0.5).numpy()
                held_bits = (model(held_features, addresses).sigmoid() >= 0.5).numpy()
            expected = np.asarray([bits(row) for row in phase["policies"]], dtype=bool)
            canonical_ok = (canonical_bits == expected).all(axis=1)
            held_ok = (held_bits == expected[addresses.numpy()]).all(axis=1)
            changed = set(phase["changed_entities"])

            def subset(rows):
                rows = sorted(rows)
                selected = np.isin(addresses.numpy(), rows)
                return {"entities": rows, "canonical_correct": int(canonical_ok[rows].sum()),
                        "canonical_count": len(rows), "held_correct": int(held_ok[selected].sum()),
                        "held_count": int(selected.sum())}

            groups = {}
            for offset, source_index in enumerate(indexes):
                key = held[source_index]["wording_group"]
                group = groups.setdefault(key, {"correct": 0, "count": 0})
                group["correct"] += int(held_ok[offset])
                group["count"] += 1
            phases_results.append({"phase": phase["phase"], "all": subset(range(8)),
                                   "changed_now": subset(changed),
                                   "unchanged_now": subset(set(range(8)) - changed),
                                   "earlier_updates": subset(prior_changes - changed),
                                   "untouched_original": subset(set(range(8)) - prior_changes - changed),
                                   "wording_groups": groups,
                                   "canonical_bits": canonical_bits.astype(int).tolist(),
                                   "held_bits": held_bits.astype(int).tolist(),
                                   "evaluation_wall_seconds": time.perf_counter() - began,
                                   "evaluation_cpu_seconds": time.process_time() - cpu})
            prior_changes |= changed
        records.append({"name": execution["name"], "arm": training["arm"],
                        "seed": training["seed"], "regime": training["regime"],
                        "counts": training["counts"], "phases": phases_results,
                        "process_cost": execution["process"], "training": training})
    return records, held_opened_ns


def run(args):
    args.fixture = args.fixture.resolve()
    args.output = args.output.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    protocol_path = ROOT / "STRUCTURE_PROTOCOL.json"
    protocol = json.loads(protocol_path.read_bytes())
    source = {p.name: sha(p.read_bytes()) for p in sorted(ROOT.glob("structure*.py"))}
    source[protocol_path.name] = sha(protocol_path.read_bytes())
    inputs = {name: sha((args.fixture / name).read_bytes()) for name in
              ("development.json", "development_features.npz", "canonical.npz",
               "held-evaluator-rows.json", "held-encoded.npz", "development-encoder.json")}
    freeze = {"schema": "hepta.structure-stream-freeze.v1", "source": source,
              "inputs": inputs, "protocol": protocol, "held_read_before_training": "hash bytes only"}
    (args.output / "FREEZE.json").write_bytes(canonical(freeze))
    executions = []
    for regime in protocol["regimes"]:
        for index, seed in enumerate(protocol["seeds"]):
            arms = protocol["arms"][index:] + protocol["arms"][:index]
            for arm in arms:
                name = f"{regime}-{seed}-{arm}"
                command = [sys.executable, "-B", str(ROOT / "structure_train.py"),
                           "--fixture", str(args.fixture), "--protocol", str(protocol_path),
                           "--output", str(args.output / name), "--seed", str(seed),
                           "--arm", arm, "--regime", regime]
                receipt = run_child(command, args.output / name)
                executions.append({"name": name, "process": receipt})
                print(json.dumps({"completed": name, "cpu_seconds": receipt["cpu_seconds"]}), flush=True)
    training_finished_ns = time.monotonic_ns()
    records, held_opened_ns = score(args, protocol, executions)
    for regime in protocol["regimes"]:
        for seed in protocol["seeds"]:
            arms = [r for r in records if r["regime"] == regime and r["seed"] == seed]
            if len({canonical(r["counts"]) for r in arms}) != 1:
                raise ValueError("parameter budget differs across arms")
            if regime == "matched_exposure":
                for phase in range(protocol["phase_count"]):
                    schedules = {r["training"]["phases"][phase]["fit"]["sample_schedule_sha256"] for r in arms}
                    if len(schedules) != 1:
                        raise ValueError("matched-exposure minibatches differ")
    summary = {}
    for regime in protocol["regimes"]:
        summary[regime] = {}
        for arm in protocol["arms"]:
            rows = [r for r in records if r["regime"] == regime and r["arm"] == arm]
            phase_rows = [p for r in rows for p in r["phases"]]
            summary[regime][arm] = {
                "canonical_correct": sum(p["all"]["canonical_correct"] for p in phase_rows),
                "canonical_count": sum(p["all"]["canonical_count"] for p in phase_rows),
                "held_correct": sum(p["all"]["held_correct"] for p in phase_rows),
                "held_count": sum(p["all"]["held_count"] for p in phase_rows),
                "untouched_correct": sum(p["untouched_original"]["canonical_correct"] for p in phase_rows),
                "untouched_count": sum(p["untouched_original"]["canonical_count"] for p in phase_rows),
                "whole_process_cpu_seconds": sum(r["process_cost"]["cpu_seconds"] for r in rows),
                "training_coordinator_cpu_seconds": sum(r["process_cost"]["coordinator_cpu_seconds"] for r in rows),
                "evaluation_cpu_seconds": sum(p["evaluation_cpu_seconds"] for p in phase_rows),
                "whole_process_wall_seconds": sum(r["process_cost"]["wall_seconds"] for r in rows),
                "rss_byte_seconds_sampled": sum(r["process_cost"]["rss_byte_seconds_sampled"] for r in rows),
                "stored_bytes": sum(r["training"]["stored_bytes"] for r in rows),
                "training_presentations": sum(p["fit"]["sample_presentations"] for r in rows for p in r["training"]["phases"])}
    result = {"schema": "hepta.structure-stream-result.v1", "summary": summary, "records": records,
              "training_finished_ns": training_finished_ns, "held_opened_ns": held_opened_ns,
              "causal_order_verified": training_finished_ns < held_opened_ns,
              "statistical_unit": "seed and wording group; repeated rows are not independent",
              "native_runtime": False, "split_superiority_automatically_claimed": False,
              "common_encoder_receipt": json.loads((args.fixture / "development-encoder.json").read_bytes())}
    current_source = {p.name: sha(p.read_bytes()) for p in sorted(ROOT.glob("structure*.py"))}
    current_source[protocol_path.name] = sha(protocol_path.read_bytes())
    if current_source != source:
        raise ValueError("source changed after experiment freeze")
    (args.output / "RESULT.json").write_bytes(canonical(result))
    print(json.dumps({"result": str(args.output / "RESULT.json"), "summary": summary}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    run(parser.parse_args())
