"""Sealed three-arm training with incremental, non-overwriting evidence."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
import traceback

import numpy as np

from ..ledger import sha, write_json_exclusive
from ..provenance import verify
from .kernel import initial_raw
from .meta import ADAM_BETA1, ADAM_BETA2, ADAM_EPSILON, ARMS, train
from .network import initialize, model_payload, parameter_digest


PROTOCOL_PATH = Path(__file__).resolve().parents[1] / "PROTOCOL.json"
HISTORY_BLOCK = 32


def validate_protocol(protocol):
    config = protocol["training"]
    fixed = {
        "arms": list(ARMS),
        "outer_optimizer": "Adam",
        "outer_beta1": ADAM_BETA1,
        "outer_beta2": ADAM_BETA2,
        "outer_epsilon": ADAM_EPSILON,
        "history_partition_steps": HISTORY_BLOCK,
    }
    if any(config.get(key) != value for key, value in fixed.items()):
        raise ValueError(
            "training protocol disagrees with the implemented optimizer or partition"
        )
    if any(
        not isinstance(config[key], int) or config[key] < 1
        for key in ("outer_steps", "support_episodes", "query_episodes")
    ):
        raise ValueError("positive integer training budgets required")
    if any(
        not np.isfinite(config[key]) or not 0 < config[key] <= 1
        for key in (
            "inner_learning_rate",
            "query_weight_learning_rate",
            "outer_learning_rate",
        )
    ):
        raise ValueError("training learning rates outside the bounded domain")
    if any(
        not np.isfinite(config[key]) or config[key] <= 0
        for key in ("gradient_norm_clip", "hypergradient_norm_clip")
    ):
        raise ValueError("positive finite clipping limits required")


def arrays_to_json(parameters):
    return {key: value.tolist() for key, value in parameters.items()}


def arrays_from_json(parameters):
    expected = {"weights": (6, 8), "readout": (8,), "bias": (1,)}
    if set(parameters) != set(expected):
        raise ValueError("checkpoint parameter names changed")
    result = {key: np.asarray(parameters[key], dtype=float) for key in expected}
    for key, value in result.items():
        limit = 6.0 if key == "bias" else 3.0
        if (
            value.shape != expected[key]
            or not np.all(np.isfinite(value))
            or np.any(np.abs(value) > limit)
        ):
            raise ValueError(f"invalid checkpoint parameter: {key}")
    return result


def checkpoint_payload(parameters, raw, identity, step):
    return {
        "schema": "hepta.adaptive-neuron.training-checkpoint.v2",
        **identity,
        "completed_step": step,
        "parameters": arrays_to_json(parameters),
        "parameter_sha256": parameter_digest(parameters),
        "raw_theta": raw.tolist(),
    }


def execute_fit(seed, arm, protocol, phase_root, identity, progress_state):
    """A checkpoint is durable before history or final summary publication."""
    started, cpu_started = time.perf_counter(), time.process_time()
    directory = phase_root / f"seed_{seed}" / arm
    directory.mkdir(parents=True, exist_ok=False)
    fit_identity = {**identity, "seed": seed, "arm": arm}
    write_json_exclusive(
        directory / "START.json",
        {
            "schema": "hepta.adaptive-neuron.fit-start.v2",
            **fit_identity,
            "initial_parameters": arrays_to_json(initialize(seed)),
            "initial_raw_theta": initial_raw().tolist(),
            "expected_steps": protocol["training"]["outer_steps"],
        },
    )
    (directory / "progress").mkdir()
    (directory / "history").mkdir()
    pending = []

    def progress(step, parameters, raw, row):
        progress_state.update(seed=seed, arm=arm, last_completed_step=step)
        pending.append(row)
        if step % HISTORY_BLOCK == 0 or step == protocol["training"]["outer_steps"]:
            write_json_exclusive(
                directory / "progress" / f"step_{step:04}.json",
                checkpoint_payload(parameters, raw, fit_identity, step),
            )
            write_json_exclusive(
                directory / "history" / f"steps_{pending[0]['step']:04}_{step:04}.json",
                {
                    "schema": "hepta.adaptive-neuron.training-history.v2",
                    **fit_identity,
                    "first_step": pending[0]["step"],
                    "last_step": step,
                    "rows": pending,
                },
            )
            pending.clear()

    parameters, raw, result = train(seed, arm, protocol, progress=progress)
    if pending:
        raise AssertionError("unpublished completed training history")
    checkpoint_path = directory / "checkpoint.json"
    write_json_exclusive(
        checkpoint_path,
        checkpoint_payload(parameters, raw, fit_identity, result["outer_steps"]),
    )
    family = "standard" if arm == "standard" else "first_passage"
    write_json_exclusive(
        directory / "neural.json",
        model_payload(parameters, raw, family, sha(checkpoint_path)),
    )
    summary = {key: value for key, value in result.items() if key != "history"}
    write_json_exclusive(
        directory / "TRAINING.json",
        {
            "schema": "hepta.adaptive-neuron.training-summary.v2",
            **fit_identity,
            **summary,
            "checkpoint_sha256": sha(checkpoint_path),
            "neural_sha256": sha(directory / "neural.json"),
        },
    )
    files = {
        str(path.relative_to(directory)): sha(path)
        for path in sorted(directory.rglob("*.json"))
    }
    receipt = {
        "schema": "hepta.adaptive-neuron.fit-complete.v2",
        **fit_identity,
        "complete": True,
        "files": files,
        "fit_wall_seconds": time.perf_counter() - started,
        "fit_cpu_seconds": time.process_time() - cpu_started,
        "cost_scope": "From before fit-directory creation through training, progress, final model, summary writes and their hashes; excludes this completion receipt write.",
    }
    write_json_exclusive(directory / "COMPLETE.json", receipt)
    return {
        "seed": seed,
        "arm": arm,
        "directory": str(directory.relative_to(phase_root)),
        "complete_sha256": sha(directory / "COMPLETE.json"),
        "checkpoint_sha256": sha(checkpoint_path),
        "neural_sha256": sha(directory / "neural.json"),
    }


def run_phase(phase, destination, source_seal):
    started, cpu_started = time.perf_counter(), time.process_time()
    if phase not in ("screening", "confirmation"):
        raise ValueError("registered screening or confirmation phase required")
    source = verify(source_seal)
    protocol = json.loads(PROTOCOL_PATH.read_text())
    validate_protocol(protocol)
    seeds = protocol[f"{phase}_seeds"]
    if len(set(seeds)) != len(seeds) or set(protocol["screening_seeds"]) & set(
        protocol["confirmation_seeds"]
    ):
        raise ValueError("phase seeds must be distinct and disjoint")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    identity = {
        "phase": phase,
        "source_seal_sha256": sha(source_seal),
        "protocol_sha256": sha(PROTOCOL_PATH),
    }
    write_json_exclusive(
        destination / "START.json",
        {
            "schema": "hepta.adaptive-neuron.learning-start.v2",
            **identity,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "seeds": seeds,
            "arms": list(ARMS),
            "expected_fits": len(seeds) * len(ARMS),
        },
    )
    records, progress = [], {}
    try:
        for seed in seeds:
            for arm in ARMS:
                records.append(
                    execute_fit(seed, arm, protocol, destination, identity, progress)
                )
        final_source = verify(source_seal)
        if sha(PROTOCOL_PATH) != identity["protocol_sha256"]:
            raise ValueError("training protocol changed during execution")
        result = {
            "schema": "hepta.adaptive-neuron.learning-index.v2",
            **identity,
            "complete": True,
            "source": final_source,
            "fits": records,
            "fit_count": len(records),
            "phase_wall_seconds": time.perf_counter() - started,
            "phase_cpu_seconds": time.process_time() - cpu_started,
            "cost_scope": "From entry before source verification and directory creation through all fits and final verification; includes subordinate fit and training timers, which must not be added again. Excludes import/process startup and final index write.",
        }
        write_json_exclusive(destination / "INDEX.json", result)
        return result
    except Exception as error:
        invalid = {
            "schema": "hepta.adaptive-neuron.learning-invalid.v2",
            **identity,
            "exception": repr(error),
            "traceback": traceback.format_exc(),
            "completed_fits": records,
            "progress": progress,
            "phase_wall_seconds": time.perf_counter() - started,
            "phase_cpu_seconds": time.process_time() - cpu_started,
        }
        try:
            write_json_exclusive(destination / "INVALID_ATTEMPT.json", invalid)
        except OSError as preservation_error:
            error.add_note(
                f"Could not preserve invalid-attempt receipt: {preservation_error}"
            )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("screening", "confirmation"), required=True)
    parser.add_argument("--source-seal", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_phase(args.phase, args.output_dir, args.source_seal)
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "fit_count": result["fit_count"],
                "output_dir": str(args.output_dir),
            }
        )
    )


if __name__ == "__main__":
    main()
