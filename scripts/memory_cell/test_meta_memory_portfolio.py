"""Fail-closed fixed-source MetaMemory policy tests; NOT prospective utility evidence."""

from pathlib import Path
import tempfile
import unittest

import associative_graph_causal as graph
import associative_meta_evolution as meta
import meta_memory_portfolio as portfolio
from test_associative_meta_evolution import make_dirs


class SourceOnlyPortfolioPolicy(unittest.TestCase):
    def test_predeclared_no_answer_text_feature(self):
        self.assertEqual(portfolio.query_class("When did Alice speak?"), "temporal")
        self.assertEqual(portfolio.query_class("Who likes blue pens?"), "general")
        for query in ("", "   ", "hello\x00world", "caf\u00e9"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                portfolio.query_class(query)

    def test_laplace_smoothing_and_conservative_margin(self):
        rows = [
            {
                "query_class": "general",
                "eligible": True,
                "values": dict.fromkeys(portfolio.CANDIDATES, 1),
            }
        ] * 18
        arm, info = portfolio.fit(rows, "general")
        self.assertEqual(arm, "temporal")
        self.assertEqual(info["reason"], "no_credible_gain")
        self.assertEqual(
            portfolio.fit(rows[:15], "general")[1]["reason"],
            "insufficient_training_support",
        )

    def test_training_cannot_consume_future_family(self):
        outcomes = {k: 0 for k in portfolio.CANDIDATES}
        train = [
            {
                "family": "conv-0",
                "query_class": "general",
                "eligible": True,
                "values": {**outcomes, "typed_split": 1},
            }
            for _ in range(60)
        ]
        heldout = [
            {
                "family": "conv-1",
                "query_class": "general",
                "eligible": True,
                "values": dict.fromkeys(portfolio.CANDIDATES, 1),
            }
        ]
        arm, _ = portfolio.fit(train, "general")
        heldout[0]["values"]["typed_split"] = 0
        self.assertEqual(arm, portfolio.fit(train, "general")[0])
        self.assertEqual(arm, "typed_split")
        with self.assertRaises(ValueError):
            portfolio.fit(train, "future_private_label")

    def test_trainable_numeric_gate_is_not_a_memory_fact(self):
        self.assertNotIn("rewired_typed", portfolio.CANDIDATES)
        self.assertNotIn("swapped_type", portfolio.CANDIDATES)
        self.assertEqual(portfolio.BASELINE, "temporal")


class OriginalReplayGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.working = tempfile.TemporaryDirectory()
        cls.root = Path(cls.working.name)
        cls.prepared, cls.worker = make_dirs(cls.root)
        cls.out = cls.root / "sealed"
        meta.run(cls.worker, cls.out)
        cls.report = portfolio.review(cls.prepared, cls.out, cls.root / "report.json")

    @classmethod
    def tearDownClass(cls):
        cls.working.cleanup()

    def test_original_ten_fold_census_and_nonpromotion(self):
        r = self.report
        self.assertEqual(r["family_count"], 10)
        self.assertEqual(r["planned_question_count"], 240)
        self.assertEqual(r["paired_question_count"], 240)
        self.assertEqual(set(r["by_family"]), {f"conv-{i}" for i in range(10)})
        self.assertEqual(
            r["totals"]["wins"] - r["totals"]["losses"],
            r["totals"]["policy_complete"] - r["totals"]["temporal_complete"],
        )
        self.assertEqual(r["disposition"], "retain_temporal_deny_topology_growth")
        self.assertFalse(r["autonomous_cell_split_authorized"])
        self.assertFalse(r["final_use_authorized"])
        self.assertFalse(r["production_accepted"])
        self.assertFalse(r["lifecycle_cost_verified"])
        self.assertFalse(r["independent_200_families"])

    def test_every_fold_has_exactly_nine_training_families(self):
        for family, fold in self.report["by_family"].items():
            self.assertEqual(fold["counts"]["planned"], 24, family)
            self.assertEqual(fold["counts"].get("unscorable", 0), 0)
            self.assertEqual(
                sum(
                    fold["counts"].get("selected_" + k, 0) for k in portfolio.CANDIDATES
                ),
                24,
            )

    def test_unsealed_or_tampered_training_artifact_rejected(self):
        bogus = self.root / "unsealed"
        bogus.mkdir()
        with self.assertRaises(ValueError):
            portfolio.review(self.prepared, bogus, self.root / "bogus.json")
        bad = self.root / "modified"
        bad.mkdir()
        for name in ("predictions.json", "seal.json"):
            (bad / name).write_bytes((self.out / name).read_bytes())
        val = graph.strict_load((bad / "predictions.json").read_bytes())
        val["rows"][0]["arms"]["typed_split"][0] = "D0:99999"
        modified = graph.canonical(val)
        (bad / "predictions.json").write_bytes(modified)
        seal = graph.strict_load((bad / "seal.json").read_bytes())
        seal["predictions_sha256"] = graph.digest(modified)
        (bad / "seal.json").write_bytes(graph.canonical(seal))
        with self.assertRaises(ValueError):
            portfolio.review(self.prepared, bad, self.root / "modified-report.json")

    def test_future_family_private_label_edit_cannot_seal(self):
        forged = self.root / "altered-private"
        forged.mkdir()
        for name in ("public.json", "private.json", "manifest.json"):
            (forged / name).write_bytes((self.prepared / name).read_bytes())
        private = graph.strict_load((forged / "private.json").read_bytes())
        private["annotations"]["conv-0/q0000"]["evidence"] = ["D0:9999"]
        (forged / "private.json").write_bytes(graph.canonical(private))
        with self.assertRaisesRegex(ValueError, "reference source hash mismatch"):
            portfolio.review(forged, self.out, self.root / "bad-private-report.json")

    def test_repeat_create_only_report_refused(self):
        with self.assertRaises(FileExistsError):
            portfolio.review(self.prepared, self.out, self.root / "report.json")

    def test_public_worker_without_private_cannot_evaluate_portfolio(self):
        with self.assertRaises(ValueError):
            portfolio.review(self.worker, self.out, self.root / "no-private.json")


if __name__ == "__main__":
    unittest.main()
