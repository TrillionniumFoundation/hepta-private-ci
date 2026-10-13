"""Synthetic fixture tests: no real private review or reviewer approval."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from reader_review_handoff import prepare_handoff
from reader_review_intake import reconcile_handoff
from test_reader_originals_attestation import example


def dump_lines(path, rows):
    raw = "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                  for row in rows).encode()
    path.write_bytes(raw)
    path.chmod(0o600)
    return hashlib.sha256(raw).hexdigest()


def read_lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


class ReviewIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        _, _, _, originals = example()
        self.handoff = self.root / "handoff"
        prepare_handoff(originals, source_file_sha256="a" * 64,
                        output=self.handoff, salt=b"\x07" * 32)
        self.receipt_pin = hashlib.sha256(
            (self.handoff / "handoff-receipt.json").read_bytes()).hexdigest()
        operator = {r["ticket"]: r for r in read_lines(
            self.handoff / "operator-private-map.jsonl")}
        rows = read_lines(self.handoff / "reviewer-blank-form.jsonl")
        for row in rows:
            condition = operator[row["ticket"]]["condition"]
            row["grounded_and_cited"] = condition == "human_sufficient"
            row["exact_refusal"] = condition in (
                "no_evidence", "critical_premise_removed")
            row["cited_semantically_supported"] = condition == "human_sufficient"
        self.first = self.root / "review-one.jsonl"
        self.second = self.root / "review-two.jsonl"
        self.first_pin = dump_lines(self.first, rows)
        self.second_pin = dump_lines(self.second, copy.deepcopy(rows))
        self.rows = rows
        self.map = operator
        self.output = self.root / "review-comparison"

    def run_intake(self, *, first_pin=None, second_pin=None, receipt_pin=None,
                   first_id="reviewer-a", second_id="reviewer-b", out=None):
        return reconcile_handoff(
            self.handoff, self.first, self.second,
            out or self.output,
            receipt_pin=receipt_pin or self.receipt_pin,
            first_pin=first_pin or self.first_pin,
            second_pin=second_pin or self.second_pin,
            first_id=first_id, second_id=second_id)

    def test_all_agreement_does_not_sign_or_approve(self):
        result = self.run_intake()
        self.assertEqual((result["positions"], result["agreed"],
                          result["disputed"], result["incomplete"]), (8, 8, 0, 0))
        self.assertFalse(result["review_approval_produced"])
        receipt = json.loads((self.output / "reconciliation-receipt.json").read_text())
        self.assertFalse(receipt["independent_human_judgment_established"])
        self.assertFalse(receipt["both_reviewers_externally_authenticated"])
        self.assertFalse(receipt["production_accepted"])
        self.assertTrue(receipt["identical_unverified_review_bytes"])
        self.assertEqual(receipt["cryptographic_review_signatures"], 0)
        self.assertEqual(receipt["neural_calls"], 0)
        self.assertEqual(self.output.stat().st_mode & 0o077, 0)
        for file in self.output.iterdir():
            self.assertEqual(file.stat().st_mode & 0o077, 0)
        comparisons = read_lines(self.output / "operator-private-comparison.jsonl")
        self.assertEqual(len(comparisons), 8)
        self.assertTrue(all(r["status"] == "agreed" for r in comparisons))
        self.assertTrue(all("raw_reader_answer" not in r for r in comparisons))

    def test_honest_disagreement_is_not_majority_approved(self):
        changed = copy.deepcopy(self.rows)
        for row in changed:
            if self.map[row["ticket"]]["condition"] == "human_sufficient":
                row["grounded_and_cited"] = False
                row["cited_semantically_supported"] = False
                break
        self.second_pin = dump_lines(self.second, changed)
        result = self.run_intake()
        self.assertEqual((result["agreed"], result["disputed"]), (7, 1))
        self.assertFalse(result["production_accepted"])

    def test_pending_review_preserved_and_not_imputed(self):
        changed = copy.deepcopy(self.rows)
        for key in ("grounded_and_cited", "cited_semantically_supported"):
            changed[0][key] = None
        self.second_pin = dump_lines(self.second, changed)
        result = self.run_intake()
        self.assertEqual(result["incomplete"], 1)
        self.assertEqual(result["agreed"], 7)
        self.assertFalse(result["review_approval_produced"])

    def test_different_verifiers_have_no_automatic_identity_assurance(self):
        with self.assertRaisesRegex(ValueError, "distinct operator-verified"):
            self.run_intake(second_id="reviewer-a")
        self.assertFalse(self.output.exists())

    def test_missing_or_duplicate_or_extra_ticket_rejected(self):
        for rows in (self.rows[:-1], self.rows + self.rows[:1],
                     [dict(r, ticket="a" * 32) if i == 0 else r
                      for i, r in enumerate(self.rows)]):
            with self.subTest(rows=len(rows)):
                self.second_pin = dump_lines(self.second, rows)
                with self.assertRaises(ValueError):
                    self.run_intake()
                self.assertFalse(self.output.exists())

    def test_wrong_operator_supplied_form_pin_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "pin or byte budget"):
            self.run_intake(first_pin="0" * 64)
        self.assertFalse(self.output.exists())

    def test_changed_handoff_packet_rejected_by_receipt_hash(self):
        packet = self.handoff / "review-questions.jsonl"
        packet.write_bytes(packet.read_bytes() + b"{}\n")
        with self.assertRaises(ValueError):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_unauthorized_handoff_approval_flag_rejected(self):
        receipt_file = self.handoff / "handoff-receipt.json"
        receipt = json.loads(receipt_file.read_text())
        receipt["reviewer_signatures"] = 2
        receipt_file.write_text(json.dumps(receipt))
        receipt_file.chmod(0o600)
        self.receipt_pin = hashlib.sha256(receipt_file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "fabricated handoff approval"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_forged_grounded_without_source_citation_is_rejected(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if self.map[row["ticket"]]["condition"] == "ordinary_retrieval":
                row["grounded_and_cited"] = True
                row["cited_semantically_supported"] = True
                break
        self.second_pin = dump_lines(self.second, rows)
        with self.assertRaisesRegex(ValueError, "without citations|lacks cited"):
            self.run_intake()

    def test_exact_refusal_must_match_original_literal_answer(self):
        rows = copy.deepcopy(self.rows)
        for row in rows:
            if self.map[row["ticket"]]["condition"] == "no_evidence":
                row["exact_refusal"] = False
                break
        self.second_pin = dump_lines(self.second, rows)
        with self.assertRaisesRegex(ValueError, "exact-refusal verdict"):
            self.run_intake()

    def test_invalid_boolean_and_fake_signature_fields_rejected(self):
        for patch in ({"grounded_and_cited": 1}, {"signature_hex": "a" * 128}):
            rows = copy.deepcopy(self.rows)
            rows[0].update(patch)
            self.second_pin = dump_lines(self.second, rows)
            with self.assertRaises(ValueError):
                self.run_intake()

    def test_duplicate_json_key_rejected_even_with_new_hash(self):
        lines = self.second.read_text().splitlines()
        lines[0] = lines[0][:-1] + ',"ticket":"' + self.rows[0]["ticket"] + '"}'
        raw = ("\n".join(lines) + "\n").encode()
        self.second.write_bytes(raw)
        self.second_pin = hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(ValueError, "invalid or ambiguous"):
            self.run_intake()

    def test_world_readable_review_form_and_symlink_rejected(self):
        self.first.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "owner-only"):
            self.run_intake()
        self.first.chmod(0o600)
        self.first.unlink()
        self.first.symlink_to(self.second)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_intake()

    def test_trailing_whitespace_is_not_an_exact_original_refusal(self):
        # Review an unaltered raw Reader response, including trailing bytes.
        _, _, _, originals = example()
        for item in originals["items"]:
            if item["item_id"] == "q1" and item["condition"] == "no_evidence":
                item["raw_answer"] += " "
                break
        modified = self.root / "modified-refusal-handoff"
        prepare_handoff(originals, source_file_sha256="a" * 64,
                        output=modified, salt=b"\x07" * 32)
        self.handoff = modified
        self.receipt_pin = hashlib.sha256(
            (modified / "handoff-receipt.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "exact-refusal verdict"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_label_only_reader_echo_cannot_be_reviewed_as_grounded_answer(self):
        # Bad Reader text can be sent for blind review, not certified positive.
        _, _, _, originals = example()
        for item in originals["items"]:
            if item["item_id"] == "q1" and item["condition"] == "human_sufficient":
                item["raw_answer"] = "[E1]"
                break
        modified = self.root / "modified-label-only-handoff"
        prepare_handoff(originals, source_file_sha256="a" * 64,
                        output=modified, salt=b"\x07" * 32)
        self.handoff = modified
        self.receipt_pin = hashlib.sha256(
            (modified / "handoff-receipt.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "only source labels"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_output_overwrite_prevented_with_no_silent_alteration(self):
        self.run_intake()
        raw = (self.output / "reconciliation-receipt.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_intake()
        self.assertEqual((self.output / "reconciliation-receipt.json").read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
