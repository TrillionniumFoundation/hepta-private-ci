"""Synthetic contract tests; tests do not claim real-LoCoMo or Reader results."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import associative_locomo_shadow as m


def synthetic(*, docs=18):
    records = []
    for j in range(10):
        name = f"conv-{j + 1}"
        messages = [dict(dia_id=f"D1:{i + 1}", speaker="Pat", text=f"Memory about plan step {i + 1} in {name}.")
                    for i in range(docs)]
        records.append(dict(sample_id=name,
                            conversation={"session_1": messages},
                            qa=[{"question": f"What is the plan in {name}?", "answer": "private_answer_only", "evidence": ["D1:3"], "category": "1"},
                                {"question": f"Who had the plan for {name}?", "evidence": ["D:1"], "category": "5"}]))
    return records


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = synthetic()

    def write_fixture(self, dataset=None):
        raw = m.canonical(self.data if dataset is None else dataset)
        path = self.root / "dataset.json"
        path.write_bytes(raw)
        return path, hashlib.sha256(raw).hexdigest()

    def prepare(self):
        path, fingerprint = self.write_fixture()
        with patch.object(m, "DATASET_SHA256", fingerprint):
            m.prepare(path, self.root / "prepared", expected_sha=fingerprint,
                      source_limit=16, question_limit=2)
        return fingerprint, self.root / "prepared"

    def sealed(self, root):
        public = m.strict_json((root / "public.json").read_bytes())
        manifest = m.strict_json((root / "manifest.json").read_bytes())
        journal = []
        for family in public["families"]:
            ids = [d["id"] for d in family["sources"]][:8]
            for question in family["questions"]:
                journal.append({"family": family["family"], "question_id": question["id"],
                                "predictions": {arm: ids[:] for arm in m.ARMS}})
        folder = self.root / "execution"
        folder.mkdir()
        obj = {"schema": m.SCHEMA, "public_sha256": manifest["public_sha256"],
               "complete_count": len(journal), "journal": journal}
        digest = m.exclusive(folder / "journal.json", obj)
        m.exclusive(folder / "seal.json", {"journal_sha256": digest,
                       "public_sha256": manifest["public_sha256"],
                       "complete_count": len(journal)})
        return folder

    def test_published_qa_annotations_cannot_enter_public_run(self):
        fingerprint, folder = self.prepare()
        public = (folder / "public.json").read_text()
        private = (folder / "private.json").read_text()
        self.assertNotIn("private_answer_only", public)
        self.assertNotIn("evidence", public)
        self.assertIn("D1:3", private)
        with patch.object(m, "DATASET_SHA256", fingerprint):
            m.validate_public(m.strict_json(public.encode()))

    def test_exact_dataset_pin_rejects_mutation(self):
        path, _ = self.write_fixture()
        with self.assertRaisesRegex(ValueError, "SHA256"):
            m.prepare(path, self.root / "mutated", expected_sha="0" * 64,
                      source_limit=16, question_limit=1)

    def test_extra_answer_or_evidence_in_public_fails_closed(self):
        fingerprint, folder = self.prepare()
        public = m.strict_json((folder / "public.json").read_bytes())
        for mutation in ["answer", "evidence", "target", "label"]:
            changed = copy.deepcopy(public)
            changed["families"][0]["questions"][0][mutation] = "sensitive"
            with patch.object(m, "DATASET_SHA256", fingerprint):
                with self.assertRaisesRegex(ValueError, "answer/evidence"):
                    m.validate_public(changed)

    def test_duplicate_source_identity_denied(self):
        changed = synthetic()
        changed[0]["conversation"]["session_1"][1]["dia_id"] = "D1:1"
        raw = m.canonical(changed)
        path = self.root / "changed.json"
        path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "duplicate dialogue"):
            m.prepare(path, self.root / "rejected", expected_sha=m.sha256(raw),
                      source_limit=16, question_limit=1)

    def test_quarantines_unresolvable_reference(self):
        fingerprint, root = self.prepare()
        with patch.object(m, "DATASET_SHA256", fingerprint):
            dest = self.root / "review.json"
            report = m.review(root, self.sealed(root), dest)
        self.assertEqual(report["questions"], 20)
        self.assertEqual(report["reference_coverage"]["unresolved_reference"], 10)
        self.assertEqual(report["reference_coverage"]["reference_label_nonempty"], 10)
        self.assertFalse(report["statistical_superiority_claim"])
        self.assertFalse(report["production_accepted"])
        self.assertIsNotNone(report["by_arm"]["cached_bm25"]["any_gold_at_8_all_reference"])

    def test_review_rejects_modified_prediction_without_reseal(self):
        fingerprint, root = self.prepare()
        run_dir = self.sealed(root)
        obj = m.strict_json((run_dir / "journal.json").read_bytes())
        obj["journal"][0]["predictions"]["cached_bm25"][0] = "D50:50"
        (run_dir / "journal.json").write_bytes(m.canonical(obj))
        with patch.object(m, "DATASET_SHA256", fingerprint):
            with self.assertRaisesRegex(ValueError, "tampered"):
                m.review(root, run_dir, self.root / "failed_review.json")

    def test_missing_prediction_fails_even_after_resigning_local_test_seal(self):
        fingerprint, root = self.prepare()
        run_dir = self.sealed(root)
        obj = m.strict_json((run_dir / "journal.json").read_bytes())
        del obj["journal"][-1]
        (run_dir / "journal.json").write_bytes(m.canonical(obj))
        seal = m.strict_json((run_dir / "seal.json").read_bytes())
        seal["journal_sha256"] = m.sha256((run_dir / "journal.json").read_bytes())
        (run_dir / "seal.json").write_bytes(m.canonical(seal))
        with patch.object(m, "DATASET_SHA256", fingerprint):
            with self.assertRaisesRegex(ValueError, "missing, duplicated"):
                m.review(root, run_dir, self.root / "failed_review.json")

    def test_source_pool_and_query_closed_world(self):
        fingerprint, root = self.prepare()
        public = m.strict_json((root / "public.json").read_bytes())
        public["families"][0]["sources"][0]["content"] = "unregistered"
        with patch.object(m, "DATASET_SHA256", fingerprint):
            with self.assertRaisesRegex(ValueError, "answer labels"):
                m.validate_public(public)

    def test_cached_bm25_and_rrf_prioritize_obvious_match(self):
        docs = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
        scores = m.bm25_score("red satellite", m.bm25_table(
            ["blue sky", "red satellite launch red", "green river"]))
        lex = m.ordered(scores, docs)
        self.assertEqual(lex[0], 1)
        dense = [0, 1, 2]
        hybrid = m.rrf(dense, lex)
        self.assertGreater(hybrid[1], hybrid[2])

    def test_nonfinite_duplicate_json_key_denied(self):
        for malformed, pattern in [(b'{"a":1,"a":2}', "duplicate"), (b'{"q":NaN}', "nonfinite")]:
            with self.assertRaisesRegex(ValueError, pattern):
                m.strict_json(malformed)

    def test_worker_denies_private_labels_in_input_directory(self):
        _, folder = self.prepare()
        with self.assertRaisesRegex(ValueError, "physically isolated"):
            m.run(folder, "/unused/encoder", self.root / "should-not-exist")

    def test_post_seal_source_frontier_does_not_retrain_or_expand_fixed_arm(self):
        self.data = synthetic(docs=130)
        path, fingerprint = self.write_fixture()
        with patch.object(m, "DATASET_SHA256", fingerprint):
            m.prepare(path, self.root / "prepared", expected_sha=fingerprint,
                      source_limit=128, question_limit=2)
            root = self.root / "prepared"
            run = self.sealed(root)
            report = m.source_pool_frontier(path, root, run,
                                             self.root / "frontier.json")
        self.assertFalse(report["inference_rerun"])
        self.assertFalse(report["posthoc_hyperparameter_selection_allowed"])
        self.assertEqual(report["source_pool_ceilings"][-1]["source_prefix_limit"], "all")
        self.assertEqual(len(report["source_pool_ceilings"]), 6)

    def test_kind_does_not_infer_model_quality(self):
        self.assertEqual(m.kind_of("How should we plan next steps?"), "procedural")
        self.assertEqual(m.kind_of("Where is the meeting room?"), "semantic")


if __name__ == "__main__":
    unittest.main()
