"""Tiny real-decoder transport controls and post-generation measurements."""

import hashlib
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_parametric_model as fixture
from native import digest
from parametric_metrics import binding_specificity, exact_kv_baseline
from parametric_model import SourceMemoryCell, adapter_digest
import parametric_worker
import prepare_parametric


class ParametricTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.SourceMemoryCellTests.setUpClass()
        cls.base = fixture.SourceMemoryCellTests.base
        cls.facts = [fixture.fact("one", "red", "a"), fixture.fact("two", "blue", "b")]
        cls.questions = ["What is the color of one?", "What is the color of two?"]
        cell = SourceMemoryCell(cls.base)
        cell.reset("alpha")
        cell.fit_sources(cls.facts, 4, 0.001, fixture.TEMPLATES)
        cls.snapshot = cls.base.parent / "transport-adapter"
        cls.manifest = cell.save(cls.snapshot)
        cls.request = dict(
            model=str(cls.base),
            snapshot=str(cls.snapshot),
            manifest_sha256=cls.manifest,
            scope="alpha",
            allowed_roots=sorted(cell.reader.roots),
            questions=cls.questions,
            rank=8,
            seed=2718,
            control="adapter",
        )

    @classmethod
    def tearDownClass(cls):
        fixture.SourceMemoryCellTests.tearDownClass()

    def test_extra_source_gold_or_lexicon_rejected_before_model_construction(self):
        for field in ("facts", "gold", "lexicon", "answer_lexicon"):
            with self.subTest(field=field):
                with patch("parametric_worker.SourceMemoryCell") as constructor:
                    with self.assertRaises(ValueError):
                        parametric_worker.run(self.request | {field: ["red", "blue"]})
                    constructor.assert_not_called()

    def test_real_matched_controls_have_distinct_effective_parameter_states(self):
        journals = {
            control: parametric_worker.run(self.request | {"control": control})
            for control in ("adapter", "base", "shuffled")
        }
        prompts = [
            tuple(row["prompt_sha256"] for row in j["rows"]) for j in journals.values()
        ]
        self.assertEqual(len(set(prompts)), 1)
        original = journals["adapter"]["consumed_adapter_state_sha256"]
        self.assertEqual(original, journals["base"]["consumed_adapter_state_sha256"])
        self.assertNotEqual(
            original, journals["shuffled"]["consumed_adapter_state_sha256"]
        )
        self.assertEqual(
            {j["admitted_adapter_state_sha256"] for j in journals.values()}, {original}
        )
        effective = set()
        for control, journal in journals.items():
            enabled = control != "base"
            self.assertTrue(
                all(
                    row["adapter_enabled"] == enabled and row["evidence"] == []
                    for row in journal["rows"]
                )
            )
            # Base has the same checkpoint bytes but its adapter is disabled.
            effective.add(
                digest(
                    (
                        journal["rows"][0]["base_identity"],
                        enabled,
                        journal["consumed_adapter_state_sha256"] if enabled else None,
                    )
                )
            )
        self.assertEqual(len(effective), 3)

    def test_prepare_rejects_an_extra_chat_template_without_downloading(self):
        content = b"{}"
        files = {"config.json": (len(content), hashlib.sha256(content).hexdigest())}
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "model"
            directory.mkdir()
            (directory / "config.json").write_bytes(content)
            with patch.object(prepare_parametric, "FILES", files):
                accepted = prepare_parametric.prepare(directory)
                self.assertEqual(accepted["total_bytes"], len(content))
                (directory / "chat_template.jinja").write_text(
                    "unexpected template", encoding="utf-8"
                )
                with self.assertRaises(ValueError):
                    prepare_parametric.prepare(directory)

    def test_binding_measurement_uses_decoder_logits_without_generation_or_updates(
        self,
    ):
        cell = SourceMemoryCell(self.base)
        cell.load(
            self.snapshot,
            expected_manifest_sha256=self.manifest,
            scope="alpha",
            allowed_roots={"a" * 64, "b" * 64},
            revoked=set(),
        )
        raw = cell.generate(self.questions)
        before = adapter_digest(cell.reader.model)
        with patch.object(
            cell,
            "generate",
            side_effect=AssertionError("measurement must not generate"),
        ):
            with patch.object(
                cell.reader.model, "forward", wraps=cell.reader.model.forward
            ) as forward:
                result = binding_specificity(cell, self.facts, self.questions)
        self.assertEqual(result["model_forward_calls"], 4)
        self.assertEqual(forward.call_count, 4)
        self.assertTrue(
            all("labels" not in call.kwargs for call in forward.call_args_list)
        )
        self.assertEqual(result["prompt_sha256"], [row["prompt_sha256"] for row in raw])
        self.assertEqual(len(result["pairs"]), 1)
        self.assertTrue(
            all(math.isfinite(result[k]) for k in ("before", "after", "delta"))
        )
        self.assertEqual(result["generation_calls"], 0)
        self.assertEqual(before, adapter_digest(cell.reader.model))

    def test_sqlite_executes_complete_word_queries_and_retains_unresolved_reads(self):
        questions = [
            "What is the color of one?",
            "What is the color of stone?",
            "What is the color of one and two?",
            "What is the color of two?",
        ]
        result = exact_kv_baseline(self.facts, questions)
        self.assertEqual(
            [row["text"] for row in result["rows"]], ["red", None, None, "blue"]
        )
        self.assertEqual(
            [row["status"] for row in result["rows"]],
            ["answered", "unresolved", "unresolved", "answered"],
        )
        self.assertEqual(result["rows_written"], 2)
        self.assertEqual(result["sql_reads"], 2)
        self.assertEqual(
            result["sqlite_bytes"], result["page_size"] * result["page_count"]
        )
        self.assertGreater(result["sqlite_bytes"], 0)
        self.assertGreater(result["write_seconds"], 0)
        self.assertGreater(result["read_seconds"], 0)


if __name__ == "__main__":
    unittest.main()
