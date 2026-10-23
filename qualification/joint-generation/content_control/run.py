"""One registered TRAIN-only build. There is intentionally no test command."""

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import time
import traceback

import numpy as np
from PIL import Image

from content_control.refiner import Capture, PATHS, Refiner, encode, forward_work
from data import metrics_from_observations, prepare_decoded_observer, render, templates
from independent.accounting import WorkLedger, counted_model_class
from independent.data_v2 import dataset, manifest
from independent.evaluation import _outputs, full_reference_work, paired_interval
from independent.inference import FrozenGenerator
from independent.learning import CachedObjective, CONTENT_PARAMETERS, setup_work, step_work
from independent.native import compile_native
from independent.native_adam import NativeAdam, setup_work as adam_setup_work
from independent.run import cpu_clock, observer_work, save_model, write_json
from model import JointModel, softmax


ROOT = Path(__file__).resolve().parents[1]
ARMS = ("S", "H", "A", "H_R", "A_R")
SEEDS, LRS = (11, 23, 47), (.001, .003, .01)
CAP, CPU_CAP = 12_000_000_000, 10.0
PROGRESS = {}


def snapshot():
    paths = sorted(ROOT.glob("*.py")) + sorted((ROOT / "independent").glob("*.py"))
    paths += sorted((ROOT / "content_control").glob("*.py"))
    paths += [ROOT / "content_control/PROTOCOL.md", ROOT / "core_confirmation/plan.json",
              ROOT / "independent/native.c"]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths}


def inner_split(data):
    valid = np.array([data["sources"][identity]["index"] % 4 == 0 for identity in data["source_ids"]])
    result = []
    for mask, label in ((~valid, "TRAIN-fit"), (valid, "TRAIN-inner")):
        rows = np.flatnonzero(mask)
        part = {key: value[rows] if isinstance(value, np.ndarray) else [value[j] for j in rows]
                for key, value in data.items() if key in ("full", "labels", "source_ids", "groups", "input_hashes")}
        part["split"] = label
        result.append(part)
    if set(result[0]["source_ids"]) & set(result[1]["source_ids"]):
        raise ValueError("physical source leakage")
    return result


def observe(p, q, labels, observer, ledger, stage):
    ledger.charge_kernel(stage, "decoded_metrics", **observer_work(len(labels)))
    metrics = metrics_from_observations(observer.observations, p, q, labels)
    metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, observer.reward[labels], q)
    return metrics


def predict(model, base, data, features, path, ledger, stage):
    if isinstance(model, Refiner):
        ledger.charge_kernel(stage, "refiner_forward", **forward_work(len(data["labels"]), path))
        return model.forward(features, path)
    ledger.model_forward(stage, rows=len(data["labels"]), input_dim=202, hidden=32, classes=12)
    return model.forward(data["full"])


def service(model, base, data, path, ledger, out, seed, *, external=False):
    started = time.process_time_ns()
    generator = FrozenGenerator(base if isinstance(model, Refiner) else model, prepare_low=False)
    preparation = time.process_time_ns() - started
    rng, ps, qs, batches = np.random.default_rng(seed), [], [], []
    reference_units = full_reference_work(generator)
    for offset in range(0, len(data["full"]), 64):
        x = data["full"][offset:offset + 64]
        begin, units_before = time.process_time_ns(), ledger.consumed_units
        if isinstance(model, Refiner):
            features = encode(base, x, ledger, "service")
            ledger.charge_kernel("service", "two_unit_refine", **forward_work(len(x), path))
            p, q = model.forward(features, path)
        else:
            p, q = generator.forward_full(x, ledger)
        outputs, sizes = _outputs(generator, p, q, ledger, rng)
        payload = json.dumps(outputs, sort_keys=True).encode()
        elapsed, used = time.process_time_ns() - begin, ledger.consumed_units - units_before
        if used > 2 * reference_units * len(x):
            raise RuntimeError("unchanged two-full-equivalent service cap exceeded")
        batches.append({"offset": offset, "rows": len(x), "cpu_ns": elapsed, "work_units": used,
                        "output_bytes": sum(sizes), "outputs_sha256": hashlib.sha256(payload).hexdigest()})
        ps.extend(p); qs.extend(q)
        if offset == 0:
            write_json(out / ("external-output.json" if external else "sample-output.json"), outputs[0])
            (out / ("external-output.png" if external else "sample-output.png")).write_bytes(base64.b64decode(outputs[0]["png_base64"]))
    return np.asarray(ps), np.asarray(qs), {"prepare_cpu_ns": preparation, "batches": batches,
        "reference_work_units": reference_units, "cpu_ns": sum(b["cpu_ns"] for b in batches),
        "rows": len(data["full"]), "cap_violations": 0}


def build(out, freeze):
    if json.loads(Path(freeze).read_text())["sources"] != snapshot():
        raise ValueError("source/protocol freeze mismatch")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    shared = WorkLedger("shared", CAP)
    PROGRESS["shared"] = shared
    plan = json.loads((ROOT / "core_confirmation/plan.json").read_text())
    # The only dataset construction in this program. No validation/test API call.
    data = dataset("train", plan["data_profile"])
    fit, inner = inner_split(data)
    shared.record("data", prepared_rows=len(data["labels"]))
    np.savez_compressed(out / "train-inputs.npz", fit_full=fit["full"], fit_labels=fit["labels"],
                        inner_full=inner["full"], inner_labels=inner["labels"])
    shared.record("data", serialized_bytes=(out / "train-inputs.npz").stat().st_size)
    compiled = compile_native(out / "build/libjoint.so")
    shared.record("compile", compiler_invocations=1)
    bases, observers = {}, {}
    Counted = counted_model_class(JointModel)
    for seed in SEEDS:
        decoder = Counted(202, 12, 192, hidden=32, seed=seed, ledger=shared)
        with shared.phase("decoder"):
            decoder.fit_decoder(templates(), steps=300)
        model = JointModel.clone(decoder)
        objective, rng = CachedObjective("S", model), np.random.default_rng(seed + 1000)
        for _ in range(500):
            idx = rng.integers(len(fit["labels"]), size=64)
            objective.step(model, fit["full"][idx], fit["labels"][idx], .003, ledger=shared, stage="pretrain")
        bases[seed] = model
        shared.charge_kernel("observer", "observer_cache", **setup_work(model.dimensions, "A"))
        observers[seed] = prepare_decoded_observer(model)
        save_model(model, out / f"base-{seed}.npz", shared, "base_export")
    calibration_out = out / "calibration"
    calibration_out.mkdir()
    calibration_idx = np.linspace(0, len(fit["full"]) - 1, 64, dtype=int)
    _, _, calibration = service(bases[11], bases[11], {"full": fit["full"][calibration_idx]},
                                "full", shared, calibration_out, 11)
    common_cpu = cpu_clock()  # Includes interpreter/imports and compiler children.
    if common_cpu > CPU_CAP:
        raise RuntimeError("shared preparation exceeded the unchanged CPU cap")
    feature_ledger, cached = WorkLedger("features", CAP), {}
    PROGRESS["features"] = feature_ledger
    feature_start = cpu_clock()
    for seed, base in bases.items():
        cached[seed] = tuple(encode(base, part["full"], feature_ledger, "features") for part in (fit, inner))
        feature_path = out / f"features-{seed}.npz"
        np.savez_compressed(feature_path, **{f"{part}_{name}": a for part, group in zip(("fit", "inner"), cached[seed])
                                           for name, a in zip(("h", "t", "i"), group)})
        feature_ledger.record("features", serialized_bytes=feature_path.stat().st_size)
    feature_cpu = cpu_clock() - feature_start
    ledgers, costs, candidates, objects = {}, {}, {}, {}
    for arm in ARMS:
        ledger = WorkLedger(arm, CAP)
        ledger.attribute_shared(shared)
        if arm.endswith("_R"):
            ledger.attribute_shared(feature_ledger)
        ledgers[arm], candidates[arm] = ledger, []
        PROGRESS[arm] = ledger
        costs[arm] = {"shared_cpu": common_cpu, "feature_cpu": feature_cpu if arm.endswith("_R") else 0,
                      "active_cpu": 0.0}
    status = 0
    try:
        for round_index, (seed, lr_index) in enumerate((s, j) for s in SEEDS for j in range(3)):
            order = ARMS[round_index % len(ARMS):] + ARMS[:round_index % len(ARMS)]
            for arm in order:
                begin, ledger, base = cpu_clock(), ledgers[arm], bases[seed]
                refined = arm.endswith("_R")
                model = Refiner() if refined else base.clone()
                if not refined:
                    ledger.charge_kernel("optimizer_setup", "native_adam_prepare", **adam_setup_work(model))
                capture = Capture(ledger, None if refined else NativeAdam(model, compiled["library_path"]))
                objective = CachedObjective(arm[0], base if refined else model, ledger=ledger,
                                            stage="objective_setup", optimizer=None if refined else capture)
                initial = {k: v.copy() for k, v in model.params.items() if refined or k in CONTENT_PARAMETERS}
                step_inventory = model.step_work(64, arm[0]) if refined else step_work(model.dimensions, arm[0], 64)
                quota_units = (CAP - shared.consumed_units - (feature_ledger.consumed_units if refined else 0) - 500_000_000) // 9
                quota_cpu = (CPU_CAP - common_cpu - costs[arm]["feature_cpu"] - 2.0) / 9
                training_start, unit_start = cpu_clock(), ledger.consumed_units
                rng, losses = np.random.default_rng(seed + 10000 + lr_index), []
                while (cpu_clock() - training_start < quota_cpu - .01
                       and ledger.consumed_units - unit_start + ledger.estimate_kernel(**step_inventory) <= quota_units):
                    idx = rng.integers(len(fit["labels"]), size=64)
                    if refined:
                        loss = model.step(tuple(a[idx] for a in cached[seed][0]), fit["labels"][idx], objective,
                                          LRS[lr_index], ledger, capture)
                    else:
                        loss = objective.step(model, fit["full"][idx], fit["labels"][idx], LRS[lr_index], ledger=ledger)
                    losses.append(loss)
                if not losses:
                    raise RuntimeError("no affordable useful content update")
                training_cpu, training_units = cpu_clock() - training_start, ledger.consumed_units - unit_start
                paths = PATHS if refined else ("full",)
                values, raw = {}, {}
                for path in paths:
                    p, q = predict(model, base, inner, cached[seed][1], path, ledger, "search_validation")
                    observed = observe(p, q, inner["labels"], observers[seed], ledger, "search_validation")
                    values[path] = {k: float(v.mean()) for k, v in observed.items()}
                    raw.update({path + "/" + k: v for k, v in observed.items()})
                name = f"{arm}-{seed}-{LRS[lr_index]}"
                folder = out / name
                folder.mkdir()
                np.savez_compressed(folder / "validation-paths.npz", **raw)
                ledger.record("search_validation", serialized_bytes=(folder / "validation-paths.npz").stat().st_size)
                if refined:
                    np.savez_compressed(folder / "refiner.npz", **model.params)
                    ledger.record("export", serialized_bytes=(folder / "refiner.npz").stat().st_size)
                else:
                    save_model(model, folder / "model.npz", ledger, "export")
                capture.save(folder / "gradient-updates.npz", model, initial, losses)
                row = {"name": name, "seed": seed, "lr": LRS[lr_index], "updates": len(losses),
                       "validation": values, "training_cpu": training_cpu, "training_units": training_units}
                candidates[arm].append(row)
                objects[name] = model
                write_json(folder / "candidate.json", row)
                costs[arm]["active_cpu"] += cpu_clock() - begin
                if sum(costs[arm].values()) > CPU_CAP:
                    raise RuntimeError(arm + " complete CPU cap exceeded")
        selected, reports, arrays = {}, {}, {}
        for arm in ARMS:
            options = [(lr, path) for lr in LRS for path in (PATHS if arm.endswith("_R") else ("full",))]
            lr, path = max(options, key=lambda pair: np.mean([r["validation"][pair[1]]["task_utility"]
                         for r in candidates[arm] if r["lr"] == pair[0]]))
            selected[arm], reports[arm], arrays[arm] = {"lr": lr, "path": path}, [], []
        # Rotate final service by seed as well. No output/timing repeat selection.
        for index, seed in enumerate(SEEDS):
            for arm in ARMS[index:] + ARMS[:index]:
                begin, ledger = cpu_clock(), ledgers[arm]
                choice, base = selected[arm], bases[seed]
                name = f"{arm}-{seed}-{choice['lr']}"
                model, folder = objects[name], out / name
                p, q, served = service(model, base, inner, choice["path"], ledger, folder, seed)
                metrics = observe(p, q, inner["labels"], observers[seed], ledger, "selected_validation")
                corrupted = base.clone()
                corrupted.params["decoder"] = np.roll(corrupted.params["decoder"], 1, axis=0)
                ledger.charge_kernel("negative_control", "observer_cache", **setup_work(base.dimensions, "A"))
                bad = prepare_decoded_observer(corrupted)
                bad_metrics = observe(p, q, inner["labels"], bad, ledger, "negative_control")
                if isinstance(model, Refiner):
                    loaded = Refiner()
                    with np.load(folder / "refiner.npz", allow_pickle=False) as saved:
                        loaded.params = {k: saved[k].copy() for k in loaded.params}
                else:
                    loaded = JointModel.load(folder / "model.npz")
                x = np.concatenate((np.clip(.02 + .91 * render(9), 0, 1).reshape(-1),
                                    np.eye(4)[1], np.eye(3)[1], np.eye(3)[2]))[None, :]
                hand = {"full": x, "labels": np.array([1])}
                hp, hq, external = service(loaded, base, hand, choice["path"], ledger, folder, seed, external=True)
                pp, qq = predict(model, base, hand, encode(base, x, ledger, "reload_check") if isinstance(model, Refiner) else None,
                                 choice["path"], ledger, "reload_check")
                if not np.array_equal(hp, pp) or not np.array_equal(hq, qq):
                    raise RuntimeError("export/reload changed exact external policies")
                Image.open(folder / "external-output.png").load()
                arrays[arm].append(metrics)
                reports[arm].append({"seed": seed, "service": served, "external_service": external,
                    "means": {k: float(v.mean()) for k, v in metrics.items()},
                    "decoder_corruption_drop": float((metrics["task_utility"] - bad_metrics["task_utility"]).mean()),
                    "reload_exact": True})
                costs[arm]["active_cpu"] += cpu_clock() - begin
        scheduler = max(0.0, cpu_clock() - common_cpu - feature_cpu - sum(v["active_cpu"] for v in costs.values()))
        for arm in ARMS:
            costs[arm]["scheduler_cpu"] = scheduler
            costs[arm]["complete_cpu"] = sum(v for k, v in costs[arm].items() if k != "complete_cpu")
            if costs[arm]["complete_cpu"] > CPU_CAP:
                raise RuntimeError(arm + " complete CPU cap exceeded at final service")
        result = {"scope": "TRAIN-only exploratory selection; no independent confirmation", "selected": selected,
            "reports": reports, "per_row": {a: [{k: v.tolist() for k, v in r.items()} for r in rows] for a, rows in arrays.items()}}
        write_json(out / "train-result.json", result)
    except Exception:
        status = 1
        write_json(out / "failure.json", {"traceback": traceback.format_exc(), "status": status})
    receipt = {"exit_code": status, "candidates": candidates, "costs": costs, "common_cpu": common_cpu,
        "feature_cpu": feature_cpu, "shared_ledger": shared.snapshot(), "feature_ledger": feature_ledger.snapshot(),
        "ledgers": {a: l.snapshot() for a, l in ledgers.items()}, "data": manifest(data),
        "fit_source_ids": sorted(set(fit["source_ids"])), "inner_source_ids": sorted(set(inner["source_ids"])),
        "inner_rows_source_ids": inner["source_ids"], "compiler": compiled,
        "calibration": calibration,
        "environment": {"cwd": os.getcwd(), "python": platform.python_version(), "numpy": np.__version__,
                        "hostname": platform.node(), "threads": {k: os.getenv(k) for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}},
        "sources": snapshot(), "freeze_sha256": hashlib.sha256(Path(freeze).read_bytes()).hexdigest(),
        "actual_build_cpu_all_arms": cpu_clock(), "formal_test_opened": False,
        "unpriced_primitives": "data generation, checks outside mathematical kernels, allocation/copy, IO/hash/PNG/JSON; included in actual CPU",
        "administration": "final lossless JSON receipt/archival CPU recorded by outer process; no budget credit"}
    write_json(out / "build.json", receipt)
    print(json.dumps({"exit_code": status, "out": str(out), "costs": costs}))
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "train"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--freeze")
    args = parser.parse_args()
    if args.action == "freeze":
        write_json(args.out, {"sources": snapshot(), "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                            "scope": "TRAIN only; no formal opening authority"})
    else:
        try:
            exit_code = build(args.out, args.freeze)
        except Exception:
            destination = Path(args.out)
            if destination.is_dir() and not (destination / "failure.json").exists():
                write_json(destination / "early-failure.json", {"traceback": traceback.format_exc(),
                    "partial_ledgers": {k: v.snapshot() for k, v in PROGRESS.items()}, "cpu_seconds": cpu_clock()})
            raise
        raise SystemExit(exit_code)
