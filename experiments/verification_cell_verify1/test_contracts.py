"""Negative tests for report separation, provenance binding and check scheduling."""

from dataclasses import FrozenInstanceError, replace
import json
import unittest

from experiments.verification_cell_verify1.contracts import (
    CalibrationReport,
    ModelIdentity,
    RiskPrediction,
    Scope,
    VerificationReceipt,
    assert_bound,
    canonical_json,
    digest,
    parse_record,
    select_check,
)


SHA = "a" * 64
OTHER = "b" * 64


def scope():
    return Scope(
        "task", "attempt", SHA, 7, "filesystem", "accepted_trajectory_error", 2, 4
    )


def model():
    return ModelIdentity(SHA, None, OTHER)


def risk():
    return RiskPrediction(scope(), model(), 0.2, 2, SHA)


def calibration():
    return CalibrationReport(
        scope(),
        model(),
        ("train",),
        ("cal",),
        ("confirm",),
        SHA,
        "brier",
        "proper_scoring_rule",
        0.1,
        80,
        "unknown",
        ("frozen policy; grouped holdout",),
    )


def receipt():
    return VerificationReceipt(
        scope(),
        "readback_matches",
        ("trusted local checker",),
        "sqlite_readback",
        "1",
        SHA,
        2,
        "unknown",
        "result unavailable",
        ("obtain independent readback",),
    )


class ContractTests(unittest.TestCase):
    def test_roundtrip_all_report_types_and_normalized_sequences(self):
        for record in (risk(), calibration(), receipt()):
            with self.subTest(record=type(record).__name__):
                self.assertEqual(parse_record(canonical_json(record)), record)
                assert_bound(record, scope(), expected_type=type(record))
        assumptions = ["trusted local checker"]
        normalized = replace(receipt(), assumptions=assumptions)
        assumptions.append("changed after construction")
        self.assertEqual(normalized, receipt())
        with self.assertRaises(FrozenInstanceError):
            normalized.verdict = "proved"

    def test_reject_missing_unknown_and_authority_fields(self):
        for section, name in (
            (None, "authorized"),
            (None, "verdict"),
            ("scope", "capability"),
            ("model", "checker"),
        ):
            data = json.loads(canonical_json(risk()))
            (data if section is None else data[section])[name] = True
            with (
                self.subTest(section=section, field=name),
                self.assertRaises(ValueError),
            ):
                parse_record(json.dumps(data))
        for section, name in (
            (None, "model"),
            ("scope", "event"),
            ("model", "policy_sha256"),
        ):
            data = json.loads(canonical_json(risk()))
            del (data if section is None else data[section])[name]
            with self.assertRaises(ValueError):
                parse_record(json.dumps(data))

    def test_reject_duplicate_json_fields_at_each_level(self):
        raw = canonical_json(risk())
        for original, duplicate in (
            (
                '"type":"risk_prediction"',
                '"type":"risk_prediction","type":"verification_receipt"',
            ),
            ('"state_version":7', '"state_version":7,"state_version":8'),
        ):
            with self.assertRaisesRegex(ValueError, "duplicate"):
                parse_record(raw.replace(original, duplicate))

    def test_reject_invalid_type_tags_and_nonobjects(self):
        for tag in ("host_capability", "verification_receipt", None, True, [], {}):
            data = json.loads(canonical_json(risk()))
            data["type"] = tag
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                parse_record(json.dumps(data))
        for raw in ("[]", "null", "1", "{}", "{", {}, " " * 65537):
            with self.assertRaises(ValueError):
                parse_record(raw)

    def test_probability_is_finite_and_not_a_bool(self):
        for value in (
            -0.1,
            1.1,
            float("nan"),
            float("inf"),
            -float("inf"),
            True,
            "0.2",
            None,
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replace(risk(), probability=value)
            data = json.loads(canonical_json(risk()))
            data["probability"] = value
            with self.assertRaises(ValueError):
                parse_record(json.dumps(data))
        with self.assertRaises(ValueError):
            replace(risk(), probability=10**1000)

    def test_scope_hashes_ranges_and_chronology(self):
        for change in (
            {"horizon_start": 5},
            {"horizon_end": -1},
            {"state_version": True},
            {"horizon_start": 1.5},
            {"domain": " "},
            {"subject_sha256": SHA.upper()},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(scope(), **change)
        for change in (
            {"observed_step": 3},
            {"observed_step": True},
            {"evidence_sha256": "missing"},
        ):
            with self.assertRaises(ValueError):
                replace(risk(), **change)
        with self.assertRaises(ValueError):
            replace(receipt(), checked_step=1)
        self.assertEqual(replace(receipt(), checked_step=8).checked_step, 8)

    def test_calibration_rejects_leakage_and_mislabelled_statistics(self):
        for change in (
            {"calibration_source_groups": ("train",)},
            {"confirmation_source_groups": ("cal",)},
            {"training_source_groups": ("x", "x")},
            {"calibration_source_groups": ()},
            {"confirmation_source_groups": ()},
            {"metric": "score_miscoverage", "metric_kind": "outcome_event_frequency"},
            {"metric": "unsupported", "metric_kind": None},
            {"metric_value": float("nan")},
            {"sample_count": 0},
            {"sample_count": True},
            {"assumptions": ()},
            {"drift": "safe"},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(calibration(), **change)

    def test_receipt_cannot_hide_unknowns_or_unmet_obligations(self):
        for change in (
            {"verdict": "accepted"},
            {"reason": ""},
            {"checker_version": None},
            {"verdict": "proved"},
            {"residual_obligations": ()},
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(receipt(), **change)
        proved = replace(
            receipt(),
            verdict="proved",
            reason="independent readback matched",
            residual_obligations=(),
        )
        self.assertEqual(parse_record(canonical_json(proved)), proved)

    def test_bindings_reject_cross_type_and_every_scope_dimension(self):
        for name, value in (
            ("task_id", "another"),
            ("attempt_id", "another"),
            ("subject_sha256", OTHER),
            ("state_version", 8),
            ("domain", "network"),
            ("event", "score_exceedance"),
            ("horizon_start", 3),
            ("horizon_end", 5),
        ):
            with self.subTest(field=name), self.assertRaises(ValueError):
                assert_bound(
                    risk(),
                    replace(scope(), **{name: value}),
                    expected_type=RiskPrediction,
                )
        with self.assertRaises(ValueError):
            assert_bound(risk(), scope(), expected_type=VerificationReceipt)
        with self.assertRaises(ValueError):
            assert_bound(
                risk(),
                scope(),
                replace(model(), policy_sha256=SHA),
                expected_type=RiskPrediction,
            )
        with self.assertRaises(ValueError):
            assert_bound(
                receipt(),
                scope(),
                evidence_sha256=OTHER,
                expected_type=VerificationReceipt,
            )
        assert_bound(risk(), scope(), model(), SHA, expected_type=RiskPrediction)

    def test_risk_and_cost_interventions_keep_evidence_fixed(self):
        low, high = replace(risk(), probability=0.1), replace(risk(), probability=0.9)
        self.assertEqual(
            (low.scope, low.model, low.evidence_sha256),
            (high.scope, high.model, high.evidence_sha256),
        )
        self.assertEqual(
            [select_check(item, 5, 10, 10) for item in (low, high)], ["defer", "check"]
        )
        self.assertEqual(
            [select_check(risk(), cost, 10, 10) for cost in (2, 3)], ["check", "defer"]
        )

    def test_mandatory_checks_block_on_exhausted_budget(self):
        self.assertEqual(select_check(0, 5, 0, 4, mandatory=True), "blocked")
        self.assertEqual(select_check(0, 5, 0, 5, mandatory=True), "check")
        self.assertEqual(select_check(1, 5, 100, 4), "defer")
        self.assertEqual(select_check(0, 0, 0, 0), "check")

    def test_schedule_rejects_invalid_numeric_inputs(self):
        for index in range(4):
            for value in (True, -1, float("nan"), float("inf"), "1", None):
                args = [0.5, 1, 10, 10]
                args[index] = value
                with (
                    self.subTest(index=index, value=value),
                    self.assertRaises(ValueError),
                ):
                    select_check(*args)
        with self.assertRaises(ValueError):
            select_check(0.5, 1, 10, 10, mandatory="yes")

    def test_canonical_hash_is_order_stable_and_rejects_ambiguous_values(self):
        raw = json.loads(canonical_json(risk()))
        self.assertEqual(digest(risk()), digest(dict(reversed(list(raw.items())))))
        self.assertNotEqual(
            digest(risk()),
            digest(replace(risk(), scope=replace(scope(), state_version=8))),
        )
        for value in ({1: "coerced key"}, {"x": float("nan")}, object()):
            with self.assertRaises(ValueError):
                canonical_json(value)


if __name__ == "__main__":
    unittest.main()
