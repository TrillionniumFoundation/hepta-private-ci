"""Independently verify sealed retention predictions, fixed contrasts and costs.

This auditor never imports the experiment/scorer, fits a model, or selects a
policy. It reads already-opened final labels only after verifying the supplied
external seal and score hashes. All output is a new exclusive local file.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import io
import json
from pathlib import Path
import platform
import stat
import zipfile

import numpy as np


EXPECTED_SEAL = "189daef4888c294886707df4203df492a0c68267a3459023396728bf312c6ce9"
EXPECTED_SCORE = "316c30e55e44ba4201ebe732225d498825d480a618167c58e323c9f981ccec0e"
HEADS = ("linear", "gated")
SEEDS = (7, 17, 29)
ARMS = ("zero", "legacy_full_quadratic", "retention_hinge_suffix")
ROLES = (("old_test", 64), ("future_june", 96), ("future_july", 128))
ATOL = 2e-12


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_bytes(path, limit=32 * 1024**2):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), "aliased path")
    status = path.stat()
    require(stat.S_ISREG(status.st_mode) and status.st_nlink == 1, "regular unaliased file required")
    require(status.st_size <= limit, "file exceeds audit bound")
    return path.read_bytes()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        require(key not in value, "duplicate JSON key")
        value[key] = item
    return value


def bad_number(value):
    raise ValueError("nonfinite JSON number: " + value)


def read_json(path):
    data = read_bytes(path)
    return json.loads(data, object_pairs_hook=unique_object, parse_constant=bad_number), digest(data)


def interval(point, samples):
    low, high = np.quantile(samples, [0.025, 0.975], method="linear")
    return {"estimate": float(point), "ci95": [float(low), float(high)],
            "upper97_5": float(high), "replicates": 2000}


def nll(probabilities, rows, labels):
    selected = probabilities[rows, labels]
    return -np.log(np.minimum(1.0, np.maximum(1e-15, selected)))


def recompute(final, initial, records, roles):
    positions = {(r["head"], r["seed"], r["arm"]): i for i, r in enumerate(records)}
    rng = np.random.default_rng(820241)
    draws = {}
    # Fixed role order is part of the preregistered RNG stream, not JSON order.
    for name, _ in ROLES:
        _, labels = roles[name]
        strata = [np.flatnonzero(labels == category) for category in range(4)]
        draws[name] = np.concatenate([
            rng.choice(stratum, (2000, len(stratum)), replace=True) for stratum in strata
        ], axis=1)
    heads = {}
    for head in HEADS:
        losses, per_seed = {}, []
        for role, _ in ROLES:
            rows, labels = roles[role]
            losses[role] = {}
            for arm in ARMS:
                losses[role][arm] = np.asarray([
                    nll(final[positions[head, seed, arm]], rows, labels) for seed in SEEDS
                ])
            losses[role]["original_warmup"] = np.asarray([
                nll(initial[SEEDS.index(seed) * 2 + HEADS.index(head)], rows, labels)
                for seed in SEEDS
            ])
            for j, seed in enumerate(SEEDS):
                accuracies = {}
                for arm in ARMS:
                    guesses = final[positions[head, seed, arm]][rows].argmax(axis=1)
                    accuracies[arm] = float(np.mean([
                        np.mean(guesses[labels == category] == category) for category in range(4)
                    ]))
                per_seed.append({"role": role, "seed": seed,
                    "nll": {arm: float(values[j].mean()) for arm, values in losses[role].items()},
                    "balanced_accuracy": accuracies})
        monthly, points, samples = {}, [], []
        for role in ("future_june", "future_july"):
            paired = np.mean(losses[role]["retention_hinge_suffix"]
                             - losses[role]["legacy_full_quadratic"], axis=0)
            boot = np.mean(paired[draws[role]], axis=1)
            monthly[role] = interval(paired.mean(), boot)
            points.append(paired.mean())
            samples.append(boot)
        future = interval(np.mean(points), np.mean(samples, axis=0))
        old = np.mean(losses["old_test"]["retention_hinge_suffix"]
                      - losses["old_test"]["original_warmup"], axis=0)
        retention = interval(old.mean(), np.mean(old[draws["old_test"]], axis=1))
        relative = np.mean(losses["old_test"]["retention_hinge_suffix"]
                           - losses["old_test"]["legacy_full_quadratic"], axis=0)
        old_vs_legacy = interval(relative.mean(), np.mean(relative[draws["old_test"]], axis=1))
        future_gate = future["upper97_5"] < 0
        retention_gate = retention["upper97_5"] <= 0.02
        heads[head] = {"primary_future_nll_hinge_minus_legacy": future,
            "monthly_future_nll_hinge_minus_legacy": monthly,
            "retention_old_test_nll_hinge_minus_original_warmup": retention,
            "secondary_old_test_nll_hinge_minus_legacy": old_vs_legacy,
            "future_gate": future_gate, "retention_gate": retention_gate,
            "joint_gates_pass": future_gate and retention_gate,
            "all_seeds_and_roles": per_seed}
    return heads


def compare(actual, expected, path="heads"):
    if isinstance(actual, dict):
        require(isinstance(expected, dict) and set(actual) == set(expected), "keys differ: " + path)
        return max((compare(value, expected[key], path + "." + key)
                    for key, value in actual.items()), default=0.0)
    if isinstance(actual, list):
        require(isinstance(expected, list) and len(actual) == len(expected), "length differs: " + path)
        return max((compare(a, b, path + f"[{i}]")
                    for i, (a, b) in enumerate(zip(actual, expected))), default=0.0)
    if isinstance(actual, float):
        require(type(expected) in (float, int), "number type differs: " + path)
        difference = abs(actual - expected)
        require(difference <= ATOL, "numeric mismatch: " + path)
        return difference
    require(type(actual) is type(expected) and actual == expected, "value differs: " + path)
    return 0.0


def costs(summary):
    groups = defaultdict(list)
    for record in summary["records"]:
        groups[record["head"], record["arm"]].append(record)
        require(record["supervisor"]["return_code"] == 0
                and record["supervisor"]["wall_timeout"] is False, "worker supervision failed")
        require(record["complete_state_reload"]["bitwise_equal"] is True
                and record["serving_roundtrip_equal"] is True, "reload equality failed")
        receipt = record["controller_receipt"]
        require(receipt["status"] == "completed" and receipt["applied_steps"] == 24
                and receipt["expected_steps"] == 24 and receipt["error"] is None,
                "incomplete controller trajectory")
        require(record["child_process_cpu_ns"] == 0, "unexpected worker subprocess CPU")
        for field in ("worker_cpu_ns", "worker_wall_ns", "process_peak_rss_bytes"):
            require(type(record[field]) is int and record[field] >= 0, "invalid worker accounting")
    totals = []
    for (head, arm), values in sorted(groups.items()):
        phase = defaultdict(lambda: {"calls": 0, "wall_ns": 0, "cpu_ns": 0})
        for record in values:
            for name, counters in record["controller_receipt"]["phase_costs"].items():
                for key in ("calls", "wall_ns", "cpu_ns"):
                    phase[name][key] += counters[key]
        totals.append({"head": head, "arm": arm, "workers": len(values),
            "reaped_worker_cpu_ns": sum(r["supervisor"]["reaped_child_cpu_ns"] for r in values),
            "sequential_supervisor_wall_ns": sum(r["supervisor"]["elapsed_wall_ns"] for r in values),
            "worker_measured_body_cpu_ns": sum(r["worker_cpu_ns"] for r in values),
            "controller_cpu_ns_subset": sum(r["controller_receipt"]["cpu_ns"] for r in values),
            "phase_subsets": dict(phase),
            "process_peak_rss_bytes_range": [min(r["process_peak_rss_bytes"] for r in values),
                                              max(r["process_peak_rss_bytes"] for r in values)]})
    reaped = sum(v["reaped_worker_cpu_ns"] for v in totals)
    require(abs(reaped - summary["all_reaped_worker_cpu_ns"]) <= 2,
            "supervisor reaped CPU does not telescope to owner census")
    return {"per_head_arm": totals,
        "owner_cpu_ns_before_publication": summary["owner_cpu_ns"],
        "reaped_worker_cpu_ns": summary["all_reaped_worker_cpu_ns"],
        "disjoint_owner_plus_reaped_cpu_ns_before_publication":
            summary["owner_cpu_ns"] + summary["all_reaped_worker_cpu_ns"],
        "experiment_wall_ns_before_publication": summary["wall_ns"],
        "shared_feature_cost_separate": summary["shared_feature_cost"],
        "owner_process_peak_rss_bytes": summary["owner_process_peak_rss_bytes"],
        "scope": ["Controller/phase/persistence times are subsets, not extra additive CPU.",
            "Reaped child CPU includes fresh interpreter work omitted by worker-body timers.",
            "Owner summary timers end before final source/input rehash, summary and seal writes.",
            "Acquisition, source/cohort preparation, encoding and scoring are separate intervals.",
            "High-water RSS values are not additive simultaneous memory, energy or incremental RSS.",
            "No deployment cost or net-benefit gate is certified by these measurements."]}


def audit(run, data, score, source, output, expected_seal, expected_score):
    run, data, source = Path(run), Path(data), Path(source)
    seal, seal_sha = read_json(run / "seal.json")
    require(seal_sha == expected_seal, "external seal mismatch")
    scored, score_sha = read_json(score)
    require(score_sha == expected_score, "external score mismatch")
    require(seal["schema"] == "hepta.cell-retention.prediction-seal.v1"
            and seal["final_labels_opened"] is False, "prediction seal status")
    verified = {"seal.json": seal_sha, "score.json": score_sha}
    for name, key in (("summary.json", "summary_sha256"), ("protocol.json", "protocol_sha256"),
                      ("input_manifest.json", "input_manifest_sha256"),
                      ("frozen_predictions.npz", "predictions_sha256")):
        verified[name] = digest(read_bytes(run / name))
        require(verified[name] == seal[key], "sealed file mismatch: " + name)
    summary, _ = read_json(run / "summary.json")
    plan, _ = read_json(run / "protocol.json")
    inputs, _ = read_json(run / "input_manifest.json")
    require(summary["protocol_sha256"] == seal["protocol_sha256"] == inputs["protocol_sha256"]
            == scored["protocol_sha256"], "protocol identity mismatch")
    require(summary["final_labels_opened"] is False and inputs["final_labels"]["opened"] is False
            and scored["final_labels_opened"] is True and scored["status"] == "scored_once"
            and scored["seal_sha256"] == seal_sha, "score/publication state mismatch")
    sources_verified = {}
    for name, pinned in {**plan["source_code_sha256"],
                         "cell_field_retention_score.py": plan["scorer_source_sha256"]}.items():
        require(Path(name).name == name, "unexpected source path")
        sources_verified[name] = digest(read_bytes(source / name))
        require(sources_verified[name] == pinned, "registered source mismatch: " + name)
    require(inputs["source_code_sha256"] == plan["source_code_sha256"], "input source identity mismatch")
    records = summary["records"]
    expected_keys = {(h, s, a) for h in HEADS for s in SEEDS for a in ARMS}
    require(len(records) == 18 and summary["completed_conditions"] == 18
            and summary["expected_conditions"] == 18, "incomplete census")
    require({(r["head"], r["seed"], r["arm"]) for r in records} == expected_keys
            and all(r["status"] == "completed" for r in records), "condition identity mismatch")
    require(all(r["initial_index"] == SEEDS.index(r["seed"]) * 2 + HEADS.index(r["head"])
                for r in records), "unpaired initial heads")
    require(len(summary["initials"]) == 6 and all(i["status"] == "completed" for i in summary["initials"]),
            "incomplete initial census")
    payload = read_bytes(run / "frozen_predictions.npz")
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        require({i.filename for i in archive.infolist()} == {"final.npy", "initial.npy"}
                and len(archive.infolist()) == 2
                and sum(i.file_size for i in archive.infolist()) < 2 * 1024**2, "prediction archive shape")
    with np.load(io.BytesIO(payload), allow_pickle=False) as archive:
        final, initial = archive["final"].copy(), archive["initial"].copy()
    require(final.shape == (18, 480, 4) and initial.shape == (6, 480, 4), "prediction tensor shape")
    for probabilities in (final, initial):
        require(probabilities.dtype == np.float64 and np.isfinite(probabilities).all()
                and np.all((probabilities >= 0) & (probabilities <= 1))
                and np.allclose(probabilities.sum(axis=-1), 1, rtol=0, atol=1e-12), "invalid probabilities")
    source_rows, verified["sources.json"] = read_json(data / "sources.json")
    require(verified["sources.json"] == seal["sources_sha256"], "source order hash mismatch")
    source_rows = source_rows["rows"]
    require(len(source_rows) == 480 and len({r["source_id"] for r in source_rows}) == 480
            and len({r["component_id"] for r in source_rows}) == 480
            and [r["source_id"] for r in source_rows] == summary["row_source_ids"], "source order mismatch")
    gold, verified["final_labels.json"] = read_json(data / "final_labels.json")
    require(verified["final_labels.json"] == seal["final_labels_sha256"]
            == inputs["final_labels"]["sha256"] == scored["final_labels_sha256"], "label hash mismatch")
    require(gold["classes"] == 4 and set(gold["roles"]) == {r for r, _ in ROLES}, "label roles mismatch")
    roles, used = {}, set()
    for role, count in ROLES:
        values = gold["roles"][role]
        rows, labels = np.asarray(values["indices"]), np.asarray(values["labels"])
        require(rows.dtype.kind in "iu" and labels.dtype.kind in "iu"
                and rows.shape == labels.shape == (count,), "gold type/shape mismatch")
        require(np.all((rows >= 0) & (rows < 480)) and len(set(rows.tolist())) == count
                and not used.intersection(rows.tolist())
                and Counter(labels.tolist()) == {c: count // 4 for c in range(4)}, "cohort alignment mismatch")
        require(values["source_ids"] == [source_rows[i]["source_id"] for i in rows]
                and all(source_rows[i]["role"] == role for i in rows), "source role mismatch")
        used.update(rows.tolist())
        roles[role] = rows, labels
    heads = recompute(final, initial, records, roles)
    max_difference = compare(heads, scored["heads"])
    result = {"schema": "hepta.cell-retention.independent-audit.v1", "status": "verified",
        "auditor_source_sha256": digest(read_bytes(__file__)),
        "audit_environment": {"python": platform.python_version(), "numpy": np.__version__},
        "verified_input_hashes": verified, "verified_registered_source_hashes": sources_verified,
        "all_conditions": 18, "heads": heads, "maximum_absolute_score_difference": max_difference,
        "comparison_absolute_tolerance": ATOL, "cost_audit": costs(summary),
        "scoring_interval_separate": {k: scored[k] for k in ("wall_ns", "cpu_ns")},
        "scope": "Independent arithmetic/byte audit; no model execution or reselection. Conditional on fixed fits and balanced historical sources; not AGI/agent/deployment evidence.",
        "historical_order_limit": "Seal/source/records checked; this audit cannot prove absence of external label access outside the recorded experiment.",
        "authority": "DENY_ALL"}
    with Path(output).open("xb") as stream:
        stream.write(json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("run", "data", "score", "source", "output"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--expected-seal", default=EXPECTED_SEAL)
    parser.add_argument("--expected-score", default=EXPECTED_SCORE)
    result = audit(**vars(parser.parse_args()))
    print(json.dumps({"status": result["status"],
        "maximum_absolute_score_difference": result["maximum_absolute_score_difference"],
        "heads": {h: {k: v for k, v in result["heads"][h].items()
                      if k not in ("all_seeds_and_roles", "monthly_future_nll_hinge_minus_legacy")}
                  for h in HEADS}}, indent=2))
