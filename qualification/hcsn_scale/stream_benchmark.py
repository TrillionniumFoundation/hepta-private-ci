"""One bounded real-sensor comparison using existing preparation and probe code.

All arms receive identical chronological windows and known query durations.
Development scores select among three saved checkpoints; test is scored once
after selection. This is a CPU reference study, not a foundation-model benchmark.
"""

import argparse
import copy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import resource
import sys
import time

import numpy as np
import torch

from qualification.hcsn_adaptive.real_sensor_data import read_rows, make_splits
from .model import ModelConfig, SequenceModel, tensor_map_digest
from .stream_baselines import KINDS, StreamBaseline, matched_width
from .train import ridge_probe, probe_prediction

HCSN_ARMS = (
    "hcsn_feedback",
    "hcsn_no_feedback",
    "hcsn_drop_value_risk",
    "hcsn_ordinary_tanh",
)
ARMS = HCSN_ARMS + KINDS
DEFAULT_PLAN = {
    "schema": "hcsn-stream-integration-study-v1",
    "seeds": [181391, 284729, 395201],
    "arms": list(ARMS),
    "steps": 64,
    "checkpoints": [0, 32, 64],
    "batch_size": 8,
    "max_train_windows": 128,
    "max_dev_windows": 64,
    "sequence_length": 16,
    "learning_rate": 0.003,
    "ridge": 0.001,
    "parameter_target": 600,
    "parameter_relative_tolerance": 0.15,
    "persistent_state_cap_bytes": 8192,
    "arm_wall_cap_seconds": 900.0,
    "dtype": "float64",
    "threads": 1,
    "device": "cpu",
    "selection": "minimum development occupancy-probe MSE; includes step zero",
    "quality_targets_dev_mse": [0.15, 0.10, 0.05],
    "preparation": "UCI864 existing chronological split, purged disjoint windows; train-only normalization",
    "sampling": "evenly spaced window indices, independent of labels",
    "parameter_comparison": "encoder plus SSL head band; selected ridge probe and total parameters reported separately",
    "state_comparison": "common upper cap, actual state bytes reported; not identical state capacity",
    "time_comparison": "same update and example caps; inner work wall excludes startup; launcher measures cold lifecycle",
    "wall_budget_semantics": "soft work-wall budget checked before admitting each update; required evaluation and serialization may overrun",
}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def validate_plan(plan):
    if (
        plan.get("dtype") != "float64"
        or plan.get("device") != "cpu"
        or plan.get("threads") != 1
    ):
        raise ValueError("this study implements single-thread CPU FP64 only")
    for key, lower, upper in (
        ("steps", 1, 4096),
        ("batch_size", 1, 256),
        ("sequence_length", 2, 128),
        ("max_train_windows", 8, 4096),
        ("max_dev_windows", 4, 4096),
        ("parameter_target", 64, 100000),
        ("persistent_state_cap_bytes", 64, 1048576),
    ):
        if type(plan.get(key)) is not int or not lower <= plan[key] <= upper:
            raise ValueError("invalid bounded study field: " + key)
    if (
        not plan["checkpoints"]
        or plan["checkpoints"] != sorted(set(plan["checkpoints"]))
        or plan["checkpoints"][0] != 0
        or plan["checkpoints"][-1] != plan["steps"]
        or len(plan["checkpoints"]) > 16
        or any(
            type(v) is not int or not 0 <= v <= plan["steps"]
            for v in plan["checkpoints"]
        )
    ):
        raise ValueError("ordered checkpoint schedule must include zero and final step")
    for key, low, high in (
        ("learning_rate", 0.0, 1.0),
        ("ridge", 0.0, 1.0),
        ("arm_wall_cap_seconds", 0.0, 7200.0),
        ("parameter_relative_tolerance", 0.0, 0.15),
    ):
        value = plan.get(key)
        if (
            type(value) not in (float, int)
            or not np.isfinite(value)
            or not low < value <= high
        ):
            raise ValueError("invalid study numeric field: " + key)
    if (
        not plan["arms"]
        or len(plan["arms"]) != len(set(plan["arms"]))
        or any(arm not in ARMS for arm in plan["arms"])
        or not plan["seeds"]
        or len(plan["seeds"]) > 16
        or len(plan["seeds"]) != len(set(plan["seeds"]))
        or any(type(seed) is not int or not 0 <= seed < 2**31 for seed in plan["seeds"])
    ):
        raise ValueError("invalid arm or seed set")
    if not plan["quality_targets_dev_mse"] or any(
        type(v) not in (float, int) or not np.isfinite(v) or v <= 0
        for v in plan["quality_targets_dev_mse"]
    ):
        raise ValueError("finite positive development quality targets required")


def prepare_data(csv_path, plan):
    splits, contract = make_splits(
        *read_rows(Path(csv_path).read_bytes()), length=plan["sequence_length"]
    )
    scale = float(np.median(splits["train"]["dt"]))
    for name, cap in (
        ("train", plan["max_train_windows"]),
        ("dev", plan["max_dev_windows"]),
    ):
        data = splits[name]
        indices = np.linspace(
            0, len(data["x"]) - 1, min(cap, len(data["x"])), dtype=np.int64
        )
        splits[name] = {key: value[indices] for key, value in data.items()}
    return splits, contract, scale


def make_model(arm, input_size, scale, target, seed, *, sequence_length=16):
    if arm not in ARMS:
        raise ValueError("unknown declared arm")
    if arm in HCSN_ARMS:
        choices = []
        for width in range(2, 33):
            config = ModelConfig(
                "hcsn",
                input_size,
                width,
                scale,
                write_law="continuous_write",
                write_rate=1.0 / scale,
                feedback_mode="all" if arm != "hcsn_no_feedback" else "none",
                feature_bank={
                    "hcsn_drop_value_risk": "drop_value_risk",
                    "hcsn_ordinary_tanh": "ordinary_tanh",
                }.get(arm, "same_generator"),
                pooling="exposure",
            )
            model = SequenceModel(config)
            count = sum(p.numel() for p in model.parameters())
            choices.append((abs(count - target), width, config))
        _, _, config = min(choices, key=lambda row: row[:2])
        torch.manual_seed(seed)
        model = SequenceModel(config)
        state_bytes = model.encoder.initial_state(1).tensor_bytes()
        identity = {
            **model.identity(),
            "arm": arm,
            "parameters": sum(p.numel() for p in model.parameters()),
            "persistent_state_bytes_per_stream": state_bytes,
        }
    else:
        width, _ = matched_width(arm, input_size, scale, target)
        torch.manual_seed(seed)
        model = StreamBaseline(arm, input_size, width, scale)
        identity = model.identity(sequence_length=sequence_length)
    return model, identity


def encoder_features(model, data, batch_size=32):
    result, weighted_loss = [], 0.0
    for start in range(0, len(data["x"]), batch_size):
        windows = torch.as_tensor(
            data["x"][start : start + batch_size], dtype=torch.float64
        )
        features, loss = model.representations(
            windows, data["dt"][start : start + batch_size]
        )
        result.append(features.detach())
        weighted_loss += loss * len(windows)
    return torch.cat(result), weighted_loss / len(data["x"])


def run_arm(csv_path, output, plan, arm, seed):
    validate_plan(plan)
    if arm not in plan["arms"] or type(seed) is not int or seed not in plan["seeds"]:
        raise ValueError("arm and seed must be present in the declared plan")
    runtime = {
        "python": sys.version,
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "torch": str(torch.__version__),
        "numpy": np.__version__,
        "torch_threads": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    try:
        runtime["ncps"] = importlib.metadata.version("ncps")
    except importlib.metadata.PackageNotFoundError:
        runtime["ncps"] = None
    if (
        runtime["torch_threads"] != plan["threads"]
        or runtime["torch_interop_threads"] != plan["threads"]
        or not runtime["deterministic_algorithms"]
    ):
        raise ValueError(
            "run_arm requires actual single-thread deterministic Torch execution"
        )
    started, cpu_started = time.perf_counter(), time.process_time()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "PLAN.json", plan)
    record = {
        "schema": "hcsn-stream-integration-arm-v1",
        "arm": arm,
        "seed": seed,
        "state": "running",
        "stop_reason": None,
        "curve": [],
        "updates": [],
        "test_evaluations": 0,
        "runtime": runtime,
        "plan_sha256": hashlib.sha256((output / "PLAN.json").read_bytes()).hexdigest(),
        "plan_digest_scope": "exact saved PLAN.json UTF-8 bytes",
        "budget_semantics": "soft work-wall update admission; evaluations and final artifacts may overrun",
        "budget_limit_seconds": plan["arm_wall_cap_seconds"],
        "parameter_budget_scope": "encoder and SSL head; ridge probe reported separately",
        "no_update_cost_scope": "all performed training, selection and final work is charged even if step zero wins",
    }
    write_json(output / "RESULT.json", record)
    try:
        splits, contract, scale = prepare_data(csv_path, plan)
        train, dev = splits["train"], splits["dev"]
        record.update(
            data={
                "source_sha256": hashlib.sha256(
                    Path(csv_path).read_bytes()
                ).hexdigest(),
                "contract": contract,
                "used_windows": {k: len(v["x"]) for k, v in splits.items()},
                "train_ids": train["ids"].tolist(),
                "dev_ids": dev["ids"].tolist(),
            },
            clock_scale_seconds=scale,
        )
        model, identity = make_model(
            arm,
            train["x"].shape[-1],
            scale,
            plan["parameter_target"],
            seed,
            sequence_length=plan["sequence_length"],
        )
        record["model"] = identity
        runtime["model_parameter_devices"] = sorted(
            {str(p.device) for p in model.parameters()}
        )
        runtime["model_parameter_dtypes"] = sorted(
            {str(p.dtype) for p in model.parameters()}
        )
        floating_tensors = [
            *model.parameters(),
            *[b for b in model.buffers() if b.is_floating_point()],
        ]
        if any(
            t.device.type != "cpu" or t.dtype != torch.float64 for t in floating_tensors
        ):
            raise ValueError(
                "actual model parameters and floating buffers must be CPU FP64"
            )
        if (
            abs(identity["parameters"] - plan["parameter_target"])
            / plan["parameter_target"]
            > plan["parameter_relative_tolerance"]
            or identity["persistent_state_bytes_per_stream"]
            > plan["persistent_state_cap_bytes"]
        ):
            raise ValueError("declared parameter/state cap violated")
        record["initial_parameters_sha256"] = tensor_map_digest(
            dict(model.named_parameters())
        )
        optimizer = torch.optim.Adam(model.parameters(), lr=plan["learning_rate"])
        generator = torch.Generator().manual_seed(seed ^ 0x539)
        ty = torch.as_tensor(train["y"], dtype=torch.float64)
        dy = torch.as_tensor(dev["y"], dtype=torch.float64)
        best = None

        def evaluate(step):
            nonlocal best
            began = time.perf_counter()
            model.eval()
            train_features, train_ssl = encoder_features(model, train)
            dev_features, dev_ssl = encoder_features(model, dev)
            probe, mse = ridge_probe(
                train_features, ty, dev_features, dy, plan["ridge"]
            )
            point = {
                "step": step,
                "train_ssl_mse": train_ssl,
                "dev_ssl_mse": dev_ssl,
                "dev_probe_mse": mse,
                "evaluation_seconds": time.perf_counter() - began,
                "elapsed_seconds": time.perf_counter() - started,
                "parameters_sha256": tensor_map_digest(dict(model.named_parameters())),
                "probe_parameters": probe["weights"].numel(),
            }
            record["curve"].append(point)
            if best is None or mse < best["dev_mse"] - 1e-12:
                best = {
                    "step": step,
                    "dev_mse": mse,
                    "model": copy.deepcopy(model.state_dict()),
                    "probe": copy.deepcopy(probe),
                }
            write_json(output / "RESULT.json", record)
            model.train()

        evaluate(0)
        training_began = time.perf_counter()
        for step in range(1, plan["steps"] + 1):
            if time.perf_counter() - started > plan["arm_wall_cap_seconds"]:
                record["state"] = "wall_budget_exhausted"
                record["stop_reason"] = "soft_work_wall_budget_prevented_next_update"
                break
            indices = torch.randperm(len(train["x"]), generator=generator)[
                : plan["batch_size"]
            ]
            x = torch.as_tensor(train["x"][indices.numpy()], dtype=torch.float64)
            dt = train["dt"][indices.numpy()]
            tick = time.perf_counter()
            optimizer.zero_grad(set_to_none=True)
            loss = model.next_sensor_loss(x, dt)
            if not bool(torch.isfinite(loss)):
                raise FloatingPointError("nonfinite training objective")
            loss.backward()
            missing = [name for name, p in model.named_parameters() if p.grad is None]
            if missing or any(
                not bool(torch.isfinite(p.grad).all()) for p in model.parameters()
            ):
                raise FloatingPointError("missing/nonfinite gradients: " + str(missing))
            norm = float(
                torch.nn.utils.clip_grad_norm_(
                    model.parameters(), 1.0, error_if_nonfinite=True
                )
            )
            optimizer.step()
            record["updates"].append(
                {
                    "step": step,
                    "loss": float(loss.detach()),
                    "gradient_norm": norm,
                    "seconds": time.perf_counter() - tick,
                    "batch_ids": train["ids"][indices.numpy()].tolist(),
                }
            )
            if step in plan["checkpoints"]:
                evaluate(step)
        record["training_interval_seconds"] = time.perf_counter() - training_began
        record["training_interval_includes_scheduled_evaluations"] = True
        if record["state"] == "running":
            record["state"] = "completed"
            record["stop_reason"] = "scheduled_updates_completed"
        if best is None:
            raise RuntimeError("no complete development checkpoint")
        last_state = copy.deepcopy(model.state_dict())
        model.load_state_dict(best["model"])
        model.eval()
        record["selected_step"], record["selected_dev_mse"] = (
            best["step"],
            best["dev_mse"],
        )
        record["adoption"] = "NoUpdate" if best["step"] == 0 else "Candidate"
        record["selected_probe_parameters"] = best["probe"]["weights"].numel()
        record["selected_total_parameters"] = (
            identity["parameters"] + record["selected_probe_parameters"]
        )
        final_start = time.perf_counter()
        # One evaluation on all chronological held-out windows after dev selection.
        test = splits["test"]
        final_features, ssl = encoder_features(model, test)
        prediction = probe_prediction(best["probe"], final_features)
        targets = torch.as_tensor(test["y"], dtype=torch.float64)
        record["test_evaluations"] = 1
        record["final"] = {
            "mse": float((prediction - targets).square().mean()),
            "accuracy": float(
                (prediction.argmax(-1) == targets.argmax(-1)).double().mean()
            ),
            "next_sensor_mse": ssl,
            "windows": len(test["x"]),
            "seconds": time.perf_counter() - final_start,
        }
        np.savez_compressed(
            output / "predictions.npz",
            prediction=prediction.numpy(),
            targets=test["y"],
            ids=test["ids"],
        )
        torch.save(
            {
                "selected": best,
                "last_model": last_state,
                "last_optimizer": optimizer.state_dict(),
                "generator_state": generator.get_state(),
                "plan": plan,
                "identity": identity,
                "plan_sha256": record["plan_sha256"],
                "runtime": runtime,
            },
            output / "checkpoint.pt",
        )
        record["quality_target_first_seconds"] = {
            str(target): next(
                (
                    p["elapsed_seconds"]
                    for p in record["curve"]
                    if p["dev_probe_mse"] <= target
                ),
                None,
            )
            for target in plan["quality_targets_dev_mse"]
        }
    except Exception as error:
        record.update(
            state="failed",
            stop_reason="exception",
            error=type(error).__name__ + ": " + str(error),
        )
        raise
    finally:
        work_wall = time.perf_counter() - started
        record.update(
            wall_seconds=work_wall,
            work_wall_seconds=work_wall,
            work_wall_scope="run_arm after preflight to before final receipt write; excludes process/import startup",
            budget_overrun_seconds=max(0.0, work_wall - plan["arm_wall_cap_seconds"]),
            updates_completed=len(record["updates"]),
            cpu_seconds=time.process_time() - cpu_started,
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        )
        write_json(output / "RESULT.json", record)
    return record


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("csv")
    parser.add_argument("output")
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--plan")
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text()) if args.plan else DEFAULT_PLAN
    if args.arm not in plan["arms"] or args.seed not in plan["seeds"]:
        raise ValueError("arm and seed must be present in the declared plan")
    torch.set_num_threads(plan["threads"])
    torch.set_num_interop_threads(plan["threads"])
    torch.use_deterministic_algorithms(True)
    result = run_arm(args.csv, args.output, plan, args.arm, args.seed)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "arm",
                    "seed",
                    "state",
                    "selected_step",
                    "final",
                    "wall_seconds",
                )
            },
            allow_nan=False,
        )
    )


if __name__ == "__main__":
    main()
