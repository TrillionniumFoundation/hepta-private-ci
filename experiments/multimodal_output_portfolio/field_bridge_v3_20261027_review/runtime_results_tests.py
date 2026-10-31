"""Constructed selected grids and paired-statistical boundary checks only."""

import copy
import gzip
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from runtime_audit_support import ARMS, canonical, object_sha, records
from runtime_results_audit import analyze, collect_seed, terminal


def fixture():
    path = Path(__file__).parent.parent / "field_bridge_v3_20261027" / "PROTOCOL.json"
    protocol = json.loads(path.read_text())
    protocol["runtime"].update(audit_pairs=5, batch_size=2)
    protocol["runtime_audit_gate"]["bootstrap_samples"] = 101
    registry = {"roles": {"runtime_audit": {"identities": [f"synthetic-source-{i}" for i in range(10)]}}}
    policies = {arm: {"synthetic_policy": arm} for arm in ARMS}
    paths = {"fixed": [0], "current": [1, 0], "history": [2, 3, 0], "native": [1, 2, 4], "reset_native": [1, 0]}
    effects = {"fixed": 0., "current": .01, "history": .02, "native": .04, "reset_native": .01}
    data = []
    for seed_index, seed in enumerate(protocol["seeds"]):
        rows = []
        for condition_index, condition in enumerate(protocol["runtime"]["conditions"]):
            for arm in ARMS:
                for pair in range(5):
                    actions = paths[arm]
                    node, depth = terminal(actions)
                    scores = {}
                    for observer in ("reward", "audit"):
                        net = .1 + .01 * seed_index + .003 * pair + .002 * condition_index + effects[arm]
                        scores[observer] = {"utility": net + .002 * (1 + depth), "net_utility": net}
                    rows.append({"seed": seed, "profile": "frozen", "role": "runtime_audit", "arm": arm,
                        "condition": condition, "pair_index": pair, "case_id": f"runtime_audit-{seed}-{condition}-{pair:06d}",
                        "source_ids": registry["roles"]["runtime_audit"]["identities"][2 * pair:2 * pair + 2],
                        "controller_sha256": object_sha(policies[arm]), "unchosen_continuations_executed": 0,
                        "actions": actions.copy(), "terminal_node": node, "depth": depth,
                        "media": [None] * (1 + depth), "feedback": [None] * min(depth, 2),
                        "decisions": [None] * len(actions), "scores": scores})
        data.append(rows)
    return protocol, registry, policies, data


def collect(rows, protocol, registry, policies, seed=17):
    return collect_seed(rows, seed=seed, profile="frozen", protocol=protocol, registry=registry, policies=policies)


class SelectedGridTests(unittest.TestCase):
    def setUp(self):
        self.protocol, self.registry, self.policies, self.rows = fixture()

    def test_complete_axes_charge_and_actual_path_costs(self):
        arrays, summary = collect(self.rows[0], self.protocol, self.registry, self.policies)
        self.assertEqual(summary["episodes"], 100)
        costs = summary["resources_reconstructed"]
        self.assertEqual(costs["encoder_examples"], 100)
        self.assertEqual(costs["decoder_examples"], 240)
        self.assertEqual(costs["public_feature_observer_digit_examples"], 440)
        self.assertEqual(costs["simulated_feedback_packets"], 120)
        self.assertEqual(costs["selection_rows"], 220)
        self.assertEqual(costs["selection_batches"], 132)
        self.assertEqual(costs["native_tick_calls"], 200)
        self.assertEqual(costs["audit_outcome_observer_digit_examples"], 200)
        self.assertEqual(arrays["reward"]["native"].shape, (5, 4))
        np.testing.assert_allclose(arrays["reward"]["native"] - arrays["reward"]["history"], .02, atol=1e-16)

    def test_missing_duplicate_and_wrong_source_rows_rejected(self):
        variants = [self.rows[0][:-1], self.rows[0] + [self.rows[0][0]]]
        changed = copy.deepcopy(self.rows[0])
        changed[0]["source_ids"].reverse()
        variants.append(changed)
        for rows in variants:
            with self.assertRaises(ValueError):
                collect(rows, self.protocol, self.registry, self.policies)

    def test_bad_charge_nonfinite_controller_and_scope_rejected(self):
        changes = [lambda r: r["scores"]["reward"].update(net_utility=.5),
                   lambda r: r["scores"]["audit"].update(utility=float("nan")),
                   lambda r: r.update(controller_sha256="0" * 64),
                   lambda r: r.update(profile="field"), lambda r: r.update(unchosen_continuations_executed=1)]
        for change in changes:
            rows = copy.deepcopy(self.rows[0])
            change(rows[0])
            with self.assertRaises(ValueError):
                collect(rows, self.protocol, self.registry, self.policies)

    def test_illegal_or_incomplete_action_sequences_rejected(self):
        for actions in ([], [1], [1, 2], [0, 1], [1, 0, 2], [1, 2, 3, 4], [True], [5]):
            with self.assertRaises(ValueError):
                terminal(actions)
        self.assertEqual(terminal([4, 4, 4]), (84, 3))
        self.assertEqual(terminal([4, 0]), (4, 1))

    def test_journal_canonical_crc_and_commit_order(self):
        with tempfile.TemporaryDirectory(prefix="v3-grid-journal-", dir="/tmp") as root:
            path = Path(root) / "events.jsonl.gz"
            lines = [{"record_index": i, "committed_monotonic_ns": i + 1} for i in range(2)]
            packed = gzip.compress(b"".join(canonical(row) + b"\n" for row in lines))
            path.write_bytes(packed)
            self.assertEqual(list(records(path)), [(row, object_sha(row)) for row in lines])
            path.write_bytes(packed[:-4])
            with self.assertRaises((EOFError, OSError)):
                list(records(path))
            lines[1]["committed_monotonic_ns"] = 0
            path.write_bytes(gzip.compress(b"".join(canonical(row) + b"\n" for row in lines)))
            with self.assertRaisesRegex(ValueError, "chronology"):
                list(records(path))


class RuntimeStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.protocol, registry, policies, rows = fixture()
        self.values = [collect(r, self.protocol, registry, policies, seed)[0]
                       for r, seed in zip(rows, self.protocol["seeds"], strict=True)]

    def test_full_family_dual_observer_and_fixed_seed_signs(self):
        result = analyze(self.values, self.protocol)
        self.assertTrue(result["complete_family_pass"])
        self.assertEqual(result["family_comparisons"], 4)
        self.assertEqual(result["interval_coverage_per_observer"], .9875)
        self.assertEqual(result["panel_shapes"], {"runtime": [3, 1, 5, 4]})
        self.values[0]["audit"]["native"] = self.values[0]["audit"]["history"].copy()
        result = analyze(self.values, self.protocol)
        self.assertFalse(result["complete_family_pass"])
        comparison = result["comparisons"][1]
        self.assertFalse(comparison["observers"]["audit"]["seed_signs_pass"])
        self.assertTrue(comparison["observers"]["reward"]["pass"])

    def test_clean_condition_uses_the_same_pair_draws(self):
        for seed, values in enumerate(self.values):
            for observer in ("reward", "audit"):
                values[observer]["native"] += np.arange(5)[:, None] * .006
                values[observer]["history"] += np.arange(5)[:, None] * .002
                values[observer]["native"][:, 3] += .003 * seed
        result = analyze(self.values, self.protocol)
        rng, checksum = np.random.default_rng(self.protocol["runtime_audit_gate"]["bootstrap_seed"]), hashlib.sha256()
        samples = []
        for _ in range(101):
            ids = rng.integers(0, 5, size=5)
            checksum.update(np.asarray(ids, dtype="<i8").tobytes())
            samples.append(sum((v["reward"]["native"] - v["reward"]["fixed"])[ids, 3].mean() / 3 for v in self.values))
        interval = np.quantile(samples, [.05 / 8, 1 - .05 / 8], method="linear")
        self.assertEqual(result["draw_sha256"], checksum.hexdigest())
        np.testing.assert_array_equal(result["comparisons"][2]["observers"]["reward"]["interval"], interval)

    def test_missing_seed_and_missing_observer_cannot_be_omitted(self):
        with self.assertRaises(ValueError):
            analyze(self.values[:2], self.protocol)
        del self.values[0]["audit"]
        with self.assertRaises(KeyError):
            analyze(self.values, self.protocol)


if __name__ == "__main__":
    unittest.main()
