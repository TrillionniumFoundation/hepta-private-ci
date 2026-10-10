"""Regression coverage for dispatch-time safety and executable fallback topology."""
from dataclasses import replace
import unittest

from reference import (
    ActuationIntent, BodyGraph, BodyStateEstimate, HomeostasisController,
    OrganManifest, ReflexController, ReflexDecision, ResourceRequest,
    ValidationError, default_reference_organs,
)


class DispatchSafetyTests(unittest.TestCase):
    def setUp(self):
        self.intent = ActuationIntent("i", "a" * 64, 1, "arm", "b" * 64, 1000, "k", "c" * 64)
        self.body = BodyStateEstimate(1, 50, 900000, 10000, "d" * 64)
        self.profile = dict(now_micros=60, maximum_state_age_micros=20,
                            minimum_integrity_ppm=800000, maximum_uncertainty_ppm=50000)

    def decision(self, body=None, intent=None, **profile):
        return ReflexController.evaluate(intent or self.intent, body or self.body,
                                         **(self.profile | profile))

    def test_stale_fused_state_is_vetoed_at_dispatch(self):
        self.assertEqual(self.decision(body=replace(self.body, observed_through=0)),
                         ReflexDecision(True, "stale_body_state"))

    def test_fresh_ingress_can_expire_while_waiting_for_dispatch(self):
        self.assertEqual(self.decision(), ReflexDecision(False, "clear"))
        self.assertEqual(self.decision(now_micros=71), ReflexDecision(True, "stale_body_state"))

    def test_future_fused_state_is_not_accepted(self):
        self.assertEqual(self.decision(body=replace(self.body, observed_through=61)),
                         ReflexDecision(True, "future_body_state"))

    def test_exact_age_boundary_and_zero_age_budget(self):
        self.assertEqual(self.decision(now_micros=70), ReflexDecision(False, "clear"))
        self.assertEqual(self.decision(now_micros=50, maximum_state_age_micros=0),
                         ReflexDecision(False, "clear"))
        self.assertEqual(self.decision(maximum_state_age_micros=0),
                         ReflexDecision(True, "stale_body_state"))

    def test_deadline_is_exclusive(self):
        self.assertEqual(self.decision(intent=replace(self.intent, deadline_micros=60)),
                         ReflexDecision(True, "deadline_expired"))

    def test_invalid_profile_fails_closed(self):
        for field, value in [("maximum_state_age_micros", -1), ("now_micros", True),
                             ("minimum_integrity_ppm", 1000001),
                             ("maximum_uncertainty_ppm", float("nan"))]:
            with self.subTest(field=field, value=value):
                self.assertEqual(self.decision(**{field: value}),
                                 ReflexDecision(True, "invalid_safety_profile"))

    def test_invalid_state_fails_closed(self):
        for field, value in [("observed_through", -1), ("generation", 0),
                             ("integrity_ppm", 1000001), ("uncertainty_ppm", -1)]:
            with self.subTest(field=field):
                self.assertEqual(self.decision(body=replace(self.body, **{field: value})),
                                 ReflexDecision(True, "invalid_body_state"))

    def test_human_stop_dominates_invalid_profile(self):
        self.assertEqual(self.decision(human_stop=True, maximum_state_age_micros=-1),
                         ReflexDecision(True, "human_stop"))

    def test_generation_mismatch_is_vetoed(self):
        self.assertEqual(self.decision(body=replace(self.body, generation=2)),
                         ReflexDecision(True, "stale_body_generation"))


class FallbackGraphTests(unittest.TestCase):
    def test_complete_registry_has_valid_order_under_permutation(self):
        organs = default_reference_organs()
        self.assertEqual(BodyGraph(1, organs).validate(), BodyGraph(1, tuple(reversed(organs))).validate())

    def test_complete_graph_rejects_removal_of_required_dependency(self):
        organs = tuple(organ for organ in default_reference_organs() if organ.organ_id != "body.schema")
        with self.assertRaisesRegex(ValidationError, "unknown graph reference"):
            BodyGraph(1, organs).validate()

    def test_fallback_must_not_depend_on_failed_organ(self):
        for dependencies in [("failed",), ("via",)]:
            with self.subTest(dependencies=dependencies):
                organs = (OrganManifest("failed", 1, "x", fallback_organs=("recovery",)),
                          OrganManifest("via", 1, "x", dependencies=("failed",)),
                          OrganManifest("recovery", 1, "x", dependencies=dependencies))
                with self.assertRaisesRegex(ValidationError, "fallback depends on failed organ"):
                    BodyGraph(1, organs).validate()

    def test_fallback_cycles_are_rejected_separately_from_dependencies(self):
        organs = (OrganManifest("a", 1, "x", fallback_organs=("b",)),
                  OrganManifest("b", 1, "x", fallback_organs=("a",)))
        with self.assertRaisesRegex(ValidationError, "fallback cycle"):
            BodyGraph(1, organs).validate()

    def test_duplicate_graph_edges_are_rejected(self):
        organs = (OrganManifest("a", 1, "x", fallback_organs=("b", "b")),
                  OrganManifest("b", 1, "x"))
        with self.assertRaisesRegex(ValidationError, "duplicate graph edge"):
            BodyGraph(1, organs).validate()

    def test_duplicate_resource_identity_cannot_hide_a_reservation(self):
        with self.assertRaisesRegex(ValidationError, "duplicate resource organ"):
            HomeostasisController.allocate(10, [ResourceRequest("a", 2, 3, 1), ResourceRequest("a", 1, 4, 1)])


if __name__ == "__main__":
    unittest.main()
