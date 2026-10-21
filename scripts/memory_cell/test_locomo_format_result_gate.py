"""Adversarial real frozen Reader format receipts and source-only prompt controls."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from locomo_format_trial import (
    BASELINE_SYSTEM,
    FORMATS,
    EVIDENCE_ARMS,
    SOURCE_PIN,
    frozen_requests,
    load_registered,
    messages,
    sha,
)
from locomo_format_result_gate import (
    audit,
    audit_literal,
    literal_pinned,
    source_pinned,
)


class OriginalFormatReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = source_pinned()

    def sample(self):
        return copy.deepcopy(self.original)

    def test_completed_original_negative_preserves_deny_all(self):
        result = audit(self.sample())
        self.assertEqual(result["original_model_requests"], 48)
        self.assertEqual(result["original_prompt_reproducibility"], 16)
        self.assertEqual(result["original_json_echo_with_annotated_witness"], 7)
        self.assertEqual(result["reformatted_json_echo_with_annotated_witness"], 0)
        self.assertEqual(result["evidence_readout_correct_among_question_first"], 0)
        self.assertEqual(result["decision"], "DENY_ALL")
        self.assertFalse(result["production_accepted"])

    def test_fabricated_task_gain_rejected(self):
        mutant = self.sample()
        mutant["by_arm"]["annotated_witness:question_first"]["strict_correct"] = 1
        with self.assertRaisesRegex(ValueError, "task/prompt-echo"):
            audit(mutant)

    def test_changed_real_reader_resource_receipts_rejected(self):
        for key, field, value in (
            ("annotated_witness:linear_evidence", "input_tokens", 1),
            ("empty:question_first", "output_tokens", 0),
            ("annotated_witness:original_json", "json_echo", 0),
            (
                "annotated_witness:linear_evidence",
                "citation_markers_structurally_valid",
                0,
            ),
        ):
            data = self.sample()
            data["by_arm"][key][field] = value
            with self.subTest(key=key, field=field):
                with self.assertRaisesRegex(ValueError, "task/prompt-echo"):
                    audit(data)

    def test_diagnostic_f1_not_rewritten_into_accuracy(self):
        data = self.sample()
        data["by_arm"]["annotated_witness:question_first"]["mean_diagnostic_f1"] = 1.0
        with self.assertRaisesRegex(ValueError, "token-F1 readout"):
            audit(data)

    def test_no_missing_or_invented_model_forward(self):
        data = self.sample()
        data["complete_real_model_requests"] = 47
        with self.assertRaisesRegex(ValueError, "physical original model"):
            audit(data)
        data = self.sample()
        data["source_reproduction_exact_original_requests"] = 48
        with self.assertRaisesRegex(ValueError, "physical original model"):
            audit(data)

    def test_refuse_fabricated_human_evidence_or_trained_cell(self):
        for field, value in (
            ("independently_human_verified_witnesses", 8),
            ("new_source_families", 8),
            ("model_training_steps", 100),
            ("semantic_citation_entailment", 1.0),
            ("complete_lifecycle_tco", 0.0),
            ("production_accepted", True),
        ):
            data = self.sample()
            data[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "unearned MemoryCell"):
                    audit(data)

    def test_postseal_witness_literal_coverage_is_not_human_sufficiency(self):
        value = literal_pinned()
        result = audit_literal(value)
        self.assertEqual(result["publisher_annotated_witness_literal_hits"], 2)
        self.assertFalse(result["independent_sufficiency_certified"])
        changed = copy.deepcopy(value)
        changed["literal_target_in_one_annotated_witness"] = 8
        with self.assertRaisesRegex(ValueError, "postseal literal"):
            audit_literal(changed)
        changed = copy.deepcopy(value)
        changed["independent_human_review"] = True
        with self.assertRaisesRegex(ValueError, "postseal literal"):
            audit_literal(changed)

    def test_blind_source_and_format_output_cannot_use_targets(self):
        req = dict(
            qid="q",
            root_sha256="root",
            question="Where did Alex travel?",
            arm="annotated_witness",
            source_ids=["s"],
            sources=[dict(id="s", speaker="Alex", text="We went to Oslo.")],
        )
        outputs = [messages(req, form) for form in FORMATS]
        self.assertEqual(outputs[0][0]["content"], BASELINE_SYSTEM)
        self.assertIn('"question": "Where did Alex travel?"', outputs[0][1]["content"])
        self.assertIn("[E1] Alex: We went to Oslo.", outputs[1][1]["content"])
        self.assertIn("[E1] Alex: We went to Oslo.", outputs[2][1]["content"])
        for output in outputs:
            self.assertEqual([x["role"] for x in output], ["system", "user"])
            self.assertNotIn("gold_answer", json.dumps(output))
        empty = copy.deepcopy(req)
        empty.update(arm="empty", sources=[], source_ids=[])
        self.assertIn('"evidence": []', messages(empty, "original_json")[1]["content"])
        self.assertIn("(none)", messages(empty, "linear_evidence")[1]["content"])

    def test_old_root_selection_never_accepts_duplicated_or_missing_questions(self):
        rows = []
        for i in range(8):
            for arm in ("empty", "bm25_top3", "annotated_witness", "witness_lesion"):
                rows.append(
                    dict(
                        qid=f"q{i}",
                        root_sha256=f"r{i}",
                        question="Where?",
                        arm=arm,
                        source_ids=[],
                        sources=[],
                    )
                )
        source = dict(
            schema="hepta.memory.locomo-fixed-reader-private-input.v1", requests=rows
        )
        self.assertEqual(len(frozen_requests(source)), 16)
        corrupt = copy.deepcopy(source)
        corrupt["requests"][1]["qid"] = "q1"
        with self.assertRaisesRegex(ValueError, "duplicate original question/arm"):
            frozen_requests(corrupt)
        corrupt = copy.deepcopy(source)
        corrupt["requests"][0]["source_ids"] = ["hidden"]
        with self.assertRaisesRegex(ValueError, "hidden evidence"):
            frozen_requests(corrupt)
        corrupt = copy.deepcopy(source)
        corrupt["requests"][2]["sources"] = [dict(id="d", speaker="A", text="X")]
        with self.assertRaisesRegex(ValueError, "delivered source census"):
            frozen_requests(corrupt)

    def test_sealed_original_source_and_model_plan_hashes_guarded(self):
        import locomo_format_trial as trial
        from locomo_format_trial import SCHEMA, GENERATOR, EVIDENCE_ARMS, FORMATS

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            # Source-only fixture exercises checksum rejection; no model calls.
            sealed = dict(
                schema=GENERATOR,
                trials=[
                    dict(request=dict(qid=f"q{i}", arm=arm), format=form)
                    for i in range(8)
                    for arm in EVIDENCE_ARMS
                    for form in FORMATS
                ],
            )
            content = json.dumps(sealed).encode()
            (directory / "sealed-prompts.json").write_bytes(content)
            registry = dict(
                schema=SCHEMA,
                source_original_sha256=SOURCE_PIN,
                sealed_prompt_sha256=sha(content),
                code_sha256=sha(Path(trial.__file__).read_bytes()),
                prompt_formats=list(FORMATS),
                evidence_conditions=list(EVIDENCE_ARMS),
                model_calls=48,
                learning_updates=0,
            )
            (directory / "preregistered.json").write_text(json.dumps(registry))
            _, controls = load_registered(directory)
            self.assertEqual(len(controls), 48)
            registry["sealed_prompt_sha256"] = "f" * 64
            (directory / "preregistered.json").write_text(json.dumps(registry))
            with self.assertRaisesRegex(ValueError, "registered source, code"):
                load_registered(directory)


if __name__ == "__main__":
    unittest.main()
