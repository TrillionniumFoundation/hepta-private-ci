"""Rebuild all public masked views; no campaign/world or cached-loss imports."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_cross_family_r19b_20261102.classes import tempered_table
from experiments.hcsn_cross_family_r19b_20261102.posterior import infer


HERE = Path(__file__).resolve().parent
MODULE = HERE.parents[2] / "experiments/hcsn_cross_family_r19b_20261102"


def run():
    frozen = json.loads((MODULE / "FITTED_CANDIDATE_FREEZE.json").read_text())
    assert frozen["formal_risk_calibration_opened"] is False and frozen["confirmation_opened"] is False
    for name, expected in frozen["files"].items():
        assert hashlib.sha256((MODULE / name).read_bytes()).hexdigest() == expected
    model = json.loads((MODULE / "candidate_01/MODELS.json").read_text())
    objective = json.loads((MODULE / "candidate_01/PUBLIC_OBJECTIVE.json").read_text())
    archives = json.loads((MODULE / "candidate_01/ARCHIVES.json").read_text())
    rebuilt, losses, maximum = {}, {}, 0.
    for split, seed in (("fitting", 19112317), ("calibration", 19112419)):
        item = archives[split]
        raw = (MODULE / item["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == item["compressed_sha256"]
        unpacked = gzip.decompress(raw)
        assert hashlib.sha256(unpacked).hexdigest() == item["raw_sha256"]
        rows = json.loads(unpacked)
        assert len(rows) == item["records"] == 384
        rng, examples = np.random.default_rng(seed), []
        for row in rows:
            assert set(row) == {"prefix", "observed", "bridges", "query", "dt"}
            actual = np.asarray(row["prefix"], dtype=np.int8)
            assert np.all(row["observed"])
            alias = np.asarray(row["query"])[19:23].argmax()
            bridge = next(bridge for bridge in row["bridges"] if bridge[19 + alias])
            key = int(np.asarray(bridge)[:4].argmax())
            target = int(next(event for event in actual[::-1] if event[12] and event[key])[4:8].argmax())
            count = int(rng.choice([2, 3, 4]))
            missing = rng.choice(len(actual), count, replace=False)
            mask = np.ones(len(actual), dtype=bool)
            mask[missing] = False
            prefix = actual.copy()
            prefix[~mask] = 0
            examples.append((actual, prefix, mask, key, target))
        rebuilt[split] = dict(worlds=len(examples), views=sum(1 + int((~e[2]).sum()) for e in examples))
        losses[split] = []
        for candidate in objective["candidates"]:
            table = tempered_table(model["shared"], candidate["beta"])
            runtime = dict(model["shared"], sequence_table=table)
            priors = [candidate["mixture_prior"]] + np.eye(3).tolist()
            values = np.zeros(4)
            for actual, prefix, mask, key, target in examples:
                base = infer(prefix, mask, runtime, np.full(3, 1/3))
                for position, prior in enumerate(priors):
                    before = base.reprior(prior)
                    views = [before] + [before.acquire(index, actual[index]) for index in base.missing]
                    values[position] -= sum(np.log(view.probability(key)[target]) for view in views) / len(views) / len(examples)
            losses[split].append(dict(beta=candidate["beta"], mixture=float(values[0]), static=values[1:].tolist()))
            claimed = candidate["conditional_fit_loss"] if split == "fitting" else candidate["conditional_public_cal_loss"]
            maximum = max(maximum, abs(values[0] - claimed))
            if split == "calibration":
                maximum = max(maximum, float(np.max(abs(values[1:] - candidate["static_public_cal_losses"]))))
            assert rebuilt[split]["views"] == candidate["fit_views" if split == "fitting" else "calibration_views"]
    primary = min((row["mixture"], -row["beta"], row["beta"]) for row in losses["calibration"])
    static = min((loss, -row["beta"], index, row["beta"]) for row in losses["calibration"] for index, loss in enumerate(row["static"]))
    assert primary[2] == model["selected"]["class_mixture"]["beta"]
    assert static[3] == model["selected"]["best_static"]["beta"]
    assert np.eye(3)[static[2]].tolist() == model["selected"]["best_static"]["prior"]
    for candidate in objective["candidates"]:
        assert candidate["conditional_fit_loss"] == min(a["objective"] for a in candidate["optimizer"]["attempts"] if a["success"])
    for name, selected in model["selected"].items():
        raw = gzip.decompress((MODULE / f"candidate_01/TABLE_{name}.json.gz").read_bytes())
        assert np.array_equal(np.array(json.loads(raw)), tempered_table(model["shared"], selected["beta"]))
    assert maximum < 2e-12
    return dict(schema="hcsn-r19b-independent-public-fit-v1", all_checks_passed=True,
        candidate_freeze_sha256=hashlib.sha256((MODULE / "FITTED_CANDIDATE_FREEZE.json").read_bytes()).hexdigest(),
        rebuilt_public_inputs=rebuilt, recomputed_losses=losses, maximum_reported_nll_discrepancy=maximum,
        selected=model["selected"], primary_validation_nll=primary[0], static_validation_nll=static[0],
        scope="All768 complete-public worlds independently remasked/alias-routed/target-derived. Direct pre/actualREAD-view probabilities use the separately manual-fixture-verified inference implementation; campaign and cached-loss wrappers not imported.",
        limits=["No owner target/family/parameters in public fitter inputs", "Validation NLL does not establish fresh risk or unknown-family success", "All12ordinary staticclass/beta options retained"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_r19b_public_fit.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key: value for key, value in report.items() if key != "recomputed_losses"}))
