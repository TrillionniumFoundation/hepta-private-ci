"""Train, execute public-only policies, then score paid-feedback outcomes."""

import argparse
import gzip
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

import numpy as np

from ..analytic import event_probs
from ..feedback_chain import _archive
from ..native_adapter import Native
from ..transport import ArtifactTransport
from . import feedback as f
from .runtime_feedback import FeedbackOwner, file_sha


def write_json(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def load_data(path):
    with np.load(path, allow_pickle=False) as source:
        return {k: source[k].item() if source[k].ndim == 0 else source[k] for k in source.files}


def archive_directory(directory):
    """Keep all bytes and verify each member before removing our temporary tree."""
    directory = Path(directory)
    target = directory.with_suffix(".tar.gz")
    if target.exists():
        raise FileExistsError(target)
    files = {str(p.relative_to(directory)): {"sha256": file_sha(p), "bytes": p.stat().st_size}
             for p in sorted(directory.rglob("*")) if p.is_file()}
    write_json(directory / "MANIFEST.json", {"files": files})
    with tarfile.open(target, "w:gz") as tar:
        tar.add(directory, arcname=directory.name)
    with tarfile.open(target, "r:gz") as tar:
        seen = set()
        for member in tar:
            if member.isfile():
                rel = str(Path(member.name).relative_to(directory.name))
                content = tar.extractfile(member).read()
                if rel != "MANIFEST.json":
                    import hashlib
                    if files[rel] != {"sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content)}:
                        raise ValueError("Archive verification failed")
                    seen.add(rel)
        if seen != set(files):
            raise ValueError("Incomplete archive")
    receipt = {"path": target.name, "sha256": file_sha(target), "bytes": target.stat().st_size,
               "verified_files": len(files) + 1, "all_members_verified_before_removal": True}
    shutil.rmtree(directory)
    return receipt


def acquire(data, i, arm, transport):
    case = str(data["ids"][i])
    initial = transport.deliver(case, arm, "initial", float(data["initial_output"][i]), "preview")
    sensor = transport.observer(case, arm, "sensor", float(data["self_evaluation"][i]))
    values = {k: transport.observer(case, arm, k, float(data[k][i])) for k in
              ("sensor_variance", "repair_cost", "wait_variance", "wait_cost")}
    residual = transport.deliver(case, arm, "residual", sensor - initial, "public_feedback")
    return {"initial": initial, "residuals": [residual], "variances": [values.pop("sensor_variance")], **values}


def acquire_wait(data, i, arm, transport, public):
    case = str(data["ids"][i])
    sensor = transport.observer(case, arm, "wait_sensor", float(data["wait_evaluation"][i]))
    residual = transport.deliver(case, arm, "wait_residual", sensor - public["initial"], "paid_feedback")
    return {**public, "residuals": [*public["residuals"], residual],
            "variances": [*public["variances"], public["wait_variance"]]}


def _training_scope(data, calibration, native, output, split):
    transport = ArtifactTransport(output / (split + "_readbacks"), "feedback3_" + split)
    owners, scopes = output / (split + "_owners"), []
    for i, identity in enumerate(data["ids"]):
        case = str(identity)
        public = acquire(data, i, "shared", transport)
        owner = FeedbackOwner(owners, case, f.digest(calibration), native)
        stages, checkpoint = [], "0" * 64
        for stage in range(2):
            if stage:
                public = acquire_wait(data, i, "shared", transport, public)
            mean, variance = f.posterior(calibration, public)
            runtime = owner.step(public, mean, variance, stage + 1, expected_checkpoint=checkpoint)
            checkpoint, law = runtime["checkpoint_after"], runtime["law"]
            vectors, native_rows = {}, {}
            for arm in f.LEARNED:
                vector, rows = f.feature(public, law, arm, calibration, native, case + f"/stage{stage}")
                vectors[arm], native_rows[arm] = vector.tolist(), rows
            values = f.action_values(law["mean"], law["variance"], public, calibration)
            delivered = transport.deliver(case, "shared", f"potential_{stage}",
                public["initial"] + values["repair_amount"], "supervised_potential")
            target = float(data["target"][i])
            stop = 1 - (public["initial"] - target) ** 2
            gain = (public["initial"] - target) ** 2 - (delivered - target) ** 2 - public["repair_cost"]
            stages.append({"public": public, "law": law, "runtime": runtime, "vectors": vectors,
                "native": native_rows, "realized_gain": gain, "stop_utility": stop, "values": values})
        scopes.append({"case": case, "stages": stages})
    return scopes, {"readbacks": _archive(transport), "owners": archive_directory(owners)}


def prepare_seed(seed, output, native_binary, native_receipt, train_n=512, dev_n=256, data_offset=80000000):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    train = f.build_dataset(data_offset + 100 * seed + 1, train_n, "train")
    dev = f.build_dataset(data_offset + 100 * seed + 2, dev_n, "development")
    np.savez_compressed(output / "TRAIN.npz", **train)
    np.savez_compressed(output / "DEVELOPMENT.npz", **dev)
    error = train["target"] - train["initial_output"]
    alpha = float(np.mean(error ** 2))
    residual = train["self_evaluation"] - train["target"]
    residual2 = train["wait_evaluation"] - train["target"]
    scale = float(np.mean(np.concatenate((residual ** 2 / train["sensor_variance"], residual2 ** 2 / train["wait_variance"]))))
    raw = []
    for i in range(train_n):
        public = {"residuals": [float(train["self_evaluation"][i] - train["initial_output"][i])],
                  "variances": [float(train["sensor_variance"][i])], "repair_cost": float(train["repair_cost"][i])}
        raw.append(f.raw_features(public))
        public["residuals"].append(float(train["wait_evaluation"][i] - train["initial_output"][i]))
        public["variances"].append(float(train["wait_variance"][i]))
        raw.append(f.raw_features(public))
    raw = np.asarray(raw)
    center, spread = raw.mean(0), np.maximum(raw.std(0), 1e-8)
    calibration = {"error_variance": alpha, "noise_scale": scale,
        "public_center": center.tolist(), "public_scale": spread.tolist(),
        "history_centers": ((raw - center) / spread)[np.linspace(0, len(raw) - 1, 43).astype(int)].tolist(),
        "event_mean_step": f.STEP, "event_log_variance_step": f.STEP,
        "fit": "supervised Gaussian variance maximum likelihood; training only"}
    with Native(native_binary, native_receipt) as native:
        train_rows, train_archive = _training_scope(train, calibration, native, output, "train")
        dev_rows, dev_archive = _training_scope(dev, calibration, native, output, "development")
        native_cost = {"requests": native.calls, "ticks": native.original_sparse_ticks, "roundtrip_ns": native.wall_ns}
        binary_sha = native.receipt["binary_sha256"]
    heads, receipts = {}, {}
    train_gain = np.asarray([s["realized_gain"] for row in train_rows for s in row["stages"]])
    dev_gain = np.asarray([[row["stages"][0]["realized_gain"], row["stages"][1]["realized_gain"],
                           row["stages"][0]["public"]["wait_cost"]] for row in dev_rows])
    dev_wait = np.asarray([row["stages"][0]["values"]["wait_gain"] for row in dev_rows])
    dev_stop = np.asarray([row["stages"][0]["stop_utility"] for row in dev_rows])
    for arm in f.LEARNED:
        x = np.asarray([s["vectors"][arm] for row in train_rows for s in row["stages"]])
        z = np.asarray([s["vectors"][arm] for row in dev_rows for s in row["stages"]])
        heads[arm], receipts[arm] = f.fit_head(x, train_gain, z, dev_gain, dev_wait, dev_stop)
    model = {"schema": "hepta.paid-feedback.models.v3", "seed": seed, "calibration": calibration,
        "heads": heads, "native_binary_sha256": binary_sha,
        "train_ids_sha256": f.digest(train["ids"].tolist()), "dev_ids_sha256": f.digest(dev["ids"].tolist()),
        "all_memory_ablation_repair_amplitudes": "same event receiver and native Q24 mean",
        "wait_value": "Gaussian future optimal-repair plug-in; learned follow-up need not equal that reference"}
    write_json(output / "MODELS.json", model)
    with gzip.open(output / "TRAINING_ROWS.json.gz", "xt") as stream:
        json.dump({"train": train_rows, "development": dev_rows}, stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
    receipt = {"seed": seed, "model_sha256": file_sha(output / "MODELS.json"),
        "model_document_sha256": f.digest(model), "heads": receipts, "native": native_cost,
        "calibration_initial": [1.0, 1.0], "calibration_final": [alpha, scale],
        "train_archive": train_archive, "development_archive": dev_archive,
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "train_rows": train_n, "development_rows": dev_n, "prior_confirmation_used": False}
    write_json(output / "TRAINING_RECEIPT.json", receipt)
    return receipt


def evaluate_public(model, data, native, output, *, development_only=False):
    required = {"initial_output", "self_evaluation", "wait_evaluation", "sensor_variance", "wait_variance",
                "repair_cost", "wait_cost", "ids", "seed", "split", "law"}
    required_split = "development" if development_only else "confirmation"
    if type(development_only) is not bool or set(data) != required or data["split"] != required_split:
        raise ValueError("Policy worker accepts only the exact target-free confirmation schema")
    if model["native_binary_sha256"] != native.receipt["binary_sha256"]:
        raise ValueError("Frozen model uses a different native executable")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = Path(output)
    transport = ArtifactTransport(output / "readbacks", "feedback3_confirmation")
    rows, model_sha = [], f.digest(model)
    for arm in f.ARMS:
        for i, identity in enumerate(data["ids"]):
            began, case = time.perf_counter_ns(), str(identity)
            public = acquire(data, i, arm, transport)
            owner = None if arm in ("gaussian", "probit") else FeedbackOwner(output / "owners", [case, arm], model_sha,
                native, "direct_quantization" if arm == "quantized" else "error_feedback")
            stages, checkpoint, cost, actions = [], "0" * 64, 0.0, []
            for stage in range(2):
                mean, variance = f.posterior(model["calibration"], public, dense=arm == "probit")
                runtime = None
                if owner is not None:
                    runtime = owner.step(public, mean, variance, stage + 1, expected_checkpoint=checkpoint)
                    checkpoint, law = runtime["checkpoint_after"], runtime["law"]
                else:
                    threshold = np.sqrt(public["repair_cost"])
                    law = {"mean": mean, "variance": variance,
                           "probabilities": event_probs(mean, variance, -threshold, threshold).tolist(), "native_quantized": False}
                vector, native_rows = f.feature(public, law, arm, model["calibration"], native, case + f"/stage{stage}")
                action, values, scores = f.choose(model, arm, public, law, vector)
                stages.append({"public": public, "law": law, "runtime": runtime, "native": native_rows,
                    "feature": None if vector is None else vector.tolist(), "action": action,
                    "values": values, "scores": scores, "decision_ns": time.perf_counter_ns()})
                actions.append(action)
                if action != "wait":
                    cost += public["repair_cost"] if action == "repair" else 0
                    proposed = public["initial"] + (values["repair_amount"] if action == "repair" else 0)
                    break
                cost += public["wait_cost"]
                public = acquire_wait(data, i, arm, transport, public)
            delivered = transport.deliver(case, arm, "final", proposed, "/".join(actions))
            rows.append({"case": case, "arm": arm, "stages": stages, "actions": actions,
                "delivered": delivered, "cost": cost, "final_readback_ns": time.perf_counter_ns(),
                "wall_ns": time.perf_counter_ns() - began, "model_sha256": model_sha})
    return {"schema": "hepta.paid-feedback.public-execution.v3", "rows": rows,
        "model_sha256": model_sha, "readbacks": _archive(transport),
        "owners": archive_directory(output / "owners"),
        "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
        "native_requests": native.calls, "native_ticks": native.original_sparse_ticks,
        "native_roundtrip_ns": native.wall_ns, "policy_worker_private_target_schema": False,
        "development_only": development_only}


def confirm_seed(seed, prepared, output, native_binary, native_receipt, expected_model_sha256,
                 n=384, data_offset=80000000):
    model_file = Path(prepared) / "MODELS.json"
    if file_sha(model_file) != expected_model_sha256:
        raise ValueError("Frozen model changed")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    data = f.build_dataset(data_offset + seed * 100 + 3, n, "confirmation")
    np.savez_compressed(output / "DATA.npz", **data)
    np.savez_compressed(output / "PUBLIC.npz", **{k: v for k, v in data.items() if k != "target"})
    command = [sys.executable, "-m", "experiments.analytic_event_neuron.round3.feedback_study", "worker",
        "--model", str(model_file), "--public", str(output / "PUBLIC.npz"), "--output", str(output),
        "--native-binary", str(native_binary), "--native-receipt", str(native_receipt)]
    completed = subprocess.run(command, capture_output=True, text=True)
    if completed.returncode:
        raise RuntimeError(completed.stderr)
    with gzip.open(output / "EXECUTION.json.gz", "rt") as stream:
        result = json.load(stream)
    score_started_ns = time.perf_counter_ns()
    by_id = {str(identity): float(data["target"][i]) for i, identity in enumerate(data["ids"])}
    for row in result["rows"]:
        target = by_id[row["case"]]
        row.update(target=target, squared_error=(row["delivered"] - target) ** 2, score_started_ns=score_started_ns)
        row["utility"] = 1 - row["squared_error"] - row["cost"]
        row["terminal_error"] = target - row["stages"][0]["public"]["initial"]
    result["summary"] = {}
    for arm in f.ARMS:
        subset = [row for row in result["rows"] if row["arm"] == arm]
        result["summary"][arm] = {key: float(np.mean([r[key] for r in subset])) for key in
            ("utility", "squared_error", "cost", "wall_ns")}
        result["summary"][arm].update(episodes=len(subset), waits=sum("wait" in r["actions"] for r in subset),
                                      repairs=sum("repair" in r["actions"] for r in subset))
    with gzip.open(output / "ROWS.json.gz", "xt") as stream:
        json.dump(result["rows"], stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
    summary = {k: v for k, v in result.items() if k != "rows"}
    summary.update(seed=seed, model_file_sha256=expected_model_sha256,
        data_sha256=file_sha(output / "DATA.npz"), rows_sha256=file_sha(output / "ROWS.json.gz"),
        policy_process_separate_from_target_generator_and_scorer=True,
        hostile_process_or_filesystem_access_control_claimed=False,
        all_final_readbacks_before_scoring=all(r["final_readback_ns"] < score_started_ns for r in result["rows"]))
    write_json(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("worker",))
    for name in ("model", "public", "output", "native-binary", "native-receipt"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    model = json.loads(Path(args.model).read_text())
    data = load_data(args.public)
    with Native(args.native_binary, args.native_receipt) as native:
        result = evaluate_public(model, data, native, args.output)
    with gzip.open(Path(args.output) / "EXECUTION.json.gz", "xt") as stream:
        json.dump(result, stream, sort_keys=True, allow_nan=False, separators=(",", ":"))
