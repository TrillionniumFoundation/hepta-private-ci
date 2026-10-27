"""Independent scalar rescore and provenance census of the frozen FSDD run."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def derive_pairs(records):
    by_key = {(r["target"], int(r["name"].rsplit("_", 1)[1][:-4])): r for r in records}
    return [(10 * a + b, by_key[a, k], by_key[b, k if a == b else (7 * k + 11) % 50])
            for a in range(10) for b in range(10) for k in range(50)]


def scalar_scores(columns, rows, identities):
    collected = {part: [] for part in ("all", "aliased", "distinct")}
    for target, left, right in rows:
        alias = left["wav_sha256"] == right["wav_sha256"]
        a, b = left["observation"], right["observation"]
        event = a if identities and alias else 10 + 10 * a + b if identities else 10 * a + b
        values = [column[event] for column in columns]
        mass = math.fsum(values)
        chosen = max(range(100), key=lambda t: values[t])
        observation = (-math.log(values[target]), -math.log(values[target] / mass),
                       values[chosen] / mass, int(chosen == target))
        collected["all"].append(observation)
        collected["aliased" if alias else "distinct"].append(observation)
    result = {}
    for part, values in collected.items():
        n = len(values)
        bins = [[] for _ in range(10)]
        for row in values:
            bins[min(int(round(row[2], 12) * 10), 9)].append(row)
        ece = math.fsum(abs(math.fsum(r[3] - r[2] for r in bucket)) / n for bucket in bins)
        result[part] = {"pair_rows": n,
            "conditional_observation_NLL": math.fsum(r[0] for r in values) / n,
            "posterior_NLL": math.fsum(r[1] for r in values) / n,
            "target_pair_accuracy": math.fsum(r[3] for r in values) / n,
            "selected_ECE_10bins": ece}
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result, registration = read(args.run / "RESULTS.json"), read(args.run / "REGISTRATION.json")
    for name, expected in result["raw_sha256"].items():
        assert digest(args.run / name) == expected, name
    for name, expected in registration["source_sha256"].items():
        assert digest(args.run / ("RUN_SOURCE_" + name)) == expected, name
    inventory = read(args.run / "SOURCE_INVENTORY.json")
    assert len(inventory) == 3000
    for name, expected in inventory.items():
        assert digest(args.run / "recordings" / name) == expected, name
    fit, test = read(args.run / "fit_observations.json"), read(args.run / "test_observations.json")
    roles = [set(registration[key]) for key in (
        "observer_train_speakers", "likelihood_fit_speakers", "development_test_speakers")]
    assert len(set.union(*roles)) == sum(map(len, roles)) == 6
    for records, role in ((fit, roles[1]), (test, roles[2])):
        assert len(records) == len({r["wav_sha256"] for r in records}) == 500
        assert Counter(r["target"] for r in records) == Counter({d: 50 for d in range(10)})
        assert {r["speaker"] for r in records} == role
        for row in records:
            assert inventory[row["name"]] == row["wav_sha256"]
            assert int(row["name"][0]) == row["target"]
            assert max(range(10), key=lambda d: row["probabilities"][d]) == row["observation"]
    assert not ({r["wav_sha256"] for r in fit} & {r["wav_sha256"] for r in test})
    single_counts = Counter((r["target"], r["observation"]) for r in fit)
    single = [[(single_counts[t, o] + .05) / 50.5 for o in range(10)] for t in range(10)]
    joint_counts = Counter((t, a["observation"], b["observation"]) for t, a, b in derive_pairs(fit))
    product = read(args.run / "alias_product.json")["likelihood_by_target"]
    paired = read(args.run / "paired_joint.json")["likelihood_by_target"]
    maximum_fit_error = 0.
    for t in range(100):
        a, b = divmod(t, 10)
        for event in range(110):
            if a == b:
                expected_product = expected_paired = single[a][event] if event < 10 else 0.
            elif event < 10:
                expected_product = expected_paired = 0.
            else:
                x, y = divmod(event - 10, 10)
                expected_product = single[a][x] * single[b][y]
                expected_paired = (joint_counts[t, x, y] + .005) / 50.5
            maximum_fit_error = max(maximum_fit_error, abs(product[t][event] - expected_product),
                                    abs(paired[t][event] - expected_paired))
        assert abs(math.fsum(paired[t]) - 1.) < 1e-12
        assert abs(math.fsum(product[t]) - 1.) < 1e-12
    assert maximum_fit_error < 1e-12
    as_labels = lambda columns: [[c[10 + o] + (c[o // 11] if o % 11 == 0 else 0.)
                                  for o in range(100)] for c in columns]
    naive = [[single[t // 10][o // 10] * single[t % 10][o % 10] for o in range(100)]
             for t in range(100)]
    models = {"naive_kron_labels": (naive, False),
              "alias_corrected_product_labels": (as_labels(product), False),
              "paired_joint_labels": (as_labels(paired), False),
              "alias_corrected_product_identity": (product, True),
              "paired_joint_identity": (paired, True)}
    rows, maximum_score_error, ece_amendments = derive_pairs(test), 0., []
    reviewed = json.loads(json.dumps(result))
    for name, (columns, identities) in models.items():
        for part, metrics in scalar_scores(columns, rows, identities).items():
            for metric, value in metrics.items():
                previous = result["scores"][name][part][metric]
                if metric == "selected_ECE_10bins":
                    if abs(previous - value) > 1e-12:
                        ece_amendments.append({"model": name, "partition": part,
                                               "original": previous, "reviewed": value})
                else:
                    maximum_score_error = max(maximum_score_error, abs(previous - value))
                reviewed["scores"][name][part][metric] = value
    assert maximum_score_error < 1e-12
    aliases = read(args.run / "ACTUAL_ALIAS_CHECKS.json")
    assert len(aliases) == 10 and all(r["repeat_posterior_identical"] for r in aliases)
    for digit, check in enumerate(aliases):
        record = test[digit * 50]
        assert (check["target"], check["actual_CNN_label"], check["event_sha256"]) == (
            11 * digit, record["observation"], record["wav_sha256"])
    amendment = {"original_results_retained": True, "training_or_likelihood_changes": False,
        "post_score_numerical_ECE_amendment": True,
        "ECE_bins": "floor(10 * round(confidence,12)), capped at 9; scalar sum of confidence errors",
        "changes": ece_amendments,
        "metadata_clarification": "Raw WAV bytes were extracted and hashed before fitting; old not-opened flags mean model features/observer outputs were not computed. They do not mean bytes were unread."}
    reviewed["review_amendment"] = amendment
    reviewed["original_results_sha256"] = digest(args.run / "RESULTS.json")
    with (args.output.parent / "REAL_AUDIO_RESULTS.json").open("x") as stream:
        json.dump(reviewed, stream, indent=2, sort_keys=True); stream.write("\n")
    audit = {"passed": True, "actual_WAV_hashes_checked": 3000, "test_source_groups": 1,
        "distinct_observer_fit_test_speakers": True, "observer_predictions_recomputed": False,
        "joint_columns_independently_reconstructed": 100, "model_pair_rescores": 25000,
        "maximum_fit_probability_error": maximum_fit_error, "maximum_non_ECE_metric_error": maximum_score_error,
        "ECE_amendment": amendment,
        "actual_alias_check_records_validated": 10, "source_sha256": digest(__file__),
        "result_sha256": digest(args.run / "RESULTS.json"), "registration_sha256": digest(args.run / "REGISTRATION.json"),
        "reviewed_results_sha256": digest(args.output.parent / "REAL_AUDIO_RESULTS.json"),
        "scope": "Independent count and scalar probability rescore; no new test source or population qualification"}
    with args.output.open("x") as stream:
        json.dump(audit, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps(audit, sort_keys=True))


if __name__ == "__main__":
    main()
