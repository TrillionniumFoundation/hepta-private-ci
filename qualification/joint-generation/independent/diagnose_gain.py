"""One bounded, protocol-first TRAIN-only critic OOF diagnostic, never qualification."""

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(run):
    run = Path(run).resolve()
    protocol_path = run / "train-gain-diagnostic.START.json"
    protocol = json.loads(protocol_path.read_text())
    out = run / "train-gain-diagnostic.json"
    if out.exists():
        raise ValueError("diagnostic already completed; no repeat")
    started_cpu, started_wall = time.process_time_ns(), time.perf_counter_ns()
    result = {"schema": "hepta.train-gain-diagnostic.v1", "qualification": False,
              "protocol": protocol, "protocol_sha256": sha(protocol_path),
              "script_sha256": sha(__file__), "command": protocol["command"], "argv": sys.argv,
              "phases": [], "seeds": [], "no_test": True,
              "limitations": ["Critic OOF only: the fixed content encoder saw all TRAIN sources.",
                 "No validation threshold tuning, held-out estimate, or qualification claim.",
                 "Weighted classifier scores are dimensionless diagnostics at fixed .5; not a drop-in raw-gain/CPU-price law."]}
    try:
        import numpy as np
        from control import features
        from data import outcome_table
        from model import JointModel
        from independent.accounting import WorkLedger
        from independent.data_v2 import dataset, manifest
        from independent.learning import setup_work, value_work

        ledger = WorkLedger("TRAIN-diagnostic-not-qualification")

        @contextmanager
        def phase(name, **identity):
            cpu, wall, units = time.process_time_ns(), time.perf_counter_ns(), ledger.consumed_units
            try:
                yield
            finally:
                result["phases"].append({"phase": name, **identity,
                    "cpu_ns": time.process_time_ns() - cpu, "wall_ns": time.perf_counter_ns() - wall,
                    "declared_units": ledger.consumed_units - units})

        selection_path = run / "selection.json"
        selection_hash = sha(selection_path)
        selection = json.loads(selection_path.read_text())
        plan = selection["plan"]
        result.update(selection_sha256=selection_hash, frozen_source_commit=selection["source_commit"],
                      diagnostic_source_commit=__import__("subprocess").check_output(
                          ["git", "rev-parse", "HEAD"], cwd=run, text=True).strip())
        with phase("construct_TRAIN"):
            train = dataset("train", plan["data_profile"])
            if manifest(train) != selection["datasets"]["train"]:
                raise ValueError("frozen TRAIN identity changed")
            result["train_manifest"] = manifest(train)
        ids = np.asarray(train["source_ids"])
        unique = np.unique(ids)
        groups = [np.flatnonzero(ids == source) for source in unique]
        source_fold, strata = {}, {}
        for source, indices in zip(unique, groups):
            values = np.unique(train["source_scenes"][indices])
            if len(values) != 1:
                raise ValueError("physical source crosses source classes")
            strata.setdefault(int(values[0]), []).append(str(source))
        for scene, sources in sorted(strata.items()):
            ordered = sorted(sources, key=lambda sid: hashlib.sha256(
                (protocol["fold_salt"] + "\0" + sid).encode()).hexdigest())
            for index, source in enumerate(ordered):
                source_fold[source] = index % protocol["folds"]
        folds = np.asarray([source_fold[str(source)] for source in ids])
        result["folds"] = [{"fold": fold, "rows": int((folds == fold).sum()),
                            "source_count": sum(value == fold for value in source_fold.values())}
                           for fold in range(protocol["folds"])]
        result["source_fold_sha256"] = hashlib.sha256(json.dumps(source_fold, sort_keys=True).encode()).hexdigest()

        def source_mean(values):
            return float(np.mean([np.mean(values[index]) for index in groups]))

        def metrics(action, delta, full, low, price):
            oracle = delta > price
            chosen = np.where(action, full, low)
            regret = np.abs(delta - price) * (action != oracle)
            false_stop = (~action) & oracle
            loss = np.where(false_stop, np.maximum(delta, 0), 0.)
            stopped = ~action
            return {"wrong_decision_regret": source_mean(regret), "chosen_raw_utility": source_mean(chosen),
                    "route_gain_vs_full": source_mean(chosen - full), "continue_fraction": source_mean(action),
                    "false_stop_raw_loss": source_mean(loss), "false_stop_count": int(false_stop.sum()),
                    "false_stop_top5_loss_fraction": float(np.sort(loss)[-5:].sum() / loss.sum()) if loss.sum() else 0.,
                    "beneficial_stop_count": int((stopped & (delta < 0)).sum()),
                    "beneficial_stop_fraction_among_stops": float((delta[stopped] < 0).mean()) if stopped.any() else None,
                    "stopped_rows": int(stopped.sum()),
                    "per_source_regret": [float(regret[index].mean()) for index in groups],
                    "per_source_route_gain": [float((chosen - full)[index].mean()) for index in groups]}

        def ridge_predict(x, target, weight, fit, hold, *, clip):
            n, d, m = int(fit.sum()), x.shape[1], int(hold.sum())
            ledger.charge_kernel("critic_OOF_fit", "normalized_weighted_ridge",
                macs=n * d * d + n * d + m * d,
                scalar_ops=10 * n * d + 4 * m * d + d**3 + d*d + 6*n,
                div_ops=(n + m) * d + 4*d + 3, sqrt_ops=d, compare_ops=d + 2*m,
                counts={"diagnostic_ridge_fits": 1, "fit_rows": n, "prediction_rows": m,
                        "fit_features": d})
            xx, yy, ww = x[fit], target[fit], weight[fit]
            mean, scale = xx.mean(axis=0), np.maximum(xx.std(axis=0), .05)
            z, zz = (xx - mean) / scale, (x[hold] - mean) / scale
            total = ww.sum()
            center, intercept = (ww[:, None] * z).sum(axis=0) / total, float((ww * yy).sum() / total)
            z = z - center
            gram = z.T @ (ww[:, None] * z)
            gram.flat[::d + 1] += .001 * total
            coefficients = np.linalg.solve(gram, z.T @ (ww * (yy - intercept)))
            predicted = (zz - center) @ coefficients + intercept
            if clip:
                predicted = np.clip(predicted, yy.min(), yy.max())
            return predicted, {"training_rows": n, "holdout_rows": m, "features": d,
                "weight_sum": float(total), "coefficient_sha256": hashlib.sha256(coefficients.astype("<f8").tobytes()).hexdigest(),
                "normalizer_sha256": hashlib.sha256(np.r_[mean, scale].astype("<f8").tobytes()).hexdigest()}

        all_values = {}
        for row in selection["selected"]:
            if row["system"] != "ndu_control":
                continue
            seed, price = row["seed"], row["decision_price"]
            path = run / row["model_file"]
            before_file = sha(path)
            if before_file != row["model_sha256"]:
                raise ValueError("selected model file changed")
            model = JointModel.load(path)
            before = model.digest()
            if before != row["model_digest"]:
                raise ValueError("selected content digest changed")
            n, k = len(ids), model.dimensions[1]
            with phase("frozen_content_probe", seed=seed):
                ledger.model_forward("content_probe", rows=2*n, input_dim=202, hidden=model.dimensions[3], classes=k)
                _, hidden, pl, ql = model._forward(train["low"])
                _, _, pf, qf = model._forward(train["full"])
                ledger.charge_kernel("content_probe", "fixed_raw_reward", **setup_work(model.dimensions, "additive"))
                reward = outcome_table(model)[train["labels"]]
                ledger.charge_kernel("content_probe", "two_raw_values", **{
                    key: 2*value for key, value in value_work("additive", n).items()})
                low = np.sum(pl * np.einsum("nij,nj->ni", reward, ql), axis=1)
                full = np.sum(pf * np.einsum("nij,nj->ni", reward, qf), axis=1)
                ledger.charge_kernel("content_probe", "raw_gain", scalar_ops=n)
                delta = full - low
                ledger.charge_kernel("content_probe", "probability_features", scalar_ops=n*(6*k+7),
                    div_ops=2*n, log_ops=2*n*k+2, sort_items=2*n*k, compare_ops=4*n*k)
                probability_features = features(pl, ql)
                affine_features = np.column_stack((hidden, train["full"][:, 192:]))
            record = {"seed": seed, "model_sha256": before_file, "model_digest": before,
                      "decision_price": price, "target": {"min": float(delta.min()), "max": float(delta.max()),
                      "mean": float(delta.mean()), "sha256": hashlib.sha256(delta.astype("<f8").tobytes()).hexdigest()},
                      "methods": {}, "baselines": {}}
            methods = [(protocol["methods"][0], probability_features, delta, np.ones(n), True),
                       (protocol["methods"][1], affine_features, delta, np.ones(n), True),
                       (protocol["methods"][2], probability_features, (delta > price).astype(float), np.abs(delta-price), False)]
            for name, x, target, weight, clip in methods:
                predicted, fits = np.full(n, np.nan), []
                with phase("grouped_critic_OOF", seed=seed, method=name):
                    for fold in range(protocol["folds"]):
                        hold = folds == fold
                        values, fit_receipt = ridge_predict(x, target, weight, ~hold, hold, clip=clip)
                        predicted[hold] = values
                        fits.append({"fold": fold, **fit_receipt})
                if not np.isfinite(predicted).all():
                    raise ValueError("incomplete OOF predictions")
                action = predicted > (.5 if not clip else price)
                record["methods"][name] = {**metrics(action, delta, full, low, price), "fits": fits,
                    "prediction_sha256": hashlib.sha256(predicted.astype("<f8").tobytes()).hexdigest()}
                all_values.setdefault(name, []).append((action, delta, full, low, price))
            for name, action in (("always_full", np.ones(n, dtype=bool)),
                                 ("always_low", np.zeros(n, dtype=bool)), ("label_known_oracle", delta > price)):
                record["baselines"][name] = metrics(action, delta, full, low, price)
                all_values.setdefault(name, []).append((action, delta, full, low, price))
            if model.digest() != before or sha(path) != before_file:
                raise ValueError("diagnostic mutated selected model")
            result["seeds"].append(record)
        result["pooled"] = {}
        for name, values in all_values.items():
            entries = [metrics(*value) for value in values]
            result["pooled"][name] = {key: float(np.mean([entry[key] for entry in entries]))
                for key in ("wrong_decision_regret", "chosen_raw_utility", "route_gain_vs_full",
                            "continue_fraction", "false_stop_raw_loss")}
            losses = np.concatenate([np.where((~a)&(d>p), np.maximum(d, 0), 0.) for a,d,f,l,p in values])
            stops = sum(int((~a).sum()) for a,d,f,l,p in values)
            result["pooled"][name].update(false_stop_top5_loss_fraction=float(np.sort(losses)[-5:].sum()/losses.sum()) if losses.sum() else 0.,
                beneficial_stop_fraction_among_stops=sum(int(((~a)&(d<0)).sum()) for a,d,f,l,p in values)/stops if stops else None)
        ref = selection["efficient_reference"]
        nc = [row for row in selection["selected"] if row["system"] == "ndu_control"]
        static = [row for row in selection["selected"] if row["system"] == ref]
        raw_nc_full = float(np.mean([row["validation"]["full"]["task_utility"] for row in nc]))
        raw_reference = float(np.mean([row["validation"]["full"]["task_utility"] for row in static]))
        reports = selection["validation_measures"]
        raw_nc_selected = float(np.mean([r["means"]["task_utility"] for r in reports["ndu_control"].values()]))
        result["saved_validation_only"] = {"efficient_reference": ref,
            "content_full_gap": raw_nc_full - raw_reference,
            "routing_gap": raw_nc_selected - raw_nc_full,
            "actual_readiness": selection["selection_ready"],
            "actual_contrasts": selection["validation_mean_contrasts"]}
        if sha(selection_path) != selection_hash:
            raise ValueError("diagnostic mutated selection")
        result.update(outcome="completed", ledger=ledger.snapshot(), model_and_selection_unchanged=True,
            cost_scope="Declared mathematical kernel estimates only; data generation/hash/I/O/memory primitives are not priced as operators. All real diagnostic process CPU/wall includes them. Not qualification build cost.")
    except Exception as error:
        result.update(outcome="failed", error=repr(error), traceback=traceback.format_exc())
        raise
    finally:
        result.update(cpu_ns=time.process_time_ns()-started_cpu, wall_ns=time.perf_counter_ns()-started_wall)
        with out.open("x") as stream:
            json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps({"out": str(out), "cpu_ns": result["cpu_ns"], "pooled": result["pooled"]}, sort_keys=True))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    execute(parser.parse_args().run)
