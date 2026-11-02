"""Read-only independent reconstruction of persisted R19 choices and scores.

This post-result auditor imports neither campaign, model nor campaign statistics.
It checks recorded prediction/action traces, not an independent neural inference.
"""

import gzip
import hashlib
import itertools
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import t

HERE = Path(__file__).resolve().parent


def load(path):
    return json.loads(gzip.decompress(path.read_bytes()) if path.suffix == ".gz" else path.read_text())


def independent_contrast(x):
    x = np.asarray(x, dtype=float)
    mean = float(np.mean(x))
    width = float(t.ppf(.975, len(x) - 1) * np.std(x, ddof=1) / np.sqrt(len(x)))
    tail = sum(abs(np.dot(sign, x) / len(x)) >= abs(mean) - 1e-15
               for sign in itertools.product((-1, 1), repeat=len(x))) / 2 ** len(x)
    return dict(mean=mean, lower=mean - width, upper=mean + width, signflip_p=tail)


def main():
    started = time.process_time()
    prepared = HERE / "run_01"
    output = prepared / "confirmation_01"
    protocol = load(HERE / "PROTOCOL.json")
    summary = load(output / "SUMMARY.json")
    selection = load(prepared / "SELECTION_FREEZE.json")
    families = ("hmm", "gru", "ssm", "cache")
    checked, exact, all_scores = [], [], {}
    for name, digest in selection["checkpoints"].items():
        assert hashlib.sha256((prepared / f"weights_{name}.pt").read_bytes()).hexdigest() == digest
        training = load(prepared / f"training_{name}.json")
        assert training["updates"] == 64 and len(training["losses"]) == 64
        assert np.isfinite(training["losses"]).all()
        assert sum(training["visited_read_histories"]) == 64 * 32
        choices = training["validation_candidates"]
        best = max(range(len(choices)), key=lambda i: (choices[i]["utility"], -choices[i]["ce"], -i))
        assert selection["selections"][name]["threshold"] == choices[best]["threshold"]
    for fit in protocol["fits"]:
        for control in ("light", "value"):
            best = max(families, key=lambda kind: (
                selection["selections"][f"{fit}_{control}_{kind}"]["validation"]["utility"],
                -selection["selections"][f"{fit}_{control}_{kind}"]["validation"]["ce"],
                -families.index(kind)))
            assert selection["ordinary"][f"{fit}_{control}"] == best
    owner_sets = {}
    for domain in ("iid", "ood", "long"):
        scores = {}
        for row in summary["results"][domain]:
            raw = load(output / f"raw_{domain}_{row['name']}.json.gz")
            p, y, a = (np.asarray(raw[key]) for key in ("probabilities", "targets", "answer"))
            reads, fees = np.asarray(raw["read"], dtype=bool), np.asarray(raw["fees"])
            assert np.isfinite(p).all() and np.all(p >= 0) and np.allclose(p.sum(-1), 1, atol=2e-6)
            # Rounded softmax may tie even when the original logits did not.
            assert np.array_equal(np.take_along_axis(p, a[..., None], -1)[..., 0], p.max(-1))
            if row["control"] == "light":
                threshold = selection["selections"][row["name"]]["threshold"]
                expected = fees.astype(np.float32) <= np.float32(threshold)
            else:
                value = np.asarray(raw["predicted_read_value"], dtype=np.float32)
                prior = np.asarray(raw["prior"], dtype=np.float32)
                expected = value - fees.astype(np.float32) > prior.max(-1)
            assert np.array_equal(reads, expected), (domain, row["name"], "causal rule")
            correct = a == y
            calculated = dict(utility=float(np.mean(correct - reads * fees)),
                accuracy=float(correct.mean()), reads=int(reads.sum()), fees=float((reads * fees).sum()),
                ce=float(-np.log(np.take_along_axis(p, y[..., None], -1)).mean()),
                brier=float(np.square(p - np.eye(4)[y]).sum(-1).mean()))
            for metric, value in calculated.items():
                assert np.isclose(value, row[metric], atol=2e-7, rtol=1e-7), (metric, value, row[metric])
            scores[row["name"]] = calculated
            checked.append(dict(domain=domain, name=row["name"], **calculated))
            owner_sets[domain] = set(raw["owner_ids"])
        for fit in protocol["fits"]:
            for control in ("light", "value"):
                a = load(output / f"raw_{domain}_{fit}_{control}_analytic.json.gz")
                h = load(output / f"raw_{domain}_{fit}_{control}_hmm.json.gz")
                assert a == h
                exact.append(dict(domain=domain, fit=fit, control=control))
        cells = {k: [] for k in "ABCD"}
        for fit in protocol["fits"]:
            for letter, control, kind in (
                ("A", "light", selection["ordinary"][f"{fit}_light"]),
                ("B", "value", selection["ordinary"][f"{fit}_value"]),
                ("C", "light", "analytic"), ("D", "value", "analytic")):
                cells[letter].append(scores[f"{fit}_{control}_{kind}"]["utility"])
        all_scores[domain] = dict(cells=cells, effects={})
        for name, x in {"B-A": np.subtract(cells["B"], cells["A"]),
                        "D-C": np.subtract(cells["D"], cells["C"]),
                        "C-A": np.subtract(cells["C"], cells["A"]),
                        "D-B": np.subtract(cells["D"], cells["B"]),
                        "interaction": np.subtract(cells["D"], cells["C"]) - np.subtract(cells["B"], cells["A"])}.items():
            result = independent_contrast(x)
            for metric, value in result.items():
                assert np.isclose(value, summary["effects"][domain][name][metric], atol=1e-12)
            all_scores[domain]["effects"][name] = result
    for left, right in itertools.combinations(owner_sets, 2):
        assert not owner_sets[left] & owner_sets[right]
    primary = [all_scores[d]["effects"]["D-B"] for d in ("iid", "ood")]
    previous = 0.
    for rank, index in enumerate(sorted(range(2), key=lambda i: primary[i]["signflip_p"])):
        previous = max(previous, min(1., (2 - rank) * primary[index]["signflip_p"]))
        primary[index]["holm_p"] = previous
    gate = all(r["mean"] >= .01 and r["lower"] > 0 and r["holm_p"] < .05 for r in primary)
    assert gate == summary["actual_core_gain_gate_passed"]
    result = dict(status="PASS", checkpoint_and_training_jobs=80, raw_traces=len(checked),
        exact_analytic_hmm_pairs=len(exact), scores=all_scores,
        original_primary_gate_passed=gate,
        independent_trace_scores=checked, auditor_cpu_seconds=time.process_time() - started,
        scope="Independent persisted-data score/decision/selection/statistical audit; not independent neural inference or physical-owner replay")
    with (output / "INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({k: result[k] for k in ("status", "raw_traces", "exact_analytic_hmm_pairs", "auditor_cpu_seconds")}))


if __name__ == "__main__":
    main()
