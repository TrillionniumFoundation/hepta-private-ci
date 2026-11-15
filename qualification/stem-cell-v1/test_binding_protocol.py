"""Controlled V5 source isolation, independent truth and retention qualification."""

from dataclasses import replace
from hashlib import sha256
import math
import random
import unittest

from binding_protocol import (binding_manifest, build_binding_protocol, retention_gate,
                              score_binding_probabilities, semantic_key, verify_binding_cases,
                              verify_binding_protocol, warmup_gate)
from token_protocol import build_binding_cases


class BindingProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = build_binding_protocol()

    def test_reuses_exact_old_train_and_internal_tune_without_global_rng_dependence(self):
        self.assertEqual(self.parts["reader_train"], build_binding_cases("train", groups=32, seed=41))
        self.assertEqual(self.parts["internal_tune"], build_binding_cases("tune", groups=16, seed=41))
        random.seed(9876)
        self.assertEqual(self.parts, build_binding_protocol())
        changed = build_binding_protocol(seed=47)
        self.assertEqual(changed["reader_train"], self.parts["reader_train"])
        self.assertNotEqual(changed["fresh_combinations"], self.parts["fresh_combinations"])
        for seed in (-1, True, 1.5, 2**32):
            with self.assertRaisesRegex(ValueError, "seed"):
                build_binding_protocol(seed=seed)

    def test_complete_roles_are_disjoint_in_semantics_and_source_bytes(self):
        reports = verify_binding_protocol(self.parts)
        keys, sources = set(), set()
        for role, cases in self.parts.items():
            expected = 64 if role == "internal_tune" else 128
            self.assertEqual((reports[role]["cases"], reports[role]["groups"]), (expected, expected // 4))
            current = {semantic_key(c) for c in cases}
            self.assertFalse(keys & current)
            keys.update(current)
            current_sources = {c.source_hash for c in cases}
            self.assertFalse(sources & current_sources)
            sources.update(current_sources)
            self.assertTrue(all(c.source_hash == sha256("\n".join(c.facts).encode()).hexdigest() for c in cases))
        old_final = build_binding_cases("final", groups=32, seed=41)
        self.assertFalse(keys & {semantic_key(c) for c in old_final})

    def test_fresh_vocabulary_entities_exclude_all_old_vocabularies(self):
        def entities(cases):
            people, objects = set(), set()
            for case in cases:
                for sentence in case.facts:
                    words = sentence.split()
                    if words[0] == "The":
                        objects.add(words[1])
                        people.add(words[-1].rstrip("."))
            return people, objects

        old = tuple(c for split in ("train", "tune", "final") for c in build_binding_cases(split))
        old_people, old_objects = entities(old)
        fresh_people, fresh_objects = entities(self.parts["fresh_vocabulary"])
        self.assertFalse(old_people & fresh_people)
        self.assertFalse(old_objects & fresh_objects)
        train_people, train_objects = entities(self.parts["reader_train"])
        for role in ("verifier_fit", "fresh_combinations"):
            people, objects = entities(self.parts[role])
            self.assertLessEqual(people, train_people)
            self.assertLessEqual(objects, train_objects)

    def test_semantic_key_ignores_sentence_order_ids_and_training_metadata(self):
        original = self.parts["reader_train"][0]
        reordered = replace(original, facts=tuple("  " + f + "  " for f in original.facts[::-1]),
                            label=1-original.label, paragraph_id="different", evidence_sentence_indices=(99,))
        self.assertEqual(semantic_key(original), semantic_key(reordered))
        self.assertNotEqual(original.feature_source_hash, reordered.feature_source_hash)
        metadata_only = replace(original, label=1-original.label, evidence_sentence_indices=(99,))
        self.assertEqual(original.feature_source_hash, metadata_only.feature_source_hash)

    def test_independent_grammar_rejects_poisoned_labels_support_and_source(self):
        cases = self.parts["fresh_combinations"]
        for poisoned in (replace(cases[0], label=1-cases[0].label),
                         replace(cases[0], evidence_sentence_indices=(1,)),
                         replace(cases[0], source_hash="0" * 64),
                         replace(cases[0], facts=("Unsupported sentence.", *cases[0].facts[1:]))):
            with self.assertRaises(ValueError):
                verify_binding_cases((poisoned, *cases[1:]))
        with self.assertRaisesRegex(ValueError, "complete"):
            verify_binding_cases((cases[0], cases[1], cases[4], cases[5]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            verify_binding_cases((*cases[:4], *cases[:4]))

    def test_protocol_rejects_old_semantic_reuse_and_source_role_drift(self):
        replaced = dict(self.parts, fresh_combinations=(*self.parts["reader_train"][:4],
                                                      *self.parts["fresh_combinations"][4:]))
        with self.assertRaisesRegex(ValueError, "disjoint"):
            verify_binding_protocol(replaced)
        changed = tuple(replace(c, source_split="train") for c in self.parts["fresh_combinations"])
        with self.assertRaisesRegex(ValueError, "source role"):
            verify_binding_protocol(dict(self.parts, fresh_combinations=changed))
        with self.assertRaisesRegex(ValueError, "byte-for-byte"):
            verify_binding_protocol(dict(self.parts, reader_train=self.parts["reader_train"][::-1]))
        with self.assertRaisesRegex(ValueError, "roles"):
            verify_binding_protocol({k: v for k, v in self.parts.items() if k != "verifier_fit"})

    def test_equal_word_bags_do_not_allow_swapping_storage_instead_of_ownership(self):
        cases = list(self.parts["fresh_combinations"][:4])
        first, second = cases[0], cases[2]
        old_storage = [f for f in first.facts if "stores all" in f]
        names = [sentence.split()[0] for sentence in old_storage]
        substitutions = dict(zip(names, names[::-1]))
        changed = tuple(substitutions[f.split()[0]] + f[len(f.split()[0]):]
                        if "stores all" in f else f for f in first.facts)
        # This also flips truth with an identical word bag, but violates the
        # registered intervention: only ownership assignments may change.
        for offset in (2, 3):
            label = second.label if offset == 2 else cases[3].label
            # Derive support through the actual owner of the queried object.
            obj = first.question.split()[3]
            owner = next(f.split()[-1].rstrip(".") for f in changed if f.startswith("The " + obj + " "))
            support = tuple(sorted((next(i for i, f in enumerate(changed, 1) if f.startswith("The " + obj + " ")),
                                    next(i for i, f in enumerate(changed, 1) if f.startswith(owner + " stores ")))))
            cases[offset] = replace(cases[offset], facts=changed, label=label, evidence_sentence_indices=support,
                                    source_hash=sha256("\n".join(changed).encode()).hexdigest())
        with self.assertRaisesRegex(ValueError, "swap ownership"):
            verify_binding_cases(cases)

    def test_metrics_distinguish_truth_binding_from_wrong_world_switches(self):
        cases = self.parts["reader_train"]
        good = [.99 if c.label else .01 for c in cases]
        metrics = score_binding_probabilities(cases, good)
        self.assertAlmostEqual(metrics["probability_CE"], -math.log(.99))
        self.assertEqual((metrics["accuracy"], metrics["both_worlds_correct"], metrics["all_four_correct"]), (1., 1., 1.))
        self.assertAlmostEqual(metrics["mean_truth_signed_world_probability_gap"], .98)
        inverse = score_binding_probabilities(cases, [1-p for p in good])
        self.assertEqual((inverse["both_worlds_correct"], inverse["evidence_switch_rate"]), (0., 1.))
        self.assertAlmostEqual(inverse["mean_truth_signed_world_probability_gap"], -.98)
        ties = score_binding_probabilities(cases, [.5] * len(cases))
        self.assertEqual((ties["accuracy"], ties["both_worlds_correct"], ties["evidence_switch_rate"]), (.5, 0., 0.))
        self.assertEqual(metrics, score_binding_probabilities(cases[::-1], good[::-1]))
        for probabilities in (good[:-1], [math.nan] * len(cases), [True] * len(cases), [1.1] * len(cases)):
            with self.assertRaisesRegex(ValueError, "probability"):
                score_binding_probabilities(cases, probabilities)

    def test_gates_require_full_fit_and_detect_paired_retention_loss(self):
        cases = self.parts["reader_train"]
        good = [.99 if c.label else .01 for c in cases]
        baseline = score_binding_probabilities(cases, good)
        self.assertTrue(warmup_gate(baseline)["passed"])
        self.assertTrue(retention_gate(baseline, baseline)["passed"])
        uncertain = score_binding_probabilities(cases, [.6 if c.label else .4 for c in cases])
        self.assertFalse(warmup_gate(uncertain)["passed"])
        for changed_groups, passed in ((3, True), (4, False)):
            changed = list(good)
            for index in range(changed_groups):
                changed[index * 4] = 1 - changed[index * 4]
            metrics = score_binding_probabilities(cases, changed)
            self.assertEqual(retention_gate(metrics, baseline)["passed"], passed)
            self.assertFalse(warmup_gate(metrics)["passed"])
        with self.assertRaisesRegex(ValueError, "reference"):
            retention_gate(baseline, uncertain)
        with self.assertRaisesRegex(ValueError, "128-case"):
            warmup_gate(score_binding_probabilities(cases[:4], good[:4]))

    def test_manifest_binds_source_bytes_membership_and_declared_scope(self):
        inventories = dict(dataset_files_sha256={"dataset.zip": "a" * 64},
                           source_files_sha256={"train.jsonl": "b" * 64},
                           code_files_sha256={"binding_protocol.py": "c" * 64})
        manifest = binding_manifest(self.parts, **inventories)
        self.assertEqual(manifest["roles"]["reader_train"]["case_ids"], [c.case_id for c in self.parts["reader_train"]])
        self.assertFalse(manifest["official_validation_loaded"])
        self.assertFalse(manifest["annotations_enter_model"])
        self.assertFalse(manifest["fresh_metrics_select_models"])
        self.assertEqual(manifest["fresh_roles"], ["fresh_combinations", "fresh_vocabulary"])
        self.assertEqual(manifest["dataset_files_sha256"], inventories["dataset_files_sha256"])
        reserved = manifest["roles"]["verifier_fit"]
        self.assertEqual(reserved["usage"], "reserved_unused")
        self.assertFalse(reserved["encoding_authorized"] or reserved["training_authorized"] or reserved["scoring_authorized"])
        with self.assertRaisesRegex(ValueError, "SHA256"):
            binding_manifest(self.parts, **dict(inventories, code_files_sha256={}))


if __name__ == "__main__":
    unittest.main()
