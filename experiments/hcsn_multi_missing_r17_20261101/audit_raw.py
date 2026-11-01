"""Independent owner replay and raw aggregation; imports no study implementation."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np

ROOT = Path(__file__).parent


def owner(rng, generator, task, missing):
    values = rng.permutation(8)[:6] if generator == "without_replacement" else rng.integers(8, size=6)
    tokens = [(0, int(key), int(values[key])) for key in rng.permutation(4)]
    tokens.extend((2, int(rng.integers(4)), int(rng.integers(8))) for _ in range(4))
    tokens = [tokens[i] for i in rng.permutation(8)]
    targets = np.array(values[:4], copy=True)
    if task == "selective":
        update_keys = rng.permutation(4)[:2]
        for key, value in zip(update_keys, values[4:6], strict=True):
            tokens.append((0, int(key), int(value)))
            targets[key] = value
    mask = np.ones(len(tokens), dtype=bool)
    mask[rng.choice(len(tokens), missing, replace=False)] = False
    aliases = rng.permutation(4) if task == "binding" else np.arange(4)
    full = np.zeros((len(tokens), 24), dtype=np.int8)
    for row, (kind, key, value) in enumerate(tokens):
        full[row, [key, 4 + value, 12 + kind, 16]] = 1
    public = full.copy()
    public[~mask] = 0
    return full, public, mask, targets, aliases


def check_row(row, expected, price):
    full, public, mask, targets, aliases = expected
    assert row["raw_prefix"] == public.tolist()
    assert row["observed"] == mask.tolist()
    assert row["target"] == targets.tolist()
    assert row["query_targets"] == targets[aliases].tolist()
    assert row["public_aliases"] == aliases.tolist()
    assert row["price"] == price
    for policy in row["policies"]:
        if policy["read_index"] is not None:
            assert not mask[policy["read_index"]]
            if not policy["invalid"]:
                assert policy["actual_read_token"] == full[policy["read_index"]].tolist()
        if policy["invalid"]:
            assert policy["policy"] == "fixed_without_replacement" and policy["rejections"]
            continue
        probabilities = np.array(policy["probabilities"])
        assert probabilities.shape == (4, 8)
        assert np.min(probabilities) >= 0 and np.max(abs(probabilities.sum(1) - 1)) < 2e-12
        assert policy["correct"] == (probabilities.argmax(1) == targets[aliases]).astype(int).tolist()
        assert np.max(abs(np.array(policy["target_probability"]) - probabilities[np.arange(4), targets[aliases]])) < 2e-12
        fee = price if policy["read_index"] is not None else 0.
        assert policy["fee"] == fee
        assert abs(policy["utility"] - (np.mean(policy["correct"]) - fee)) < 2e-12
        assert abs(policy["squared_error"] - np.sum((probabilities - np.eye(8)[targets[aliases]]) ** 2, 1).mean()) < 2e-12


def main():
    start = time.process_time()
    protocol = json.loads((ROOT / "protocol.json").read_text())
    raw_path, summary_path = ROOT / "verification_01/RAW.json", ROOT / "verification_01/SUMMARY.json"
    raw_bytes = raw_path.read_bytes() if raw_path.exists() else gzip.decompress(raw_path.with_suffix(".json.gz").read_bytes())
    rows, summary = json.loads(raw_bytes), json.loads(summary_path.read_text())
    cursor, accepted_confidence, observed_failures = 0, [], 0
    for gi, generator in enumerate(protocol["profiles"]):
        for ti, task in enumerate(protocol["tasks"]):
            for missing in protocol["missing_counts"]:
                rng = np.random.default_rng(np.random.SeedSequence([protocol["seed"], gi, ti, missing]))
                for episode in range(protocol["episodes_per_cell"]):
                    row = rows[cursor]
                    assert (row["generator"], row["task"], row["missing_count"], row["episode"]) == (generator, task, missing, episode)
                    expected = owner(rng, generator, task, missing)
                    price = protocol["prices"][episode % len(protocol["prices"])]
                    check_row(row, expected, price)
                    if cursor == 0:
                        first, first_expected, first_price = copy.deepcopy(row), expected, price
                    exact = row["policies"][0]
                    assert exact["policy"] == "known_exact"
                    observed_failures += exact["invalid"] or min(exact["target_probability"]) <= 0
                    for policy in row["policies"]:
                        if policy["policy"] == "unknown_finite_set" and not policy["invalid"]:
                            accepted_confidence.extend(max(p) for p, a in zip(policy["probabilities"], policy["accepted"], strict=True) if a)
                    cursor += 1
    assert cursor == len(rows) == summary["episodes"] == 288
    assert observed_failures == summary["known_support_failures"] == 0
    for entry in summary["summaries"]:
        policies = [p for row in rows if row["generator"] == entry["generator"] for p in row["policies"] if p["policy"] == entry["policy"]]
        valid = [p for p in policies if not p["invalid"]]
        assert entry["attempts"] == len(policies)
        assert entry["invalid"] == len(policies) - len(valid)
        assert entry["reads"] == sum(p["read_index"] is not None for p in policies)
        answered = sum(sum(p["accepted"]) for p in valid)
        errors = sum(sum(a and not c for a, c in zip(p["accepted"], p["correct"], strict=True)) for p in valid)
        assert (entry["answered_queries"], entry["accepted_errors"]) == (answered, errors)
        assert abs(entry["valid_mean_accuracy"] - np.mean([np.mean(p["correct"]) for p in valid])) < 2e-12
        assert abs(entry["query_coverage"] - answered / (4 * len(policies))) < 2e-12
        if entry["invalid"]:
            assert entry["whole_population_quality"] is None and entry["mean_net_accuracy"] is None
        else:
            assert abs(entry["mean_net_accuracy"] - np.mean([p["utility"] for p in valid])) < 2e-12
    rejected = []
    mutations = [lambda row: row["target"].__setitem__(0, (row["target"][0] + 1) % 8),
                 lambda row: row.__setitem__("price", row["price"] + .01),
                 lambda row: row["observed"].__setitem__(0, not row["observed"][0])]
    for index, mutate in enumerate(mutations):
        altered = copy.deepcopy(first)
        mutate(altered)
        try:
            check_row(altered, first_expected, first_price)
        except AssertionError:
            rejected.append(index)
        else:
            raise AssertionError("Corruption escaped independent owner replay")
    result = dict(schema="hcsn.r17.multi-missing.independent-raw-audit.v1", episodes_replayed=cursor,
                  owner_targets_masks_aliases_read_tokens_prices_verified=True,
                  known_support_failures=observed_failures, raw_statistics_verified=True,
                  accepted_queries=len(accepted_confidence), uncertain_accepted_queries=sum(c < 1 for c in accepted_confidence),
                  interpretation="All accepted unknown-finite-set outputs are point masses; zero errors does not validate useful uncertain answers or arbitrary unknown generators",
                  corrupted_copies_rejected=rejected, cpu_seconds=time.process_time() - start,
                  inputs={str(raw_path.relative_to(ROOT)):hashlib.sha256(raw_bytes).hexdigest(),
                          str(summary_path.relative_to(ROOT)):hashlib.sha256(summary_path.read_bytes()).hexdigest()},
                  scope="Independent seeded owner replay and arithmetic/statistics, not a second implementation of the full posterior")
    with Path(sys.argv[1]).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
