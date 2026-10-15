"""No pretrained Reader in these fault tests: injected responses are NOT evidence."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import tempfile
import unittest

from test_amcn_causal_task_audit import fixture, sha
import amcn_causal_reader_generation as r
import amcn_causal_task_audit as a


class Fake:
    def __init__(self, plan, response="synthetic [E1]", fail_on=None):
        self.identity = plan["reader_sha256"]
        self.response = response
        self.fail_on = fail_on
        self.calls = []

    def generate(self, prompt, *, max_input_tokens, max_output_tokens):
        self.calls.append((prompt, max_input_tokens, max_output_tokens))
        if len(self.calls) == self.fail_on:
            raise RuntimeError("fake model outage")
        return self.response, 128, 8


class ReaderGenerationMechanics(unittest.TestCase):
    def setUp(self):
        self.plan, _, _ = fixture()
        self.plan["prompt_sha256"] = r.PROMPT_SHA
        for case in self.plan["cases"]:
            for arm in a.ARMS:
                case["arm_plans"][arm]["planned_request_sha256"] = a.request_digest(
                    self.plan, case, arm, {x["source_id"]: x for x in case["sources"]})

    def trial(self, folder, *, reader=None):
        reader = reader or Fake(self.plan)
        return r.generate_original(self.plan, sha("injected material only"), reader,
                                   folder, source_sha256=sha("test-only plan pin"))

    def test_replays_exact_frozen_questions_without_gold(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "first"
            reader = Fake(self.plan)
            rows = self.trial(folder, reader=reader)
            self.assertEqual(len(rows), 54)
            self.assertEqual(len(reader.calls), 54)
            self.assertEqual(len((folder / "starts.jsonl").read_text().splitlines()), 54)
            self.assertEqual(len((folder / "answers.jsonl").read_text().splitlines()), 54)
            self.assertEqual(json.loads((folder / "sealed-original.json").read_text())[
                "failed_attempts"], 0)
            self.assertEqual(json.loads((folder / "answers.json").read_text()), rows)
            self.assertTrue(all(z["emitted_source_ids"] == [self.plan["cases"][i // 9]
                            ["arm_plans"][a.ARMS[i % 9]]["source_ids"][0]]
                            for i, z in enumerate(rows)))
            self.assertNotIn("publisher_support", (folder / "frozen-plan.json").read_text())
            self.assertIn("synthetic", rows[0]["raw_answer"])
            self.assertTrue(all(x["reader_execution_receipt_sha256"] for x in rows))

    def test_bad_citation_is_preserved_as_undelivered(self):
        with tempfile.TemporaryDirectory() as d:
            rows = self.trial(Path(d) / "first", reader=Fake(self.plan, "[E44]"))
            self.assertTrue(all(x["emitted_source_ids"] == ["UNDELIVERED:[E44]"] for x in rows))

    def test_malformed_citation_shared_parser_is_exact(self):
        original = "text [E1] [E99999] [E0001] [e1] [Ebad]"
        expected = ["source-one", "UNDELIVERED:[E99999]",
                    "UNDELIVERED:[E0001]", "UNDELIVERED:[e1]",
                    "UNDELIVERED:[Ebad]"]
        self.assertEqual(r.decoded_citations(original, ["source-one"]), expected)
        self.assertEqual(a.original_emitted_sources(original, ["source-one"]),
                         expected)

    def test_original_failed_call_preserved_not_inferred_as_answer(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "first"
            rows = self.trial(folder, reader=Fake(self.plan, fail_on=3))
            self.assertEqual(sum(x["status"] == "failed" for x in rows), 1)
            self.assertIsNone(rows[2]["raw_answer_sha256"])
            self.assertIsNone(rows[2]["raw_answer"])
            self.assertEqual(json.loads((folder / "sealed-original.json").read_text())[
                "failed_attempts"], 1)
            self.assertIn("RuntimeError", (folder / "attempt-status.jsonl").read_text())

    def test_no_preexisting_or_reused_output(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "first"
            self.trial(path)
            with self.assertRaises(a.Refused):
                self.trial(path)

    def test_bad_original_plan_never_creates_journal(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "first"
            self.plan["cases"][0]["sources"][0]["text"] = "tamper"
            with self.assertRaises(a.Refused):
                self.trial(path)
            self.assertFalse(path.exists())

    def test_reader_identity_mismatch_denied(self):
        with tempfile.TemporaryDirectory() as d:
            reader = Fake(self.plan)
            reader.identity = sha("different model")
            with self.assertRaises(a.Refused):
                self.trial(Path(d) / "first", reader=reader)

    def test_too_many_tokens_produces_failures_not_success(self):
        class OverBudget(Fake):
            def generate(self, *args, **kwargs):
                return "hallucination [E1]", 100000, 5
        with tempfile.TemporaryDirectory() as d:
            rows = self.trial(Path(d) / "first", reader=OverBudget(self.plan))
            self.assertTrue(all(x["status"] == "failed" for x in rows))
            self.assertTrue(all(x["raw_answer"] is None for x in rows))

    def test_model_missing_rejects_before_loading_transformers(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(a.Refused):
                r.bounded_local_manifest(d, {"broken": "model"})

    def test_unlisted_model_weights_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as d:
            directory = Path(d)
            for file in ("config.json", "tokenizer_config.json", "model.safetensors"):
                (directory / file).write_bytes(file.encode())
            inventory = {"profile": "hepta.amcn.frozen-reader-material.shadow.v1",
                         "reader_sha256": sha("Reader"),
                         "tokenizer_sha256": sha("tokenizer"),
                         "prompt_sha256": r.PROMPT_SHA,
                         "file_sha256": {file: a.bytes_sha((directory / file).read_bytes())
                                         for file in ("config.json", "tokenizer_config.json",
                                                      "model.safetensors")},
                         "pretrained_origin_independently_attested": False}
            self.assertTrue(a.is_sha(r.bounded_local_manifest(directory, inventory)))
            (directory / "extra.safetensors").write_bytes(b"extra")
            with self.assertRaisesRegex(a.Refused, "unlisted"):
                r.bounded_local_manifest(directory, inventory)
            (directory / "extra.safetensors").unlink()
            (directory / "model.safetensors").unlink()
            (directory / "model.safetensors").symlink_to(directory / "config.json")
            with self.assertRaises(a.Refused):
                r.bounded_local_manifest(directory, inventory)

    def test_interrupt_does_not_create_false_complete_seal(self):
        class Crash(Fake):
            def generate(self, *args, **kwargs):
                raise KeyboardInterrupt("hard process interruption")
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "first"
            with self.assertRaises(KeyboardInterrupt):
                self.trial(folder, reader=Crash(self.plan))
            self.assertTrue((folder / "starts.jsonl").exists())
            self.assertFalse((folder / "sealed-original.json").exists())
            self.assertFalse((folder / "answers.json").exists())

    def test_missing_gold_or_history_stays_outside_reader_contract(self):
        plan = deepcopy(self.plan)
        plan["cases"][0]["publisher_gold"] = "answer"
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(a.Refused):
                r.generate_original(plan, sha("dummy"), Fake(plan),
                                    Path(d) / "first", source_sha256=sha("dummy"))


if __name__ == "__main__":
    unittest.main()
