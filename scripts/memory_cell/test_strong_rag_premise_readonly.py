"""Tamper tests for immutable 64-generation premise-citation source replay.

No model is simulated as successful: model tests use archived original bytes
only when the two pinned research ZIPs are provided as external inputs.
"""

import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import strong_rag_premise_readonly as audit


class PremiseAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        folder = os.environ.get("HEPTA_MEMORY_PREMISE_ARCHIVES")
        cls.inputs = (Path(folder) if folder else Path(__file__).resolve().parent)
        cls.model = cls.inputs / "memory-premise-actual-64-38385138211.zip"
        cls.original = cls.inputs / "event-inputs-20261010.zip"

    def require_archives(self):
        if not self.model.is_file() or not self.original.is_file():
            self.skipTest("model/source pinned ZIPs not attached; fixture results do not replace inference")

    def mutate(self, changed, *, reseal=True, model=True):
        self.require_archives()
        src = self.model if model else self.original
        with zipfile.ZipFile(src) as z:
            contents = {n: z.read(n) for n in z.namelist()}
        contents.update(changed)
        if reseal:
            contents["SHA256SUMS"] = "".join(
                hashlib.sha256(payload).hexdigest() + "  ./" + name + "\n"
                for name, payload in sorted(contents.items()) if name != "SHA256SUMS"
            ).encode()
        tempdir = tempfile.TemporaryDirectory()
        target = Path(tempdir.name) / "mutated.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as z:
            for name, value in contents.items():
                z.writestr(name, value)
        self.addCleanup(tempdir.cleanup)
        return target

    def test_original_64_real_calls_and_negative_promotion(self):
        self.require_archives()
        result = audit.replay(self.model, self.original)
        self.assertEqual(result["actual_model_generations"], 64)
        self.assertEqual(result["matched_question_condition_pairs"], 32)
        self.assertFalse(result["prompt_promotion_qualified"])
        self.assertFalse(result["production_accepted"])
        organized = result["conditions"]["organized"]
        self.assertEqual((organized["original_correct"], organized["premise_chain_correct"]), (8, 3))
        self.assertEqual((organized["original_complete_chain"], organized["premise_chain_complete_chain"]), (4, 2))
        self.assertEqual(organized["premise_chain_truncated_identifier"], 5)
        self.assertEqual(result["conditions"]["hybrid"]["task_wins"], 1)

    def test_external_model_zip_pin_is_not_optional(self):
        self.require_archives()
        target = self.mutate({"experiment.log": b"modified log"})
        with self.assertRaisesRegex(ValueError, "outer ZIP"):
            audit.replay(target, self.original)

    def test_external_original_plan_pin_is_not_optional(self):
        self.require_archives()
        target = self.mutate({"plan/plan.json": b"{}"}, model=False)
        with self.assertRaisesRegex(ValueError, "outer ZIP"):
            audit.replay(self.model, target)

    def test_member_manifest_disallows_changed_bytes_even_with_new_outer_pin(self):
        target = self.mutate({"evaluation/raw-answers.jsonl": b"{}\n"}, reseal=False)
        with patch.object(audit, "MODEL_SHA", audit.hashbytes(target.read_bytes())):
            with self.assertRaisesRegex(ValueError, "manifest file hash mismatch"):
                audit.replay(target, self.original)

    def test_resigned_raw_answer_mutation_does_not_validate(self):
        self.require_archives()
        with zipfile.ZipFile(self.model) as z:
            raw = z.read("evaluation/raw-answers.jsonl")
        modified = raw.replace(b"site_849f0372", b"site_00000000", 1)
        self.assertNotEqual(modified, raw)
        target = self.mutate({"evaluation/raw-answers.jsonl": modified})
        with patch.object(audit, "MODEL_SHA", audit.hashbytes(target.read_bytes())):
            with self.assertRaisesRegex(ValueError, "scorer modified"):
                audit.replay(target, self.original)

    def test_resigned_result_relabel_does_not_validate(self):
        self.require_archives()
        with zipfile.ZipFile(self.model) as z:
            raw = z.read("evaluation/scored-answers.json")
        changed = raw.replace(b'"strict_task_success": false', b'"strict_task_success": true', 1)
        self.assertNotEqual(changed, raw)
        target = self.mutate({"evaluation/scored-answers.json": changed})
        with patch.object(audit, "MODEL_SHA", audit.hashbytes(target.read_bytes())):
            with self.assertRaisesRegex(ValueError, "independent original answer replay"):
                audit.replay(target, self.original)

    def test_resigned_prompt_receipt_mutation_is_rejected(self):
        self.require_archives()
        with zipfile.ZipFile(self.model) as z:
            raw = z.read("evaluation/raw-answers.jsonl")
        changed = raw.replace(b'"input_ids_digest": "ed332f8c37d0d3fc656819404776d0aedf62f9d44ef94dbe7239b020cc3bd3b9"', b'"input_ids_digest": "' + b"0" * 64 + b'"', 1)
        self.assertNotEqual(changed, raw)
        target = self.mutate({"evaluation/raw-answers.jsonl": changed})
        with patch.object(audit, "MODEL_SHA", audit.hashbytes(target.read_bytes())):
            with self.assertRaises(ValueError):
                audit.replay(target, self.original)

    def test_missing_attempt_never_shrinks_denominator(self):
        self.require_archives()
        with zipfile.ZipFile(self.model) as z:
            raw = z.read("evaluation/raw-answers.jsonl")
        target = self.mutate({"evaluation/raw-answers.jsonl": b"\n".join(raw.splitlines()[:-1]) + b"\n"})
        with patch.object(audit, "MODEL_SHA", audit.hashbytes(target.read_bytes())):
            with self.assertRaisesRegex(ValueError, "64 original complete"):
                audit.replay(target, self.original)

    def test_duplicate_json_field_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            audit.strict_json('{"status":"failed","status":"succeeded"}')

    def test_nonfinite_json_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "nonfinite JSON"):
            audit.strict_json('{"seconds":NaN}')

    def test_worker_recipe_bound_has_no_arbitrary_code(self):
        with self.assertRaisesRegex(ValueError, "unregistered program worker"):
            audit.procedure_outcome({"values":[1,2],"modes":{"mode_1234":"shell"},"target":[1,2]},"mode_1234")

    def test_token_identifier_format_is_strict(self):
        self.assertIsNotNone(audit.IDENTIFIER.fullmatch("site_11111111 [E1]"))
        self.assertIsNone(audit.IDENTIFIER.fullmatch("site_ [E1]"))
        self.assertIsNone(audit.IDENTIFIER.fullmatch("[site_11111111]"))


if __name__ == "__main__":
    unittest.main()
