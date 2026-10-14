"""Synthetic fixture tests: no real private review or reviewer approval."""

import copy
import hashlib
import json
from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from reader_review_handoff import prepare_handoff
from reader_review_intake import reconcile_handoff
from reader_originals_attestation import canonical_sha
from test_reader_originals_attestation import example


def dump_lines(path, rows):
    raw = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
    ).encode()
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
        prepare_handoff(
            originals,
            source_file_sha256="a" * 64,
            output=self.handoff,
            salt=b"\x07" * 32,
        )
        self.receipt_pin = hashlib.sha256(
            (self.handoff / "handoff-receipt.json").read_bytes()
        ).hexdigest()
        operator = {
            r["ticket"]: r
            for r in read_lines(self.handoff / "operator-private-map.jsonl")
        }
        rows = read_lines(self.handoff / "reviewer-blank-form.jsonl")
        for row in rows:
            condition = operator[row["ticket"]]["condition"]
            row["grounded_and_cited"] = condition == "human_sufficient"
            row["exact_refusal"] = condition in (
                "no_evidence",
                "critical_premise_removed",
            )
            row["cited_semantically_supported"] = condition == "human_sufficient"
        self.first = self.root / "review-one.jsonl"
        self.second = self.root / "review-two.jsonl"
        self.first_pin = dump_lines(self.first, rows)
        self.second_pin = dump_lines(self.second, copy.deepcopy(rows))
        self.rows = rows
        self.map = operator
        self.output = self.root / "review-comparison"

    def run_intake(
        self,
        *,
        first_pin=None,
        second_pin=None,
        receipt_pin=None,
        first_id="reviewer-a",
        second_id="reviewer-b",
        out=None,
    ):
        return reconcile_handoff(
            self.handoff,
            self.first,
            self.second,
            out or self.output,
            receipt_pin=receipt_pin or self.receipt_pin,
            first_pin=first_pin or self.first_pin,
            second_pin=second_pin or self.second_pin,
            first_id=first_id,
            second_id=second_id,
        )

    def test_all_agreement_does_not_sign_or_approve(self):
        result = self.run_intake()
        self.assertEqual(
            (
                result["positions"],
                result["agreed"],
                result["disputed"],
                result["incomplete"],
            ),
            (8, 8, 0, 0),
        )
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
        for rows in (
            self.rows[:-1],
            self.rows + self.rows[:1],
            [
                dict(r, ticket="a" * 32) if i == 0 else r
                for i, r in enumerate(self.rows)
            ],
        ):
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

    def test_positive_grounded_claim_requires_explicit_source_support(self):
        # A positive claim with unknown citation adequacy is NOT review-complete.
        for verdict in (None, False):
            with self.subTest(cited_support=verdict):
                rows = copy.deepcopy(self.rows)
                row = next(
                    row
                    for row in rows
                    if self.map[row["ticket"]]["condition"] == "human_sufficient"
                )
                row["cited_semantically_supported"] = verdict
                self.second_pin = dump_lines(self.second, rows)
                with self.assertRaisesRegex(
                    ValueError, "affirmative cited-source support"
                ):
                    self.run_intake()
                self.assertFalse(self.output.exists())

    def test_positive_grounded_claim_requires_explicit_non_refusal(self):
        rows = copy.deepcopy(self.rows)
        row = next(
            row
            for row in rows
            if self.map[row["ticket"]]["condition"] == "human_sufficient"
        )
        row["exact_refusal"] = None
        self.second_pin = dump_lines(self.second, rows)
        with self.assertRaisesRegex(ValueError, "explicit non-refusal review"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_unfinished_negative_claim_remains_incomplete_not_approved(self):
        # Unknown source support on a NON-positive answer is a legitimate
        # unfinished review. It must not be converted into agreement.
        rows = copy.deepcopy(self.rows)
        row = next(
            row
            for row in rows
            if self.map[row["ticket"]]["condition"] == "ordinary_retrieval"
        )
        row["cited_semantically_supported"] = None
        self.second_pin = dump_lines(self.second, rows)
        result = self.run_intake()
        self.assertEqual((result["incomplete"], result["agreed"]), (1, 7))
        self.assertFalse(result["review_approval_produced"])
        self.assertFalse(result["production_accepted"])

    def test_invalid_boolean_and_fake_signature_fields_rejected(self):
        for tamper in ({"grounded_and_cited": 1}, {"signature_hex": "a" * 128}):
            rows = copy.deepcopy(self.rows)
            rows[0].update(tamper)
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
        prepare_handoff(
            originals, source_file_sha256="a" * 64, output=modified, salt=b"\x07" * 32
        )
        self.handoff = modified
        self.receipt_pin = hashlib.sha256(
            (modified / "handoff-receipt.json").read_bytes()
        ).hexdigest()
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
        prepare_handoff(
            originals, source_file_sha256="a" * 64, output=modified, salt=b"\x07" * 32
        )
        self.handoff = modified
        self.receipt_pin = hashlib.sha256(
            (modified / "handoff-receipt.json").read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(ValueError, "only source labels"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def _rewrite_pinned_reviewer_view(self, change):
        # Simulate an operator who re-pinned a malformed/private handoff.
        # All raw files and ticket/case digests remain structurally pinned;
        # merely checking the new SHA256SUMS would otherwise accept it.
        questions = self.handoff / "review-questions.jsonl"
        rows = read_lines(questions)
        change(rows)
        new_pin = dump_lines(questions, rows)
        receipt = self.handoff / "handoff-receipt.json"
        body = json.loads(receipt.read_text())
        body["written_file_sha256"]["review-questions.jsonl"] = new_pin
        receipt.write_text(
            json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
        )
        receipt.chmod(0o600)
        self.receipt_pin = hashlib.sha256(receipt.read_bytes()).hexdigest()

    def _rewrite_pinned_reviewer_evidence(self, qid, condition, edit):
        # A fully recomputed private handoff pin can still be internally wrong.
        # Alter BOTH ticket view and operator provenance, then re-pin both.
        questions = self.handoff / "review-questions.jsonl"
        mappings = self.handoff / "operator-private-map.jsonl"
        views = read_lines(questions)
        links = read_lines(mappings)
        link = next(
            r for r in links if r["item_id"] == qid and r["condition"] == condition
        )
        view = next(r for r in views if r["ticket"] == link["ticket"])
        edit(view["evidence"])
        link["exact_provenance"]["delivered_source_sha256"] = [
            e["source_fingerprint"] for e in view["evidence"]
        ]
        receipt_path = self.handoff / "handoff-receipt.json"
        receipt = json.loads(receipt_path.read_text())
        receipt["written_file_sha256"]["review-questions.jsonl"] = dump_lines(
            questions, views
        )
        receipt["written_file_sha256"]["operator-private-map.jsonl"] = dump_lines(
            mappings, links
        )
        receipt_path.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        )
        receipt_path.chmod(0o600)
        self.receipt_pin = hashlib.sha256(receipt_path.read_bytes()).hexdigest()

    def test_re_pinned_no_evidence_cannot_display_a_source(self):
        views = read_lines(self.handoff / "review-questions.jsonl")
        ordinary = next(
            r
            for r in views
            if self.map[r["ticket"]]["item_id"] == "q1"
            and self.map[r["ticket"]]["condition"] == "ordinary_retrieval"
        )
        source = copy.deepcopy(ordinary["evidence"][0])
        self._rewrite_pinned_reviewer_evidence(
            "q1", "no_evidence", lambda evidence: evidence.append(source)
        )
        with self.assertRaisesRegex(
            ValueError, "evidence intervention not strictly nested"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_re_pinned_removed_condition_cannot_introduce_new_source(self):
        novel = dict(
            label="E2",
            excerpt="Synthetic substituted premise.",
            observed_at="2026-01-01T00:00:00+00:00",
            source_fingerprint="f" * 64,
        )
        self._rewrite_pinned_reviewer_evidence(
            "q1", "critical_premise_removed", lambda evidence: evidence.append(novel)
        )
        with self.assertRaisesRegex(
            ValueError, "evidence intervention not strictly nested"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_re_pinned_same_evidence_fingerprint_twice_is_invalid(self):
        def duplicate(evidence):
            evidence[1] = dict(evidence[0], label="E2")

        self._rewrite_pinned_reviewer_evidence("q1", "human_sufficient", duplicate)
        with self.assertRaisesRegex(
            ValueError, "duplicate reviewer-visible source fingerprint"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_reviewer_visible_question_cannot_change_across_blinded_conditions(self):
        def change(rows):
            row = next(r for r in rows if self.map[r["ticket"]]["item_id"] == "q1")
            row["question"] += " Unrelated altered request."

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(
            ValueError, "question changed across blinded conditions"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_reviewer_visible_question_timestamp_cannot_drift(self):
        # Keep the edited instant AFTER the synthetic 2026-01-01 sources.
        # This isolates cross-condition question drift from the independent
        # fail-closed future-source check.
        def change(rows):
            row = next(r for r in rows if self.map[r["ticket"]]["item_id"] == "q1")
            row["question_observed_at"] = "2026-01-02T01:00:00+00:00"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(
            ValueError, "question changed across blinded conditions"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_re_pinned_question_preceding_its_sources_fails_closed(self):
        # Move every visible q1 question timestamp together, eliminating
        # cross-condition drift; this must still fail on source-time order.
        def change(rows):
            for row in rows:
                if self.map[row["ticket"]]["item_id"] == "q1":
                    row["question_observed_at"] = "2025-12-31T23:00:00+00:00"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(ValueError, "future reviewer-visible source time"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_same_source_fingerprint_cannot_show_conflicting_original_excerpt(self):
        # Source q1-b occurs in three conditions. Tamper just the review view,
        # while retaining its operator-map/source-fingerprint binding.
        def change(rows):
            ordinary = next(
                r
                for r in rows
                if self.map[r["ticket"]]["item_id"] == "q1"
                and self.map[r["ticket"]]["condition"] == "ordinary_retrieval"
            )
            ordinary["evidence"][0]["excerpt"] += " fabricated reviewer-visible fact"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(
            ValueError, "same source fingerprint displays inconsistent evidence"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_reviewer_visible_question_and_excerpts_require_bounded_strings(self):
        for edit in (
            lambda r: r.update(question={"not": "text"}),
            lambda r: r["evidence"][0].update(excerpt=""),
        ):
            with self.subTest(edit=edit):
                # The original fixture is restored between subcases so the
                # receipt pin does not hide a later type-check failure.
                _, _, _, originals = example()
                other = self.root / (
                    "handoff-" + str(len(list(self.root.glob("handoff-*"))))
                )
                prepare_handoff(
                    originals,
                    source_file_sha256="a" * 64,
                    output=other,
                    salt=b"\x07" * 32,
                )
                self.handoff = other
                self.receipt_pin = hashlib.sha256(
                    (other / "handoff-receipt.json").read_bytes()
                ).hexdigest()

                def change(rows):
                    row = next(r for r in rows if r["evidence"])
                    edit(row)

                self._rewrite_pinned_reviewer_view(change)
                with self.assertRaisesRegex(
                    ValueError, "invalid reviewer-visible (question|source excerpt)"
                ):
                    self.run_intake()
                self.assertFalse(self.output.exists())

    def test_re_pinned_future_source_time_is_rejected_before_review(self):
        # A hash-pinned handoff is not allowed to display future observations.
        # The attacker updates both the question JSONL pin and receipt pin.
        def change(rows):
            row = next(r for r in rows if r["evidence"])
            row["evidence"][0]["observed_at"] = "2099-01-01T00:00:00+00:00"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(ValueError, "future reviewer-visible source time"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_re_pinned_source_time_must_include_a_time_zone(self):
        def change(rows):
            row = next(r for r in rows if r["evidence"])
            row["evidence"][0]["observed_at"] = "2026-01-01T00:00:00"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(ValueError, "invalid reviewer-visible source time"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_re_pinned_question_time_must_be_offset_aware_for_every_condition(self):
        # Alter all four views so the old across-condition equality still holds.
        def change(rows):
            for row in rows:
                row["question_observed_at"] = "2026-01-02T00:00:00"

        self._rewrite_pinned_reviewer_view(change)
        with self.assertRaisesRegex(
            ValueError, "invalid reviewer-visible question time"
        ):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_review_time_checks_compare_offsets_as_real_instants(self):
        # This is a NEW SYNTHETIC original, not a tampered review view:
        # 01:00+02:00 is 23:00Z, before the original 00:00Z question.
        _, _, _, originals = example()
        for item in originals["items"]:
            for source in item["delivered_sources"]:
                source["observed_at"] = "2026-01-02T01:00:00+02:00"
        valid = self.root / "offset-time-original-handoff"
        prepare_handoff(
            originals, source_file_sha256="a" * 64, output=valid, salt=b"\x07" * 32
        )
        self.handoff = valid
        self.receipt_pin = hashlib.sha256(
            (valid / "handoff-receipt.json").read_bytes()
        ).hexdigest()
        result = self.run_intake()
        self.assertEqual(result["agreed"], 8)
        self.assertFalse(result["review_approval_produced"])

    def test_output_overwrite_prevented_with_no_silent_alteration(self):
        self.run_intake()
        raw = (self.output / "reconciliation-receipt.json").read_bytes()
        with self.assertRaises(FileExistsError):
            self.run_intake()
        self.assertEqual(
            (self.output / "reconciliation-receipt.json").read_bytes(), raw
        )

    def test_hardlinked_review_form_paths_are_not_two_independent_files(self):
        # Distinct file *names* and operator-claimed identities do not prove
        # independently delivered files when both paths share one inode.
        self.second.unlink()
        self.second.hardlink_to(self.first)
        self.second_pin = self.first_pin
        with self.assertRaisesRegex(ValueError, "one filesystem inode"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_fully_repinned_padded_citation_cannot_alias_e1(self):
        # Tamper BOTH the reviewer-visible view and private operator map,
        # including the internal receipt hashes. The original signed-source
        # protocol already rejects [E01]; offline intake must reject it too.
        questions = self.handoff / "review-questions.jsonl"
        maps = self.handoff / "operator-private-map.jsonl"
        views, links = read_lines(questions), read_lines(maps)
        link = next(
            row
            for row in links
            if row["item_id"] == "q1" and row["condition"] == "human_sufficient"
        )
        view = next(row for row in views if row["ticket"] == link["ticket"])
        view["raw_reader_answer"] = "synthetic answer [E01]"
        view["cited_labels"] = ["E01"]
        link["exact_provenance"]["raw_answer_sha256"] = canonical_sha(
            view["raw_reader_answer"]
        )
        link["exact_provenance"]["cited_source_sha256"] = [
            view["evidence"][0]["source_fingerprint"]
        ]
        receipt_file = self.handoff / "handoff-receipt.json"
        receipt = json.loads(receipt_file.read_text())
        receipt["written_file_sha256"]["review-questions.jsonl"] = dump_lines(
            questions, views
        )
        receipt["written_file_sha256"]["operator-private-map.jsonl"] = dump_lines(
            maps, links
        )
        receipt_file.write_text(
            json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
        )
        receipt_file.chmod(0o600)
        self.receipt_pin = hashlib.sha256(receipt_file.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "noncanonical reviewer-visible"):
            self.run_intake()
        self.assertFalse(self.output.exists())

    def test_reviewer_form_file_symlink_swap_cannot_pass_pinned_input(self):
        # Same content and out-of-band hash are insufficient if the input
        # inode is swapped for a symlink after the preliminary path check.
        matching = self.root / "same-raw-review.jsonl"
        matching.write_bytes(self.first.read_bytes())
        matching.chmod(0o600)
        real_open, swaps = os.open, []

        def swap_file(name, flags, **kwargs):
            if name == self.first.name and "dir_fd" in kwargs and not swaps:
                self.first.unlink()
                self.first.symlink_to(matching)
                swaps.append(True)
            return real_open(name, flags, **kwargs)

        with patch("reader_originals_attestation.os.open", side_effect=swap_file):
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.run_intake()
        self.assertEqual(swaps, [True])
        self.assertFalse(self.output.exists())

    def test_reviewer_permission_swap_after_precheck_is_rejected(self):
        # Owner-only permissions are checked on the OPEN descriptor, not
        # the path metadata obtained before the open operation.
        real_open, swaps = os.open, []

        def change_mode(name, flags, **kwargs):
            if name == self.first.name and "dir_fd" in kwargs and not swaps:
                self.first.chmod(0o644)
                swaps.append(True)
            return real_open(name, flags, **kwargs)

        with patch("reader_originals_attestation.os.open", side_effect=change_mode):
            with self.assertRaisesRegex(ValueError, "owner-only"):
                self.run_intake()
        self.assertEqual(swaps, [True])
        self.assertFalse(self.output.exists())

    def test_output_directory_swapped_during_write_stays_inode_bound(self):
        # The comparison and receipt must never follow a replacement alias.
        relocated = self.root / "original-private-comparison"
        decoy = self.root / "untrusted-output"
        decoy.mkdir()
        real_open, swapped = os.open, []

        def swap_at_first_write(name, flags, *args, **kwargs):
            if (
                name == "operator-private-comparison.jsonl"
                and "dir_fd" in kwargs
                and not swapped
            ):
                self.output.rename(relocated)
                self.output.symlink_to(decoy, target_is_directory=True)
                swapped.append(True)
            return real_open(name, flags, *args, **kwargs)

        with patch("reader_review_handoff.os.open", side_effect=swap_at_first_write):
            result = self.run_intake()
        self.assertEqual(swapped, [True])
        self.assertFalse(result["production_accepted"])
        self.assertFalse(list(decoy.iterdir()))
        for filename in (
            "operator-private-comparison.jsonl",
            "reconciliation-receipt.json",
        ):
            file = relocated / filename
            self.assertTrue(file.is_file())
            self.assertEqual(file.stat().st_mode & 0o077, 0)

    def test_output_directory_swap_before_fd_open_rejected(self):
        relocated = self.root / "original-private-comparison"
        decoy = self.root / "untrusted-output"
        decoy.mkdir()
        real_open, swapped = os.open, []

        def swap_at_fd_open(name, flags, *args, **kwargs):
            if (
                name == self.output.name
                and "dir_fd" in kwargs
                and flags & os.O_DIRECTORY
                and not swapped
            ):
                self.output.rename(relocated)
                self.output.symlink_to(decoy, target_is_directory=True)
                swapped.append(True)
            return real_open(name, flags, *args, **kwargs)

        with patch("reader_review_handoff.os.open", side_effect=swap_at_fd_open):
            with self.assertRaisesRegex(ValueError, "symlink"):
                self.run_intake()
        self.assertEqual(swapped, [True])
        self.assertFalse(list(decoy.iterdir()))
        self.assertFalse(list(relocated.iterdir()))


if __name__ == "__main__":
    unittest.main()
