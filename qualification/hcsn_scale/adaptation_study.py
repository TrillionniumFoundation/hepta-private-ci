"""Fixed real-sensor study of conditional solves and a small editable block.

Run all fifteen declared trials serially, or one declared arm/seed per output
directory. No test score or occupancy label is used. The incumbent is explicitly
untrained; preservation therefore does not establish retention of learned skills.
"""

import time

_ENTRY_WALL, _ENTRY_CPU = time.perf_counter(), time.process_time()

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import resource

import numpy as np
import torch

from qualification.hcsn_adaptive.real_sensor_data import (
    FEATURES,
    SOURCE_SHA256,
    SOURCE_URL,
    make_splits,
    read_rows,
)
from .adaptation import AdaptationConfig, METHODS, adapt_model
from .model import tensor_map_digest
from .stream_benchmark import make_model


PLAN = {
    "schema": "hcsn-sensor-adaptation-study-v1",
    "seeds": [181391, 284729, 395201],
    "arms": list(METHODS),
    "max_train_windows": 64,
    "max_dev_windows": 32,
    "preservation_windows": 16,
    "purge_windows_after_preservation": 1,
    "sequence_length": 16,
    "parameter_target": 600,
    "dtype": "float64",
    "threads": 1,
    "device": "cpu",
    "editable_names": ["feedback.projection.weight"],
    "adaptation": asdict(
        AdaptationConfig(
            steps=8,
            learning_rate=0.001,
            ridge=0.001,
            max_edit_l2=0.05,
            max_edit_linf=0.05,
            min_dev_improvement=1e-12,
            preservation_tolerance=0.01,
        )
    ),
    "edit_l2": 0.02,
    "edit_directions": [
        [1, 0],
        [-1, 0],
        [0, 1],
        [0, -1],
        [1, 1],
        [-1, -1],
        [1, -1],
        [-1, 1],
    ],
    "selection": "minimum next-sensor dev MSE subject to preservation MSE <= KEEP + 0.01",
    "incumbent": "common seeded untrained HCSN and random sensor predictor; no pretraining",
    "comparison": "same data, initial state and editable parameter block; actual budgets differ",
    "test_evaluations": 0,
    "occupancy_labels_used": False,
}


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def prepare_data(csv_path):
    """Reuse verified chronological windows, then exclude preservation from fitting."""
    raw = Path(csv_path).read_bytes()
    values, labels, stamps = read_rows(raw)
    full, contract = make_splits(values, labels, stamps, length=PLAN["sequence_length"])
    early = PLAN["preservation_windows"]
    offset = early + PLAN["purge_windows_after_preservation"]
    if len(full["train"]["x"]) < offset + 8:
        raise ValueError(
            "insufficient nonoverlapping windows for train and preservation"
        )
    indices = {
        "preservation": np.arange(early),
        "train": np.linspace(
            offset,
            len(full["train"]["x"]) - 1,
            min(PLAN["max_train_windows"], len(full["train"]["x"]) - offset),
            dtype=np.int64,
        ),
        "dev": np.linspace(
            0,
            len(full["dev"]["x"]) - 1,
            min(PLAN["max_dev_windows"], len(full["dev"]["x"])),
            dtype=np.int64,
        ),
    }
    selected, row_sets = {}, {}
    for name, chosen in indices.items():
        source = full["dev" if name == "dev" else "train"]
        item = {
            key: source[key][chosen]
            for key in ("ids", "dt", "input_times", "target_times")
        }
        bounds = [
            tuple(int(v) for v in identity.split(":")[1:3]) for identity in item["ids"]
        ]
        item["x"] = np.stack([values[start:stop] for start, stop in bounds])
        row_sets[name] = {
            row for start, stop in bounds for row in range(start, stop + 1)
        }
        for (start, stop), duration in zip(bounds, item["dt"]):
            if not np.array_equal(duration, np.diff(stamps[start : stop + 1])):
                raise AssertionError("the adapter altered a physical interval")
        selected[name] = item
    if any(
        row_sets[a] & row_sets[b]
        for a, b in (
            ("train", "dev"),
            ("train", "preservation"),
            ("dev", "preservation"),
        )
    ):
        raise AssertionError(
            "source rows overlap across fitting and evaluation windows"
        )
    fitting = selected["train"]["x"].reshape(-1, len(FEATURES))
    mean, scale = fitting.mean(0), fitting.std(0)
    scale = np.where(scale > 1e-8, scale, 1.0)
    for item in selected.values():
        item["x"] = np.clip((item["x"] - mean) / scale, -8.0, 8.0)
    clock = float(np.median(selected["train"]["dt"][:, :-1]))
    contract["normalization_train_only"] = {
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "clip": 8,
        "fit_sensor_rows": len(fitting),
        "scope": "selected adaptation train input rows only",
        "original_adapter_normalizer": "computed during window construction, discarded and never used by a model",
    }
    metadata = {
        "source_csv_sha256": hashlib.sha256(raw).hexdigest(),
        "expected_source_sha256": SOURCE_SHA256,
        "source_url": SOURCE_URL,
        "feature_columns": list(FEATURES),
        "contract": contract,
        "clock_scale_seconds": clock,
        "used_windows": {name: len(item["x"]) for name, item in selected.items()},
        "ids": {name: item["ids"].tolist() for name, item in selected.items()},
        "normalizer_and_clock_exclude_preservation": True,
        "test_evaluations": 0,
        "test_handling": "common source loader parses chronology; no test tensor retained or evaluated",
        "task": "one-step sensor prediction inside each observed window; no occupancy target used",
    }
    return selected, metadata, clock


def semantic_edits(model):
    """Fixed directions in mean-mark drift/reward coefficients; no data queries."""
    edits, manifest = [], []
    for index, (drift, reward) in enumerate(PLAN["edit_directions"]):
        delta = torch.zeros_like(model.feedback.projection.weight)
        delta[0].fill_(drift)
        delta[2].fill_(reward)
        delta *= PLAN["edit_l2"] / torch.linalg.vector_norm(delta)
        edit = {"feedback.projection.weight": delta}
        edits.append(edit)
        manifest.append(
            {
                "index": index,
                "drift_direction": drift,
                "reward_direction": reward,
                "delta_l2": float(delta.norm()),
                "delta_linf": float(delta.abs().max()),
                "parameter_digest": tensor_map_digest(edit),
                "boundary_row_delta": 0.0,
            }
        )
    return edits, manifest


def code_identity():
    root = Path(__file__).resolve().parents[2]
    names = [
        "hcsn_scale/" + name
        for name in (
            "adaptation_study.py",
            "adaptation.py",
            "model.py",
            "feedback.py",
            "stream_benchmark.py",
            "stream_baselines.py",
        )
    ]
    names += [
        "hcsn_adaptive/" + name
        for name in (
            "real_sensor_data.py",
            "batched_flow.py",
            "flow_semantics.py",
            "finite_control.py",
        )
    ]
    names += [
        "hcsn_mechanism_v2/" + name for name in ("readout.py", "representation.py")
    ]
    return {
        name: hashlib.sha256((root / "qualification" / name).read_bytes()).hexdigest()
        for name in names
    }


def run_study(csv_path, output, *, arm=None, seed=None):
    if (
        (arm is None) != (seed is None)
        or (arm is not None and arm not in PLAN["arms"])
        or (seed is not None and seed not in PLAN["seeds"])
    ):
        raise ValueError(
            "supply both a declared arm and seed, or neither for the complete study"
        )
    if torch.get_num_threads() != 1 or torch.get_num_interop_threads() != 1:
        raise ValueError(
            "the declared study requires one intra-op and one inter-op CPU thread"
        )
    started, cpu_started = time.perf_counter(), time.process_time()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    trials = [
        (s, a)
        for s in PLAN["seeds"]
        for a in PLAN["arms"]
        if arm is None or (a == arm and s == seed)
    ]
    record = {
        "schema": PLAN["schema"],
        "state": "running",
        "plan": PLAN,
        "planned_trials": len(trials),
        "declared_full_study_trials": 15,
        "trials": [],
        "test_evaluations": 0,
        "plan_sha256": hashlib.sha256(
            json.dumps(PLAN, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "source_code_sha256": code_identity(),
        "incumbents": {},
        "runtime": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "numpy": np.__version__,
            "threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "device": "cpu",
            "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
        },
        "shared_cost": {},
        "module_import_seconds": started - _ENTRY_WALL,
    }
    write_json(out / "PLAN.json", PLAN)
    write_json(out / "STUDY.json", record)
    try:
        tick = time.perf_counter()
        data, metadata, clock = prepare_data(csv_path)
        record["data"] = metadata
        tensors = {
            name: (
                torch.as_tensor(item["x"], dtype=torch.float64),
                torch.as_tensor(item["dt"], dtype=torch.float64),
            )
            for name, item in data.items()
        }
        np.savez_compressed(
            out / "prepared_inputs.npz",
            **{
                f"{name}_{key}": item[key]
                for name, item in data.items()
                for key in ("x", "dt", "ids", "input_times", "target_times")
            },
        )
        record["prepared_inputs_sha256"] = hashlib.sha256(
            (out / "prepared_inputs.npz").read_bytes()
        ).hexdigest()
        record["shared_cost"]["data_preparation_and_save_seconds"] = (
            time.perf_counter() - tick
        )
        for current_seed in dict.fromkeys(s for s, _ in trials):
            tick = time.perf_counter()
            incumbent, identity = make_model(
                "hcsn_feedback",
                len(FEATURES),
                clock,
                PLAN["parameter_target"],
                current_seed,
            )
            initial_digest = tensor_map_digest(incumbent.state_dict())
            edits, edit_plan = semantic_edits(incumbent)
            directory = out / f"seed_{current_seed}"
            directory.mkdir()
            torch.save(
                {
                    "identity": identity,
                    "state_dict": incumbent.state_dict(),
                    "seed": current_seed,
                },
                directory / "incumbent.pt",
            )
            torch.save(edits, directory / "edit_candidates.pt")
            write_json(directory / "EDIT_PLAN.json", edit_plan)
            record["incumbents"][str(current_seed)] = {
                "state_digest": initial_digest,
                "identity": identity,
                "initialization_edit_assembly_and_save_seconds": time.perf_counter()
                - tick,
                "kind": PLAN["incumbent"],
                "edit_candidates": edit_plan,
            }
            for current_arm in (a for s, a in trials if s == current_seed):
                arm_start, arm_cpu = time.perf_counter(), time.process_time()
                destination = directory / current_arm
                destination.mkdir()
                result = {
                    "arm": current_arm,
                    "seed": current_seed,
                    "state": "running",
                    "initial_state_digest": initial_digest,
                    "test_evaluations": 0,
                }
                write_json(destination / "RESULT.json", result)
                try:
                    selected, ledger, states = adapt_model(
                        incumbent,
                        *tensors["train"],
                        *tensors["dev"],
                        method=current_arm,
                        config=AdaptationConfig(**PLAN["adaptation"]),
                        edits=edits if current_arm == "bounded_edit" else None,
                        editable_names=PLAN["editable_names"],
                        preservation=tensors["preservation"],
                    )
                    if tensor_map_digest(incumbent.state_dict()) != initial_digest:
                        raise AssertionError(
                            "an adaptation arm mutated the common incumbent"
                        )
                    if ledger["initial_state_digest"] != initial_digest:
                        raise AssertionError(
                            "arm did not start from the declared incumbent"
                        )
                    tick = time.perf_counter()
                    torch.save(
                        {
                            "states_by_digest": states,
                            "selected_state_dict": selected.state_dict(),
                            "ledger": ledger,
                            "model_identity": identity,
                        },
                        destination / "candidates.pt",
                    )
                    result.update(
                        state="completed",
                        ledger=ledger,
                        artifact_write_seconds=time.perf_counter() - tick,
                        candidate_artifact_sha256=hashlib.sha256(
                            (destination / "candidates.pt").read_bytes()
                        ).hexdigest(),
                        selected_dev_mse=ledger["selected_dev_mse"],
                        adoption="KEEP"
                        if ledger["selected_index"] == 0
                        else "Candidate",
                        rejected_candidates=sum(
                            not row["selected_when_seen"]
                            for row in ledger["candidates"][1:]
                        ),
                        preservation_rejections=sum(
                            row["reason"] == "preservation tolerance exceeded"
                            for row in ledger["candidates"][1:]
                        ),
                    )
                except Exception as error:
                    result.update(
                        state="failed",
                        error=type(error).__name__ + ": " + str(error),
                        incomplete_internal_cost="unknown; external elapsed time remains charged",
                        partial_candidate_states_available=False,
                    )
                finally:
                    result.update(
                        arm_total_seconds=time.perf_counter() - arm_start,
                        arm_cpu_seconds=time.process_time() - arm_cpu,
                        peak_process_rss_kib=resource.getrusage(
                            resource.RUSAGE_SELF
                        ).ru_maxrss,
                    )
                    write_json(destination / "RESULT.json", result)
                record["trials"].append(
                    {
                        key: result.get(key)
                        for key in (
                            "arm",
                            "seed",
                            "state",
                            "adoption",
                            "selected_dev_mse",
                            "rejected_candidates",
                            "preservation_rejections",
                            "arm_total_seconds",
                            "error",
                        )
                    }
                )
                write_json(out / "STUDY.json", record)
                print(json.dumps(record["trials"][-1], allow_nan=False), flush=True)
        record["state"] = (
            "completed"
            if all(row["state"] == "completed" for row in record["trials"])
            else "completed_with_failures"
        )
    except Exception as error:
        record.update(state="failed", error=type(error).__name__ + ": " + str(error))
        raise
    finally:
        record.update(
            study_wall_seconds=time.perf_counter() - started,
            study_cpu_seconds=time.process_time() - cpu_started,
            module_entry_wall_seconds=time.perf_counter() - _ENTRY_WALL,
            module_entry_cpu_seconds=time.process_time() - _ENTRY_CPU,
            wall_scope="all preparation, initialization, evaluated/rejected arms and artifact writes before final report; OS launch excluded",
        )
        write_json(out / "STUDY.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("output")
    parser.add_argument("--arm", choices=METHODS)
    parser.add_argument("--seed", type=int, choices=PLAN["seeds"])
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    result = run_study(args.csv, args.output, arm=args.arm, seed=args.seed)
    if result["state"] != "completed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
