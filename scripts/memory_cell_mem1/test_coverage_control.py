"""Controls for data matching, old selector compatibility and truth derivation."""

from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import patch

from coverage_control import audit_pair, audit_window, payload, replay_order
from environment import Experience, Owner, ReplayPool, commitment, panels


def population():
    owner = Owner(4)
    rows = [
        Experience(s, 1, owner.features[s], fact.label, i, i / 24, s[0])
        for i, (s, fact) in enumerate(owner.facts.items())
    ]
    return owner, rows


class CoverageControlTests(unittest.TestCase):
    def test_legacy_selectors_reproduce_existing_pool_rule(self):
        owner, rows = population()
        pool = ReplayPool()
        for row in rows:
            pool.add(row)
        for strategy in ("uniform", "structured"):
            for seed in range(5):
                rng = random.Random(seed)
                expected = [pool.sample(owner, rng, strategy, i) for i in range(64)]
                order = replay_order(rows, seed=seed, profile="legacy_" + strategy)
                self.assertEqual([rows[i] for i in order], expected)

    def test_matching_is_exact_for_sources_versions_payload_and_counts(self):
        _, rows = population()
        for size in (1, 8, 12, 22, 24):
            for seed in range(5):
                sample = rows[:size]
                orders = [
                    replay_order(sample, seed=seed, profile="coverage_" + p)
                    for p in ("uniform", "structured")
                ]
                multisets = [
                    Counter(payload(sample[i]) for i in order) for order in orders
                ]
                self.assertEqual(multisets[0], multisets[1])
                self.assertEqual(sum(multisets[0].values()), 64)
                self.assertEqual(set(multisets[0]), {payload(row) for row in sample})
                self.assertLessEqual(
                    max(multisets[0].values()) - min(multisets[0].values()), 1
                )

    def test_invalid_pool_rejected_before_native_mutation(self):
        _, rows = population()
        for sample in (
            [],
            [rows[0], rows[0]],
            [replace(rows[0], surprise=float("nan"))],
        ):
            with self.assertRaises(ValueError):
                replay_order(sample, seed=1, profile="coverage_uniform")

    def test_pair_rejects_same_coverage_count_with_changed_identity_or_bytes(self):
        base = {
            "pre_state": "state",
            "pool_sha256": "pool",
            "updates": 64,
            "replay_payload_bytes": 40,
            "replay_request_bytes": 30,
            "kernel_multiplications": 64,
            "teacher": {"calls": 0},
        }
        audit = {"source_multiset": {"source-version-a": 64}}
        self.assertEqual(audit_pair(base, dict(base), audit, audit), base)
        for key, value in (
            ("replay_payload_bytes", 41),
            ("teacher", {"calls": 1}),
            ("pre_state", "other"),
        ):
            with self.assertRaises(ValueError):
                audit_pair(base, {**base, key: value}, audit, audit)
        with self.assertRaises(ValueError):
            audit_pair(base, base, audit, {"source_multiset": {"source-version-b": 64}})

    def test_audit_derives_truth_and_rejects_changed_provenance(self):
        owner, rows = population()
        profile, seed = "coverage_uniform", 1
        order = replay_order(rows, seed=seed, profile=profile)
        requests, lineage = [], []
        for i in order:
            row = rows[i]
            support = owner.support(row)
            target = [float(j == row.label) for j in range(8)]
            requests.append(
                (
                    f"update 1 {support} "
                    + ",".join(map(repr, row.key))
                    + " "
                    + ",".join(map(repr, target))
                    + "\n"
                ).encode()
            )
            lineage.append({"pool_index": i, "support": support})
        result = {
            "profile": profile,
            "status": "completed",
            "pre_state": "pre",
            "pool_sha256": commitment([asdict(r) for r in rows]),
            "lineage": lineage,
            "updates": 64,
            "replay_payload_bytes": sum(len(payload(rows[i])) for i in order),
            "replay_request_bytes": sum(map(len, requests)),
            "replay_request_sha256": hashlib.sha256(b"".join(requests)).hexdigest(),
            "kernel_multiplications": 26624,
            "teacher": {"calls": 0, "bytes": 0, "multiplications": 0},
            "queries": [
                {
                    "panel": p,
                    "sources": q,
                    "output": [(owner.facts[s].label + 1) % 8 for s in q],
                    "expected": "forged",
                    "correct": True,
                }
                for p, queries in panels().items()
                for q in queries
            ],
        }
        audit = audit_window(result, rows, owner, seed=seed, checkpoint_sha256="pre")
        self.assertEqual(audit["scores"]["stable"], {"correct": 0, "total": 8})
        result["lineage"][0]["support"] = "forged"
        with self.assertRaises(ValueError):
            audit_window(result, rows, owner, seed=seed, checkpoint_sha256="pre")

    def test_failed_later_phase_preserves_earlier_windows_and_full_roster(self):
        import run_coverage

        class FailingTrial:
            def __init__(self, *args, on_attempt, **kwargs):
                self.windows = []
                self.on_attempt = on_attempt

            def run(self):
                for profile in run_coverage.PROFILES:
                    self.on_attempt("A1", profile, {"status": "completed"})
                self.windows.append({"phase": "A1"})
                self.on_attempt("B", "legacy_uniform", {"status": "failed"})
                raise ValueError("injected B failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "binary"
            binary.write_bytes(b"not-executed-test-double")
            argv = [
                "run_coverage.py",
                "--native",
                str(binary),
                "--output",
                str(root / "out"),
                "--source-revision",
                "a" * 40,
                "--seeds",
                "0",
            ]
            with (
                patch("sys.argv", argv),
                patch.object(run_coverage, "SnapshotTrial", FailingTrial),
            ):
                with self.assertRaises(SystemExit):
                    run_coverage.main()
            result = json.loads((root / "out/results.json").read_text())
            self.assertEqual(result["windows"], [{"phase": "A1"}, {"phase": "A1"}])
            self.assertEqual(
                Counter(r["status"] for r in result["attempt_roster"]),
                {"completed": 8, "failed": 2, "not_started": 6},
            )


if __name__ == "__main__":
    unittest.main()
