"""Source-bound engineering qualification of the two Cell implementation routes.

This fixed CPU probe is not the HCSN formal study, a serving benchmark, or a
production selection. Original per-seed measurements and failures are retained.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time
import zipfile

import numpy as np

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED, validate_local_update
from hepta_cells.lifecycle import CellOwner, Partition, Qualification
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent
from hepta_pred1.models import matched_hidden_dim


PROTOCOL = {
    "schema": "hepta.stem-cell.engineering-probe.v1",
    "scope": "synthetic delayed-cue correctness and state-owner integration",
    "seeds": [41, 67, 89], "train_episodes": 64, "confirmation_episodes": 64,
    "episode_steps": 12, "updates": 40, "learning_rate": 0.02, "clip": 5.0,
    "reference_gru_hidden": 12, "kernels": ["gru", "diag_ssm"],
    "matching": "nearest actual parameter count; report mismatch without padding",
    "rule_control": "exactly retain the observed first cue",
    "selection": "none; no tuning or production adoption from this probe",
    "hcsn_formal_fits_started_by_this_probe": 0,
}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else canonical(value).encode()).hexdigest()


def retain(path, value):
    raw = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return hashlib.sha256(raw).hexdigest()


def source_manifest():
    root = Path(__file__).resolve().parent
    files = [Path(__file__).resolve(), root / "hepta_pred1/models.py"]
    files += sorted((root / "hepta_cells").glob("*.py"))
    return {str(path.relative_to(root.parent)): hashlib.sha256(path.read_bytes()).hexdigest() for path in files}


def dataset(seed, count, steps):
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 2, size=count)
    inputs = np.zeros((count, steps, 3), dtype=np.float64)
    inputs[:, 0, 0] = 2 * labels - 1
    inputs[:, :, 1] = rng.normal(0, 0.015, size=(count, steps))
    inputs[:, :, 2] = 1
    return inputs, np.zeros((count, 1)), labels


def evaluate(kernel, inputs, actions, labels):
    started, cpu = time.perf_counter(), time.process_time()
    logits = []
    for index, (episode, action) in enumerate(zip(inputs, actions)):
        episode_id = f"confirmation-{index}"
        state = kernel.initial_state(episode_id)
        for cursor, observation in enumerate(episode):
            state = kernel.observe(state, observation, episode_id=episode_id, cursor=cursor)
        logits.append(kernel.predict(state, action, episode_id=episode_id))
    logits = np.stack(logits)
    loss = np.logaddexp.reduce(logits, axis=1) - logits[np.arange(len(labels)), labels]
    return {"nll": float(loss.mean()), "accuracy": float((logits.argmax(axis=1) == labels).mean()),
            "logits": logits.tolist(), "labels": labels.tolist(),
            "wall_seconds": time.perf_counter() - started, "process_cpu_seconds": time.process_time() - cpu,
            "measurement_scope": "streamed Python observe/predict including identity checks"}


def bundle_for(kernel, artifact_id):
    parts = {name: sha(["engineering-fixture", name]) for name in REQUIRED}
    parts.update({name: None for name in OPTIONAL})
    parts.update(base=kernel.kernel_sha256, heads=kernel.heads_sha256, composition=kernel.config.sha256)
    return Bundle(artifact_id, 1, parts)


def owner_roundtrip(path, source, candidate, training):
    """Real SQLite owner, actual trained parameters, reset and next-task readback."""
    partition = Partition("qualification", "stem-agent", source.cell_id, "episode-next")
    base = bundle_for(source, "artifact:temporal-source")
    evaluation = sha(["engineering-evaluation-only", training["data_sha256"]])
    next_bundle = base.successor("artifact:temporal-candidate",
                                dict(base.components, base=candidate.kernel_sha256, heads=candidate.heads_sha256),
                                training["data_sha256"], sha(PROTOCOL), evaluation)
    validate_local_update("stateful_temporal", base, next_bundle, "kernel_and_heads")
    first = TemporalComponent(source, base, partition.run_id)
    updated = TemporalComponent(candidate, next_bundle, partition.run_id)
    expected = Qualification(first.identity.digest, updated.identity.digest, evaluation)
    with_owner = CellOwner(path, qualify=lambda record: record == expected)
    try:
        with_owner.create(partition, first)
        payload = {"operation": "observe", "cursor": 0, "observation": [1, 0, 1]}
        old = with_owner.step(partition, first, "source-observation", payload)
        reset = with_owner.adopt(partition, updated, expected)
        if reset["state"]["cursor"] != 0:
            raise AssertionError("trained parameters reused old hidden state")
        consumed = with_owner.step(partition, updated, "candidate-observation", payload)
        predicted = with_owner.step(partition, updated, "candidate-prediction", {"operation": "predict", "action": [0]})
    finally:
        with_owner.close()
    reopened = CellOwner(path)
    try:
        if reopened.step(partition, updated, "candidate-observation", payload) != consumed:
            raise AssertionError("restart changed original receipt")
        current = reopened.checkpoint(partition)
        if current["state"]["cursor"] != 1:
            raise AssertionError("prediction/replay advanced observed belief")
    finally:
        reopened.close()
    return {"source_bundle": base.record(), "candidate_bundle": next_bundle.record(),
            "source_receipt": old, "reset_state": reset["state"],
            "next_use": consumed, "prediction": predicted, "restart_exact_replay": True,
            "qualification_scope": "injected engineering evaluator; not production evaluation authority"}


def run(output):
    output.mkdir(parents=True, exist_ok=False)
    manifest = source_manifest()
    retain(output / "protocol.json", PROTOCOL)
    retain(output / "source.json", manifest)
    source_root = Path(__file__).resolve().parent.parent
    with zipfile.ZipFile(output / "source_snapshot.zip", "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, expected in manifest.items():
            raw = (source_root / name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError("source changed before snapshot retention")
            archive.writestr(name, raw)
    started, cpu = time.perf_counter(), time.process_time()
    records, current = [], None
    try:
        for seed in PROTOCOL["seeds"]:
            train = dataset(seed + 10000, PROTOCOL["train_episodes"], PROTOCOL["episode_steps"])
            confirmation = dataset(seed + 20000, PROTOCOL["confirmation_episodes"], PROTOCOL["episode_steps"])
            reference = TemporalKernel("predictor", TemporalConfig(3, 1, 2, PROTOCOL["reference_gru_hidden"], seed))
            target = reference.parameter_count
            for kind in PROTOCOL["kernels"]:
                width = PROTOCOL["reference_gru_hidden"] if kind == "gru" else matched_hidden_dim(kind, 3, 1, 2, target)
                kernel = TemporalKernel("predictor", TemporalConfig(3, 1, 2, width, seed, kind))
                current = {"seed": seed, "kind": kind, "config": asdict(kernel.config)}
                before = evaluate(kernel, *confirmation)
                candidate, training = kernel.train_candidate(train[0], train[1], np.eye(2, dtype=bool)[train[2]],
                                                             updates=PROTOCOL["updates"], lr=PROTOCOL["learning_rate"], clip=PROTOCOL["clip"])
                after = evaluate(candidate, *confirmation)
                checkpoint = output / f"{kind}-{seed}.npz"
                checkpoint_sha = candidate.checkpoint(checkpoint, candidate.initial_state("checkpoint-episode"))
                recovered, state = TemporalKernel.restore_checkpoint(checkpoint, expected_sha256=checkpoint_sha,
                                                                      cell_id="predictor", config=kernel.config)
                if recovered.weights_sha256 != candidate.weights_sha256 or recovered.optimizer_sha256 != candidate.optimizer_sha256:
                    raise AssertionError("checkpoint did not preserve parameters and Adam state")
                record = dict(current, actual_parameters=kernel.parameter_count,
                              relative_parameter_mismatch=abs(kernel.parameter_count - target) / target,
                              before=before, after=after, training=training, checkpoint_sha256=checkpoint_sha,
                              recovered_state=state,
                              rule_accuracy=float(((confirmation[0][:, 0, 0] > 0).astype(int) == confirmation[2]).mean()),
                              rule_scope="exact first-cue retention; same observed cue, no future data")
                if not records:
                    record["owner_roundtrip"] = owner_roundtrip(output / "owner.sqlite", kernel, candidate, training)
                retain(output / f"{kind}-{seed}.json", record)
                records.append(record)
        if source_manifest() != manifest:
            raise AssertionError("sources changed during qualification")
        result = {"status": "engineering_probe_completed", "protocol_digest": sha(PROTOCOL),
                  "source_manifest_digest": sha(manifest), "numpy": np.__version__, "python": sys.version,
                  "source_snapshot_sha256": hashlib.sha256((output / "source_snapshot.zip").read_bytes()).hexdigest(),
                  "platform": platform.platform(), "fits": len(records),
                  "summary": [{"seed": row["seed"], "kind": row["kind"], "parameters": row["actual_parameters"],
                               "nll_before": row["before"]["nll"], "nll_after": row["after"]["nll"],
                               "accuracy_after": row["after"]["accuracy"], "rule_accuracy": row["rule_accuracy"],
                               "train_cpu_seconds": row["training"]["process_cpu_seconds"]} for row in records],
                  "wall_seconds": time.perf_counter() - started, "process_cpu_seconds": time.process_time() - cpu,
                  "energy_joules": None, "production_qualified": False, "hcsn_formal_study_started": False,
                  "llm_vlm_serving_measured": False, "scientific_winner_selected": False}
        retain(output / "result.json", result)
        return result
    except BaseException as error:
        failure = {"status": "failed", "last_attempt": current, "error": f"{type(error).__name__}: {error}",
                   "completed_fits": len(records), "wall_seconds": time.perf_counter() - started,
                   "process_cpu_seconds": time.process_time() - cpu,
                   "training_receipt": getattr(error, "receipt", None)}
        retain(output / "failure.json", failure)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(run(options.output), sort_keys=True, indent=2))
