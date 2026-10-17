"""Independent start-journal protocol tests, NEVER physical model efficacy."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, main

import memory_reader_causal_panel as base
import memory_reader_strong_reference as strong
import memory_reader_strong_custody as custody
import test_memory_reader_strong_reference as fixtures


class CustodyTests(TestCase):
    def setUp(self):
        self.parent = fixtures.StrongReferenceTests("test_closed_original_panel_acceptance")
        self.parent.setUp()
        self.addCleanup(self.parent.doCleanups)
        self.plan, self.ph = strong.preflight(self.parent.plan_dir)
        self.rows = self.parent.population()
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.write_starts()

    def write_starts(self):
        path = self.out / "started.jsonl"
        if path.exists():
            path.unlink()
        for row in self.rows:
            if row["status"] == "succeeded":
                strong.write_start(path, row)

    def test_exact_120_call_replay_provides_non_authorizing_receipt(self):
        report = custody.check(self.plan, self.ph, self.rows, self.out)
        self.assertEqual(report["started_calls"], 120)
        self.assertFalse(report["external_model_execution_independently_attested"])
        self.assertFalse(report["production_accepted"])
        if os.name == "posix":
            self.assertEqual((self.out / "started.jsonl").stat().st_mode & 0o777, 0o600)

    def test_missing_complete_journal_denies_even_resealed_answers(self):
        (self.out / "started.jsonl").unlink()
        with self.assertRaisesRegex(ValueError, "missing or truncated"):
            custody.check(self.plan, self.ph, self.rows, self.out)

    def test_reordered_before_effects_denied(self):
        path = self.out / "started.jsonl"
        lines = path.read_bytes().splitlines(keepends=True)
        lines[:2] = list(reversed(lines[:2]))
        path.write_bytes(b"".join(lines))
        with self.assertRaisesRegex(ValueError, "disagree"):
            custody.check(self.plan, self.ph, self.rows, self.out)

    def test_truncated_and_duplicate_start_denied(self):
        path = self.out / "started.jsonl"
        valid = path.read_bytes()
        for corruption in (valid[:-1], valid + valid.splitlines(keepends=True)[0]):
            path.write_bytes(corruption)
            with self.assertRaisesRegex(ValueError, "truncated|disagree"):
                custody.check(self.plan, self.ph, self.rows, self.out)

    def test_prompt_model_plan_input_drift_denied(self):
        path = self.out / "started.jsonl"
        pristine = path.read_bytes()
        original = base.strict(pristine.splitlines()[0])
        for key, value in [("model_spec_digest", "not-model"),
                           ("prompt_digest", "not-prompt"),
                           ("input_ids_digest", "0"*64),
                           ("input_tokens", 12),
                           ("plan_sha256", "0"*64)]:
            altered = {**original, key: value}
            path.write_bytes(base.canonical(altered) + b"".join(pristine.splitlines(keepends=True)[1:]))
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "disagree"):
                custody.check(self.plan, self.ph, self.rows, self.out)
        path.write_bytes(pristine)

    def test_unavailable_historical_rows_have_no_effect_intent(self):
        self.plan["requests"][0]["unavailable"] = True
        self.rows[0] = strong.make_record(self.plan["requests"][0], self.ph,
                                          self.parent.seal["model_spec_digest"])
        self.write_starts()
        self.assertEqual(custody.check(self.plan, self.ph, self.rows, self.out)["started_calls"], 119)
        strong.write_start(self.out / "started.jsonl", self.parent.population()[0])
        with self.assertRaisesRegex(ValueError, "disagree"):
            custody.check(self.plan, self.ph, self.rows, self.out)

    def test_non_tokenized_or_malicious_before_effect_denied(self):
        row = strong.make_record(self.plan["requests"][0], self.ph,
                                 self.parent.seal["model_spec_digest"])
        with self.assertRaisesRegex(ValueError, "token identity"):
            custody.event(row)
        fake_hash = {**self.rows[0], "input_ids_digest": "z" * 64}
        with self.assertRaisesRegex(ValueError, "token identity"):
            custody.event(fake_hash)
        path = self.out / "evil.jsonl"
        path.symlink_to(self.out / "started.jsonl")
        row = self.rows[0]
        with self.assertRaises(OSError):
            strong.write_start(path, row)

    def test_actual_prior_plan_when_provided(self):
        original = os.getenv("HEPTA_STRONG_ACTUAL_PLAN")
        if not original:
            self.skipTest("original answer-free plan not mounted")
        plan, ph = strong.preflight(original)
        self.assertEqual(ph, strong.HISTORICAL_PLAN_SHA)
        self.assertEqual((len(plan["requests"]), sum(r["unavailable"] for r in plan["requests"])),(120, 2))


if __name__ == "__main__":
    main()
