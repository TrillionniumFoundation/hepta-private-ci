"""Qualification of the exact feedback runtime used for paid-action scoring."""

import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from ..native_adapter import Native
from . import feedback as f
from .feedback_study import archive_directory, write_json
from .runtime_feedback import FeedbackOwner, ZERO, file_sha


def _public(data, i, second=False):
    initial = float(data["initial_output"][i])
    public = {"initial": initial, "residuals": [float(data["self_evaluation"][i]) - initial],
        "variances": [float(data["sensor_variance"][i])],
        **{k: float(data[k][i]) for k in ("repair_cost", "wait_cost", "wait_variance")}}
    if second:
        public["residuals"].append(float(data["wait_evaluation"][i]) - initial)
        public["variances"].append(public["wait_variance"])
    return public


def qualify_seed(seed, prepared, output, native_binary, native_receipt, expected_model_sha256,
                 n=32, data_offset=90000000, *, development_only=False):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    model_file = Path(prepared) / "MODELS.json"
    if file_sha(model_file) != expected_model_sha256 or type(n) is not int or n < 2:
        raise ValueError("Frozen model and two or more histories required")
    model, output = json.loads(model_file.read_text()), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    if type(development_only) is not bool:
        raise ValueError("Explicit Boolean development qualification flag required")
    data = f.build_dataset(data_offset + seed, n, "development" if development_only else "runtime_confirmation")
    data.pop("target")
    np.savez_compressed(output / "PUBLIC.npz", **data)
    checks, records, stress = [], [], []
    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    with Native(native_binary, native_receipt) as native:
        for i, identity in enumerate(data["ids"]):
            owner = FeedbackOwner(output / "owners", [str(identity), "event"], f.digest(model), native)
            checkpoint = ZERO
            for stage in range(2):
                public = _public(data, i, bool(stage))
                mean, variance = f.posterior(model["calibration"], public)
                row = owner.step(public, mean, variance, stage + 1, expected_checkpoint=checkpoint)
                checkpoint = row["checkpoint_after"]
                check("actual reopened receiver", row["receiver_reopened_before_native"] and not row["encoder_residual_used_by_policy"])
                check("original native qualification", row["native"]["original_neuron_runtime"]
                      and row["native"]["legacy_runtime_confidence_ppm"] == 0 and row["native"]["abstain"])
                check("head probability mass", sum(row["native"]["head"]["probabilities_q24"]) == 1 << 24)
                check("analytic CDF numerical reference", row["native_cdf_error"] < 2e-15)
                records.append(row)
        # Independent delivery witness catches adapter rollback/corruption.
        public = _public(data, 0)
        mean, variance = f.posterior(model["calibration"], public)
        owner = FeedbackOwner(output / "owners", [str(data["ids"][0]), "stress"], f.digest(model), native)
        first = owner.step(public, mean, variance, 1)
        old_state = (owner.root / "state.json").read_bytes()
        second = owner.step(public, mean, variance, 2, expected_checkpoint=first["checkpoint_after"])
        new_state = (owner.root / "state.json").read_bytes()
        calls = native.calls
        for name, job in (
            ("stale CAS", lambda: owner.step(public, mean, variance, 3, expected_checkpoint=ZERO)),
            ("changed duplicate", lambda: owner.step({**public, "wait_cost": public["wait_cost"] + .01}, mean, variance, 1)),
        ):
            try:
                job()
            except ValueError:
                check(name + " rejected before native", native.calls == calls)
            else:
                raise AssertionError(name)
        for name, content in (("rollback", old_state), ("corruption", b"invalid")):
            (owner.root / "state.json").write_bytes(content)
            try:
                owner.step(public, mean, variance, 3, expected_checkpoint=second["checkpoint_after"])
            except (ValueError, KeyError):
                check(name + " rejected before native", native.calls == calls)
            else:
                raise AssertionError(name)
            finally:
                (owner.root / "state.json").write_bytes(new_state)
        stress.extend([first, second])
        for failure in ("after_pending", "after_native", "after_commit"):
            trial = FeedbackOwner(output / "owners", [str(data["ids"][0]), failure], f.digest(model), native)
            before = native.calls
            try:
                trial.step(public, mean, variance, 1, fail_stage=failure)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Expected interruption")
            if failure == "after_commit":
                saved = trial.step(public, mean, variance, 1)
                stress.append(saved)
                check("lost acknowledgement duplicate has no new tick", native.calls - before == 1)
            else:
                calls_after_failure = native.calls
                try:
                    trial.step(public, mean, variance, 1)
                except RuntimeError:
                    check(failure + " fails closed", native.calls == calls_after_failure)
                else:
                    raise AssertionError("Partial commit continued")
                check(failure + " expected native call count", native.calls - before == int(failure == "after_native"))
        in_process_cost = {"native_requests": native.calls, "native_ticks": native.original_sparse_ticks,
                           "native_roundtrip_ns": native.wall_ns}
    recoveries = []
    for sequence in (2, 3):
        job = {"root": str(output / "owners"), "identity": [str(data["ids"][0]), "event"],
               "public": _public(data, 0, True), "sequence": sequence,
               "expected_checkpoint": ZERO if sequence == 2 else records[1]["checkpoint_after"],
               "expected_model_sha256": expected_model_sha256}
        job_path, result_path = output / f"recovery_job_{sequence}.json", output / f"recovery_{sequence}.json"
        write_json(job_path, job)
        command = [sys.executable, "-m", "experiments.analytic_event_neuron.round3.runtime_feedback_study", "worker",
            "--model", str(model_file), "--job", str(job_path), "--output", str(result_path),
            "--native-binary", str(native_binary), "--native-receipt", str(native_receipt)]
        completed = subprocess.run(command, capture_output=True, text=True)
        if completed.returncode:
            raise RuntimeError(completed.stderr)
        recoveries.append(json.loads(result_path.read_text()))
    check("fresh process duplicate exact", recoveries[0]["receipt"] == records[1] and recoveries[0]["native_ticks"] == 0)
    check("fresh process continuation one native tick", recoveries[1]["native_ticks"] == 1
          and recoveries[1]["receipt"]["native"]["checkpoint_before"] == records[1]["native"]["checkpoint_after"])
    check("propagation silence is not terminal neutral", recoveries[1]["receipt"]["packet"]["counts"] == [0, 0]
          and recoveries[1]["receipt"]["law"] == records[1]["law"])
    with gzip.open(output / "FORECASTS.json.gz", "xt") as stream:
        json.dump({"ordinary": records, "stress": stress}, stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
    report = {"schema": "hepta.feedback-runtime-qualification.v3", "passed": True, "seed": seed,
        "checks": checks, "unique_histories": n, "ordinary_forecasts": 2 * n,
        "model_sha256": expected_model_sha256, "same_runtime_as_feedback_utility": True,
        "runtime_source_sha256": file_sha(Path(__file__).with_name("runtime_feedback.py")),
        "fresh_processes": 2, "recovery_native_ticks": sum(x["native_ticks"] for x in recoveries),
        "in_process_cost": in_process_cost, "owners": archive_directory(output / "owners"),
        "source_or_density_retention_certificate": None, "production_promotion": False,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "cross_owner_atomicity": False}
    report["development_only"] = development_only
    write_json(output / "QUALIFICATION.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("worker",))
    for name in ("model", "job", "output", "native-binary", "native-receipt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    job, model = json.loads(Path(args.job).read_text()), json.loads(Path(args.model).read_text())
    if file_sha(args.model) != job.pop("expected_model_sha256"):
        raise ValueError("Changed model")
    with Native(args.native_binary, args.native_receipt) as native:
        owner = FeedbackOwner(job.pop("root"), job.pop("identity"), f.digest(model), native)
        mean, variance = f.posterior(model["calibration"], job["public"])
        row = owner.step(mean=mean, variance=variance, **job)
        result = {"receipt": row, "native_ticks": native.original_sparse_ticks,
                  "native_requests": native.calls, "native_roundtrip_ns": native.wall_ns}
    write_json(args.output, result)
