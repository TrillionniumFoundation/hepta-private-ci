"""Pure answer-blind packet controls; fixtures are NOT independent reviews."""

from copy import deepcopy
import json
from pathlib import Path
import unittest

from project_pr_source_precommit import read_pinned
from project_pr_review_packet import compile_packet

PIN = "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
SOURCE = (
    Path(__file__).resolve().parent / "data/real-project-pr-source-cut-20261012.json"
)


class BlindPacketTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = read_pinned(SOURCE, PIN)

    def fixture(self):
        rows = []
        for case in self.manifest["cases"]:
            for item in case["files"]:
                rows.append(
                    dict(
                        project=case["repo"],
                        partition=case["partition"],
                        pull_number=case["pull_number"],
                        head_sha=case["head_sha"],
                        tree_sha=case["tree_sha"],
                        path=item["path"],
                        blob_sha=item["blob_sha"],
                        mode="100644",
                        sha256="a" * 64,
                        bytes=12,
                        blob_path="blobs/" + item["blob_sha"] + ".blob",
                    )
                )
        return (
            dict(
                schema="hepta.memorycell.real-project-immutable-source-bytes.v1",
                source_manifest_sha256=PIN,
                human_review_performed=False,
                selection_or_evaluation_labels_read=False,
                model_calls=0,
                production_accepted=False,
                semantic_citation_precision=None,
                originals=rows,
            ),
            dict(
                schema="hepta.memorycell.real-project-source-readback.v1",
                generating_source_manifest_sha256=PIN,
                original_inventory_sha256="b" * 64,
                original_ready_sha256="c" * 64,
                verified_file_bindings=80,
                offline_reopen_without_network=True,
                model_calls=0,
                independent_human_semantic_review=False,
                production_accepted=False,
            ),
        )

    def compiled(self, inventory=None, receipt=None):
        a, b = self.fixture()
        return compile_packet(
            self.manifest,
            a if inventory is None else inventory,
            b if receipt is None else receipt,
            inventory_sha256="b" * 64,
        )

    def test_all_real_original_bindings_and_questions_remain_blind(self):
        packet = self.compiled()
        self.assertEqual(packet["unsigned_questions"], 16)
        self.assertEqual(packet["original_file_bindings"], 80)
        self.assertEqual(
            packet["tasks_by_partition"],
            {"train": 4, "selection": 4, "evaluation": 8},
        )
        self.assertEqual(
            sum(len(r["verified_head_files"]) for r in packet["questions"]), 160
        )
        self.assertEqual(len({r["task_id"] for r in packet["questions"]}), 16)
        self.assertTrue(
            all(
                r["answer_gold"] is None
                and r["reviewer_verdict"] == "unreviewed"
                and r["source_sufficiency"] == "unknown"
                and r["decoded_parent_diff_available"] is False
                for r in packet["questions"]
            )
        )
        self.assertFalse(packet["production_accepted"])
        self.assertIsNone(packet["semantic_citation_precision"])
        self.assertIsNone(packet["independent_sample_size"])
        self.assertEqual(packet, self.compiled())
        self.assertNotIn("site_", json.dumps(packet))

    def test_all_original_evaluation_projects_remain_held_out(self):
        packet = self.compiled()
        self.assertEqual(
            {
                r["source_project"]
                for r in packet["questions"]
                if r["partition"] == "evaluation"
            },
            {"numpy/numpy", "astral-sh/ruff"},
        )
        self.assertEqual(
            {
                r["source_project"]
                for r in packet["questions"]
                if r["partition"] == "selection"
            },
            {"kubernetes/kubernetes"},
        )

    def test_mutation_duplicate_missing_and_swapped_file_rejected(self):
        for change in ("drop", "duplicate", "swapped", "tamper", "path"):
            inventory, receipt = self.fixture()
            rows = inventory["originals"]
            if change == "drop":
                rows.pop()
            elif change == "duplicate":
                rows[-1] = deepcopy(rows[0])
            elif change == "swapped":
                rows[0], rows[1] = rows[1], rows[0]
            elif change == "tamper":
                rows[0]["sha256"] = "x" * 64
            else:
                rows[0]["blob_path"] = "../injected"
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.compiled(inventory=inventory, receipt=receipt)

    def test_false_admission_or_receipt_drift_rejected(self):
        for name, value in (
            ("human_review_performed", True),
            ("model_calls", 1),
            ("semantic_citation_precision", 1.0),
            ("source_manifest_sha256", "0" * 64),
        ):
            inventory, receipt = self.fixture()
            inventory[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.compiled(inventory=inventory, receipt=receipt)
        for name, value in (
            ("offline_reopen_without_network", False),
            ("original_inventory_sha256", "0" * 64),
            ("verified_file_bindings", 79),
            ("independent_human_semantic_review", True),
            ("model_calls", 1),
        ):
            inventory, receipt = self.fixture()
            receipt[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.compiled(inventory=inventory, receipt=receipt)


if __name__ == "__main__":
    unittest.main()
