"""Raw decision and family-wise risk recalculation; no campaign imports."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import beta


HERE = Path(__file__).resolve().parent
MODULE = HERE.parents[2] / "experiments/hcsn_cross_family_r19b_20261102"


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(item):
    compressed = (MODULE / item["path"]).read_bytes()
    assert hashlib.sha256(compressed).hexdigest() == item["compressed_sha256"]
    raw = gzip.decompress(compressed)
    assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
    rows = json.loads(raw)
    assert len(rows) == item["records"]
    return rows


def upper(errors, count, delta):
    return 1. if count == 0 or count == errors else float(beta.ppf(1-delta, errors+1, count-errors))


def run():
    spec = load(MODULE / "protocol.json")
    source = load(MODULE / "SOURCE_FREEZE.json")
    for name, sha in source["files"].items():
        assert digest(MODULE / name) == sha
    candidate = load(MODULE / "FITTED_CANDIDATE_FREEZE.json")
    frozen = load(MODULE / "POSTCALIBRATION_FREEZE.json")
    assert frozen["confirmation_opened"] is False
    assert frozen["candidate_freeze_sha256"] == digest(MODULE / "FITTED_CANDIDATE_FREEZE.json")
    assert frozen["source_freeze_sha256"] == digest(MODULE / "SOURCE_FREEZE.json")
    for name, sha in dict(candidate["files"], **frozen["files"]).items():
        assert digest(MODULE / name) == sha
    directory = MODULE / "calibration_01"
    saved, guards, archives = [load(directory / name) for name in ("CALIBRATION.json", "GUARDS.json", "ARCHIVES.json")]
    models, families, thresholds = spec["models"], spec["trained_families"], spec["thresholds"]
    delta = .05 / (len(models)*len(families)*len(thresholds)*2)
    assert delta == saved["simultaneous_delta"] and spec["risk_limit"] == .1
    ood = archive(archives["ood"])
    for model in models:
        for key in ("surprise", "broad"):
            expected = max(float(np.quantile([r["values"][model][key] for r in ood if r["family"] == family], .99, method="higher")) for family in families)
            assert expected == guards[model][key]
    counts = {model:{str(t):{family:dict(accepted=0, errors=0, fractional=0, fractional_errors=0, invalid=0)
                           for family in families} for t in thresholds} for model in models}
    worlds, decisions, reads, score_error = set(), 0, 0, 0.
    for item in archives["risk"]:
        for row in archive(item):
            family, generator, target = row["family"], row["generator"], row["target"]
            identity = family, generator
            assert identity not in worlds and family in families and 0 <= generator < 8192
            worlds.add(identity)
            mask = np.array(row["public"]["observed"], dtype=bool)
            assert set(row["predictions"]) == set(models)
            for model in models:
                assert set(row["predictions"][model]) == {str(t) for t in thresholds}
                for threshold in thresholds:
                    value = row["predictions"][model][str(threshold)]
                    entry = counts[model][str(threshold)][family]
                    decisions += 1
                    entry["invalid"] += value["invalid"]
                    if value["invalid"]:
                        assert value["accepted"] is False
                        continue
                    p, before = np.array(value["probability"]), np.array(value["before"])
                    assert p.shape == before.shape == (4,) and np.isfinite(p).all() and np.isfinite(before).all()
                    assert min(p.min(), before.min()) >= 0 and max(abs(p.sum()-1), abs(before.sum()-1)) < 2e-12
                    admitted = value["surprise"] <= guards[model]["surprise"] and value["broad_before"] <= guards[model]["broad"]+1e-12
                    accepted = bool(admitted and value["broad_after"] <= guards[model]["broad"]+1e-12 and p.max() >= threshold)
                    fractional, correct = bool(p.max() < 1-1e-9), int(p.argmax() == target)
                    assert bool(value["admitted"]) == admitted and bool(value["accepted"]) == accepted
                    assert bool(value["fractional"]) == fractional and value["correct"] == correct
                    assert abs(value["confidence"]-p.max()) < 1e-12 and abs(value["true_probability"]-p[target]) < 1e-12
                    for suffix in ("before", "after"):
                        classes = np.array(value["class_"+suffix])
                        assert np.isfinite(classes).all() and classes.min() >= 0 and abs(classes.sum()-1) < 2e-12
                        assert abs(classes[2]-value["broad_"+suffix]) < 2e-12
                    purchased = value["read_index"] is not None
                    assert value["fee"] == (row["price"] if purchased else 0.)
                    if purchased:
                        index, token = value["read_index"], np.array(value["actual_read"])
                        assert not mask[index] and token.shape == (24,) and np.isin(token, [0, 1]).all()
                        reads += 1
                    else:
                        assert value["actual_read"] is None
                    actual_payoff = (2*correct-1 if accepted else 0)-value["fee"]
                    no_read_payoff = (2*int(before.argmax() == target)-1 if admitted and before.max() >= threshold else 0)
                    calculated = {"payoff":actual_payoff, "no_read_payoff":no_read_payoff,
                        "before_brier":float(np.square(before-np.eye(4)[target]).sum()),
                        "after_brier":float(np.square(p-np.eye(4)[target]).sum())}
                    for key, expected in calculated.items():
                        error = abs(value[key]-expected)
                        score_error = max(score_error, error)
                        assert error < 2e-12
                    entry["accepted"] += accepted
                    entry["errors"] += accepted and not correct
                    entry["fractional"] += accepted and fractional
                    entry["fractional_errors"] += accepted and fractional and not correct
    bounds, selection, bound_count = {}, {}, 0
    for model in models:
        passing, bounds[model] = [], {}
        for threshold in thresholds:
            key = str(threshold)
            summaries = bounds[model][key] = {}
            for family in families:
                entry = counts[model][key][family]
                claimed = saved["grid"][model][key][family]
                assert all(entry[name] == claimed[name] for name in entry)
                risk = upper(entry["errors"], entry["accepted"], delta)
                fractional_risk = upper(entry["fractional_errors"], entry["fractional"], delta)
                passed = not entry["invalid"] and risk <= .1 and fractional_risk <= .1 and entry["fractional"] >= 32
                assert risk == claimed["upper_error"] and fractional_risk == claimed["upper_fractional_error"] and bool(passed) == claimed["passed"]
                summaries[family] = dict(**entry, overall_upper=risk, fractional_upper=fractional_risk, passed=passed)
                bound_count += 2
            if all(row["passed"] for row in summaries.values()):
                passing.append((min(row["fractional"] for row in summaries.values()), sum(row["fractional"] for row in summaries.values()), -threshold, threshold))
        selection[model] = dict(calibration_gate_passed=bool(passing), threshold=max(passing)[3] if passing else 1-1e-12)
    assert selection == saved["selected"] == frozen["selected"]
    assert len(worlds) == 24576 and decisions == 196608 and bound_count == 48
    assert all({g for f,g in worlds if f == family} == set(range(8192)) for family in families)
    return dict(schema="hcsn-r19b-independent-calibration-v1", all_checks_passed=True,
        source_sha256=digest(MODULE / "SOURCE_FREEZE.json"), candidate_sha256=digest(MODULE / "FITTED_CANDIDATE_FREEZE.json"),
        postcalibration_sha256=digest(MODULE / "POSTCALIBRATION_FREEZE.json"),
        archives=len(archives["risk"]), independent_generator_worlds=len(worlds), raw_decision_records=decisions,
        actual_read_policy_decisions=reads, maximum_score_error=score_error, cp_bounds=bound_count,
        simultaneous_delta=delta, selected=selection, bounds=bounds,
        scope="Raw recorded guards/acceptance/fees/score/classposterior consistency and48family-specificCPbounds recomputed; no campaign/world/model imports",
        limits=["Independent one-query generator is calibration unit", "READ posterior/choice mechanism separately manual-fixture-audited, not196608new full posterior inferences",
                "These3trained-family calibrations do not establish5familyconfirmation or arbitrary unknown-generator robustness"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_r19b_calibration.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key:value for key,value in report.items() if key not in ("bounds", "limits")}))
