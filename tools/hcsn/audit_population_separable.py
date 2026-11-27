#!/usr/bin/env python3
"""Exploratory space/time sensitivity of the three frozen smoke B checkpoints.

This external diagnostic first calls the unchanged baseline audit, preserving
its coverage, identity, budget, grid, test-byte and exact replay checks. It
does not retrain, select parameters, qualify resolution independence, or alter
the original 48-run denominator. All calculations use CPU FP32 as in that audit.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
from importlib import metadata
import io
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback


RECEIPT_SHA256 = "42d9224251fcee5e5a71f9da88542f72c06636fabd335986785b6fda7b412aae"
GRIDS = ((1, 1), (2, 1), (4, 1), (4, 2), (4, 4), (2, 2))
PAIRS = (((1, 1), (2, 1), "space"), ((2, 1), (4, 1), "space"),
         ((4, 1), (4, 2), "time"), ((4, 2), (4, 4), "time"),
         ((1, 1), (2, 2), "joint"), ((2, 2), (4, 4), "joint"),
         ((2, 1), (2, 2), "time"), ((2, 2), (4, 2), "space"))


def digest(data):
    return hashlib.sha256(data).hexdigest()


def snapshot(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in sorted(root.rglob("*.py"))}


def publish(path, record, *, initial=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name+".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if initial:
            os.link(name, path)
        else:
            os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def trace(encoder, readout, inputs, space_factor, time_factor):
    import torch
    from qualification.hcsn.population_torch import TorchPopulation

    original = encoder.population.config
    if (space_factor, time_factor) == (1, 1):
        config, population = original, encoder.population
    else:
        config = replace(original, bins=original.bins*space_factor,
                         dt=original.dt/time_factor,
                         refractory=original.effective_refractory)
        population = TorchPopulation(config).to(inputs.device)
    if not math.isclose(config.effective_refractory, original.effective_refractory,
                        rel_tol=0, abs_tol=1e-12):
        raise ValueError("effective refractory duration changed")
    state = population.initial_state((len(inputs), encoder.hidden_size))
    filtered = inputs.new_zeros(len(inputs), encoder.hidden_size)
    outputs = []
    mass_error = escape = 0.
    minimum_mass = 1.
    decay = math.exp(-config.dt/0.5)
    with torch.no_grad():
        for value in inputs.unbind(1):
            for _ in range(time_factor):
                drive = 6*torch.sigmoid(encoder.input(value)+encoder.recurrent(filtered))
                step = population(state, drive=drive)
                state = step.state
                filtered = decay*filtered+(1-decay)*step.rate
                mass_error = max(mass_error, float((state.total_mass()-1).abs().max()))
                escape = max(escape, float(state.escaped.max()))
                minimum_mass = min(minimum_mass, float(state.active.min()),
                                   float(state.refractory.min()), float(state.escaped.min()))
            outputs.append(filtered.clone())
        prediction = readout(filtered)
    outputs = torch.stack(outputs, 1)
    if not bool(torch.isfinite(outputs).all()) or not bool(torch.isfinite(prediction).all()):
        raise FloatingPointError("nonfinite refined trace or prediction")
    return prediction, outputs, dict(config=asdict(config),
        effective_refractory=config.effective_refractory,
        maximum_mass_error=mass_error, maximum_escape=escape, minimum_mass=minimum_mass)


def audit_separable(run, report, report_path, original_audit):
    import torch
    from qualification.hcsn.attempts import resolve_weights
    from qualification.hcsn.baselines import make_encoder
    from qualification.hcsn.benchmark import make_dataset

    config = report["config"]
    path = resolve_weights(report_path.with_suffix(".runs"), run)
    checkpoint_bytes = path.read_bytes()
    if digest(checkpoint_bytes) != run["best_checkpoint_sha256"]:
        raise ValueError("checkpoint changed after the original audit")
    saved = torch.load(io.BytesIO(checkpoint_bytes), map_location="cpu", weights_only=True)
    encoder = make_encoder(run["model"], 2, config["hidden_size"], dt=config["dt"])
    encoder.load_state_dict({key.removeprefix("encoder."): value
                            for key, value in saved["state_dict"].items()
                            if key.startswith("encoder.")}, strict=True)
    readout = torch.nn.Linear(config["hidden_size"], 1)
    readout.load_state_dict({key.removeprefix("readout."): value
                            for key, value in saved["state_dict"].items()
                            if key.startswith("readout.")}, strict=True)
    encoder.eval()
    readout.eval()
    x, y = make_dataset(run["task"], config["test_count"], config["length"], config["data_seed"]+2)
    test_hash = digest(x.tobytes()+y.tobytes())
    if test_hash != report["datasets"][run["task"]]["split_sha256"][2]:
        raise ValueError("held-out test split changed after the original audit")
    row = dict(task=run["task"], model=run["model"], seed=run["seed"],
               checkpoint_sha256=run["best_checkpoint_sha256"],
               test_split_sha256=test_hash, status="audited", grids=[], adjacent_pairs=[])
    values, legacy = {}, {item["factor"]: item for item in original_audit["resolutions"]}
    for space_factor, time_factor in GRIDS:
        predictions, outputs, measurements = [], [], []
        error = torch.zeros(())
        began = time.perf_counter()
        for offset in range(0, len(x), config["batch_size"]):
            inputs = torch.from_numpy(x[offset:offset+config["batch_size"]])
            prediction, output, metrics = trace(encoder, readout, inputs, space_factor, time_factor)
            if (space_factor, time_factor) == (1, 1):
                with torch.no_grad():
                    direct = encoder(inputs, dt=config["dt"])
                    direct_prediction = readout(direct[:, -1])
                torch.testing.assert_close(output, direct, rtol=0, atol=0)
                torch.testing.assert_close(prediction, direct_prediction, rtol=0, atol=0)
            error += (prediction-torch.from_numpy(y[offset:offset+len(inputs)])).square().sum()
            predictions.append(prediction)
            outputs.append(output)
            measurements.append(metrics)
        prediction, output = torch.cat(predictions), torch.cat(outputs)
        mse = float(error/y.size)
        values[space_factor, time_factor] = (output, prediction, mse)
        base_output, base_prediction, _ = values[1, 1]
        hidden_rms = float((output-base_output).square().mean().sqrt())
        prediction_rms = float((prediction-base_prediction).square().mean().sqrt())
        # Shared joint grids must reproduce the unchanged original audit;
        # this is an equivalence check, not a new convergence tolerance.
        if space_factor == time_factor:
            if mse != legacy[space_factor]["test_mse"]:
                raise ValueError("joint-grid MSE differs from the original audit")
            if hidden_rms != legacy[space_factor]["output_rms_change"]:
                raise ValueError("joint-grid hidden RMS differs from the original audit")
        row["grids"].append(dict(space_factor=space_factor, time_factor=time_factor,
            config=measurements[0]["config"], effective_refractory=measurements[0]["effective_refractory"],
            maximum_mass_error=max(v["maximum_mass_error"] for v in measurements),
            maximum_escape=max(v["maximum_escape"] for v in measurements),
            minimum_mass=min(v["minimum_mass"] for v in measurements), test_mse=mse,
            hidden_trace_rms_change_from_original=hidden_rms,
            final_prediction_rms_change_from_original=prediction_rms,
            diagnostic_wall_seconds=time.perf_counter()-began))
        print(json.dumps(dict(phase="grid_completed", seed=run["seed"],
                              space_factor=space_factor, time_factor=time_factor)), flush=True)
    for left, right, axis in PAIRS:
        left_output, left_prediction, left_mse = values[left]
        right_output, right_prediction, right_mse = values[right]
        row["adjacent_pairs"].append(dict(from_grid=list(left), to_grid=list(right),
            changed_axis=axis,
            hidden_trace_rms_difference=float((right_output-left_output).square().mean().sqrt()),
            final_prediction_rms_difference=float((right_prediction-left_prediction).square().mean().sqrt()),
            test_mse_change=right_mse-left_mse))
    row["factor_one_forward_exact"] = True
    row["shared_joint_grids_match_original_audit_exactly"] = True
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.repo_root.resolve()/"qualification/hcsn"
    result = dict(status="running", scope=__doc__, benchmark_sha256=RECEIPT_SHA256,
                  diagnostic_sha256=digest(Path(__file__).read_bytes()),
                  device="cpu", grids=[list(grid) for grid in GRIDS], records=[],
                  training_steps_performed=0, candidate_selection_performed=False,
                  original_denominator_preserved=True, research_qualification_pass=None,
                  limits=["Exploratory sensitivity only; no post-hoc passing threshold.",
                          "Smoke weights do not qualify full-budget B or task advantage.",
                          "External input is held over each original interval; recurrent drive is recomputed each substep, as in the original audit."])
    publish(args.output, result, initial=True)
    before = None
    began = time.perf_counter()
    try:
        receipt_bytes = args.benchmark.read_bytes()
        if digest(receipt_bytes) != RECEIPT_SHA256:
            raise ValueError("benchmark is not the complete byte-exact frozen smoke receipt")
        report = json.loads(receipt_bytes)
        before = snapshot(root)
        if before != report["source_files_sha256"]:
            raise ValueError("baseline source differs from the original smoke receipt")
        result.update(source_files_sha256=before,
                      original_accounting=report["accounting"],
                      original_attempt_accounting=report["attempt_accounting"],
                      original_run_records=len(report["runs"]))
        sys.path.insert(0, str(args.repo_root.resolve()))
        import torch
        from qualification.hcsn import audit_population
        if Path(audit_population.__file__).resolve().parent != root:
            raise RuntimeError("original auditor imported outside the frozen baseline")
        result["software"] = {name: metadata.version(name) for name in ("torch", "numpy", "scipy")}
        original_started = time.perf_counter()
        print(json.dumps(dict(phase="original_audit_started")), flush=True)
        original = audit_population.audit(args.benchmark)
        result.update(original_audit=original,
                      original_audit_wall_seconds=time.perf_counter()-original_started,
                      requested_b_runs=original["requested_b_runs"],
                      completed_b_runs=original["completed_b_runs"])
        publish(args.output, result)
        runs = {(row["task"], row["model"], row["seed"]): row for row in report["runs"]}
        for checked in original["records"]:
            if checked["status"] != "audited":
                result["records"].append(checked)
                continue
            identity = tuple(checked[key] for key in ("task", "model", "seed"))
            try:
                row = audit_separable(runs[identity], report, args.benchmark, checked)
            except Exception:
                row = dict(task=identity[0], model=identity[1], seed=identity[2],
                           status="failed", error=traceback.format_exc())
            result["records"].append(row)
            publish(args.output, result)
        result["audited_b_runs"] = sum(row["status"] == "audited" for row in result["records"])
        result["failed_b_audits"] = sum(row["status"] == "failed" for row in result["records"])
        result["status"] = ("failed" if result["failed_b_audits"] else
                            "unavailable" if not result["audited_b_runs"] else
                            "completed" if result["audited_b_runs"] == result["requested_b_runs"] else "partial")
    except ImportError:
        result.update(status="unavailable", error=traceback.format_exc())
    except Exception:
        result.update(status="failed", error=traceback.format_exc())
    finally:
        if before is not None:
            result["source_unchanged"] = snapshot(root) == before
            result["receipt_unchanged"] = digest(args.benchmark.read_bytes()) == RECEIPT_SHA256
            if not result["source_unchanged"] or not result["receipt_unchanged"]:
                result["status"] = "invalidated"
        result["diagnostic_wall_seconds"] = time.perf_counter()-began
        publish(args.output, result)
    return 0 if result["status"] == "completed" else 2 if result["status"] in ("unavailable", "partial") else 1


if __name__ == "__main__":
    raise SystemExit(main())
