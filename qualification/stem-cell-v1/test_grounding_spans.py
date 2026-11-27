"""Offset fixtures only: no model, real corpus, tokenizer download or neural call."""
import copy
import hashlib
import re
import unittest

from grounding_spans import grounding_from_bank, make_grounding_targets, token_span_target


class OffsetTokenizer:
    is_fast = True

    def __call__(self, text, *, add_special_tokens, truncation, return_offsets_mapping):
        assert add_special_tokens is False and truncation is False and return_offsets_mapping is True
        ids, offsets = [], []
        for match in re.finditer(r"\s*[A-Za-z]+|[.?]", text):
            start, end = match.span()
            value = match.group()
            pieces = [(start, end)]
            if value.strip() in ("Cleo", "Esme"):
                split = start + len(value) - 2
                pieces = [(start, split), (split, end)]
            for left, right in pieces:
                ids.append(int(hashlib.sha256(text[left:right].encode()).hexdigest()[:8], 16))
                offsets.append((left, right))
        return dict(input_ids=ids, offset_mapping=offsets)


def source():
    facts = ["The bead belongs to Esme.", "The shell belongs to Cleo.",
        "Cleo stores all their possessions in the silver box.",
        "Esme stores all their possessions in the golden box."]
    return dict(facts=facts, source_split="train", paragraph_id="binding-v4/train/41/0/world-0",
        question_id="0", answer_id="0", question="Where is the shell stored?", candidate="The silver box.",
        sentence_ids=[1, 2, 3, 4], source_hash=hashlib.sha256("\n".join(facts).encode()).hexdigest(),
        segmentation="synthetic-ownership-storage-v1", label=1, evidence_sentence_indices=[2, 3])


def cache(cases, tokenizer):
    return {text: tokenizer(text, add_special_tokens=False, truncation=False, return_offsets_mapping=True)["input_ids"]
            for case in cases for text in (*case["facts"], case["question"], case["candidate"])}


class GroundingSpansTests(unittest.TestCase):
    def setUp(self):
        self.case, self.tokenizer = source(), OffsetTokenizer()
        self.tokens = cache([self.case], self.tokenizer)

    def test_byte_prefix_splits_are_covered_with_uniform_span_attention(self):
        text = self.case["facts"][1]
        span = (text.index("Cleo"), text.index("Cleo") + 4)
        target, indices = token_span_target(text, span, self.tokens[text], self.tokenizer)
        self.assertEqual(len(indices), 2)
        self.assertEqual([target[index] for index in indices], [.5, .5])
        self.assertEqual(sum(target), 1.)
        other = self.case["facts"][2]
        _, start_indices = token_span_target(other, (0, 4), self.tokens[other], self.tokenizer)
        self.assertNotEqual([self.tokens[text][i] for i in indices], [self.tokens[other][i] for i in start_indices])
        targets = make_grounding_targets([self.case], self.tokens, self.tokenizer)
        self.assertEqual(targets["mention_entity_keys"][0][1][1], "person:Cleo")
        self.assertEqual(targets["mention_entity_keys"][0][2][0], "person:Cleo")
        self.assertNotEqual(targets["mention_context_keys"][0][1][1], targets["mention_context_keys"][0][2][0])

    def test_all_fact_roles_query_and_candidate_have_exact_normalized_targets(self):
        result = make_grounding_targets([self.case], self.tokens, self.tokenizer)
        self.assertEqual(result["aux_available"], [True])
        self.assertEqual(result["mention_entity_keys"][0], [["object:bead", "person:Esme"],
            ["object:shell", "person:Cleo"], ["person:Cleo", "color:silver"], ["person:Esme", "color:golden"]])
        self.assertEqual(result["question_entity_keys"], ["object:shell"])
        self.assertEqual(result["candidate_entity_keys"], ["color:silver"])
        for fact in result["fact_attention_targets"][0]:
            self.assertEqual([sum(slot) for slot in fact], [1., 1.])
        self.assertEqual(sum(result["question_attention_targets"][0]), 1.)
        self.assertEqual(sum(result["candidate_attention_targets"][0]), 1.)
        self.assertEqual(len(result["span_records"]), 10)

    def test_labels_and_support_are_never_read_and_duplicate_contexts_are_stable(self):
        class Guarded(dict):
            def __getitem__(self, key):
                if key in ("label", "evidence_sentence_indices"):
                    raise AssertionError("forbidden outcome/support access")
                return super().__getitem__(key)
        changed = copy.deepcopy(self.case)
        changed["answer_id"], changed["label"], changed["evidence_sentence_indices"] = "1", 0, [1, 4]
        result = make_grounding_targets([Guarded(self.case), Guarded(changed)], self.tokens, self.tokenizer)
        self.assertEqual(result["fact_attention_targets"][0], result["fact_attention_targets"][1])
        self.assertEqual(result["mention_context_keys"][0], result["mention_context_keys"][1])
        self.assertNotIn("labels", result)
        self.assertFalse(result["answer_labels_read"])
        self.assertFalse(result["support_annotations_read"])

    def test_mixed_natural_chunk_geometry_is_zero_and_unavailable(self):
        natural = copy.deepcopy(self.case)
        natural.update(segmentation="source-lines", paragraph_id="natural", facts=[" ".join(["Long"] * 75)])
        tokens = cache([self.case, natural], self.tokenizer)
        result = make_grounding_targets([self.case, natural], tokens, self.tokenizer)
        self.assertEqual(result["aux_available"], [True, False])
        self.assertEqual(result["target_shapes"]["fact"], [2, 4, 2, 62])
        self.assertEqual(sum(sum(sum(slot) for slot in fact) for fact in result["fact_attention_targets"][1]), 0.)
        self.assertFalse(any(any(fact) for fact in result["fact_supervision_mask"][1]))
        self.assertEqual(result["mention_entity_keys"][1], [[None, None]] * 4)
        self.assertEqual(sum(result["question_attention_targets"][1]), 0.)
        self.assertEqual(sum(result["candidate_attention_targets"][1]), 0.)

    def test_bad_grammar_partitions_cache_ids_and_alignment_are_rejected(self):
        malformed = copy.deepcopy(self.case)
        malformed["facts"][0] = "Unsupported owner sentence."
        malformed["source_hash"] = hashlib.sha256("\n".join(malformed["facts"]).encode()).hexdigest()
        with self.assertRaisesRegex(ValueError, "grammar"):
            make_grounding_targets([malformed], cache([malformed], self.tokenizer), self.tokenizer)
        for updates in (dict(source_split="validation"), dict(paragraph_id="binding-v4/tune/41/0/world-0")):
            case = dict(self.case, **updates)
            with self.assertRaises(ValueError):
                make_grounding_targets([case], self.tokens, self.tokenizer)
        tokens = copy.deepcopy(self.tokens)
        tokens[self.case["facts"][0]][0] += 1
        with self.assertRaisesRegex(ValueError, "cached"):
            make_grounding_targets([self.case], tokens, self.tokenizer)
        with self.assertRaisesRegex(ValueError, "one short fact"):
            make_grounding_targets([self.case], self.tokens, self.tokenizer, payload_tokens=3)
        text = "The shell"
        class Merged(OffsetTokenizer):
            def __call__(self, *args, **kwargs):
                return dict(input_ids=[1], offset_mapping=[(0, 9)])
        with self.assertRaisesRegex(ValueError, "ambiguous"):
            token_span_target(text, (4, 9), [1], Merged())
        slow = OffsetTokenizer()
        slow.is_fast = False
        with self.assertRaisesRegex(ValueError, "fast tokenizer"):
            token_span_target("shell", (0, 5), [1], slow)

    def test_explicit_frozen_diagnostic_role_is_separate_and_exposes_auditable_offsets(self):
        heldout = dict(self.case, source_split="validation",
                       paragraph_id="binding-v5/fresh_vocabulary/2901/0/world-0")
        with self.assertRaises(ValueError):
            make_grounding_targets([heldout], self.tokens, self.tokenizer)
        result = make_grounding_targets([heldout], self.tokens, self.tokenizer, role="frozen_diagnostic")
        self.assertEqual(result["role"], "frozen_diagnostic")
        self.assertFalse(result["trainer_only"])
        self.assertTrue(result["caller_must_enforce_all_models_frozen_and_raw_predictions_first"])
        self.assertFalse(result["annotations_authorized_as_model_inputs"])
        for record in result["public_token_alignments"].values():
            self.assertEqual(record["cached_input_ids"], record["tokenizer_input_ids"])
            self.assertEqual(len(record["cached_input_ids"]), len(record["offset_mapping"]))
        with self.assertRaises(ValueError):
            make_grounding_targets([heldout], self.tokens, self.tokenizer, role=True)

    def test_thin_bank_wrapper_uses_the_same_cached_ids_and_tokenizer(self):
        from types import SimpleNamespace
        bank = SimpleNamespace(tokens=self.tokens, payload_tokens=62, encoder=SimpleNamespace(tokenizer=self.tokenizer))
        self.assertEqual(grounding_from_bank([self.case], bank),
                         make_grounding_targets([self.case], self.tokens, self.tokenizer))


if __name__ == "__main__":
    unittest.main()
