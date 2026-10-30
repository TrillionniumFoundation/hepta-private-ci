"""Actual native-feedback training with saved potentials and all head candidates."""

import gzip
import json
from pathlib import Path
import time

import numpy as np

from ..native_adapter import Native
from ..round3 import feedback as previous
from ..round4.runtime_evidence import EvidenceZip, acquire, acquire_wait, transport, write_json
from ..round4.runtime_law import posterior
from ..round4.runtime_learning import fit_dynamics, gaussian_dense
from ..round4.runtime_owner import Owner, ZERO, file_sha, validate_public
from ..runtime import digest
from .continuation import action_values
from .data import ARMS, LEARNED, SEEDS, SMOKE_SEED, dataset, native_paths


def noise_scale(model, arm):
    if arm not in ARMS:
        raise ValueError("Undeclared arm")
    return 1.0 if arm == "uncalibrated" else model["calibration"]["noise_scale"]


def law(model, public, arm):
    validate_public(public)
    scale = noise_scale(model, arm)
    prior = model["gaussian_prior"] if arm in ("gaussian", "probit") else model["prior"]
    implementation = gaussian_dense if arm == "probit" else posterior
    return implementation(prior, public["residuals"], public["variances"], scale)


def training_scope(data, model, native, output, split):
    """Supervised potential outcomes may use private labels only during preparation."""
    archive, rows = EvidenceZip(output / (split + ".zip")), []
    for i, identity in enumerate(data["ids"]):
        directory = output / "working_case"
        delivery = transport(directory, "runtime6_" + split)
        case = str(identity)
        public = acquire(data, i, "shared", delivery)
        owner = Owner(directory / "owners", [case, "shared"], digest(model), native)
        stages, checkpoint = [], ZERO
        for stage in range(2):
            if stage:
                public = acquire_wait(data, i, "shared", delivery, public)
            receipt = owner.step(public, law(model, public, "event"), stage + 1,
                                 expected_checkpoint=checkpoint)
            checkpoint, received = receipt["checkpoint_after"], receipt["law"]
            values = action_values(received["conditional_law"], public, noise_scale(model, "event"))
            features, native_rows = {}, {}
            for arm in LEARNED:
                vector, actual = previous.feature(public, received, arm, model["calibration"], native,
                                                  case + f"/stage{stage}/{arm}")
                if vector.shape != (63,) or not np.isfinite(vector).all():
                    raise ValueError("Every trained comparator requires 63 finite features")
                features[arm], native_rows[arm] = vector.tolist(), actual
            delivered = delivery.deliver(case, "shared", f"potential{stage}",
                public["initial"] + values["repair_amount"], "supervised_potential")
            error = public["initial"] - float(data["target"][i])
            gain = error ** 2 - (delivered - float(data["target"][i])) ** 2 - public["repair_cost"]
            stages.append({"public": public, "runtime": receipt, "features": features,
                           "native": native_rows, "values": values, "realized_gain": gain,
                           "stop_utility": 1 - error ** 2})
        delivery.save_receipts()
        rows.append({"case": case, "stages": stages})
        archive.append(directory, f"case-{i}")
    return rows, archive.finish()


def prepare_seed(run_dir, seed, train_n=256, dev_n=128, *, smoke=False):
    if ((smoke and (seed != SMOKE_SEED or train_n != 24 or dev_n != 12))
            or (not smoke and (seed not in SEEDS or train_n != 256 or dev_n != 128))):
        raise ValueError("Preparation counts and seed must match the declared namespace")
    run_dir = Path(run_dir)
    if smoke:
        if (run_dir / "PREPARING.json").exists():
            raise ValueError("Smoke cannot enter a registered preparation namespace")
    else:
        from .lifecycle import verify_preparing
        verify_preparing(run_dir)
    if (run_dir / "FREEZE.json").exists() or (run_dir / "confirmation").exists():
        raise ValueError("Preparation cannot modify a frozen or confirmed run")
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    output = run_dir / "prepared" / f"seed_{seed}"
    output.mkdir(parents=True, exist_ok=False)
    train = dataset(seed, train_n, "train", smoke=smoke)
    dev = dataset(seed, dev_n, "development", smoke=smoke)
    np.savez_compressed(output / "TRAIN.npz", **train)
    np.savez_compressed(output / "DEVELOPMENT.npz", **dev)
    model, dynamics = fit_dynamics(train)
    with Native(*native_paths(run_dir)) as native:
        train_rows, train_archive = training_scope(train, model, native, output, "train")
        dev_rows, dev_archive = training_scope(dev, model, native, output, "development")
        costs = {"requests": native.calls, "ticks": native.original_sparse_ticks,
                 "roundtrip_ns": native.wall_ns}
        binary_sha = native.receipt["binary_sha256"]
    train_gain = np.asarray([s["realized_gain"] for row in train_rows for s in row["stages"]])
    dev_gain = np.asarray([[r["stages"][0]["realized_gain"], r["stages"][1]["realized_gain"],
                           r["stages"][0]["public"]["wait_cost"]] for r in dev_rows])
    dev_wait = np.asarray([r["stages"][0]["values"]["wait_gain"] for r in dev_rows])
    dev_stop = np.asarray([r["stages"][0]["stop_utility"] for r in dev_rows])
    heads, fits = {}, {}
    for arm in LEARNED:
        x = np.asarray([s["features"][arm] for row in train_rows for s in row["stages"]])
        z = np.asarray([s["features"][arm] for row in dev_rows for s in row["stages"]])
        heads[arm], fits[arm] = previous.fit_head(x, train_gain, z, dev_gain, dev_wait, dev_stop)
        if fits[arm]["parameter_l2_change"] <= 0 or len(fits[arm]["candidates"]) != 15:
            raise ValueError("Actual trained head and complete declared candidate grid required")
    model.update(schema="hepta.paid-feedback.models.v6", heads=heads,
                 namespace="smoke" if smoke else "registered", native_binary_sha256=binary_sha,
                 training_ids_sha256=digest(train["ids"].tolist()),
                 development_ids_sha256=digest(dev["ids"].tolist()))
    write_json(output / "MODELS.json", model)
    with gzip.open(output / "TRAINING_ROWS.json.gz", "xt") as stream:
        json.dump({"train": train_rows, "development": dev_rows}, stream, sort_keys=True,
                  separators=(",", ":"), allow_nan=False)
    report = {"schema": "hepta.paid-feedback.preparation.v6", "seed": seed,
              "namespace": model["namespace"], "dynamics": dynamics, "fits": fits, "native": costs,
              "training_archive": train_archive, "development_archive": dev_archive,
              "model_file_sha256": file_sha(output / "MODELS.json"),
              "training_rows_sha256": file_sha(output / "TRAINING_ROWS.json.gz"),
              "training_data_sha256": file_sha(output / "TRAIN.npz"),
              "development_data_sha256": file_sha(output / "DEVELOPMENT.npz"),
              "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
              "train_rows": train_n, "development_rows": dev_n, "prior_confirmation_used": False,
              "shared_potential_training_cost_counted_once": True, "native_energy": None,
              "financial_cost": None, "production_promotion": False}
    write_json(output / "TRAINING_RECEIPT.json", report)
    if not smoke:
        verify_preparing(run_dir)
    return report
