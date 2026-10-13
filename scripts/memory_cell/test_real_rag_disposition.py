"""Pinned, real Qwen-RAG disposition invariants; fixtures are not inference."""

import json
from pathlib import Path
import unittest


DATA = (
    Path(__file__).resolve().with_name("data")
    / "strong-rag-38224780900-disposition-summary.json"
)


class RealRagDispositionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = json.loads(DATA.read_text(encoding="utf-8"))

    def test_pinned_source_and_artifacts(self):
        r = self.receipt
        self.assertEqual(r["generating_run_id"], 38224780900)
        self.assertEqual(
            r["source_commit"],
            "6304b451268c73f3d1a605985226b102df841bbf",
        )
        self.assertEqual(
            set(r["artifact_sha256"]), {"original", "reader", "independent_replay"}
        )
        self.assertEqual(sum(r["verified_manifest_members"].values()), 86)

    def test_exact_model_and_real_call_census(self):
        r = self.receipt
        self.assertEqual(r["model"]["trainable_parameters"], 0)
        self.assertEqual(r["calibration"]["actual_generations"], 40)
        self.assertEqual(r["evaluation"]["actual_generations"], 72)
        self.assertEqual(len(r["evaluation"]["by_arm"]), 9)

    def test_frozen_k_is_cost_tie_not_robust_accuracy(self):
        c = self.receipt["calibration"]
        self.assertEqual(c["selected_k"], 1)
        self.assertEqual([c["scores"][f"k{k}"] for k in (1, 2, 3, 4)], [4] * 4)
        self.assertFalse(c["stable_to_one_case_omission"])

    def test_organization_does_not_beat_full_path_on_task_success(self):
        e = self.receipt["evaluation"]
        self.assertEqual(e["by_arm"]["entity_time"]["strict_correct"], 8)
        self.assertEqual(e["by_arm"]["organized"]["strict_correct"], 8)
        self.assertEqual(
            e["paired_task_outcomes"]["organized_vs_full_path"],
            {"wins": 0, "losses": 0, "ties": 8},
        )
        self.assertEqual(e["organized_saved_input_tokens_vs_entity_time"], 573)

    def test_citations_not_inferred_from_answer_accuracy(self):
        e = self.receipt["evaluation"]
        self.assertEqual(e["by_arm"]["organized"]["complete_chain_cited"], 4)
        self.assertEqual(e["calibrated_correct_missing_program_support"], 2)
        for arm in e["by_arm"].values():
            self.assertLessEqual(arm["complete_chain_cited"], arm["strict_correct"])

    def test_research_controls_do_not_authorize_training_or_production(self):
        r = self.receipt
        self.assertEqual(r["admission"]["prospective_independent_source_families"], 0)
        for key, value in r["admission"].items():
            if key != "prospective_independent_source_families":
                self.assertIs(value, False)


if __name__ == "__main__":
    unittest.main()
