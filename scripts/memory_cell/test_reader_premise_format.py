"""Adversarial author-made fixtures; not actual LoCoMo or pretrained model evidence."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import associative_graph_causal as graph
import parametric_stem_reader as stem
import reader_premise_format as trial
from test_parametric_stem_reader_language import ReaderSourceBoundary


class FakeTokenizer:
    def render(self, messages):
        return "\n".join(m["content"] for m in messages)

    def encode(self, text):
        return [2, 4, 6] if "Question" in text else [3, 5, 7]

    def decode(self, tokens):
        return "Answer with source [E1]" if tokens == [2, 4, 6] else "I don't know"


class FakeReader:
    tokenizer = FakeTokenizer()

    def generate(self, ids, maximum):
        assert maximum == 48
        return list(ids)


class PublishedPlanContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ReaderSourceBoundary.setUpClass()
        cls.original = []
        for f in ReaderSourceBoundary.public["families"]:
            sources = f["sources"]
            family = f["family"]
            answers = []
            for n, q in enumerate(f["questions"]):
                ids = [sources[0]["id"]]
                if family == "conv-0":
                    ids.append(sources[1]["id"])
                    ids.append(sources[0]["id"])  # intentional publisher duplicate
                answers.append(
                    {
                        "question": q["text"],
                        "evidence": ids,
                        "answer": "private gold must not appear in plan",
                    }
                )
            cls.original.append(
                {
                    "sample_id": family,
                    "qa": answers,
                    "conversation": {
                        "session_1": [
                            {
                                "dia_id": d["id"],
                                "speaker": d["speaker"],
                                "text": d["text"],
                            }
                            for d in sources
                        ]
                    },
                }
            )
        cls.plan = trial.make_plan(
            ReaderSourceBoundary.public_dir, ReaderSourceBoundary.rank_dir, cls.original
        )

    @classmethod
    def tearDownClass(cls):
        ReaderSourceBoundary.tearDownClass()

    def test_sealed_plan_40_fixed_arms_and_no_answer_fields(self):
        trial.validate_plan(self.plan)
        self.assertEqual(len(self.plan["entries"]), 40)
        self.assertEqual({r["arm"] for r in self.plan["entries"]}, set(trial.ARMS))
        self.assertNotIn(
            "private gold must not appear in plan", graph.canonical(self.plan).decode()
        )
        self.assertFalse(self.plan["answers_exported"])
        self.assertFalse(self.plan["production_accepted"])

    def test_duplicate_annotation_dedup_and_label_rebind(self):
        full = [
            r
            for r in self.plan["entries"]
            if r["family"] == "conv-0" and r["arm"] == "annotated_json"
        ][0]
        removed = [
            r
            for r in self.plan["entries"]
            if r["family"] == "conv-0" and r["arm"] == "removed_json"
        ][0]
        self.assertEqual(len(full["evidence"]), 2)
        self.assertEqual(len(removed["evidence"]), 1)
        self.assertEqual(removed["evidence"][0]["label"], "E1")
        self.assertTrue(
            {r["source_id"] for r in removed["evidence"]}
            < {r["source_id"] for r in full["evidence"]}
        )

    def test_oracle_annotation_not_validity_proof(self):
        self.assertTrue(self.plan["oracle_reference_ids_from_publisher"])
        self.assertTrue(self.plan["oracle_is_not_independent_sufficiency"])
        self.assertEqual(trial.SCHEMA, "hepta.reader-premise-format.shadow.v1")

    def test_reject_unavailable_original_source(self):
        original = copy.deepcopy(self.original)
        chosen = next(row for row in self.plan["entries"] if row["family"] == "conv-0")
        question_index = int(chosen["question_id"].rsplit("/q", 1)[1])
        original[0]["qa"][question_index]["evidence"] = ["D999:999"]
        with self.assertRaisesRegex(ValueError, "unresolved"):
            trial.make_plan(
                ReaderSourceBoundary.public_dir, ReaderSourceBoundary.rank_dir, original
            )

    def test_reject_original_question_drift(self):
        original = copy.deepcopy(self.original)
        for item in original[0]["qa"]:
            item["question"] = "altered question"
        with self.assertRaisesRegex(ValueError, "public question changed"):
            trial.make_plan(
                ReaderSourceBoundary.public_dir, ReaderSourceBoundary.rank_dir, original
            )

    def test_cross_axis_prompt_and_premise_consistency(self):
        changed = copy.deepcopy(self.plan)
        row = next(r for r in changed["entries"] if r["arm"] == "removed_lines")
        row["evidence"].append(
            {"label": "E1", "source_id": "D0:999", "text": "malicious altered evidence"}
        )
        with self.assertRaises(ValueError):
            trial.validate_plan(changed)

    def test_exact_plan_digest_and_mutation_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan_hash = graph.create_only(folder / "plan.json", self.plan)
            graph.create_only(
                folder / "seal.json",
                {
                    "schema": trial.SCHEMA,
                    "plan_sha256": plan_hash,
                    "planned": 40,
                    "answers_in_worker": False,
                    "production_accepted": False,
                },
            )
            self.assertEqual(trial._read_plan(folder)[1]["plan_sha256"], plan_hash)
            tampered = copy.deepcopy(self.plan)
            tampered["entries"][0]["question"] = "different question"
            (folder / "plan.json").write_bytes(graph.canonical(tampered))
            with self.assertRaises(ValueError):
                trial._read_plan(folder)

    def test_gold_file_at_worker_boundary_denied_by_inventory(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            plan_hash = graph.create_only(folder / "plan.json", self.plan)
            graph.create_only(
                folder / "seal.json",
                {
                    "schema": trial.SCHEMA,
                    "plan_sha256": plan_hash,
                    "planned": 40,
                    "answers_in_worker": False,
                    "production_accepted": False,
                },
            )
            (folder / "answers.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "only plan"):
                trial._read_plan(folder)

    def test_reader_profiles_are_genuinely_distinct_without_gold(self):
        json_arm = next(x for x in self.plan["entries"] if x["arm"] == "annotated_json")
        line_arm = next(
            x for x in self.plan["entries"] if x["arm"] == "annotated_lines"
        )
        self.assertNotEqual(trial._prompt(json_arm), trial._prompt(line_arm))
        self.assertEqual(json_arm["evidence"], line_arm["evidence"])
        self.assertNotIn(
            "private gold must not appear in plan", trial._prompt(line_arm)
        )

    def test_same_reader_max_tokens_and_no_postprocessed_citation(self):
        model = FakeReader()
        line = next(x for x in self.plan["entries"] if x["arm"] == "annotated_lines")
        base = next(x for x in self.plan["entries"] if x["arm"] == "annotated_json")
        a = trial._generate(model, line)
        b = trial._generate(model, base)
        self.assertEqual(a["status"], "succeeded")
        self.assertEqual(b["status"], "succeeded")
        self.assertFalse(a["answer_postprocessed"])
        self.assertFalse(b["answer_postprocessed"])
        self.assertEqual(a["generated_tokens"], 3)
        self.assertEqual(b["generated_tokens"], 3)

    def test_created_seal_rejects_rewritten_and_resealed_original_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_hash = graph.create_only(root / "plan.json", self.plan)
            sealed = {
                "schema": trial.SCHEMA,
                "plan_sha256": raw_hash,
                "planned": 40,
                "answers_in_worker": False,
                "production_accepted": False,
            }
            graph.create_only(root / "seal.json", sealed)
            self.assertEqual(trial._read_plan(root)[0], self.plan)
            # Modifying one premise and then resealing does not pass the
            # reviewer-side original-source re-computation contract.
            altered = copy.deepcopy(self.plan)
            altered["entries"][0]["evidence"][0]["text"] = "fabricated text"
            (root / "plan.json").write_bytes(graph.canonical(altered))
            sealed["plan_sha256"] = graph.digest((root / "plan.json").read_bytes())
            (root / "seal.json").write_bytes(graph.canonical(sealed))
            trial._read_plan(root)  # producer-local checksum is self-attested
            self.assertNotEqual(
                trial.make_plan(
                    ReaderSourceBoundary.public_dir,
                    ReaderSourceBoundary.rank_dir,
                    self.original,
                ),
                trial._read_plan(root)[0],
            )


if __name__ == "__main__":
    unittest.main()
