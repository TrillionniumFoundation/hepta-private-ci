"""Offline original Reader boundary tests: no inference, no release claim."""

import copy
from pathlib import Path
import tempfile
import unittest

import associative_graph_causal as graph
import parametric_stem_reader as stem
import parametric_stem_reader_language as language
from test_associative_graph_causal import public_fixture


class ReaderSourceBoundary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory()
        cls.root = Path(cls.scratch.name)
        cls.public_dir = cls.root / "public"
        cls.rank_dir = cls.root / "rank"
        cls.public_dir.mkdir()
        cls.rank_dir.mkdir()
        cls.public = public_fixture()
        cls.pubsha = graph.create_only(cls.public_dir / "public.json", cls.public)
        cls.manifest = {"schema": graph.SCHEMA,
                        "public_sha256": cls.pubsha,
                        "private_sha256": "b" * 64,
                        "source_sha256": graph.DATASET_SHA256,
                        "family_count": 10, "question_count": 240,
                        "labels_visible_to_worker": False,
                        "production_accepted": False}
        graph.create_only(cls.public_dir / "manifest.json", cls.manifest)
        rows = []
        for f in cls.public["families"]:
            selected = [d["id"] for d in f["sources"][:8]]
            for q in f["questions"]:
                rows.append({"family": f["family"], "question_id": q["id"],
                             "arms": dict.fromkeys(stem.ARMS, selected)})
        cls.journal = {"schema": stem.SCHEMA,
                       "source_sha256": graph.DATASET_SHA256,
                       "public_sha256": cls.pubsha,
                       "arms": list(stem.ARMS), "top_k": graph.TOP_K,
                       "rows": rows, "cells": {}, "training_receipts": {}, "model": {}}
        cls.digest = graph.create_only(cls.rank_dir / "predictions.json", cls.journal)
        cls.seal = {"schema": stem.SCHEMA, "public_sha256": cls.pubsha,
                    "predictions_sha256": cls.digest,
                    "number_questions": 240, "labels_visible": False,
                    "production_accepted": False}
        graph.create_only(cls.rank_dir / "seal.json", cls.seal)

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def test_all_five_arms_exactly_50_label_free_inputs(self):
        rows, _ = language.reader_inputs(self.public_dir, self.rank_dir)
        self.assertEqual(len(rows), 50)
        self.assertEqual(len({r["question_id"] for r in rows}), 10)
        for r in rows:
            self.assertEqual(set(r), {"family", "question_id", "arm", "question",
                                      "evidence", "public_sha256"})
            if r["arm"] == "empty":
                self.assertEqual(r["evidence"], [])
            else:
                self.assertEqual(len(r["evidence"]), 8)
                self.assertEqual([e["label"] for e in r["evidence"]],
                                 [f"E{i}" for i in range(1, 9)])

    def test_unknown_candidate_source_denied(self):
        bad = copy.deepcopy(self.journal)
        bad["rows"][0]["arms"]["trained_cell"] = ["D0:9999", *bad["rows"][0]["arms"]["trained_cell"][1:]]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = graph.create_only(path / "predictions.json", bad)
            graph.create_only(path / "seal.json", {**self.seal,
                        "predictions_sha256": digest})
            with self.assertRaisesRegex(ValueError, "source out"):
                language.reader_inputs(self.public_dir, path)

    def test_reader_input_denies_rewritten_and_resealed_question(self):
        forged = copy.deepcopy(self.journal)
        forged["rows"][0]["question_id"] = "conv-0/q9999"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            digest = graph.create_only(path / "predictions.json", forged)
            graph.create_only(path / "seal.json", {**self.seal,
                        "predictions_sha256": digest})
            with self.assertRaisesRegex(ValueError, "foreign"):
                language.reader_inputs(self.public_dir, path)

    def test_reader_seal_bitflip_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            (path / "predictions.json").write_bytes((self.rank_dir / "predictions.json").read_bytes())
            graph.create_only(path / "seal.json", {**self.seal,
                        "predictions_sha256": "e" * 64})
            with self.assertRaisesRegex(ValueError, "unregistered"):
                language.reader_inputs(self.public_dir, path)

    def test_reader_must_not_see_hidden_reference_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            for name in ("public.json", "manifest.json"):
                (path / name).write_bytes((self.public_dir / name).read_bytes())
            (path / "private.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "hidden"):
                language.run(path, self.rank_dir, "/missing-model", "/forbidden")

    def test_model_attempt_does_not_fake_oracle_evidence(self):
        rows, _ = language.reader_inputs(self.public_dir, self.rank_dir)
        self.assertTrue(all("answer" not in r and "gold" not in r for r in rows))
        self.assertEqual(set(stem.READER_ARMS),
                         {"empty", "temporal", "rrf", "trained_cell", "rrf_cell"})


if __name__ == "__main__":
    unittest.main()
