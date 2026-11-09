"""Receipt-prefix and model-consumption checks; no real owner is exercised."""

from dataclasses import replace
import unittest

import numpy as np

from .action_history import ActionEvent, TIME_VALUES, ablate, encode, supervision
from .contracts import Evidence
from .models import Model


def event(sequence, stage, observed_at, event_at=None, evidence=None, **kwargs):
    return ActionEvent(
        sequence,
        "attempt-1",
        "candidate-1",
        "read",
        stage,
        observed_at,
        f"record:{sequence}",
        event_at,
        evidence=evidence,
        **kwargs,
    )


def snapshot(events, at=10, cursor=20):
    return encode(
        events,
        actions=("read", "repair"),
        decision_at=at,
        through_sequence=cursor,
        remaining_budget=12,
        deadline_at=20,
    )


class ActionHistoryTests(unittest.TestCase):
    def setUp(self):
        self.request = event(0, "request", 0, 0)
        self.executed = event(1, "executed", 3, 1)
        self.terminal = event(
            3,
            "effect_observed",
            8,
            5,
            Evidence(
                observation_status="terminal",
                outcome=1,
                time_kind="exact",
                time_lower=4,
                final_cost=2,
                observed_at=8,
                receipt_ref="real:result",
            ),
        )

    def value(self, snap, name, row=-2):
        return snap.features[row, snap.feature_names.index(name)]

    def test_late_readback_and_equal_clock_later_sequence_do_not_backfill(self):
        before = snapshot([self.request, self.executed], at=3, cursor=1)
        same_tick = event(2, "accepted", 3, 0.5)
        after = snapshot(
            [self.request, self.executed, same_tick, self.terminal], at=3, cursor=1
        )
        np.testing.assert_array_equal(before.features, after.features)
        self.assertEqual(before.events, after.events)
        with self.assertRaises(ValueError):
            before.features.setflags(write=True)
        self.assertEqual(
            len(
                snapshot(
                    [self.request, self.executed, same_tick], at=3, cursor=2
                ).events
            ),
            3,
        )

    def test_reordered_acceptance_ack_does_not_invent_or_rewrite_execution(self):
        late_accept = event(2, "accepted", 4, 0.5)
        snap = snapshot([self.request, self.executed, late_accept, self.terminal])
        self.assertEqual(
            snap.events, (self.request, self.executed, late_accept, self.terminal)
        )
        self.assertEqual(self.value(snap, "stage:effect_observed"), 1)
        self.assertEqual(self.value(snap, "stage:executed", 1), 1)
        self.assertEqual(self.value(snap, "stage:accepted", 1), 0)
        request_only = snapshot([self.request])
        self.assertEqual(self.value(request_only, "stage:executed"), 0)
        self.assertEqual(self.value(request_only, "execution_age_known"), 0)

    def test_missing_receipt_is_not_failure_zero_time_or_right_censoring(self):
        unknown = event(
            2,
            "readback",
            6,
            evidence=Evidence(observation_status="receipt_missing", observed_at=6),
        )
        snap = snapshot([self.request, self.executed, unknown])
        self.assertEqual(
            (self.value(snap, "outcome"), self.value(snap, "outcome_known")), (0, 0)
        )
        self.assertEqual(self.value(snap, "effect_lower_known"), 0)
        self.assertEqual(self.value(snap, "time_kind:right_censored"), 0)
        np.testing.assert_array_equal(supervision(unknown), np.ones(32, dtype=bool))
        failure = replace(
            self.terminal, evidence=replace(self.terminal.evidence, outcome=0)
        )
        failed = snapshot([self.request, self.executed, failure])
        self.assertEqual(
            (self.value(failed, "outcome"), self.value(failed, "outcome_known")), (0, 1)
        )
        self.assertEqual(int(supervision(failure).sum()), 1)

    def test_only_verified_nonoccurrence_produces_right_censoring(self):
        with self.assertRaises(ValueError):
            Evidence(
                observation_status="receipt_missing",
                time_kind="right_censored",
                time_lower=2,
            )
        ongoing = event(
            2,
            "readback",
            6,
            evidence=Evidence(
                observation_status="verified_ongoing",
                time_kind="right_censored",
                time_lower=2,
                observed_at=6,
                nonoccurrence_witness="owner:ongoing",
            ),
        )
        mask = supervision(ongoing).reshape(2, 4, 4)
        self.assertFalse(mask[:, :2].any())
        self.assertTrue(mask[:, 2:].all())
        unsupported = replace(
            self.terminal, evidence=replace(self.terminal.evidence, final_cost=3)
        )
        with self.assertRaisesRegex(ValueError, "support"):
            supervision(unsupported)

    def test_identity_phase_order_and_evidence_mismatch_are_rejected(self):
        bad_logs = [
            [self.executed],
            [self.request, replace(self.executed, candidate_id="other")],
            [self.request, replace(self.executed, action="unregistered")],
            [self.request, self.request],
            [self.request, self.executed, event(2, "accepted", 4, 2)],
            [self.request, self.executed, replace(self.terminal, event_at=4)],
            [
                self.request,
                self.executed,
                self.terminal,
                event(4, "readback", 9, evidence=Evidence(observed_at=9)),
            ],
        ]
        for events in bad_logs:
            with self.subTest(events=events), self.assertRaises(ValueError):
                snapshot(events)
        for fields in (
            {"observed_at": float("nan")},
            {"remaining_budget": -1},
            {"sequence": True},
            {"source": "imagined"},
            {"record_ref": ""},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                replace(self.request, **fields)
        with self.assertRaisesRegex(ValueError, "arrival"):
            replace(self.terminal, observed_at=9)
        with self.assertRaisesRegex(ValueError, "Evidence"):
            replace(self.request, evidence={"outcome": 1})

    def test_execution_ack_arriving_after_effect_reconciles_earlier_duration(self):
        early_terminal = replace(self.terminal, sequence=1, event_at=None)
        valid_ack = replace(self.executed, sequence=2, observed_at=9)
        self.assertEqual(
            len(snapshot([self.request, early_terminal, valid_ack]).events), 3
        )
        invalid_ack = replace(valid_ack, event_at=6)
        with self.assertRaisesRegex(ValueError, "duration"):
            snapshot([self.request, early_terminal, invalid_ack])

    def test_ablation_removes_values_and_masks_without_mutation(self):
        snap = snapshot([self.request, self.executed, self.terminal])
        full = snap.features.copy()
        time_columns = [
            i
            for i, n in enumerate(snap.feature_names)
            if n.startswith("time_kind:") or n.removesuffix("_known") in TIME_VALUES
        ]
        self.assertFalse(ablate(snap, "no_time")[:, time_columns].any())
        action_columns = [
            i
            for i, n in enumerate(snap.feature_names)
            if n.startswith("action:") or n == "action_slot"
        ]
        self.assertFalse(ablate(snap, "no_action")[:, action_columns].any())
        latest = ablate(snap, "no_history")
        self.assertEqual(latest.shape[0], 2)
        self.assertEqual(latest[0, snap.feature_names.index("outcome_known")], 1)
        np.testing.assert_array_equal(full, snap.features)

    def test_later_terminal_cannot_contradict_earlier_time_or_cost_facts(self):
        ongoing = event(
            2,
            "readback",
            6,
            evidence=Evidence(
                observation_status="verified_ongoing",
                time_kind="right_censored",
                time_lower=4,
                confirmed_cost_lower_bound=4,
                observed_at=6,
                nonoccurrence_witness="owner:cutoff-four",
            ),
        )
        short = replace(
            self.terminal,
            event_at=3,
            evidence=replace(
                self.terminal.evidence, time_lower=2, time_upper=2, final_cost=4
            ),
        )
        cheap = replace(
            self.terminal,
            event_at=9,
            observed_at=10,
            evidence=replace(
                self.terminal.evidence,
                time_lower=8,
                time_upper=8,
                observed_at=10,
                final_cost=2,
            ),
        )
        for terminal in (short, cheap):
            with self.subTest(terminal=terminal), self.assertRaises(ValueError):
                snapshot([self.request, self.executed, ongoing, terminal])
        # Contradictory relative durations remain contradictory if execution
        # acknowledgement is missing; missing times cannot erase old facts.
        with self.assertRaisesRegex(ValueError, "duration"):
            snapshot([self.request, ongoing, short])

    def test_terminal_occurrence_must_lie_in_declared_continuous_interval(self):
        interval = replace(
            self.terminal,
            event_at=5,
            evidence=replace(
                self.terminal.evidence, time_kind="interval", time_lower=2, time_upper=4
            ),
        )
        self.assertEqual(
            len(snapshot([self.request, self.executed, interval]).events), 3
        )
        for instant in (3, 7):
            with (
                self.subTest(instant=instant),
                self.assertRaisesRegex(ValueError, "duration"),
            ):
                snapshot(
                    [self.request, self.executed, replace(interval, event_at=instant)]
                )
        # Off-grid 2.5 is valid history; discrete supervision may reject it.
        continuous = replace(
            self.terminal,
            event_at=3.5,
            evidence=replace(
                self.terminal.evidence, time_lower=2.5, time_upper=2.5, final_cost=2.25
            ),
        )
        self.assertEqual(
            len(snapshot([self.request, self.executed, continuous]).events), 3
        )
        with self.assertRaisesRegex(ValueError, "support"):
            supervision(continuous)

    def test_late_execution_ack_reconciles_interval_receipts_without_backfill(self):
        interval = replace(
            self.terminal,
            sequence=1,
            event_at=7,
            evidence=replace(
                self.terminal.evidence, time_kind="interval", time_lower=2, time_upper=4
            ),
        )
        prefix = snapshot([self.request, interval], at=8, cursor=1)
        late_ack = replace(self.executed, sequence=2, observed_at=9)
        same = snapshot([self.request, interval, late_ack], at=8, cursor=1)
        np.testing.assert_array_equal(prefix.features, same.features)
        with self.assertRaisesRegex(ValueError, "duration"):
            snapshot([self.request, interval, late_ack])

    def test_strict_censor_boundary_and_decreasing_lower_bound_receipts(self):
        ongoing = event(
            2,
            "readback",
            5,
            evidence=Evidence(
                observation_status="verified_ongoing",
                time_kind="right_censored",
                time_lower=4,
                confirmed_cost_lower_bound=2,
                observed_at=5,
                nonoccurrence_witness="owner:cutoff-four",
            ),
        )
        # T > 4 excludes exact T = 4 even though every envelope alone is valid.
        with self.assertRaisesRegex(ValueError, "duration"):
            snapshot([self.request, self.executed, ongoing, self.terminal])
        unknown = event(
            2,
            "readback",
            4,
            evidence=Evidence(observed_at=4, confirmed_cost_lower_bound=4),
        )
        stale = event(
            3,
            "readback",
            5,
            evidence=Evidence(observed_at=5, confirmed_cost_lower_bound=1),
        )
        paid = replace(
            self.terminal,
            sequence=4,
            evidence=replace(self.terminal.evidence, final_cost=4),
        )
        self.assertEqual(
            len(snapshot([self.request, self.executed, unknown, stale, paid]).events), 5
        )
        with self.assertRaisesRegex(ValueError, "previously confirmed"):
            snapshot(
                [
                    self.request,
                    self.executed,
                    unknown,
                    stale,
                    replace(self.terminal, sequence=4),
                ]
            )

    def test_real_model_accepts_snapshot_and_recurrent_reset_is_separate(self):
        snap = snapshot([self.request, self.executed, self.terminal])
        model = Model("gru", len(snap.feature_names), 2, 32, 8, 42)
        query = np.array([[1.0, 0.0]])
        full = model.predict_proba(snap.features[None], query)
        latest = model.predict_proba(ablate(snap, "no_history")[None], query)
        reset = model.predict_proba(snap.features[None], query, reset=True)
        self.assertTrue(np.isfinite(full).all())
        self.assertAlmostEqual(float(full.sum()), 1)
        self.assertFalse(np.allclose(latest, reset))
        state = model.initial_state()
        for row in snap.features:
            state = model.observe(row[None], state)
        np.testing.assert_allclose(
            model.predict_from_state(state, query),
            model.forward(snap.features[None], query),
        )

    def test_empty_prefix_and_bounded_generator(self):
        empty = snapshot([], cursor=-1)
        self.assertEqual(empty.features.shape[0], 1)
        self.assertTrue(np.isfinite(empty.features).all())
        self.assertTrue(((empty.features >= 0) & (empty.features <= 1)).all())
        with self.assertRaisesRegex(ValueError, "255"):
            snapshot(self.request for _ in range(256))


if __name__ == "__main__":
    unittest.main()
