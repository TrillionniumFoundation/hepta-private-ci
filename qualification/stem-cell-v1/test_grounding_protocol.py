"""Stdlib fixtures only: fresh identity, independent truth and final-only gates."""
from dataclasses import replace
import unittest

from binding_protocol import build_binding_protocol, score_binding_probabilities
from grounding_protocol import (ROLES, build_grounding_protocol, grounding_campaign_gate,
    grounding_gate, grounding_manifest, verify_grounding_protocol)
from retention_data import build_augmentation


class GroundingProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.historical = build_binding_protocol(seed=41)
        cls.augmentation, _ = build_augmentation(cls.historical)
        cls.parts = build_grounding_protocol(cls.historical, cls.augmentation)

    def metrics(self):
        return {role: score_binding_probabilities(cases, [.9 if c.label else .1 for c in cases])
                for role, cases in self.parts.items()}

    def test_complete_disjoint_deterministic_worlds_and_manifest(self):
        self.assertEqual(self.parts, build_grounding_protocol(self.historical, self.augmentation))
        reports = verify_grounding_protocol(self.parts, self.historical, self.augmentation)
        self.assertEqual({r: (m["cases"], m["groups"], m["paired_candidates"])
                          for r, m in reports.items()}, {r: (128, 32, 64) for r in ROLES})
        manifest = grounding_manifest(self.parts, self.historical, self.augmentation)
        self.assertFalse(manifest["longer_chains"])
        self.assertFalse(manifest["original_V5_reserved_domains_scored"])
        self.assertEqual(manifest, grounding_manifest(self.parts, self.historical, self.augmentation))
        self.assertTrue(all(c.source_split == "validation" for cs in self.parts.values() for c in cs))

    def test_reused_historical_role_seed_and_augmentation_drift_fail(self):
        with self.assertRaisesRegex(ValueError, "role/seed"):
            build_grounding_protocol(self.historical, self.augmentation, seed=41)
        with self.assertRaisesRegex(ValueError, "augmentation"):
            build_grounding_protocol(self.historical, self.augmentation[:-4])

    def test_grammar_truth_and_complete_groups_are_independently_checked(self):
        changed = dict(self.parts)
        cases = changed[ROLES[0]]
        changed[ROLES[0]] = (replace(cases[0], label=1-cases[0].label), *cases[1:])
        with self.assertRaisesRegex(ValueError, "grammar"):
            verify_grounding_protocol(changed, self.historical, self.augmentation)
        changed[ROLES[0]] = cases[:-1]
        with self.assertRaises(ValueError):
            verify_grounding_protocol(changed, self.historical, self.augmentation)

    def test_old_world_rejected_even_with_new_ids_and_random_order_hashes(self):
        changed = dict(self.parts)
        changed[ROLES[0]] = tuple(replace(c, source_split="validation", paragraph_id=
            f"binding-v5/fresh_combinations/2901/{c.paragraph_id.split('/')[-2]}/{c.paragraph_id.split('/')[-1]}")
            for c in self.historical["reader_train"])
        with self.assertRaisesRegex(ValueError, "disjoint"):
            verify_grounding_protocol(changed, self.historical, self.augmentation)

    def test_one_shared_frozen_data_seed_required(self):
        other = build_grounding_protocol(self.historical, self.augmentation, seed=2902)
        with self.assertRaisesRegex(ValueError, "share"):
            verify_grounding_protocol({ROLES[0]: self.parts[ROLES[0]], ROLES[1]: other[ROLES[1]]},
                                      self.historical, self.augmentation)

    def test_integer_thresholds_and_every_panel_are_required(self):
        metrics = self.metrics()
        metrics[ROLES[0]].update(accuracy=109/128, both_worlds_correct=48/64)
        self.assertTrue(grounding_gate(metrics)["passed"])
        metrics[ROLES[1]].update(accuracy=108/128, both_worlds_correct=47/64)
        gate = grounding_gate(metrics)
        self.assertFalse(gate["passed"])
        self.assertEqual(len(gate["reasons"]), 2)
        self.assertFalse(gate["automatic_downstream_authorized"])

    def test_bad_floats_tuned_threshold_and_missing_panels_fail_closed(self):
        for patch in (dict(accuracy=float("nan")), dict(accuracy=True), dict(accuracy=.85),
                      dict(threshold_selected=True), dict(both_worlds_correct=1., accuracy=.75)):
            metrics = self.metrics()
            metrics[ROLES[0]].update(patch)
            with self.assertRaises(ValueError):
                grounding_gate(metrics)
        with self.assertRaises(ValueError):
            grounding_gate({ROLES[0]: self.metrics()[ROLES[0]]})

    def test_global_gate_recomputes_three_seed_raw_metrics(self):
        metrics = {str(s): self.metrics() for s in (41, 47, 53)}
        self.assertTrue(grounding_campaign_gate(metrics)["primary_all_passed"])
        metrics["47"][ROLES[1]]["both_worlds_correct"] = 47/64
        self.assertFalse(grounding_campaign_gate(metrics)["primary_all_passed"])
        with self.assertRaises(ValueError):
            grounding_campaign_gate({"41": self.metrics()})


if __name__ == "__main__":
    unittest.main()
