"""Protocol-only tests; no synthetic result can qualify language memory."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

import memory_reader_causal_panel as m


class PanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = self.root / "plan"
        self.plan.mkdir()
        requests = []
        for arm in m.ARMS:
            requests.append({"request_id": "conv-1/q0000:" + arm,
                             "question_id": "conv-1/q0000", "family": "conv-1",
                             "question": "Which thing happened?", "arm": arm,
                             "evidence": [], "unavailable": False})
        self.raw_plan = {"schema": m.SCHEMA,
                         "public_sha256": "a"*64, "rank_journal_sha256": "b"*64,
                         "original_sha256": m.ORIGINAL_SHA,
                         "planned_questions": 1, "arms": list(m.ARMS),
                         "max_input_tokens": m.MAX_INPUT_TOKENS,
                         "max_new_tokens": m.MAX_TOKENS,
                         "generated_with_annotation_privileges": True,
                         "answer_labels_in_model_plan": False,
                         "production_accepted": False, "requests": requests}
        ph = m.write(self.plan / "plan.json", self.raw_plan)
        m.write(self.plan / "plan-seal.json",
                {"schema": m.SCHEMA, "plan_sha256": ph,
                 "expected_rows": len(requests), "production_accepted": False})

    def test_closed_world_plan_no_gold_and_frozen_identity(self):
        plan, ph = m.load_plan(self.plan)
        self.assertEqual(ph, m.digest((self.plan / "plan.json").read_bytes()))
        self.assertFalse(plan["answer_labels_in_model_plan"])
        self.assertNotIn('"answer"', (self.plan / 'plan.json').read_text())

    def test_reject_private_label_file_and_unknown_fields(self):
        (self.plan / "private.json").write_text('{}')
        with self.assertRaisesRegex(ValueError, "closed-world"):
            m.load_plan(self.plan)
        (self.plan / "private.json").unlink()
        self.raw_plan["answer"] = "leak"
        (self.plan / "plan.json").write_bytes(m.canonical(self.raw_plan))
        with self.assertRaisesRegex(ValueError, "unsealed"):
            m.load_plan(self.plan)

    def test_reject_gold_leak_even_if_resealed(self):
        self.raw_plan["answer"] = "secret"
        raw = m.canonical(self.raw_plan)
        (self.plan / "plan.json").write_bytes(raw)
        (self.plan / "plan-seal.json").write_bytes(m.canonical(
            {"schema": m.SCHEMA, "plan_sha256": m.digest(raw),
             "expected_rows": len(self.raw_plan["requests"]), "production_accepted": False}))
        with self.assertRaisesRegex(ValueError, "reader plan"):
            m.load_plan(self.plan)

    def test_fail_on_duplicate_or_nonfinite_json(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            m.strict(b'{"x":1,"x":2}')
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            m.strict(b'{"x":NaN}')

    def test_checkpoint_must_be_exact_prefix_and_plan_bound(self):
        plan, ph = m.load_plan(self.plan)
        checkpoint = self.root / "checkpoint.jsonl"
        row = {"request_id": plan['requests'][0]['request_id'],
               "arm": "empty", "status": "unavailable", "plan_sha256": ph}
        checkpoint.write_bytes(m.canonical(row))
        self.assertEqual(len(m.load_checkpoint(checkpoint, plan["requests"], ph)), 1)
        checkpoint.write_bytes(m.canonical(dict(row, plan_sha256="0"*64)))
        with self.assertRaisesRegex(ValueError, "cross-plan"):
            m.load_checkpoint(checkpoint, plan["requests"], ph)
        checkpoint.write_bytes(m.canonical(dict(row, request_id="forged")))
        with self.assertRaisesRegex(ValueError, "nonprefix"):
            m.load_checkpoint(checkpoint, plan["requests"], ph)

    def test_no_gold_in_request_and_true_evidence_id_constraints(self):
        self.raw_plan["requests"][0]["evidence"] = [
            {"source_id": "D1:1", "label": "E1", "text": "Alice: hello"}]
        self.raw_plan["requests"][0]["answer"] = "leak"
        raw = m.canonical(self.raw_plan)
        (self.plan / "plan.json").write_bytes(raw)
        (self.plan / "plan-seal.json").write_bytes(m.canonical(
            {"schema": m.SCHEMA, "plan_sha256": m.digest(raw),
             "expected_rows": len(self.raw_plan["requests"]), "production_accepted": False}))
        with self.assertRaisesRegex(ValueError, "noncanonical"):
            m.load_plan(self.plan)

    def test_original_required_exact_digest(self):
        p = self.root / "badoriginal.json"
        p.write_bytes(b'[]')
        with self.assertRaisesRegex(ValueError, "original source SHA"):
            m.validated_original(p, {"families": []})

    def test_token_f1_and_citation_are_not_equivalent(self):
        self.assertAlmostEqual(m.token_f1("Tokyo [E1]", "Tokyo"), 2/3)
        self.assertEqual(m.token_f1("unknown", "actual fact"), 0.0)

    def test_actual_original_panel_producer_if_available(self):
        original = os.getenv("HEPTA_MEMORY_ORIGINAL")
        prepared = os.getenv("HEPTA_MEMORY_PREPARED")
        source_run = os.getenv("HEPTA_MEMORY_GRAPH_RUN")
        if not all((original, prepared, source_run)):
            self.skipTest("opt-in SHA-pinned original corpus only")
        dest = self.root / "actual-plan"
        result = m.make_plan(original, prepared, source_run, dest, 2)
        data, _ = m.load_plan(dest)
        self.assertEqual(result["requests"], 120)
        self.assertEqual(sum(r["unavailable"] for r in data["requests"]), 2)


if __name__ == "__main__":
    unittest.main()
