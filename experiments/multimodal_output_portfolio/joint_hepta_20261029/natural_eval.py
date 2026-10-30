"""Bounded natural observer experiment with training-only selection and fresh gates.

The 64-source pilot is separately versioned; it cannot replace the original
512-source v4 study. A completed negative result remains a scientific failure.
"""

import argparse
from collections import Counter
import json
from pathlib import Path
import platform
import resource
import time

from .natural_data import (HERE, OLD, budget_check, cpu_seconds, digest, download_weights,
                           freeze_allocation, load_allocation, prepare_role, read_inputs,
                           restore_portable_seed, select_training, write_new)


def source_weights(rows):
    import numpy as np
    counts = Counter(row["source_id"] for row in rows)
    if not counts:
        raise ValueError("Observer needs nonempty original source clusters")
    return np.asarray([1 / (len(counts) * counts[r["source_id"]]) for r in rows], dtype=np.float64)


def load_features(allocation, assets, role):
    import numpy as np
    expected = [r for r in allocation["selected"] if r["study_role"] == role]
    rows, features = [], {"action": [], "sound": []}
    hashes = set()
    for source in expected:
        root = Path(assets) / "prepared" / role / source["source_id"]
        record = json.loads((root / "RECEIPT.json").read_text())
        if (record["allocation_sha256"] != allocation["allocation_sha256"]
                or record["role"] != role or record["source_id"] != source["source_id"]
                or record["original_sha256"] in hashes
                or digest((root / "FEATURES.npz").read_bytes()) != record["feature_sha256"]):
            raise ValueError("Real observer feature provenance changed")
        hashes.add(record["original_sha256"])
        events = source["events"][:source["retained_event_count"]]
        if len(record["events"]) != len(events):
            raise ValueError("Incomplete frozen natural events")
        for actual, frozen in zip(record["events"], events, strict=True):
            if (actual["role"] != role or actual["source_id"] != source["source_id"]
                    or any(actual[key] != value for key, value in frozen.items())):
                raise ValueError("Prepared natural labels or windows changed")
        with np.load(root / "FEATURES.npz", allow_pickle=False) as data:
            for kind, key, width in (("action", "video", 1424), ("sound", "audio", 1551)):
                value = data[key]
                if value.shape != (len(events), width) or not np.isfinite(value).all():
                    raise ValueError("Unexpected real feature shape or nonfinite feature")
                features[kind].append(value)
        rows.extend(record["events"])
    return rows, {k: np.concatenate(v).astype(np.float64) for k, v in features.items()}


def report_accuracy(predicted, rows, kind):
    import numpy as np
    actual = np.asarray([r[kind + "_id"] for r in rows])
    correct = np.asarray(predicted) == actual
    return {"source_uniform_accuracy": float(correct @ source_weights(rows)),
            "event_accuracy": float(correct.mean()), "correct": int(correct.sum()),
            "events": len(rows), "sources": len({r["source_id"] for r in rows}),
            "predictions": np.asarray(predicted).tolist(), "labels": actual.tolist(),
            "source_ids": [r["source_id"] for r in rows]}


def majority_label(rows, kind, classes):
    weights = source_weights(rows)
    mass = {label: 0.0 for label in classes}
    for weight, row in zip(weights, rows, strict=True):
        mass[row[kind + "_id"]] += float(weight)
    return max(classes, key=lambda label: mass[label])


def normalize_fit(features, weights):
    import numpy as np
    mean = weights @ features
    scale = np.maximum(np.sqrt(weights @ ((features - mean) ** 2)), .01)
    return mean, scale, np.clip((features - mean) / scale, -8, 8)


def make_mlp(width, classes):
    import torch
    return torch.nn.Sequential(torch.nn.Linear(width, 128), torch.nn.SiLU(),
                               torch.nn.Dropout(.15), torch.nn.Linear(128, len(classes)))


def fit(features, rows, kind, family, classes, seed, protocol, recovery, start_cpu, start_wall):
    import numpy as np
    import torch
    weights = source_weights(rows)
    mean, scale, x = normalize_fit(features, weights)
    labels = np.asarray([classes.index(r[kind + "_id"]) for r in rows])
    state = {"family": family, "mean": mean, "scale": scale, "classes": classes,
             "feature_width": features.shape[1], "majority_label": majority_label(rows, kind, classes)}
    identity = digest({"kind": kind, "family": family, "source_events": [r["event_id"] for r in rows],
                       "features": digest(features.tobytes()), "labels": labels.tolist(), "protocol": protocol})
    if family == "ridge100":
        target = np.eye(len(classes))[labels]
        xmean, ymean = weights @ x, weights @ target
        rootw = np.sqrt(weights * len(rows))[:, None]
        xx, yy = (x - xmean) * rootw, (target - ymean) * rootw
        beta = xx.T @ np.linalg.solve(xx @ xx.T + protocol["ridge"]["lambda"] * np.eye(len(rows)), yy)
        return {**state, "weights": beta, "intercept": ymean - xmean @ beta,
                "identity": identity, "optimizer_updates": 0}
    if family != "mlp128":
        raise ValueError("Unregistered natural observer candidate")
    torch.manual_seed(seed)
    model = make_mlp(features.shape[1], classes)
    optimizer = torch.optim.AdamW(model.parameters(), lr=protocol["mlp"]["learning_rate"],
                                  weight_decay=protocol["mlp"]["weight_decay"])
    xx, yy = torch.tensor(x, dtype=torch.float32), torch.tensor(labels, dtype=torch.long)
    rng = torch.Generator().manual_seed(seed + 1)
    probability = torch.tensor(weights, dtype=torch.float64)
    for step in range(1, protocol["mlp"]["updates"] + 1):
        indices = torch.multinomial(probability, protocol["mlp"]["batch_size"], replacement=True, generator=rng)
        loss = torch.nn.functional.cross_entropy(model(xx[indices]), yy[indices])
        optimizer.zero_grad(set_to_none=True); loss.backward(); optimizer.step()
        if step % protocol["mlp"]["recovery_every"] == 0:
            temporary = recovery.with_suffix(".pending")
            torch.save({"identity": identity, "completed_step": step, "model": model.state_dict(),
                        "optimizer": optimizer.state_dict(), "sampler_rng": rng.get_state(),
                        "global_rng": torch.get_rng_state(), "seed": seed}, temporary)
            temporary.replace(recovery)
            budget_check(start_cpu, start_wall, protocol)
    return {**state, "state_dict": {k: v.detach().clone() for k, v in model.state_dict().items()},
            "identity": identity, "optimizer_updates": protocol["mlp"]["updates"]}


def predict(state, features):
    import numpy as np
    import torch
    x = np.clip((features - state["mean"]) / state["scale"], -8, 8)
    if state["family"] == "ridge100":
        scores = x @ state["weights"] + state["intercept"]
    else:
        model = make_mlp(state["feature_width"], state["classes"]).eval()
        model.load_state_dict(state["state_dict"], strict=True)
        with torch.no_grad():
            scores = model(torch.tensor(x, dtype=torch.float32)).numpy()
    return np.asarray(state["classes"])[scores.argmax(1)]


def fit_observers(allocation, assets, output, start_cpu, start_wall):
    import numpy as np
    import torch
    rows, features = load_features(allocation, assets, "observer_train")
    protocol = allocation["protocol"]
    folds = np.asarray([r["fold"] for r in rows])
    if set(folds) != set(range(5)):
        raise ValueError("All five source folds are required")
    all_results, selected, saved = {}, {}, {}
    updates = 0
    for kind in ("action", "sound"):
        classes = sorted(map(int, allocation["ontology"][kind]))
        results = []
        for family in protocol["candidate_order"]:
            predictions, majority = np.empty(len(rows), int), np.empty(len(rows), int)
            visits = np.zeros(len(rows), int)
            fits = []
            for fold in range(5):
                train, valid = np.where(folds != fold)[0], np.where(folds == fold)[0]
                training_rows = [rows[i] for i in train]
                if {rows[i]["source_id"] for i in train} & {rows[i]["source_id"] for i in valid}:
                    raise ValueError("Original source leaked across observer folds")
                state = fit(features[kind][train], training_rows, kind, family, classes,
                            protocol["mlp"]["base_seed"] + fold, protocol,
                            output / f"{kind}-{family}-fold{fold}-recovery.pt", start_cpu, start_wall)
                predictions[valid] = predict(state, features[kind][valid])
                majority[valid] = state["majority_label"]
                visits[valid] += 1
                updates += state["optimizer_updates"]
                fits.append({"fold": fold, "fit_identity": state["identity"], "training_sources": len({r["source_id"] for r in training_rows}),
                             "validation_sources": len({rows[i]["source_id"] for i in valid}), "optimizer_updates": state["optimizer_updates"]})
            if not np.all(visits == 1):
                raise ValueError("Each retained event needs exactly one OOF prediction")
            result = {"candidate": family, "out_of_fold": report_accuracy(predictions, rows, kind),
                      "majority_control": report_accuracy(majority, rows, kind), "folds": fits}
            results.append(result)
            print(json.dumps({"natural_observer": kind, "candidate": family,
                              "source_oof_accuracy": result["out_of_fold"]["source_uniform_accuracy"]}), flush=True)
        best = max(range(len(results)), key=lambda i: results[i]["out_of_fold"]["source_uniform_accuracy"])
        chosen = results[best]
        state = fit(features[kind], rows, kind, chosen["candidate"], classes, protocol["mlp"]["final_seed"],
                    protocol, output / f"{kind}-final-recovery.pt", start_cpu, start_wall)
        updates += state["optimizer_updates"]
        path = output / (kind + "_observer.pt")
        torch.save({k: torch.from_numpy(v) if isinstance(v, np.ndarray) else v for k, v in state.items()}, path)
        selected[kind] = {"candidate": chosen["candidate"], "out_of_fold": chosen["out_of_fold"],
                          "majority_control": chosen["majority_control"], "checkpoint_file": path.name,
                          "checkpoint_sha256": digest(path.read_bytes()), "training_majority_label": state["majority_label"],
                          "training_present_classes": sorted({r[kind + "_id"] for r in rows}), "all_classes": classes}
        all_results[kind], saved[kind] = results, state
    passed = all(value["out_of_fold"]["source_uniform_accuracy"] >= .6
                 and value["out_of_fold"]["source_uniform_accuracy"] > value["majority_control"]["source_uniform_accuracy"]
                 for value in selected.values())
    freeze = {"schema": "hepta.joint-natural-observer-freeze.v1", "allocation_sha256": allocation["allocation_sha256"],
              "protocol_sha256": allocation["protocol_sha256"], "candidates": all_results, "selected": selected,
              "complete_folds": 5, "models_refitted_and_frozen": True, "optimizer_updates": updates,
              "development_passed": passed, "fresh_calibration_media_accessed": False,
              "old_heldout_media_accessed": False, "generator_semantic_qualification": False,
              "training_source_hashes": sorted({r["source_sha256"] for r in rows}),
              "source_code_sha256": {p.name: digest(p.read_bytes()) for p in (HERE / "natural_data.py", HERE / "natural_eval.py", HERE / "natural_protocol.json")}}
    write_new(output / "OBSERVER_FREEZE.json", freeze)
    return freeze, saved


def calibrate(allocation, assets, freeze, states, output):
    from scipy.stats import beta
    rows, features = load_features(allocation, assets, "fresh_observer_calibration")
    if len(rows) != 64 or len({r["source_id"] for r in rows}) != 64:
        raise ValueError("All 64 one-event fresh sources are required")
    if {r["source_sha256"] for r in rows} & set(freeze["training_source_hashes"]):
        raise ValueError("Fresh calibration duplicates training media bytes")
    results = {}
    for kind in ("action", "sound"):
        selected = freeze["selected"][kind]
        if digest((output / selected["checkpoint_file"]).read_bytes()) != selected["checkpoint_sha256"]:
            raise ValueError("Selected observer changed after its freeze")
        report = report_accuracy(predict(states[kind], features[kind]), rows, kind)
        majority = report_accuracy([selected["training_majority_label"]] * len(rows), rows, kind)
        n, k = len(rows), report["correct"]
        report["binomial_interval_95"] = [float(beta.ppf(.025, k, n - k + 1)) if k else 0.,
                                          float(beta.ppf(.975, k + 1, n - k)) if k < n else 1.]
        report["majority_control"] = majority
        report["adequate"] = report["source_uniform_accuracy"] >= .6 and report["source_uniform_accuracy"] > majority["source_uniform_accuracy"]
        results[kind] = report
    result = {"schema": "hepta.joint-natural-observer-calibration.v1", "allocation_sha256": allocation["allocation_sha256"],
              "observer_freeze_sha256": digest(freeze), "results": results,
              "adequate_on_original_media": all(r["adequate"] for r in results.values()),
              "generated_output_reliability_established": False, "generator_semantic_qualification": False,
              "old_policy_or_qualification_accessed": False,
              "scope": "Original-media observer accuracy; generated distribution and independent participant generalization remain unqualified"}
    write_new(output / "CALIBRATION.json", result)
    return result


def run(output, phase, seed_source=None, registry_path=None):
    start_cpu, start_wall = cpu_seconds(), time.monotonic()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {"schema": "hepta.joint-natural-run.v1", "phase": phase, "status": "started",
              "old_policy_or_qualification_accessed": False, "semantic_qualification": False,
              "network_failure_is_not_negative_scientific_evidence": True}
    try:
        assets = restore_portable_seed(output / "assets", seed_source)
        protocol, source, registry = read_inputs(assets, registry_path)
        if phase == "seed":
            selected = select_training(source, protocol)
            result.update(status="original_seed_and_roles_verified", prepared_observer_sources=8,
                          observer_events=43, selected_generator_sources=[r["source_id"] for r in selected if r["study_role"] == "generator_train"],
                          historical_excluded_count=len({r["source_id"] for r in registry["source_rows"]}
                          | set(registry["historical112_source_ids"]) | set(registry["host16_source_ids"])))
            return result
        allocation = freeze_allocation(assets, output, registry_path)
        # Original seed cache remains immutable and is not mixed with new post-codec features.
        prepared_assets = output / "actual"
        prepared_assets.mkdir()
        if phase == "generator":
            rows = prepare_role(allocation, prepared_assets, "generator_train", start_cpu=start_cpu, start_wall=start_wall)
            result.update(status="real_generator_training_media_prepared", sources=len({r["source_id"] for r in rows}),
                          events=len(rows), assets=str(prepared_assets), manifest=str(output / "ALLOCATION.json"),
                          generator_updates=0, observer_training_sources_used_by_generator=0)
            return result
        import torch
        from ..closure_20261028.semantic_backbones import SemanticBackbones
        torch.set_num_threads(protocol["budget"]["torch_threads"])
        result["runtime"] = {"python": platform.python_version(), "torch": torch.__version__}
        result["weights"] = download_weights(prepared_assets / "pretrained")
        models = SemanticBackbones(prepared_assets / "pretrained")
        rows = prepare_role(allocation, prepared_assets, "observer_train", models=models, start_cpu=start_cpu, start_wall=start_wall)
        freeze, states = fit_observers(allocation, prepared_assets, output, start_cpu, start_wall)
        result.update(observer_training_sources=len({r["source_id"] for r in rows}), observer_training_events=len(rows),
                      optimizer_updates=freeze["optimizer_updates"], development_passed=freeze["development_passed"])
        if not freeze["development_passed"]:
            result.update(status="observer_development_gate_failed", fresh_calibration_media_accessed=False,
                          fresh_calibration_predictions=0, frozen_failure_retained=True)
            return result
        # Freeze and checkpoint verification precede the very first fresh media read.
        for selected in freeze["selected"].values():
            if digest((output / selected["checkpoint_file"]).read_bytes()) != selected["checkpoint_sha256"]:
                raise ValueError("Frozen observer checkpoint changed before fresh-media admission")
        write_new(output / "CALIBRATION_CONSUMPTION_STARTED.json", {"allocation_sha256": allocation["allocation_sha256"],
                  "observer_freeze_sha256": digest(freeze), "new_run_required_after_interruption": True})
        prepare_role(allocation, prepared_assets, "fresh_observer_calibration", models=models, freeze=freeze,
                     start_cpu=start_cpu, start_wall=start_wall)
        cal = calibrate(allocation, prepared_assets, freeze, states, output)
        result.update(status="observer_calibration_passed_original_media_only" if cal["adequate_on_original_media"] else "observer_calibration_failed",
                      fresh_calibration_media_accessed=True, fresh_calibration_predictions=64,
                      generated_output_reliability_established=False)
        return result
    except Exception as exc:
        result.update(status="incomplete_or_failed", error=type(exc).__name__ + ": " + str(exc))
        return result
    finally:
        result.update(cpu_seconds_self_plus_completed_children=cpu_seconds() - start_cpu,
                      wall_seconds=time.monotonic() - start_wall,
                      self_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      largest_child_peak_rss_bytes=resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024,
                      physical_cpu_tail_bound_proved=False,
                      cost_scope="Python entry through result assembly including in-process downloads and all reaped codec children; external runner setup/package installation excluded")
        write_new(output / "RESULT.json", result)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("seed", "generator", "observer"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed-source", type=Path)
    parser.add_argument("--registry", type=Path)
    arguments = parser.parse_args()
    report = run(arguments.output, arguments.phase, arguments.seed_source, arguments.registry)
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(1 if report["status"] == "incomplete_or_failed" else 0)
