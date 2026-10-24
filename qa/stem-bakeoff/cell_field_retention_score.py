"""Open only the newly registered final labels after the full prediction seal.

No fitting, selection, threshold search or rerunning a condition occurs here.
Bootstrap intervals condition on the three fixed fits and balanced source sample;
they are not uncertainty over all future training seeds/tasks/deployment traffic.
"""

import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from cell_learning_models import canonical


ROLES = {"old_test": 64, "future_june": 96, "future_july": 128}
ARMS = ("zero", "legacy_full_quadratic", "retention_hinge_suffix")
SEEDS, HEADS = (7, 17, 29), ("linear", "gated")


def _sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(path):
    return json.loads(Path(path).read_bytes())


def _write(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value) + b"\n")


def _loss(probabilities, labels):
    return -np.log(np.clip(probabilities[..., np.arange(len(labels)), labels], 1e-15, 1.0))


def _bootstrap_indices(labels, rng, draws):
    # Match the predeclared balanced-source design and pair every arm/seed.
    strata = [np.flatnonzero(labels == label) for label in range(4)]
    if any(len(index) == 0 for index in strata):
        raise ValueError("every registered final class must be represented")
    return np.concatenate([rng.choice(index, size=(draws, len(index)), replace=True) for index in strata], axis=1)


def _validate_predictions(final, initial, records):
    if (final.shape != (18, 480, 4) or initial.shape != (6, 480, 4)
            or not all(np.isfinite(p).all() and np.all(p >= 0) and np.all(p <= 1)
                       and np.allclose(p.sum(axis=-1), 1, rtol=0, atol=1e-12) for p in (final, initial))):
        raise ValueError("complete finite frozen probability predictions required")
    by_key = {(r["head"], r["seed"], r["arm"]): i for i, r in enumerate(records)}
    expected = {(h, s, a) for h in HEADS for s in SEEDS for a in ARMS}
    if (set(by_key) != expected or len(records) != 18 or any(r["status"] != "completed" for r in records)
            or any(r["initial_index"] != SEEDS.index(r["seed"]) * 2 + HEADS.index(r["head"]) for r in records)):
        raise ValueError("all declared paired conditions required; no complete-case subset")
    return by_key


def contrasts(final, initial, records, roles, *, draws=2000, seed=820241, tolerance=0.02):
    if draws != 2000 or seed != 820241 or tolerance != 0.02 or set(roles) != set(ROLES):
        raise ValueError("exact frozen scoring protocol required")
    by_key = _validate_predictions(final, initial, records)
    rng = np.random.default_rng(seed)
    bootstrap = {role: _bootstrap_indices(values[1], rng, draws) for role, values in roles.items()}

    def interval(point, samples):
        low, high = np.quantile(samples, [0.025, 0.975], method="linear")
        return {"estimate": float(point), "ci95": [float(low), float(high)],
                "upper97_5": float(high), "replicates": draws}

    result = {}
    for head in HEADS:
        losses, per_seed = {}, []
        for role, (indices, labels) in roles.items():
            losses[role] = {}
            for arm in ARMS:
                values = np.stack([_loss(final[by_key[(head, s, arm)]][indices], labels) for s in SEEDS])
                losses[role][arm] = values
            initial_indices = [next(r["initial_index"] for r in records if r["head"] == head and r["seed"] == s)
                               for s in SEEDS]
            losses[role]["original_warmup"] = np.stack([_loss(initial[i][indices], labels) for i in initial_indices])
            for j, s in enumerate(SEEDS):
                per_seed.append({"role": role, "seed": s,
                    "nll": {arm: float(v[j].mean()) for arm, v in losses[role].items()},
                    "balanced_accuracy": {arm: float(np.mean([
                        (np.argmax(final[by_key[(head, s, arm)]][indices], axis=1)[labels == label] == label).mean()
                        for label in range(4)])) for arm in ARMS}})
        future_deltas, future_boot = [], []
        monthly = {}
        for role in ("future_june", "future_july"):
            difference = (losses[role]["retention_hinge_suffix"] - losses[role]["legacy_full_quadratic"]).mean(axis=0)
            samples = difference[bootstrap[role]].mean(axis=1)
            future_deltas.append(difference.mean())
            future_boot.append(samples)
            monthly[role] = interval(difference.mean(), samples)
        future = interval(np.mean(future_deltas), np.mean(future_boot, axis=0))
        old = (losses["old_test"]["retention_hinge_suffix"] - losses["old_test"]["original_warmup"]).mean(axis=0)
        retention = interval(old.mean(), old[bootstrap["old_test"]].mean(axis=1))
        old_relative = (losses["old_test"]["retention_hinge_suffix"] - losses["old_test"]["legacy_full_quadratic"]).mean(axis=0)
        old_vs_legacy = interval(old_relative.mean(), old_relative[bootstrap["old_test"]].mean(axis=1))
        result[head] = {"primary_future_nll_hinge_minus_legacy": future,
            "monthly_future_nll_hinge_minus_legacy": monthly,
            "retention_old_test_nll_hinge_minus_original_warmup": retention,
            "secondary_old_test_nll_hinge_minus_legacy": old_vs_legacy,
            "future_gate": future["upper97_5"] < 0,
            "retention_gate": retention["upper97_5"] <= tolerance,
            "joint_gates_pass": future["upper97_5"] < 0 and retention["upper97_5"] <= tolerance,
            "all_seeds_and_roles": per_seed}
    return result


def score(run, data, output, *, expected_seal_sha256):
    began, cpu_began = time.perf_counter_ns(), time.process_time_ns()
    run, data = Path(run), Path(data)
    if _sha(run / "seal.json") != expected_seal_sha256:
        raise ValueError("externally frozen prediction seal differs")
    seal = _json(run / "seal.json")
    if seal.get("schema") != "hepta.cell-retention.prediction-seal.v1" or seal.get("final_labels_opened") is not False:
        raise ValueError("unopened-label prediction seal required")
    for name, key in (("summary.json", "summary_sha256"), ("frozen_predictions.npz", "predictions_sha256"),
                      ("input_manifest.json", "input_manifest_sha256"), ("protocol.json", "protocol_sha256")):
        if _sha(run / name) != seal[key]:
            raise ValueError("prediction/input/protocol publication changed after sealing")
    plan, summary = _json(run / "protocol.json"), _json(run / "summary.json")
    if (plan.get("scorer_source_sha256") != _sha(__file__) or summary["protocol_sha256"] != seal["protocol_sha256"]
            or summary.get("final_labels_opened") is not False):
        raise ValueError("registered scoring source or experiment identity differs")
    if summary["completed_conditions"] != 18 or any(r["status"] != "completed" for r in summary["records"]):
        result = {"schema": "hepta.cell-retention.score.v1", "status": "blocked_incomplete_conditions",
                  "final_labels_opened": False, "expected_conditions": 18,
                  "completed_conditions": summary["completed_conditions"], "seal_sha256": expected_seal_sha256}
        _write(output, result)
        return result
    with np.load(run / "frozen_predictions.npz", allow_pickle=False) as arrays:
        final, initial = arrays["final"], arrays["initial"]
    _validate_predictions(final, initial, summary["records"])
    if _sha(data / "sources.json") != seal["sources_sha256"]:
        raise ValueError("source row identity differs from frozen predictions")
    sources = _json(data / "sources.json")["rows"]
    if len(sources) != 480 or [r["source_id"] for r in sources] != summary["row_source_ids"]:
        raise ValueError("source order differs from frozen predictions")
    # FIRST new final-label access occurs only after every label-free identity gate.
    if _sha(data / "final_labels.json") != seal["final_labels_sha256"]:
        raise ValueError("new registered final labels changed")
    gold = _json(data / "final_labels.json")
    if gold.get("classes") != 4 or set(gold.get("roles", {})) != set(ROLES):
        raise ValueError("only the three newly registered final cohorts may be scored")
    roles, used = {}, set()
    for role, count in ROLES.items():
        values = gold["roles"][role]
        indices, labels = np.asarray(values["indices"]), np.asarray(values["labels"])
        if (indices.dtype.kind not in "iu" or labels.dtype.kind not in "iu"
                or indices.shape != (count,) or labels.shape != (count,)
                or np.any(indices < 0) or np.any(indices >= 480)
                or len(set(indices.tolist())) != count or used.intersection(indices.tolist())
                or dict(zip(*np.unique(labels, return_counts=True))) != {k: count // 4 for k in range(4)}
                or values["source_ids"] != [sources[i]["source_id"] for i in indices]
                or any(sources[i]["role"] != role for i in indices)):
            raise ValueError("final source/role/category alignment differs")
        used.update(indices.tolist())
        roles[role] = (indices, labels)
    result = {"schema": "hepta.cell-retention.score.v1", "status": "scored_once",
        "seal_sha256": expected_seal_sha256, "protocol_sha256": seal["protocol_sha256"],
        "final_labels_sha256": seal["final_labels_sha256"], "final_labels_opened": True,
        "heads": contrasts(final, initial, summary["records"], roles),
        "inference_scope": "paired category-stratified source-component bootstrap, conditional on three fixed fits; equal June/July month weight",
        "multiplicity": "two heads, Bonferroni one-sided alpha0.025 each; require future gain and retention vs original warmup together",
        "cost_gate": "not automatically certified; report all common/worker/controller/recovery costs and failures separately",
        "claim_scope": "one finite historical news classification family, registered-source disjointness only; no agent/split/network/AGI gain",
        "wall_ns": time.perf_counter_ns() - began, "cpu_ns": time.process_time_ns() - cpu_began,
        "authority": "DENY_ALL"}
    _write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("run", "data", "output", "expected-seal-sha256"):
        parser.add_argument("--" + name, required=True)
    result = score(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"], "heads": {k: {name: value for name, value in v.items()
        if name != "all_seeds_and_roles"} for k, v in result.get("heads", {}).items()}}, indent=2))
