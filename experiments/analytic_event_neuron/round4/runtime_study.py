"""Fresh training and actual paid-feedback execution with matched transport."""

import argparse
import gzip
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from ..native_adapter import Native
from ..round3 import feedback as previous
from ..runtime import digest
from .runtime_evidence import EvidenceZip, acquire, acquire_wait, transport, write_json
from .runtime_law import action_values, posterior
from .runtime_learning import ARMS, DATA_OFFSET, LEARNED, SEEDS, dataset, fit_dynamics, gaussian_dense
from .runtime_owner import Owner, ZERO, file_sha


REGISTRATION = {
    "seeds": list(SEEDS), "train_rows": 256, "development_rows": 128, "confirmation_rows": 256,
    "data_offset": DATA_OFFSET, "seed_rule": "offset+1000*seed+split; train1,development2,confirmation3,qualification4",
    "arms": list(ARMS), "native_components": "K2 event/direct/float/analytic/numeric/history; K1 gaussian/probit",
    "primary_noninferiority": [["event", "direct"], ["event", "float"]],
    "noninferiority_margin": .01, "all_seed_means_above_negative_margin": True,
    "family_alpha": .05, "primary_family_size": 2, "bootstrap_replicates": 4000, "bootstrap_seed": 641028,
    "secondary": [["analytic", "numeric"], ["analytic", "history"], ["event", "gaussian"], ["gaussian", "probit"]],
    "secondary_intervals": "descriptive95percent", "gauss_hermite_wait_nodes": 64,
    "superiority_not_required_of_equivalent_codec": True, "latency_and_byte_results_separate": True,
    "codec_mean_logvariance_bits": 12, "codec_mixture_weight_bits": 24,
    "positive_release_minimum_count": 1, "release_absolute_error_bound_relative_to_native_mixture": 3 / (1 << 24),
    "all_actual_native_calls_replayed": True, "production_promotion": False,
}


def load_data(path):
    with np.load(path, allow_pickle=False) as source:
        return {k: source[k].item() if source[k].ndim == 0 else source[k] for k in source.files}


def _native_paths(run_dir):
    root = Path(run_dir) / "native"
    return root / "analytic_event", root / "BUILD_RECEIPT.json"


def _law(model, public, arm):
    prior = model["gaussian_prior"] if arm in ("gaussian", "probit") else model["prior"]
    if arm == "probit":
        return gaussian_dense(prior, public["residuals"], public["variances"], model["calibration"]["noise_scale"])
    return posterior(prior, public["residuals"], public["variances"], model["calibration"]["noise_scale"])


def _training_scope(data, model, native, output, split):
    archive, rows = EvidenceZip(output / (split + ".zip")), []
    for i, identity in enumerate(data["ids"]):
        directory = output / "working_case"
        delivery = transport(directory, "runtime4_" + split)
        case = str(identity)
        public = acquire(data, i, "shared", delivery)
        owner = Owner(directory / "owners", [case, "shared"], digest(model), native)
        stages, checkpoint = [], ZERO
        for stage in range(2):
            if stage:
                public = acquire_wait(data, i, "shared", delivery, public)
            receipt = owner.step(public, _law(model, public, "event"), stage + 1, expected_checkpoint=checkpoint)
            checkpoint, law = receipt["checkpoint_after"], receipt["law"]
            values = action_values(law["conditional_law"], public, model["calibration"]["noise_scale"])
            features, native_rows = {}, {}
            for arm in LEARNED:
                vector, actual = previous.feature(public, law, arm, model["calibration"], native, case + f"/stage{stage}/{arm}")
                features[arm], native_rows[arm] = vector.tolist(), actual
            delivered = delivery.deliver(case, "shared", f"potential{stage}", public["initial"] + values["repair_amount"], "supervised_potential")
            error = public["initial"] - float(data["target"][i])
            gain = error ** 2 - (delivered - float(data["target"][i])) ** 2 - public["repair_cost"]
            stages.append({"public": public, "runtime": receipt, "features": features, "native": native_rows,
                           "values": values, "realized_gain": gain, "stop_utility": 1 - error ** 2})
        delivery.save_receipts()
        rows.append({"case": case, "stages": stages})
        archive.append(directory, f"case-{i}")
    return rows, archive.finish()


def prepare_seed(run_dir, seed, train_n=256, dev_n=128):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(run_dir) / "runtime_prepared" / f"seed_{seed}"
    output.mkdir(parents=True, exist_ok=False)
    train, dev = dataset(seed, train_n, "train"), dataset(seed, dev_n, "development")
    np.savez_compressed(output / "TRAIN.npz", **train)
    np.savez_compressed(output / "DEVELOPMENT.npz", **dev)
    model, dynamics = fit_dynamics(train)
    with Native(*_native_paths(run_dir)) as native:
        train_rows, train_archive = _training_scope(train, model, native, output, "train")
        dev_rows, dev_archive = _training_scope(dev, model, native, output, "development")
        costs = {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}
        binary_sha = native.receipt["binary_sha256"]
    train_gain = np.asarray([s["realized_gain"] for row in train_rows for s in row["stages"]])
    dev_gain = np.asarray([[r["stages"][0]["realized_gain"], r["stages"][1]["realized_gain"], r["stages"][0]["public"]["wait_cost"]] for r in dev_rows])
    dev_wait = np.asarray([r["stages"][0]["values"]["wait_gain"] for r in dev_rows])
    dev_stop = np.asarray([r["stages"][0]["stop_utility"] for r in dev_rows])
    heads, fits = {}, {}
    for arm in LEARNED:
        x = np.asarray([s["features"][arm] for row in train_rows for s in row["stages"]])
        z = np.asarray([s["features"][arm] for row in dev_rows for s in row["stages"]])
        heads[arm], fits[arm] = previous.fit_head(x, train_gain, z, dev_gain, dev_wait, dev_stop)
    model.update(schema="hepta.packed-feedback.models.v4", seed=seed, heads=heads,
                 native_binary_sha256=binary_sha, training_ids_sha256=digest(train["ids"].tolist()),
                 development_ids_sha256=digest(dev["ids"].tolist()))
    write_json(output / "MODELS.json", model)
    with gzip.open(output / "TRAINING_ROWS.json.gz", "xt") as stream:
        json.dump({"train": train_rows, "development": dev_rows}, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    report = {"seed": seed, "dynamics": dynamics, "fits": fits, "native": costs,
              "training_archive": train_archive, "development_archive": dev_archive,
              "model_file_sha256": file_sha(output / "MODELS.json"), "training_rows_sha256": file_sha(output / "TRAINING_ROWS.json.gz"),
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
              "train_rows": train_n, "development_rows": dev_n, "prior_confirmation_used": False}
    write_json(output / "TRAINING_RECEIPT.json", report)
    return report


def evaluate_public(model, data, native, output):
    expected = {"initial_output", "self_evaluation", "wait_evaluation", "sensor_variance", "wait_variance",
                "repair_cost", "wait_cost", "ids", "seed", "split", "law"}
    if set(data) != expected or data["split"] != "confirmation" or model["native_binary_sha256"] != native.receipt["binary_sha256"]:
        raise ValueError("Policy worker accepts exact target-free confirmation schema and frozen executable")
    archive, rows = EvidenceZip(output / "execution.zip"), []
    rng = np.random.default_rng(DATA_OFFSET + int(data["seed"]) + 99)
    for i, identity in enumerate(data["ids"]):
        # Paired random arm order limits systematic warm-cache/timing order bias.
        for arm in rng.permutation(ARMS):
            started, cpu = time.perf_counter_ns(), time.process_time_ns()
            case, arm = str(identity), str(arm)
            directory = output / "working_case"
            delivery = transport(directory, "runtime4_confirmation")
            public = acquire(data, i, arm, delivery)
            mode = arm if arm in ("event", "direct", "float") else "float" if arm in ("gaussian", "probit") else "event"
            owner = Owner(directory / "owners", [case, arm], digest(model), native, mode)
            stages, checkpoint, cost = [], ZERO, 0.0
            before_calls, before_ticks, before_ipc = native.calls, native.original_sparse_ticks, native.wall_ns
            for stage in range(2):
                if stage:
                    public = acquire_wait(data, i, arm, delivery, public)
                receipt = owner.step(public, _law(model, public, arm), stage + 1, expected_checkpoint=checkpoint)
                checkpoint, law = receipt["checkpoint_after"], receipt["law"]
                values = action_values(law["conditional_law"], public, model["calibration"]["noise_scale"])
                vector, feature_rows = previous.feature(public, law, arm, model["calibration"], native, case + f"/stage{stage}/{arm}") if arm in LEARNED else (None, [])
                repair = values["repair_gain"] if vector is None else float(np.dot(vector, model["heads"][arm]["weights"])) + model["heads"][arm]["offset"]
                scores = {"stop": 0.0, "repair": repair}
                if stage == 0:
                    scores["wait"] = values["wait_gain"]
                choice = max(scores, key=scores.get)
                stages.append({"public": public, "runtime": receipt, "values": values, "scores": scores,
                               "feature": None if vector is None else vector.tolist(), "native": feature_rows,
                               "action": choice, "decision_ns": time.perf_counter_ns()})
                cost += public["wait_cost"] if choice == "wait" else public["repair_cost"] if choice == "repair" else 0.0
                if choice != "wait":
                    break
            final = public["initial"] + (values["repair_amount"] if choice == "repair" else 0.0)
            delivered = delivery.deliver(case, arm, "final", final, choice)
            final_readback_ns = time.perf_counter_ns()
            delivery_cost = delivery.save_receipts()
            rows.append({"case": case, "arm": arm, "stages": stages, "actions": [s["action"] for s in stages],
                         "delivered": delivered, "cost": cost, "final_readback_ns": final_readback_ns,
                         "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                         "packet_bytes": sum(s["runtime"]["packet_bytes"] for s in stages),
                         "native_requests": native.calls - before_calls, "native_ticks": native.original_sparse_ticks - before_ticks,
                         "native_roundtrip_ns": native.wall_ns - before_ipc, "transport": delivery_cost})
            archive.append(directory, f"case-{i}/{arm}")
    return rows, archive.finish()


def confirm_seed(run_dir, seed, n=256):
    from .freeze import verify
    verify(run_dir)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(run_dir) / "runtime_confirmation" / f"seed_{seed}"
    output.mkdir(parents=True, exist_ok=False)
    model_file = Path(run_dir) / "runtime_prepared" / f"seed_{seed}" / "MODELS.json"
    data = dataset(seed, n, "confirmation")
    np.savez_compressed(output / "DATA.npz", **data)
    np.savez_compressed(output / "PUBLIC.npz", **{k: v for k, v in data.items() if k != "target"})
    command = [sys.executable, "-m", __name__, "worker", "--run-dir", str(run_dir), "--seed", str(seed)]
    command[2] = "experiments.analytic_event_neuron.round4.runtime_study"
    completed = subprocess.run(command, capture_output=True, text=True)
    (output / "WORKER.stdout.log").write_text(completed.stdout)
    (output / "WORKER.stderr.log").write_text(completed.stderr)
    if completed.returncode:
        raise RuntimeError("Policy subprocess failed; raw partial evidence retained: " + completed.stderr)
    with gzip.open(output / "PUBLIC_ROWS.json.gz", "rt") as stream:
        rows = json.load(stream)
    indexes = {str(identity): i for i, identity in enumerate(data["ids"])}
    for row in rows:
        target = float(data["target"][indexes[row["case"]]])
        row.update(target=target, squared_error=(row["delivered"] - target) ** 2,
                   utility=1 - (row["delivered"] - target) ** 2 - row["cost"], score_started_ns=time.perf_counter_ns())
    with gzip.open(output / "ROWS.json.gz", "xt") as stream:
        json.dump(rows, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    worker = json.loads((output / "WORKER.json").read_text())
    summary = {arm: {key: float(np.mean([r[key] for r in rows if r["arm"] == arm])) for key in
               ("utility", "squared_error", "cost", "wall_ns", "cpu_ns", "packet_bytes", "native_requests", "native_ticks", "native_roundtrip_ns")} for arm in ARMS}
    report = {"seed": seed, "independent_trajectories": n, "executions": len(rows), "summary": summary, "worker": worker,
              "model_file_sha256": file_sha(model_file), "data_sha256": file_sha(output / "DATA.npz"), "rows_sha256": file_sha(output / "ROWS.json.gz"),
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
              "target_only_in_scoring_process_after_final_readback": True, "same_uid_hostile_isolation_claimed": False}
    write_json(output / "SUMMARY.json", report)
    verify(run_dir)
    return report


def worker(run_dir, seed):
    output = Path(run_dir) / "runtime_confirmation" / f"seed_{seed}"
    model = json.loads((Path(run_dir) / "runtime_prepared" / f"seed_{seed}" / "MODELS.json").read_text())
    data = load_data(output / "PUBLIC.npz")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    with Native(*_native_paths(run_dir)) as native:
        rows, archive = evaluate_public(model, data, native, output)
        costs = {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}
    with gzip.open(output / "PUBLIC_ROWS.json.gz", "xt") as stream:
        json.dump(rows, stream, sort_keys=True, separators=(",", ":"), allow_nan=False)
    write_json(output / "WORKER.json", {"archive": archive, "native": costs,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("prepare", "confirm", "worker", "qualify", "summary", "audit"))
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--seed", type=int)
    args = parser.parse_args()
    seeds = [args.seed] if args.seed is not None else SEEDS
    if args.operation == "summary":
        from .runtime_summary import summarize
        print(json.dumps(summarize(args.run_dir), sort_keys=True))
    else:
        for seed in seeds:
            if args.operation == "prepare":
                result = prepare_seed(args.run_dir, seed)
            elif args.operation == "confirm":
                result = confirm_seed(args.run_dir, seed)
            elif args.operation == "worker":
                result = worker(args.run_dir, seed)
            elif args.operation == "qualify":
                from .runtime_qualification import qualify
                result = qualify(args.run_dir, seed)
            else:
                from .runtime_audit import audit
                result = audit(args.run_dir, seed)
            print(json.dumps({"operation": args.operation, "seed": seed, "completed": True}, sort_keys=True), flush=True)
