"""Content-swap controls and saved-artifact checks; all local fixtures.

No fixture is a natural-task result or external semantic review. Official tiny
model tests are mandatory in the hosted lane, never silently skipped.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

import five_causal_experiments as c
import reader_content_swap as s
from reader_content_swap_trial import extract_verified


def records():
    rows = []
    for name, split, answer in (("A", "train", "Alpha"), ("B", "train", "Beta"),
                                ("C", "select", "Gamma"), ("D", "select", "Delta")):
        request = {"question": "Question " + name + "?", "options": [], "evidence": [
            {"id": "E_" + name, "modality": "text", "text": "source-" + name,
             "asset_sha256": None, "position": 7}]}
        rows.append({"question_id": c.digest("q-" + name), "family": "family-" + name,
                     "split": split, "request": request, "answer_body": answer})
    return rows


def cases(rows):
    out = []
    for r in rows:
        name = r["family"].removeprefix("family-")
        for condition in ("support_only", "no_evidence"):
            out.append({"question_id": "q-" + name, "family": r["family"], "split": r["split"],
                "condition": condition, "request": deepcopy(r["request"] if condition == "support_only"
                                                           else r["request"] | {"evidence": []})})
    return out


class ContentPlanTests(unittest.TestCase):
    def test_donor_selection_is_order_independent(self):
        self.assertEqual(s.build_comparisons(records()), s.build_comparisons(list(reversed(records()))))

    def test_donor_is_same_partition_and_different_family(self):
        lookup = {r["question_id"]: r for r in records()}
        for r in s.build_comparisons(records()):
            self.assertEqual(r["status"], "available")
            donor = lookup[r["donor_question_id"]]
            self.assertEqual(donor["split"], r["split"])
            self.assertNotEqual(donor["family"], r["family"])
            self.assertFalse(r["semantic_incompatibility_reviewed"])

    def test_question_and_options_never_swap(self):
        lookup = {r["question_id"]: r for r in records()}
        for r in s.build_comparisons(records()):
            for request in r["requests"].values():
                self.assertEqual(request["question"], lookup[r["question_id"]]["request"]["question"])
                self.assertEqual(request["options"], [])

    def test_equal_local_ids_hide_original_citation_names(self):
        for r in s.build_comparisons(records()):
            a, b = (r["requests"][k] for k in ("own_sources", "donor_sources"))
            self.assertEqual([e["id"] for e in a["evidence"]], ["S1"])
            self.assertEqual([e["id"] for e in b["evidence"]], ["S1"])
            self.assertEqual(a["evidence"][0]["position"], 0)
            self.assertNotEqual(a["evidence"][0]["text"], b["evidence"][0]["text"])

    def test_dates_and_source_body_are_not_rewritten(self):
        row = records()[0]
        row["request"]["evidence"][0]["text"] = 'SOURCE SESSION TIME: "2023-01-20"\nsource-A [not]'
        out, proof = s.neutral_request(row["request"])
        self.assertEqual(out["evidence"][0]["text"], row["request"]["evidence"][0]["text"])
        self.assertEqual(proof[0]["original_position"], 7)
        self.assertEqual(proof[0]["original_id"], "E_A")

    def test_no_donor_stays_in_recipient_census(self):
        result = s.build_comparisons(records()[:1])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "unavailable_donor")
        self.assertIsNone(result[0]["requests"]["donor_sources"])

    def test_source_count_must_match(self):
        rows = records()[:2]
        extra = deepcopy(rows[1]["request"]["evidence"][0]); extra["id"] = "extra"
        rows[1]["request"]["evidence"].append(extra)
        self.assertTrue(all(r["status"] == "unavailable_donor" for r in s.build_comparisons(rows)))

    def test_same_answer_and_same_content_are_not_useful_donors(self):
        for kind in ("answer", "content"):
            rows = records()[:2]
            if kind == "answer": rows[1]["answer_body"] = " ALPHA "
            else: rows[1]["request"]["evidence"][0]["text"] = rows[0]["request"]["evidence"][0]["text"]
            self.assertTrue(all(r["status"] == "unavailable_donor" for r in s.build_comparisons(rows)))

    def test_test_partition_and_duplicate_identity_rejected(self):
        rows = records(); rows[0]["split"] = "test"
        with self.assertRaises(c.Invalid): s.build_comparisons(rows)
        rows = records(); rows.append(deepcopy(rows[0]))
        with self.assertRaises(c.Invalid): s.build_comparisons(rows)

    def test_cross_partition_source_and_family_rejected(self):
        for kind in ("id", "body", "family"):
            rows = records()
            if kind == "family": rows[2]["family"] = rows[0]["family"]
            else:
                field = "id" if kind == "id" else "text"
                rows[2]["request"]["evidence"][0][field] = rows[0]["request"]["evidence"][0][field]
            with self.assertRaises(c.Invalid): s.build_comparisons(rows)

    def test_input_not_mutated_or_aliased(self):
        rows = records(); before = deepcopy(rows)
        result = s.build_comparisons(rows)
        result[0]["requests"]["own_sources"]["evidence"][0]["text"] = "changed"
        self.assertEqual(rows, before)

    def test_media_and_model_scores_rejected(self):
        rows = records(); rows[0]["request"]["evidence"][0].update(modality="image", asset_sha256="a"*64)
        with self.assertRaises(c.Invalid): s.build_comparisons(rows)
        rows = records(); rows[0]["model_score"] = 1.0
        with self.assertRaises(c.Invalid): s.build_comparisons(rows)

    def test_generation_packets_have_no_answers_or_donor_provenance(self):
        plan = s.generation_plan(cases(records()), s.build_comparisons(records()))
        self.assertEqual(len(plan), 12)
        for row in plan:
            self.assertEqual(set(row), {"question_id", "family", "split", "condition", "request"})
            self.assertEqual(set(row["request"]), {"question", "options", "evidence"})
            if row["condition"] == "empty": self.assertEqual(row["request"]["evidence"], [])

    def test_missing_support_generation_keeps_empty_and_denominator(self):
        prior = cases(records())
        for row in prior:
            if row["question_id"] == "q-D" and row["condition"] == "support_only": row["request"] = None
        plan = s.generation_plan(prior, s.build_comparisons(records()[:3]))
        group = [r for r in plan if r["question_id"] == "q-D"]
        self.assertEqual(len(group), 3)
        self.assertEqual(sum(r["request"] is None for r in group), 2)
        self.assertEqual(next(r for r in group if r["condition"] == "empty")["request"]["evidence"], [])

    def test_incomplete_or_changed_generation_pair_rejected(self):
        with self.assertRaises(c.Invalid): s.generation_plan(cases(records())[:-1], s.build_comparisons(records()))
        prior = cases(records()); prior[0]["request"]["question"] = "different"
        with self.assertRaises(c.Invalid): s.generation_plan(prior, s.build_comparisons(records()))


class InteractionTests(unittest.TestCase):
    def test_evidence_independent_preference_cancels(self):
        self.assertEqual(s.interaction([-2., -5., -2., -5.])["difference_in_differences"], 0.0)

    def test_answer_and_context_main_effects_cancel(self):
        first = s.interaction([-2., -5., -6., -3.])["difference_in_differences"]
        # Add answer offsets (0.1,0.2) and context offsets (0.3,0.4).
        second = s.interaction([-1.6, -4.5, -5.5, -2.4])["difference_in_differences"]
        self.assertAlmostEqual(first, second)

    def test_positive_contrast_is_not_a_semantic_grade(self):
        r = s.interaction([-1., -4., -5., -2.])
        self.assertGreater(r["difference_in_differences"], 0)
        self.assertIsNone(r["semantic_accuracy"])
        self.assertFalse(r["donor_is_proven_false"])

    def test_invalid_score_cannot_be_zero_filled(self):
        for values in ([-1., -2., -3.], [-1., float("nan"), -2., -3.], [-1., float("inf"), -2., -3.]):
            with self.assertRaises(c.Invalid): s.interaction(values)

    def test_failed_recipients_stay_in_summary(self):
        report = s.summarize([{"split":"train", "family":"f", "status":"failed", "audit":None}])[0]
        self.assertEqual(report["planned_recipient_pairs"], 1)
        self.assertEqual(report["scored_pairs"], 0)
        self.assertIsNone(report["mean_interaction"])
        self.assertFalse(report["donor_pairs_independent"])


class ArchiveTests(unittest.TestCase):
    def make_archive(self, root, *, extra=False, tamper=False, unsafe=False):
        path = root / "result.zip"
        member = "../bad" if unsafe else "study/report.json"
        content = b'{"fixture":true}'
        manifest = hashlib.sha256(content).hexdigest() + "  ./" + member + "\n"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr(member, b"changed" if tamper else content)
            z.writestr("SHA256SUMS", manifest)
            if extra: z.writestr("unlisted", b"x")
        return path, c.file_sha(path)

    def test_all_result_bytes_checked_before_extract(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, pin = self.make_archive(root)
            extracted, result = extract_verified(archive, root/"out", pin)
            self.assertEqual(result["verified_members"], 1)
            self.assertTrue((extracted/"study/report.json").is_file())
            self.assertFalse(result["artifact_code_executed"])

    def test_changed_member_and_unlisted_member_rejected(self):
        for option in ("tamper", "extra", "unsafe"):
            with tempfile.TemporaryDirectory() as d:
                root = Path(d); archive, pin = self.make_archive(root, **{option:True})
                with self.assertRaises(c.Invalid): extract_verified(archive, root/"out", pin)
                self.assertFalse((root/"out").exists())

    def test_external_pin_required(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, _ = self.make_archive(root)
            with self.assertRaises(c.Invalid): extract_verified(archive, root/"out", "0"*64)

    def test_existing_destination_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, pin = self.make_archive(root)
            out = root/"out"; out.mkdir(); (out/"keep").write_text("old")
            with self.assertRaises(FileExistsError): extract_verified(archive, out, pin)
            self.assertEqual((out/"keep").read_text(), "old")


class OfficialFrozenTests(unittest.TestCase):
    def setup_model(self):
        import torch
        import test_five_reader_response as fixture
        torch.set_num_threads(1)
        backend = fixture.NativeAdapterTests().backend()
        class ContextTokenizer(fixture.Tokenizer):
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                prefix = [1, 10 if "source-A" in messages[1]["content"] else 11, 3]
                if add_generation_prompt: return prefix
                return prefix + [4 + ord(x) % 64 for x in messages[-1]["content"]] + [2]
        backend.tokenizer = ContextTokenizer()
        comparison = next(r for r in s.build_comparisons(records()[:2]) if r["question_id"] == c.digest("q-A"))
        return backend, comparison

    def test_four_actual_scores_keep_frozen_weights(self):
        import five_reader_response_learning as learning
        backend, comparison = self.setup_model()
        before = learning.state_digest(backend.loaded.state_dict())
        variants = s.compile_comparison(backend.tokenizer, comparison, position_cap=128)
        with learning.count_forwards(backend.loaded.base_model) as count:
            result = s.score_comparison(backend.loaded, variants)
        self.assertEqual(count["model_calls"], 4)
        self.assertEqual(before, learning.state_digest(backend.loaded.state_dict()))
        self.assertEqual(result["parameter_updates"], 0)
        self.assertEqual(result["projection_profile"], "full-logits-v1")

    def test_scoring_rejects_trainable_candidate(self):
        backend, comparison = self.setup_model()
        variants = s.compile_comparison(backend.tokenizer, comparison, position_cap=128)
        backend.loaded.requires_grad_(True)
        with self.assertRaises(c.Invalid): s.score_comparison(backend.loaded, variants)

    def test_metadata_only_swap_and_identical_token_targets_fail(self):
        backend, comparison = self.setup_model()
        comparison["requests"]["donor_sources"] = deepcopy(comparison["requests"]["own_sources"])
        with self.assertRaises(c.Invalid): s.compile_comparison(backend.tokenizer, comparison, position_cap=128)
        backend, comparison = self.setup_model()
        comparison["answers"][1] = comparison["answers"][0]
        with self.assertRaises(c.Invalid): s.compile_comparison(backend.tokenizer, comparison, position_cap=128)


if __name__ == "__main__":
    unittest.main()
