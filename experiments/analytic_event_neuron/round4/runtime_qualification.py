"""Fresh-process recovery, explicit tail release, and actual calibration bridge."""

import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from ..native_adapter import Native
from ..runtime import digest
from .runtime_codec import MODES
from .runtime_evidence import EvidenceZip, write_json
from .runtime_law import Q24, make_law, posterior
from .runtime_learning import dataset, public_row
from .runtime_owner import Owner, ZERO, file_sha
from .runtime_study import _native_paths


REGISTRATION = {"histories_per_seed": 16, "modes": list(MODES), "ordinary_forecasts_per_seed": 96,
                "fresh_processes_per_seed": 6, "qualification_data_split_code": 4,
                "tail_fixture_laws": 4, "cross_track_calibration_fixtures_per_seed": 10,
                "cross_owner_atomicity_claimed": False, "hardware_energy_claimed": False}


def prepare_bridge(run_dir, seed):
    """Bind ten deterministic development queries, without confirmation labels."""
    from .. import task
    from . import calibration, calibration_study
    source = Path(run_dir) / "calibration_prepared" / f"seed_{seed}"
    paths = [source / name for name in ("window_01_CHECKPOINT.json", "window_01_NEW_DEV.npz", "window_01_NEW_DEV_CONTEXT.npz")]
    checkpoint = json.loads(paths[0].read_text())
    model = checkpoint["models"]["mixture_context"]
    data, context = calibration_study.load(paths[1]), calibration_study.load(paths[2])
    history = task.history(data)
    distribution = calibration.predict_distribution(model, history, context)
    rows = []
    for index in range(len(data["ids"])):
        law = calibration.law_at(distribution, index, 2)
        if all(abs(m) <= 8 for m in law["means"]) and all(2**-24 <= v <= 8 for v in law["variances"]):
            public_history = {key: history[key][index:index+1].tolist() for key in ("obs", "times", "mask", "occupied", "obs_var")}
            public_context = {key: context[key][8*index:8*(index+1)].tolist() for key in ("obs", "times", "mask", "occupied", "obs_var")}
            conditioning = {"history": public_history, "context": public_context, "physical_horizon": 1.0}
            rows.append({"row": index, "query_id": str(data["ids"][index]), "law": law, "physical_horizon": 1.0,
                         "conditioning": conditioning, "conditioning_sha256": digest(conditioning)})
        if len(rows) == 10:
            break
    if len(rows) != 10:
        raise ValueError("Insufficient valid deterministic development bridge laws")
    result = {"schema": "hepta.calibration-native-bridge.prepared.v4", "seed": seed,
              "source_files": {str(p.relative_to(Path(run_dir))): file_sha(p) for p in paths},
              "model_sha256": digest(model), "queries": rows,
              "calibration_physical_horizon_distinct_from_feedback_stage_clock": True}
    target = Path(run_dir) / "runtime_bridge_prepared"
    target.mkdir(exist_ok=True)
    write_json(target / f"seed_{seed}.json", result)
    return result


def qualify(run_dir, seed, *, development_only=False):
    from .freeze import verify
    if not development_only:
        verify(run_dir)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(run_dir) / ("runtime_qualification_development" if development_only else "runtime_qualification") / f"seed_{seed}"
    output.mkdir(parents=True, exist_ok=False)
    model = json.loads((Path(run_dir) / "runtime_prepared" / f"seed_{seed}" / "MODELS.json").read_text())
    data = dataset(seed, 16, "qualification" if not development_only else "development")
    data.pop("target")
    np.savez_compressed(output / "PUBLIC.npz", **data)
    checks, records, stress, recoveries = [], [], [], []
    def require(name, condition):
        if not condition:
            raise AssertionError(name)
        checks.append(name)
    with Native(*_native_paths(run_dir)) as native:
        first_owners = {}
        for mode in MODES:
            for i, identity in enumerate(data["ids"]):
                owner = Owner(output / "owners", [str(identity), mode], digest(model), native, mode)
                checkpoint = ZERO
                for stage in range(2):
                    public = public_row(data, i, bool(stage))
                    law = posterior(model["prior"], public["residuals"], public["variances"], model["calibration"]["noise_scale"])
                    row = owner.step(public, law, stage + 1, expected_checkpoint=checkpoint)
                    checkpoint = row["checkpoint_after"]
                    require("positive Q24 simplex", sum(row["law"]["probabilities_q24"]) == Q24 and min(row["law"]["probabilities_q24"]) >= 1)
                    require("native mixture probability used", row["law"]["native_vs_reference_max_absolute_error"] < 2e-15)
                    require("actual count receiver reopened", row["receiver_reopened_before_native"] and not row["policy_receives_encoder_residual"])
                    require("per-component original native execution", len(row["native"]) == len(law["weights"]) and all(r["original_neuron_runtime"] and r["abstain"] and r["legacy_runtime_confidence_ppm"] == 0 for r in row["native"]))
                    records.append(row)
                if i == 0:
                    first_owners[mode] = {"identity": [str(identity), mode], "row": row, "law": law, "public": public}
            public = public_row(data, 0)
            law = posterior(model["prior"], public["residuals"], public["variances"], model["calibration"]["noise_scale"])
            owner = Owner(output / "owners", ["stress", mode], digest(model), native, mode)
            first = owner.step(public, law, 1)
            old_state = (owner.root / "state.json").read_bytes()
            second = owner.step(public, law, 2, expected_checkpoint=first["checkpoint_after"])
            new_state = (owner.root / "state.json").read_bytes()
            before = native.calls
            for name, call in (
                ("stale CAS", lambda: owner.step(public, law, 3, expected_checkpoint=ZERO)),
                ("changed duplicate", lambda: owner.step({**public, "wait_cost": public["wait_cost"] + .01}, law, 1)),
            ):
                try:
                    call()
                except ValueError:
                    require(mode + name + " rejected before native", native.calls == before)
                else:
                    raise AssertionError(name)
            for name, payload in (("rollback", old_state), ("corruption", b"invalid")):
                (owner.root / "state.json").write_bytes(payload)
                try:
                    owner.step(public, law, 3, expected_checkpoint=second["checkpoint_after"])
                except (ValueError, KeyError):
                    require(mode + name + " rejected before native", native.calls == before)
                else:
                    raise AssertionError(name)
                finally:
                    (owner.root / "state.json").write_bytes(new_state)
            stress.extend([first, second])
            for failure in ("after_packet", "after_first_native", "after_native", "after_commit"):
                trial = Owner(output / "owners", [mode, failure], digest(model), native, mode)
                prior_calls = native.calls
                try:
                    trial.step(public, law, 1, fail_stage=failure)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("Expected injected interruption")
                if failure == "after_commit":
                    saved = trial.step(public, law, 1)
                    stress.append(saved)
                    require("cached lost acknowledgement no new calls", native.calls - prior_calls == 2)
                else:
                    after_failure = native.calls
                    try:
                        trial.step(public, law, 1)
                    except RuntimeError:
                        require("partial mixture commits fail closed", native.calls == after_failure)
                    else:
                        raise AssertionError("Unsafe pending continuation")
                    require("precise interrupted native call count", native.calls - prior_calls == {"after_packet": 0, "after_first_native": 1, "after_native": 2}[failure])
        tail_laws = [make_law([1], [7.5], [.0001]), make_law([1], [-7.5], [.0001]),
                     make_law([.5, .5], [-7.5, 7.5], [.0001, .0001]), make_law([.01, .99], [0, 7.5], [.0001, .01])]
        tail_rows = []
        for i, law in enumerate(tail_laws):
            owner = Owner(output / "owners", ["tail", i], digest(model), native)
            row = owner.step(public_row(data, 0), law, 1)
            require("finite physical extreme log tails", all(np.isfinite(row["law"]["physical_log_probabilities"])))
            require("finite released tail NLL cap", all(-np.log(p) <= np.log(Q24) for p in row["law"]["probabilities"]))
            require("native raw zero preserved as diagnostic", min(row["law"]["raw_probabilities_q24"]) == 0)
            tail_rows.append(row)
        bridge_path = Path(run_dir) / "runtime_bridge_prepared" / f"seed_{seed}.json"
        bridge_rows = []
        if bridge_path.exists():
            bridge = json.loads(bridge_path.read_text())
            diagnostic_context = {"initial": 0.0, "residuals": [0.0], "variances": [1.0],
                                  "repair_cost": .12, "wait_cost": .04, "wait_variance": .16}
            for i, query in enumerate(bridge["queries"]):
                require("calibration conditioning binding", query["conditioning_sha256"] == digest(query["conditioning"]))
                owner = Owner(output / "owners", ["calibration_bridge", i, query["conditioning_sha256"]], bridge["model_sha256"], native)
                row = owner.step(diagnostic_context, query["law"], 1)
                require("actual calibrated mixture reaches same native owner", len(row["native"]) == len(query["law"]["weights"]))
                bridge_rows.append({"query": query, "runtime": row,
                    "profile": "calibration prediction-head adapter; fixed diagnostic cost context is not the law conditioning history",
                    "feedback_utility_claimed_for_bridge": False})
        elif not development_only:
            raise FileNotFoundError("Frozen calibration-to-native bridge required")
        in_process = {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}
    for mode, item in first_owners.items():
        for sequence in (2, 3):
            job = {"root": str(output / "owners"), "identity": item["identity"], "mode": mode, "model_sha256": digest(model),
                   "public": item["public"], "law": item["law"], "sequence": sequence,
                   "expected_checkpoint": ZERO if sequence == 2 else item["row"]["checkpoint_after"]}
            path, result_path = output / f"job_{mode}_{sequence}.json", output / f"recovery_{mode}_{sequence}.json"
            write_json(path, job)
            completed = subprocess.run([sys.executable, "-m", "experiments.analytic_event_neuron.round4.runtime_qualification", "worker",
                "--run-dir", str(run_dir), "--job", str(path), "--output", str(result_path)], capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError(completed.stderr)
            result = json.loads(result_path.read_text())
            require("fresh process exact cached receipt", result["receipt"] == item["row"] and result["native"]["ticks"] == 0) if sequence == 2 else require("fresh process continuation two component ticks", result["native"]["ticks"] == 2 and result["receipt"]["law"] == item["row"]["law"])
            recoveries.append(result)
    archive = EvidenceZip(output / "owners.zip")
    archive.append(output / "owners", "owners")
    archive_receipt = archive.finish()
    with gzip.open(output / "FORECASTS.json.gz", "xt") as stream:
        json.dump({"ordinary": records, "stress": stress, "tails": tail_rows, "calibration_bridge": bridge_rows}, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report = {"passed": True, "seed": seed, "checks": checks, "histories": 16, "ordinary_forecasts": len(records),
              "fresh_processes": len(recoveries), "in_process_native": in_process,
              "fresh_process_native_ticks": sum(r["native"]["ticks"] for r in recoveries),
              "calibration_bridge_forecasts": len(bridge_rows), "tails": len(tail_rows), "archive": archive_receipt,
              "development_only": development_only, "cross_owner_atomicity": False, "production_promotion": False,
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu}
    write_json(output / "QUALIFICATION.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("worker", "bridge"))
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--job")
    parser.add_argument("--output")
    args = parser.parse_args()
    if args.operation == "bridge":
        print(json.dumps(prepare_bridge(args.run_dir, args.seed), sort_keys=True))
    else:
        job = json.loads(Path(args.job).read_text())
        with Native(*_native_paths(args.run_dir)) as native:
            owner = Owner(job.pop("root"), job.pop("identity"), job.pop("model_sha256"), native, job.pop("mode"))
            receipt = owner.step(**job)
            result = {"receipt": receipt, "native": {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}}
        write_json(args.output, result)
