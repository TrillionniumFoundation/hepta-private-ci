"""One protocol-first, TRAIN-source OOF decision-regret diagnostic; never qualification."""

import time

CPU_START = time.process_time_ns()
WALL_START = time.perf_counter_ns()

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import resource
import subprocess
import sys
import traceback

import numpy as np

from data import outcome_table
from independent.accounting import WorkLedger
from independent.data_v2 import dataset, manifest
from independent.learning import setup_work, value_work
from independent.native import NativeGenerator
from model import JointModel


ROOT = Path(__file__).resolve().parents[1]
SEALED_MARKER = ROOT / "independent/efficient-r2-test-opened.json"
METHODS = ("mse42", "weighted_binary42")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _cpu():
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return time.process_time_ns() + round((usage.ru_utime + usage.ru_stime) * 1e9)


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def probe_content(model, library_path, inputs, ledger):
    """Run the two frozen content probes using explicit native API keywords."""
    generator = NativeGenerator(model, ledger=ledger, stage="content_probe",
                                prepare_low=False, library_path=library_path)
    low = generator.forward_low_state(inputs, ledger, "content_probe")
    full = generator.forward_full(inputs, ledger, "content_probe")
    return (*low, *full)


def source_folds(data, folds=4, salt="hepta-t11-decision-regret-q1"):
    """Assign whole TRAIN physical sources in source-class-stratified SHA order."""
    if data.get("split") != "train" or type(folds) is not int or not 2 <= folds <= 16:
        raise ValueError("TRAIN metadata and bounded physical-source folds required")
    ids, scenes = list(data["source_ids"]), np.asarray(data["source_scenes"])
    if (scenes.shape != (len(ids),) or not len(ids) or scenes.dtype.kind not in "iu"
            or np.any(scenes < 0) or np.any(scenes >= 12)
            or any(not isinstance(value, str) or not value for value in ids)
            or not isinstance(salt, str) or not 1 <= len(salt) <= 256):
        raise ValueError("consistent twelve-class physical-source identities required")
    classes = {}
    for source, scene in zip(ids, scenes):
        if source in classes and classes[source] != int(scene):
            raise ValueError("physical source crosses semantic classes")
        classes[source] = int(scene)
    assigned = {}
    for scene in range(12):
        sources = [source for source, value in classes.items() if value == scene]
        if len(sources) < folds or len(sources) % folds:
            raise ValueError("every source class must divide evenly across folds")
        sources.sort(key=lambda value: (hashlib.sha256((salt + "\0" + value).encode()).hexdigest(), value))
        assigned.update({source: index % folds for index, source in enumerate(sources)})
    row_folds = np.asarray([assigned[source] for source in ids], dtype=np.int8)
    receipt = {"source_fold_sha256": _hash(assigned), "source_count": len(classes),
        "folds": [{"fold": fold, "rows": int(np.sum(row_folds == fold)),
            "source_count": sum(value == fold for value in assigned.values()),
            "source_class_counts": {str(scene): sum(classes[source] == scene and value == fold
                for source, value in assigned.items()) for scene in range(12)}} for fold in range(folds)]}
    return row_folds, receipt


def ridge_work(n, d, m, *, binary):
    if (any(type(value) is not int or not 1 <= value <= 65536 for value in (n, m))
            or type(d) is not int or not 1 <= d <= 522 or type(binary) is not bool):
        raise ValueError("bounded ridge geometry required")
    work = {"macs": n*d*d + n*d + m*d,
        "scalar_ops": (4*n-2)*d + 2*n-1 + d**3+d+1 + m*(d+1),
        "div_ops": (n+m+2)*d+1, "sqrt_ops": d,
        "compare_ops": (n+m)*d + 3*n+4*m+5*d+2}
    if binary:
        # Weighted centering, target, Gram/RHS operands and held-row centering.
        work["scalar_ops"] += 4*n*d + 2*m*d + 6*n+d*d+d
        work["div_ops"] += d+2
        work["compare_ops"] += 4*(n+m)
    return work


def ridge_oof_fit_predict(features, target, weights, fit, hold, *, binary, ledger, stage="critic_OOF"):
    """Fixed .001 ridge; normalizers/intercepts use fit rows only, never hold rows."""
    x, y, w = (np.asarray(value, dtype=np.float64) for value in (features, target, weights))
    fit, hold = np.asarray(fit), np.asarray(hold)
    if (x.ndim != 2 or not len(x) or y.shape != (len(x),) or w.shape != y.shape
            or fit.shape != y.shape or hold.shape != y.shape or fit.dtype != bool or hold.dtype != bool
            or np.any(fit == hold) or not fit.any() or not hold.any()
            or not np.isfinite(x).all() or not np.isfinite(y).all() or not np.isfinite(w).all()
            or np.any(w < 0) or type(binary) is not bool
            or (binary and np.any((y != 0) & (y != 1))) or (not binary and np.any(w != 1))):
        raise ValueError("finite disjoint fit/hold rows and declared ridge objective required")
    n, d, m = int(fit.sum()), x.shape[1], int(hold.sum())
    inventory = ridge_work(n, d, m, binary=binary)
    if not isinstance(ledger, WorkLedger):
        raise TypeError("WorkLedger required")
    if float(w[fit].sum()) <= 0:
        raise ValueError("zero training regret weight; no informative weighted fit")
    ledger.charge_kernel(stage, "weighted_binary_ridge" if binary else "ordinary_gain_ridge",
        **inventory, counts={"diagnostic_ridge_fits": 1, "fit_rows": n, "hold_rows": m, "fit_features": d})
    xx, yy, ww = x[fit], y[fit], w[fit]
    mean = xx.mean(axis=0)
    centered = xx - mean
    scale = np.maximum(np.sqrt((centered*centered).mean(axis=0)), .05)
    z, zz = centered/scale, (x[hold]-mean)/scale
    if binary:
        total = float(ww.sum())
        center = (ww[:, None]*z).sum(axis=0)/total
        intercept = float(np.sum(ww*yy)/total)
        z = z-center
        gram, rhs = z.T @ (ww[:, None]*z), z.T @ (ww*(yy-intercept))
        zz = zz-center
        bounds = np.array([0., 1.])
    else:
        total, center, intercept = float(n), np.zeros(d), float(yy.mean())
        gram, rhs = z.T @ z, z.T @ (yy-intercept)
        bounds = np.array([yy.min(), yy.max()])
    gram.flat[::d+1] += .001*total
    coefficients = np.linalg.solve(gram, rhs)
    prediction = np.clip(zz @ coefficients+intercept, *bounds)
    if not np.isfinite(prediction).all() or not np.isfinite(coefficients).all():
        raise ValueError("nonfinite diagnostic ridge result")
    arrays = {"mean": mean, "scale": scale, "center": center, "coefficients": coefficients,
              "intercept": np.array([intercept]), "bounds": bounds}
    receipt = {"fit_rows": n, "hold_rows": m, "features": d, "weight_sum": total,
               "ridge_regularization": .001, "work": inventory,
               "coefficient_sha256": hashlib.sha256(coefficients.astype("<f8").tobytes()).hexdigest()}
    return prediction, receipt, arrays


def decision_metrics(action, delta, full, low, price, source_ids, *, ledger=None):
    action = np.asarray(action)
    delta, full, low = (np.asarray(value, dtype=np.float64) for value in (delta, full, low))
    if (action.dtype != bool or action.ndim != 1 or not len(action) or delta.shape != action.shape
            or full.shape != action.shape or low.shape != action.shape or len(source_ids) != len(action)
            or not all(np.isfinite(value).all() for value in (delta, full, low))
            or type(price) not in (int, float) or not np.isfinite(price) or price < 0
            or not np.allclose(delta, full-low, atol=1e-13, rtol=1e-12)):
        raise ValueError("finite matching decisions and actual raw utility differences required")
    groups = {}
    for index, source in enumerate(source_ids):
        groups.setdefault(str(source), []).append(index)
    n, count = len(action), len(groups)
    if ledger is not None:
        ledger.charge_kernel("regret_metrics", "source_equal_decision_regret", scalar_ops=80*n+32*count,
            compare_ops=35*n+8*count, div_ops=14*count+2, sort_items=3*count,
            counts={"diagnostic_metric_rows": n, "diagnostic_metric_sources": count})
    oracle = delta > price
    false_stop = (~action) & oracle
    vectors = {"regret": np.abs(delta-price)*(action != oracle),
        "false_stop_lost_net": np.where(false_stop, delta-price, 0.),
        "false_stop_lost_raw": np.where(false_stop, np.maximum(delta, 0), 0.),
        "chosen_raw_utility": np.where(action, full, low), "route_gain_vs_full": np.where(action, 0., -delta),
        "continue_fraction": action.astype(float)}
    per_source = [{"source_id": source, "rows": len(indices),
        "false_stop_count": int(false_stop[indices].sum()),
        **{key: float(value[indices].mean()) for key, value in vectors.items()}}
        for source, indices in sorted(groups.items())]
    result = {key: float(np.mean([row[key] for row in per_source])) for key in vectors}
    result.update(false_stop_count=int(false_stop.sum()),
        false_stop_source_count=sum(row["false_stop_count"] > 0 for row in per_source),
        beneficial_stop_count=int(((~action) & (delta < 0)).sum()), per_source=per_source)
    for kind in ("net", "raw"):
        losses = sorted((row["false_stop_lost_"+kind] for row in per_source), reverse=True)
        total = sum(losses)
        for k in (1, 5):
            result[f"false_stop_top{k}_{kind}_fraction"] = sum(losses[:k])/total if total else None
    return result


def execute(directory):
    directory = Path(directory).resolve()
    if sorted(path.name for path in directory.iterdir()) != ["protocol.json"]:
        raise ValueError("exclusive diagnostic requires a directory containing only protocol.json")
    protocol = json.loads((directory/"protocol.json").read_text())
    result = {"schema": "hepta.train-decision-diagnostic.v1", "qualification": False,
        "protocol_sha256": sha(directory/"protocol.json"), "script_sha256": sha(__file__),
        "phases": [], "seeds": [], "no_test": True, "no_validation_selection": True}
    _write(directory/"START.json", {"protocol_sha256": result["protocol_sha256"],
        "script_sha256": result["script_sha256"], "argv": sys.argv, "started_unix_ns": time.time_ns()})
    ledger, arrays = None, {}

    @contextmanager
    def phase(name, **identity):
        if (_cpu()-CPU_START)/1e9 > protocol["worker_cpu_cap_seconds"]:
            raise ValueError("diagnostic process CPU cap exceeded before phase")
        cpu, wall, units = _cpu(), time.perf_counter_ns(), ledger.consumed_units
        try:
            yield
        finally:
            result["phases"].append({"phase": name, **identity, "cpu_ns": _cpu()-cpu,
                "wall_ns": time.perf_counter_ns()-wall, "declared_units": ledger.consumed_units-units})
            if sys.exc_info()[0] is None and (_cpu()-CPU_START)/1e9 > protocol["worker_cpu_cap_seconds"]:
                raise ValueError("diagnostic process CPU cap exceeded")

    try:
        if (protocol["schema"] != "hepta.train-decision-protocol.v1" or protocol["folds"] != 4
                or protocol["methods"] != list(METHODS) or protocol["regularization"] != .001
                or protocol["classifier_threshold"] != .5 or protocol["feature_dim"] != 42
                or protocol["model_seeds"] != [11, 23, 47] or SEALED_MARKER.exists()):
            raise ValueError("fixed diagnostic protocol mismatch or r2 no longer sealed")
        if (type(protocol["worker_cpu_cap_seconds"]) not in (int, float)
                or not np.isfinite(protocol["worker_cpu_cap_seconds"]) or protocol["worker_cpu_cap_seconds"] <= 0
                or any(type(protocol[key]) is not int or not 0 < protocol[key] <= 128*1024*1024
                       for key in ("artifact_bound_bytes", "array_uncompressed_bound_bytes"))):
            raise ValueError("finite diagnostic CPU cap and bounded artifact limits required")
        ledger = WorkLedger("TRAIN-q1-not-qualification", total_cap=protocol["declared_unit_cap"])
        run = (ROOT/protocol["source_run"]).resolve()
        if not run.is_relative_to(ROOT/"runs"):
            raise ValueError("diagnostic source must be the declared local run")
        identities = {ROOT/name: digest for name, digest in protocol["sources"].items()}
        identities.update({run/name: digest for name, digest in protocol["artifacts"].items()})
        if any(not path.is_file() or path.is_symlink() or sha(path) != digest for path, digest in identities.items()):
            raise ValueError("frozen diagnostic source/artifact identity changed")
        selection = json.loads((run/"selection.json").read_text())
        result.update(protocol=protocol, execution_commit=subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            artifact_reuse="existing T11 content/base/native bytes; no compilation or content updates; R&D only")
        expected = {(row["seed"], row["model_file"], row["model_sha256"], row["decision_price"])
                    for row in protocol["models"]}
        actual = {(row["seed"], row["model_file"], row["model_sha256"], row["decision_price"])
                  for row in selection["selected"] if row["system"] == "ndu_control"}
        if actual != expected or len(expected) != 3:
            raise ValueError("T11 selected model identities or TRAIN decision prices changed")
        with phase("construct_TRAIN"):
            train = dataset("train", protocol["data_profile"])
            if manifest(train) != protocol["train_manifest"]:
                raise ValueError("frozen TRAIN manifest changed")
            ledger.record("construct_TRAIN", diagnostic_train_rows=len(train["labels"]),
                          diagnostic_tensor_bytes=train["full"].nbytes+train["low"].nbytes)
            folds, fold_receipt = source_folds(train, protocol["folds"], protocol["fold_salt"])
            ledger.charge_kernel("grouping", "physical_source_sort", sort_items=len(train["sources"]),
                                 compare_ops=2*len(folds))
            result["folds"] = fold_receipt
        for identity in protocol["models"]:
            seed, price = identity["seed"], identity["decision_price"]
            with phase("fixed_content_probe", seed=seed):
                model = JointModel.load(run/identity["model_file"])
                if model.digest() != identity["model_digest"] or model.dimensions[3] != 32:
                    raise ValueError("fixed T11 content geometry/digest changed")
                pl, ql, hidden, pf, qf = probe_content(
                    model, run/protocol["native_library"], train["full"], ledger)
                n = len(pl)
                ledger.charge_kernel("content_probe", "fixed_raw_reward", **setup_work(model.dimensions, "additive"))
                reward = outcome_table(model)[train["labels"]]
                ledger.charge_kernel("content_probe", "two_raw_values", **{
                    key: 2*value for key, value in value_work("additive", n).items()})
                low = np.sum(pl*np.einsum("nij,nj->ni", reward, ql), axis=1)
                full = np.sum(pf*np.einsum("nij,nj->ni", reward, qf), axis=1)
                ledger.charge_kernel("content_probe", "regret_target", scalar_ops=3*n, compare_ops=n)
                delta, features = full-low, np.column_stack((hidden, train["full"][:, 192:]))
                weighted_target, importance = (delta > price).astype(float), np.abs(delta-price)
                arrays.update({f"s{seed}_delta": delta, f"s{seed}_full": full, f"s{seed}_low": low})
            record = {"seed": seed, "model_digest": model.digest(), "decision_price": price, "methods": {}}
            for method in METHODS:
                binary = method == "weighted_binary42"
                prediction, fits = np.full(n, np.nan), []
                with phase("grouped_critic_OOF", seed=seed, method=method):
                    for fold in range(protocol["folds"]):
                        hold = folds == fold
                        values, fit_receipt, tensors = ridge_oof_fit_predict(features,
                            weighted_target if binary else delta, importance if binary else np.ones(n),
                            ~hold, hold, binary=binary, ledger=ledger)
                        prediction[hold] = values
                        fits.append({"fold": fold, **fit_receipt})
                        arrays.update({f"s{seed}_{method}_f{fold}_{name}": value for name, value in tensors.items()})
                    ledger.charge_kernel("OOF_decisions", "fixed_threshold", compare_ops=n)
                    action = prediction > (.5 if binary else price)
                    record["methods"][method] = {"fits": fits, **decision_metrics(
                        action, delta, full, low, price, train["source_ids"], ledger=ledger)}
                    arrays[f"s{seed}_{method}_predictions"], arrays[f"s{seed}_{method}_actions"] = prediction, action
            with phase("analytic_references", seed=seed):
                record["baselines"] = {name: decision_metrics(action, delta, full, low, price,
                    train["source_ids"], ledger=ledger) for name, action in (
                        ("always_full", np.ones(n, dtype=bool)), ("always_low", np.zeros(n, dtype=bool)),
                        ("label_known_TRAIN_oracle", delta > price))}
                if model.digest() != identity["model_digest"]:
                    raise ValueError("diagnostic changed fixed content parameters")
            result["seeds"].append(record)
        with phase("persist_bounded_predictions"):
            arrays.update(row_folds=folds, source_ids=np.asarray(train["source_ids"], dtype="S76"),
                          input_hashes=np.asarray(train["input_hashes"], dtype="S64"))
            if sum(value.nbytes for value in arrays.values()) > protocol["array_uncompressed_bound_bytes"]:
                raise ValueError("diagnostic prediction inventory exceeds byte bound")
            path = directory/"predictions.npz"
            with path.open("xb") as stream:
                np.savez_compressed(stream, **arrays)
            if path.stat().st_size > protocol["artifact_bound_bytes"]:
                raise ValueError("compressed predictions exceed byte bound")
            result["predictions"] = {"file": path.name, "bytes": path.stat().st_size, "sha256": sha(path)}
            if SEALED_MARKER.exists() or any(sha(path) != digest for path, digest in identities.items()):
                raise ValueError("sealed state or frozen source/artifact identity changed")
            if ledger.totals.get("diagnostic_ridge_fits") != 24:
                raise ValueError("diagnostic fit count changed")
        result.update(outcome="completed", immutable_artifacts_verified=True)
    except Exception as error:
        result.update(outcome="failed", error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        result.update(ledger=None if ledger is None else ledger.snapshot(),
            worker_cpu_ns=_cpu()-CPU_START, worker_wall_ns=time.perf_counter_ns()-WALL_START,
            cost_boundary="Internal CPU/wall starts before dependency imports and ends before final receipt serialization, including own child CPU; outer launcher is authoritative for full process, final serialization, startup and parent overhead. Declared mathematical kernels exclude data-generation RNG, hashing, allocation, I/O and serialization; those remain in actual CPU. No service CPU or qualification claim.")
        _write(directory/"diagnostic.json", result)
    print(json.dumps({"out": str(directory/"diagnostic.json"), "outcome": result["outcome"],
                      "worker_cpu_ns": result["worker_cpu_ns"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-dir", required=True)
    execute(parser.parse_args().protocol_dir)
