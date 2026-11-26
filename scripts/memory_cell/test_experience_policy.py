"""Real small-tensor policy tests; authored schemas are not semantic review."""

from copy import deepcopy
from dataclasses import replace
import json
import unittest

from event_experience import question
from event_projection import EventProjection, Lookup
from experience_policy import (
    INITIAL,
    candidate_features,
    choose,
    fit_policy,
    lookup_from_question,
    validate_policy,
)
from native import digest
from test_event_projection import doc
from test_experience_write_trial import records
from experience_write_trial import summarize


def sources(scope):
    rows = (
        doc(scope + "_other", entity="neighbor", value="site_other"),
        doc(scope + "_bridge", attribute="component", value="component_one"),
        doc(scope + "_old", entity="component_one", value="site_old"),
        doc(
            scope + "_new",
            entity="component_one",
            value="site_new",
            revision=2,
            supersedes=(scope + "_old",),
        ),
        doc(scope + "_future", entity="component_one", value="site_future", revision=3),
    )
    return tuple(replace(d, scope=scope, session=scope) for d in rows)


class LearnedReadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.documents = sources("calibration") + sources("test")
        cls.identity = digest("test-reader-not-pretrained")
        cls.policy = fit_policy(
            cls.documents,
            ["calibration"],
            revision=2,
            reader_identity=cls.identity,
            revoked=set(),
        )

    def test_real_update_and_new_scope_inference_follow_source_relations(self):
        p = self.policy
        self.assertEqual(p["parameters"], 10)
        self.assertGreater(p["delta_squared_norm"], 0)
        self.assertEqual(p["steps"], len(p["losses"]))
        self.assertEqual(set(p["roots"]), {d.root for d in sources("calibration")})
        weights = validate_policy(
            json.loads(json.dumps(p)),
            self.documents,
            reader_identity=self.identity,
            test_scopes={"test"},
            revoked=set(),
        )
        projection = EventProjection(sources("test"))
        pool = tuple(projection.facts)
        selected, receipt = choose(
            projection,
            Lookup("service", ("component", "location"), 2),
            pool,
            weights,
            revoked=set(),
        )
        self.assertEqual(selected, ("test_bridge", "test_new"))
        self.assertEqual(receipt["injected_out_of_pool_sources"], 0)
        self.assertFalse(p["test_queries_consumed"])
        self.assertFalse(p["production_accepted"])

    def test_heldout_source_values_cannot_train_the_policy(self):
        changed = self.documents[:5] + sources("unrelated_test")
        again = fit_policy(
            changed,
            ["calibration"],
            revision=2,
            reader_identity=self.identity,
            revoked=set(),
        )
        self.assertEqual(again["weights"], self.policy["weights"])
        self.assertEqual(again["losses"], self.policy["losses"])

    def test_fixed_features_identical_before_different_policy_scores(self):
        projection = EventProjection(sources("test"))
        lookup = Lookup("service", ("component", "location"), 2)
        pool = tuple(projection.facts)
        a = choose(projection, lookup, pool, INITIAL, revoked=set())[1]
        b = choose(projection, lookup, pool, self.policy["weights"], revoked=set())[1]
        self.assertEqual(
            a["decisions"][0]["feature_digest"], b["decisions"][0]["feature_digest"]
        )
        self.assertNotEqual(a["weights_digest"], b["weights_digest"])

    def test_no_out_of_pool_recovery_of_missing_prerequisite(self):
        projection = EventProjection(sources("test"))
        selected, _ = choose(
            projection,
            Lookup("service", ("component", "location"), 2),
            ("test_other", "test_old"),
            self.policy["weights"],
            revoked=set(),
        )
        self.assertTrue(set(selected).issubset({"test_other", "test_old"}))
        self.assertNotIn("test_new", selected)

    def test_public_question_parser_roundtrips_every_controlled_path(self):
        for path in (
            ("location",),
            ("component", "location"),
            ("component", "successful_mode"),
        ):
            spec = dict(entity="service", path=path, revision=2, id="test")
            q, expected = question(spec, "2026-01-01T00:00:00Z")
            self.assertEqual(lookup_from_question(q), expected)
            with self.assertRaises(ValueError):
                lookup_from_question(
                    replace(q, content=q.content + " answer=site_target")
                )

    def test_revoked_or_mutated_source_and_test_scope_overlap_reject(self):
        for fields in (
            dict(test_scopes={"test", "calibration"}, revoked=set()),
            dict(test_scopes={"test"}, revoked={"root_calibration_old"}),
        ):
            with self.assertRaises(ValueError):
                validate_policy(
                    self.policy, self.documents, reader_identity=self.identity, **fields
                )
        changed = (replace(self.documents[0], content="changed"), *self.documents[1:])
        with self.assertRaises(ValueError):
            validate_policy(
                self.policy,
                changed,
                reader_identity=self.identity,
                test_scopes={"test"},
                revoked=set(),
            )
        shared = (
            *self.documents[:5],
            replace(self.documents[5], root=self.documents[0].root),
            *self.documents[6:],
        )
        with self.assertRaises(ValueError):
            validate_policy(
                self.policy,
                shared,
                reader_identity=self.identity,
                test_scopes={"test"},
                revoked=set(),
            )

    def test_malformed_policy_does_not_become_an_untrained_fallback(self):
        for field, value in (
            ("weights", [float("nan")] * 10),
            ("weights", [True] * 10),
            ("reader_identity", "other"),
            ("training_scopes", []),
            ("production_accepted", True),
            ("test_queries_consumed", True),
            ("revision", True),
        ):
            bad = deepcopy(self.policy)
            bad[field] = value
            with self.assertRaises(ValueError):
                validate_policy(
                    bad,
                    self.documents,
                    reader_identity=self.identity,
                    test_scopes={"test"},
                    revoked=set(),
                )

    def test_invalid_training_admission_rejects_before_gradient(self):
        for scopes, revision in (
            (["missing"], 2),
            (["calibration"] * 2, 2),
            (["calibration"], True),
        ):
            with self.assertRaises(ValueError):
                fit_policy(
                    self.documents,
                    scopes,
                    revision=revision,
                    reader_identity=self.identity,
                    revoked=set(),
                )
        with self.assertRaises(ValueError):
            fit_policy(
                self.documents,
                ["calibration"],
                revision=2,
                reader_identity=self.identity,
                revoked={"root_calibration_old"},
            )

    def test_conflicting_sources_remain_unknown_not_arbitrary_targets(self):
        a, b = doc("one", value="site_one"), doc("two", value="site_two")
        with self.assertRaises(ValueError):
            fit_policy(
                (a, b),
                ["scope"],
                revision=2,
                reader_identity=self.identity,
                revoked=set(),
            )

    def test_recorded_adapter_mode_cannot_counterfeit_parameter_gain(self):
        data = records()
        data[0]["receipt"]["knowledge_module_enabled"] = True
        with self.assertRaises(ValueError):
            summarize(data, ["q1", "q2"])

    def test_seven_arm_census_and_failed_policy_attempt(self):
        data = records()
        for q in ("q1", "q2"):
            for arm in ("policy", "policy_initial"):
                row = deepcopy(
                    next(
                        r
                        for r in data
                        if r["question_id"] == q and r["arm"] == "organized"
                    )
                )
                row["arm"] = arm
                data.append(row)
        result = summarize(data, ["q1", "q2"], policy_enabled=True)
        self.assertEqual(result["all_attempts"], 14)
        self.assertEqual(result["learned_policy_minus_initial"], 0)
        bad = next(r for r in data if r["arm"] == "policy")
        bad["status"] = "failed"
        bad.pop("receipt")
        result = summarize(data, ["q1", "q2"], policy_enabled=True)
        self.assertEqual(result["learned_policy_minus_initial"], -0.5)
        with self.assertRaises(ValueError):
            summarize(data[:-1], ["q1", "q2"], policy_enabled=True)


if __name__ == "__main__":
    unittest.main()
