"""Synthetic protocol fixtures only: never count as empirical MemoryCell evidence."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from memory_ai_acceptance import (ARMS, COMPARISONS, MEASURES, ROLES,
                                  ProtocolError, adjudicate, digest, main)

ZERO = "0" * 64
ONE = "1" * 64
TWO = "2" * 64
THREE = "3" * 64
FOUR = "4" * 64


def fixture(n_families=30, n_cases=10):
    tasks = [dict(task_id="cal00", family_id="cal00", split="calibration",
                  allowed_source_ids=["cal-ev"], source_snapshot_sha256=ZERO,
                  tags=[], future_window=None),
             dict(task_id="train00", family_id="train00", split="train",
                  allowed_source_ids=["train-ev"], source_snapshot_sha256=ZERO,
                  tags=[], future_window=None)]
    gold, predictions = [], []
    cutoffs = {"A": 0, "B": 2, "C": 3, "D": 3, "E": 4,
               "F": 5, "G": 6, "H": 7, "I": 8}
    for i in range(n_families):
        family = f"f{i:03d}"
        for j in range(n_cases):
            tid = f"{family}_{j:02d}"
            ev = f"{family}-ev"
            answerable = j >= 2
            tasks.append(dict(task_id=tid, family_id=family, split="evaluation",
                              allowed_source_ids=[ev], source_snapshot_sha256=ZERO,
                              tags=["adversarial"] if j < 2 else ["multi_hop"] if j < 4
                              else ["ood"] if j < 6 else ["temporal"],
                              future_window="future-1" if i < n_families / 2 else "future-2"))
            gold.append(dict(task_id=tid, answerable=answerable,
                             accepted_answers=["correct"] if answerable else [],
                             required_support_ids=[ev] if answerable else []))
            for arm in ARMS:
                passed = j < cutoffs[arm]
                abstained = passed and not answerable
                measurements = dict(context_tokens=32, reader_output_tokens=2,
                                    reader_calls=1, encoder_calls=int(arm in "EFGHI"),
                                    head_calls=int(arm in "EFGHI"),
                                    router_calls=int(arm in "GHI"),
                                    graph_hops=int(arm in "CHI"),
                                    wall_ns=100, cpu_ns=50, peak_rss_bytes=1000, io_bytes=10)
                predictions.append(dict(arm=arm, task_id=tid,
                                        answer_text="" if abstained else "correct" if passed else "wrong",
                                        abstained=abstained,
                                        selected_source_ids=[] if abstained else [ev],
                                        cited_source_ids=[] if abstained else [ev],
                                        confidence_ppm=500_000,
                                        artifact_sha256=ONE,
                                        source_closure_sha256=TWO,
                                        source_snapshot_sha256=ZERO,
                                        reader_sha256=THREE,
                                        invocation_receipt_sha256=FOUR,
                                        graph_artifact_sha256=ONE if arm in "CHI" else None,
                                        router_artifact_sha256=TWO if arm in "GHI" else None,
                                        measured=measurements))
    tasks.sort(key=lambda t: t["task_id"])
    manifests = {a: dict(method=ROLES[k], artifact_sha256=ONE,
                         source_closure_sha256=TWO, reader_sha256=THREE,
                         encoder_sha256=FOUR if a in "EFGHI" else None,
                         resident_bytes=100, training_work_units=10 if a in "EFGHI" else 0,
                         learned_from_families=["train00"] if a in "EFGHI" else [],
                         route_before_head=True if a in "GHI" else False,
                         evaluated_split_merge=a == "I",
                         graph_artifact_sha256=ONE if a in "CHI" else None,
                         router_artifact_sha256=TWO if a in "GHI" else None,
                         topology_receipt_sha256=THREE if a == "I" else None) for k, a in enumerate(ARMS)}
    plan = dict(schema_version=1, arms=list(ARMS),
                comparisons=[list(v) for v in COMPARISONS],
                status="SHADOW_ONLY", evaluation_frozen_before_outputs=True,
                source_snapshot_sha256=ZERO, reader_sha256=THREE,
                encoder_sha256=FOUR, scorer_sha256=ONE,
                limits=dict(context_tokens=100, reader_output_tokens=32,
                            reader_calls=1, encoder_calls=1, head_calls=2, router_calls=1,
                            graph_hops=2, io_bytes=100, selected_source_count=8,
                            cpu_ns=1000, wall_ns=1000, peak_rss_bytes=10000,
                            resident_bytes=1000, training_work_units=1000),
                acceptance=dict(seed=7, bootstrap_repetitions=100,
                                min_evaluation_families=30, min_future_windows=2,
                                min_effect=0.01, max_cost_ratio=1.2,
                                max_slice_regression=0.02),
                arm_manifests=manifests, tasks=tasks)
    return plan, predictions, gold


class AcceptanceProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case = fixture()

    def setUp(self):
        self.p, self.r, self.g = copy.deepcopy(self.case)

    def test_valid_fixture_scores_but_never_promotes(self):
        report = adjudicate(self.p, self.r, self.g)
        self.assertTrue(report["scientific_matrix_candidate"])
        self.assertEqual(report["qualification"], "HOLD_NO_GO")
        self.assertFalse(report["production_activation_allowed"])
        self.assertFalse(report["independent_evaluator_authenticated"])
        self.assertEqual(len(report["comparisons"]), len(COMPARISONS))

    def test_incomplete_arm_census_rejected(self):
        self.r.pop()
        with self.assertRaisesRegex(ProtocolError, "partial A-I census"):
            adjudicate(self.p, self.r, self.g)

    def test_duplicate_prediction_rejected(self):
        self.r[-1] = self.r[0]
        with self.assertRaises(ProtocolError):
            adjudicate(self.p, self.r, self.g)

    def test_source_family_overlap_rejected(self):
        self.p["tasks"][0]["family_id"] = "train00"
        with self.assertRaises(ProtocolError):
            adjudicate(self.p, self.r, self.g)

    def test_reused_source_across_families_rejected(self):
        self.p["tasks"][1]["allowed_source_ids"] = self.p["tasks"][0]["allowed_source_ids"]
        with self.assertRaisesRegex(ProtocolError, "source reused"):
            adjudicate(self.p, self.r, self.g)

    def test_future_family_cannot_span_two_windows(self):
        first = next(t for t in self.p["tasks"] if t["task_id"] == "f001_00")
        first["future_window"] = "future-2"
        with self.assertRaisesRegex(ProtocolError, "multiple future windows"):
            adjudicate(self.p, self.r, self.g)

    def test_training_on_heldout_family_rejected(self):
        self.p["arm_manifests"]["G"]["learned_from_families"] = ["f001"]
        with self.assertRaisesRegex(ProtocolError, "trained from"):
            adjudicate(self.p, self.r, self.g)

    def test_single_shared_encoder_call_required(self):
        row = next(r for r in self.r if r["arm"] == "I")
        row["measured"]["encoder_calls"] = 2
        with self.assertRaisesRegex(ProtocolError, "encoder_calls resource ceiling"):
            adjudicate(self.p, self.r, self.g)

    def test_zero_measured_cpu_rejected(self):
        self.r[0]["measured"]["cpu_ns"] = 0
        with self.assertRaisesRegex(ProtocolError, "nonphysical zero"):
            adjudicate(self.p, self.r, self.g)

    def test_graph_must_run(self):
        for row in self.r:
            if row["arm"] == "H":
                row["measured"]["graph_hops"] = 0
        with self.assertRaisesRegex(ProtocolError, "graph never executed"):
            adjudicate(self.p, self.r, self.g)

    def test_correct_answer_without_source_citation_not_grounded(self):
        chosen = next(row for row in self.r if row["arm"] == "I" and row["answer_text"] == "correct")
        chosen["cited_source_ids"] = []
        report = adjudicate(self.p, self.r, self.g)
        self.assertLess(report["arm_metrics"]["I"]["micro_grounded_success"], 0.8)

    def test_reader_swap_rejected(self):
        self.r[0]["reader_sha256"] = ZERO
        with self.assertRaisesRegex(ProtocolError, "Reader drift"):
            adjudicate(self.p, self.r, self.g)

    def test_modified_weight_artifact_rejected(self):
        self.r[0]["artifact_sha256"] = ZERO
        with self.assertRaisesRegex(ProtocolError, "artifact/lineage"):
            adjudicate(self.p, self.r, self.g)

    def test_source_not_in_authority_census_rejected(self):
        self.r[0]["selected_source_ids"] = ["forbidden"]
        with self.assertRaisesRegex(ProtocolError, "unauthorized"):
            adjudicate(self.p, self.r, self.g)

    def test_citation_without_selection_rejected(self):
        self.r[0]["selected_source_ids"] = []
        with self.assertRaisesRegex(ProtocolError, "citation absent"):
            adjudicate(self.p, self.r, self.g)

    def test_measured_resource_missing_rejected(self):
        del self.r[0]["measured"]["cpu_ns"]
        with self.assertRaisesRegex(ProtocolError, "incomplete physical"):
            adjudicate(self.p, self.r, self.g)

    def test_unbounded_graph_budget_rejected(self):
        self.p["limits"].pop("graph_hops")
        with self.assertRaisesRegex(ProtocolError, "graph_hops must be a measured integer"):
            adjudicate(self.p, self.r, self.g)

    def test_over_budget_rejected(self):
        self.r[0]["measured"]["context_tokens"] = 101
        with self.assertRaisesRegex(ProtocolError, "resource ceiling"):
            adjudicate(self.p, self.r, self.g)

    def test_unreal_selected_head_count_rejected(self):
        row = next(v for v in self.r if v["arm"] == "G")
        row["measured"]["head_calls"] = 0
        with self.assertRaisesRegex(ProtocolError, "sparse selected-only"):
            adjudicate(self.p, self.r, self.g)

    def test_split_unequal_budget_rejected(self):
        self.p["arm_manifests"]["I"]["training_work_units"] = 500
        with self.assertRaisesRegex(ProtocolError, "evolution must match"):
            adjudicate(self.p, self.r, self.g)

    def test_graph_identity_mutation_rejected(self):
        row = next(v for v in self.r if v["arm"] == "H")
        row["graph_artifact_sha256"] = ZERO
        with self.assertRaisesRegex(ProtocolError, "graph artifact identity"):
            adjudicate(self.p, self.r, self.g)

    def test_no_evolution_gain_blocks_candidate(self):
        h = {r["task_id"]: r for r in self.r if r["arm"] == "H"}
        for r in self.r:
            if r["arm"] == "I":
                ref = h[r["task_id"]]
                r["answer_text"], r["abstained"] = ref["answer_text"], ref["abstained"]
                r["selected_source_ids"] = ref["selected_source_ids"]
                r["cited_source_ids"] = ref["cited_source_ids"]
        report = adjudicate(self.p, self.r, self.g)
        self.assertFalse(report["scientific_matrix_candidate"])
        self.assertFalse(report["comparisons"]["I-H"]["passes"])

    def test_missing_split_receipt_rejected(self):
        self.p["arm_manifests"]["I"]["evaluated_split_merge"] = False
        with self.assertRaisesRegex(ProtocolError, "structural"):
            adjudicate(self.p, self.r, self.g)

    def test_unregistered_gold_rejected(self):
        self.g[0]["task_id"] = "unknown"
        with self.assertRaisesRegex(ProtocolError, "gold"):
            adjudicate(self.p, self.r, self.g)

    def test_scorer_ignores_producer_correctness_claim(self):
        self.r[0]["producer_says_correct"] = True
        baseline = adjudicate(self.p, self.r, self.g)
        self.r[0]["producer_says_correct"] = False
        self.assertEqual(baseline["arm_metrics"], adjudicate(self.p, self.r, self.g)["arm_metrics"])

    def test_weak_generalization_stays_blocked(self):
        p, r, g = fixture(n_families=6)
        report = adjudicate(p, r, g)
        self.assertFalse(report["scientific_matrix_candidate"])
        self.assertTrue(any("insufficient independent" in b for b in report["blockers"]))

    def test_bootstrap_output_deterministic(self):
        left = adjudicate(self.p, self.r, self.g)
        right = adjudicate(self.p, self.r, self.g)
        self.assertEqual(left, right)

    def test_external_sha_pinning_and_create_only_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            paths = {}
            for name, obj in (("plan", self.p), ("predictions", self.r), ("gold", self.g)):
                path = root / (name + ".json")
                path.write_text(json.dumps(obj, sort_keys=True), encoding="utf-8")
                paths[name] = path
            argv = []
            for name, path in paths.items():
                argv += ["--" + name, str(path), "--" + name + "-sha256", digest(path.read_bytes())]
            output = root / "report.json"
            self.assertEqual(main(argv + ["--output", str(output)]), 0)
            self.assertEqual(json.loads(output.read_text())["qualification"], "HOLD_NO_GO")
            with self.assertRaisesRegex(ProtocolError, "create-only"):
                main(argv + ["--output", str(output)])
            paths["gold"].write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ProtocolError, "unsealed"):
                main(argv + ["--output", str(root / "new-report.json")])


if __name__ == "__main__":
    unittest.main()
