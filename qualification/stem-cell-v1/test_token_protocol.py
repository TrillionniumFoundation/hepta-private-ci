"""Source isolation and evidence-only interventions, without model downloads."""

from collections import Counter
from dataclasses import replace
from hashlib import sha256
import unittest

from multirc_data import ReaderCase
from token_protocol import (PARAGRAPH_CAPS, build_binding_cases, make_partitions,
                            protocol_manifest, score_binding)


def natural_cases(split, paragraphs):
    return tuple(ReaderCase(str(i), "q", str(a), "What is supported?", f"Candidate {a}",
                            (f"Source {split} paragraph {i}.",), a,
                            split, sha256(f"{split}/{i}".encode()).hexdigest())
                 for i in range(paragraphs) for a in (0, 1))


class TokenProtocolTests(unittest.TestCase):
    def setUp(self):
        self.train = natural_cases("train", 100)
        self.validation = natural_cases("validation", 8)
        old_sources = sorted({case.source_hash for case in self.validation})[:2]
        self.previous = dict(partitions=dict(final=old_sources), final_case_ids=[
            case.case_id for case in self.validation if case.source_hash in old_sources])
        self.caps = dict.fromkeys(PARAGRAPH_CAPS, 1)

    def parts(self):
        return make_partitions(self.train, self.validation, self.previous, caps=self.caps)

    def test_fresh_final_excludes_exact_prior_complete_regression(self):
        parts = self.parts()
        self.assertEqual({case.case_id for case in parts["regression"]}, set(self.previous["final_case_ids"]))
        sets = {name: {case.source_hash for case in cases} for name, cases in parts.items()}
        self.assertEqual(sum(map(len, sets.values())), len(set.union(*sets.values())))
        self.assertEqual(sets["final"], {sorted({case.source_hash for case in self.validation})[2]})
        self.assertTrue(all(len(cases) == (4 if name == "regression" else 2) for name, cases in parts.items()))
        poisoned = make_partitions(tuple(replace(case, label=1-case.label) for case in self.train),
                                  tuple(replace(case, label=1-case.label) for case in self.validation),
                                  self.previous, caps=self.caps)
        self.assertEqual({k: [c.case_id for c in v] for k, v in parts.items()},
                         {k: [c.case_id for c in v] for k, v in poisoned.items()})

    def test_missing_prior_sources_or_candidates_fail_before_selection(self):
        bad = dict(self.previous, partitions=dict(final=["0" * 64]))
        with self.assertRaisesRegex(ValueError, "absent"):
            make_partitions(self.train, self.validation, bad, caps=self.caps)
        bad = dict(self.previous, final_case_ids=self.previous["final_case_ids"][:-1])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            make_partitions(self.train, self.validation, bad, caps=self.caps)
        with self.assertRaisesRegex(ValueError, "official"):
            make_partitions(self.validation, self.train, self.previous, caps=self.caps)
        with self.assertRaisesRegex(ValueError, "insufficient"):
            make_partitions(self.train, self.validation, self.previous,
                            caps=dict(self.caps, final=7))

    def test_manifest_tracks_exact_prior_membership_without_labels(self):
        parts = self.parts()
        manifest = protocol_manifest(parts, dataset_files_sha256={"train.jsonl": "a" * 64},
                                     previous_design_sha256="b" * 64)
        self.assertEqual(manifest["previous_final_source_hashes"], self.previous["partitions"]["final"])
        self.assertEqual(set(manifest["previous_final_case_ids"]), set(self.previous["final_case_ids"]))
        self.assertEqual(manifest["natural_evidence_annotations"], dict.fromkeys(parts, 0))
        overlapping = dict(parts, final=parts["regression"])
        with self.assertRaisesRegex(ValueError, "overlap"):
            protocol_manifest(overlapping, dataset_files_sha256={}, previous_design_sha256="b" * 64)

    def test_paired_worlds_require_evidence_with_fixed_query_candidate_and_bag(self):
        cases = build_binding_cases(groups=8)
        self.assertEqual(cases, build_binding_cases(groups=8))
        self.assertEqual(len(cases), 32)
        for offset in range(0, len(cases), 4):
            first, second = cases[offset], cases[offset + 2]
            self.assertEqual((first.question, first.candidate), (second.question, second.candidate))
            self.assertEqual(Counter(" ".join(first.facts).split()), Counter(" ".join(second.facts).split()))
            self.assertNotEqual((first.label, first.feature_source_hash),
                                (second.label, second.feature_source_hash))
            self.assertEqual((first.label, second.label), (1, 0))
            self.assertEqual(len(first.evidence_sentence_indices), 2)
            support = " ".join(first.facts[i-1] for i in first.evidence_sentence_indices)
            self.assertIn("belongs", support)
            self.assertIn(first.candidate.split()[1], support)
            poisoned = replace(first, label=0, evidence_sentence_indices=(999,))
            self.assertEqual(first.feature_source_hash, poisoned.feature_source_hash)

    def test_binding_splits_separate_lexical_entities_and_provenance(self):
        split_cases = {split: build_binding_cases(split, groups=8) for split in ("train", "tune", "final")}
        source_sets = [{c.source_hash for c in cases} for cases in split_cases.values()]
        self.assertEqual(sum(map(len, source_sets)), len(set.union(*source_sets)))
        questions = [{c.question for c in cases} for cases in split_cases.values()]
        self.assertEqual(sum(map(len, questions)), len(set.union(*questions)))
        self.assertTrue(all(c.source_split == "validation" for c in split_cases["final"]))
        for kwargs in (dict(groups=0), dict(groups=257), dict(split="validation"), dict(seed=1.5)):
            with self.assertRaises(ValueError):
                build_binding_cases(**kwargs)

    def test_paired_score_distinguishes_switching_from_correct_binding(self):
        cases = build_binding_cases(groups=4)
        correct = score_binding(cases, [c.label for c in cases])
        inverted = score_binding(cases, [1-c.label for c in cases])
        fixed = score_binding(cases, [1] * len(cases))
        self.assertEqual((correct["accuracy"], correct["both_worlds_correct"], correct["evidence_switch_rate"]), (1, 1, 1))
        self.assertEqual((inverted["accuracy"], inverted["both_worlds_correct"], inverted["evidence_switch_rate"]), (0, 0, 1))
        self.assertEqual((fixed["accuracy"], fixed["both_worlds_correct"], fixed["evidence_switch_rate"]), (.5, 0, 0))
        with self.assertRaisesRegex(ValueError, "complete"):
            score_binding(cases[:-1], [c.label for c in cases[:-1]])
        with self.assertRaisesRegex(ValueError, "controlled"):
            score_binding(self.train, [c.label for c in self.train])


if __name__ == "__main__":
    unittest.main()
