"""Behavioral checks for support identity and independently frozen decoders."""
import copy
from types import SimpleNamespace
import unittest

import numpy as np

from ..digital_read_before_20261031.task import initial, successor
from .diagnostics import (audit_episodes, build_support, evaluate_decoders,
                          extract_pairs, state_fingerprint, train_decoders)


def fixture():
    public = dict(schema="digital-read-before-public-v1", id="world-a", deadline=6,
                  initial_budget=3, duration=[.5] * 6, reliability=[.85] * 6,
                  read_price=[.03] * 6, read_delay=[1] * 6,
                  latency_price=.025, repair_price=.03, failure_probability=.08,
                  packets=[f"packet-{i}.json" for i in range(6)], packet_sha256=["a" * 64] * 6)
    return public, initial(public)


def decoder_pairs(prefix, count=24):
    rows = []
    for i in range(count):
        y = .1 + .8 * (i % 12) / 11
        before, after = [0.] * 12, [y] + [0.] * 11
        rows.append(dict(id=f"{prefix}-{i}", world=f"{prefix}-{i // 3}", fit=7,
                         group="event" if i % 2 else "recovery", teacher_before=y,
                         teacher_after=y, completion=None, content_failure=False,
                         before_cell=before, after_cell=after,
                         before_full=[0.] * 36 + before, after_full=[0.] * 36 + after))
    return rows


class DiagnosticChecks(unittest.TestCase):
    def test_full_identity_excludes_names_but_preserves_task_information(self):
        public, state = fixture()
        original = state_fingerprint(public, state, 7)
        renamed = dict(public, id="new-world", packets=[f"new-{i}.json" for i in range(6)],
                       packet_sha256=["b" * 64] * 6)
        self.assertEqual(original, state_fingerprint(renamed, state, 7))
        for changed_public, changed_state, index in (
                (dict(public, read_price=[.04] + [.03] * 5), state, 7),
                (public, dict(state, charges=.1), 7),
                (public, dict(state, history=[dict(source_tick=0, observation=1, reliability=.85)]), 7),
                (public, state, 8)):
            self.assertNotEqual(original, state_fingerprint(changed_public, changed_state, index))

    def test_sparse_universe_exact_support_and_actual_label_separation(self):
        public, state = fixture()
        rows = [dict(public=public, state=state, latent_support=[7])]
        support = build_support(rows, {"round-1": [dict(public=public, state=state, latent_index=8)]})
        episode = dict(world=public["id"], label=0, label_access_after_terminal=True,
                       final_state=dict(state, terminal=True), metrics=dict(utility=-1., submitted=True, correct=0),
                       decisions=[dict(state=state, latent_index=9, action=5,
                                       scores=dict(q=[0., .1, .1, 0., -.6, .6], belief=.8),
                                       teacher_q=[0., .1, .1, 0., -.6, .6], teacher_belief=.8)])
        result = audit_episodes([episode], {public["id"]: public}, support)
        self.assertEqual(result["counts"], dict(episodes=1, decisions=1, unique_states=1, exact_unseen=1))
        self.assertEqual(result["universe"]["zero_evaluation_strata"], 22847)
        self.assertEqual(result["universe"]["zero_everywhere_strata"], 22845)
        self.assertEqual(result["decision_metrics"]["belief_teacher_mse"], 0.)
        self.assertAlmostEqual(result["decision_metrics"]["actual_label_brier"], .64)
        self.assertEqual(result["actual_outcomes"]["accuracy_given_submission"], 0.)
        absent = build_support([dict(public=public, state=state)], {})
        self.assertEqual(absent["sources"]["behavior"]["missing_latent_support_rows"], 1)
        self.assertEqual(absent["sources"]["behavior"]["fingerprints"], [])

    def test_frozen_decoder_recovers_new_linear_signal_without_test_fitting(self):
        train, test = decoder_pairs("train"), decoder_pairs("test")
        artifact = train_decoders(train)
        frozen = copy.deepcopy(artifact)
        result = evaluate_decoders(artifact, test)
        self.assertEqual(artifact, frozen)
        for group in result["groups"].values():
            self.assertEqual(group["status"], "complete")
            self.assertLess(group["mse"]["after_cell"], group["mse"]["before_cell"] / 100)
            self.assertAlmostEqual(group["mse"]["after_cell"], group["mse"]["after_full"])
            self.assertEqual(len(group["predictions"]), group["test_count"])
        self.assertFalse(result["fitted_during_evaluation"])
        leaked = copy.deepcopy(test)
        leaked[0]["world"] = train[0]["world"]
        with self.assertRaisesRegex(ValueError, "overlap"):
            evaluate_decoders(artifact, leaked)
        changed = copy.deepcopy(train)
        changed[0]["teacher_after"] += .01
        with self.assertRaisesRegex(ValueError, "ineligible"):
            train_decoders(changed)

    def test_missing_event_support_remains_null(self):
        train = [row for row in decoder_pairs("train") if row["group"] == "event"]
        artifact = train_decoders(train)
        result = evaluate_decoders(artifact, decoder_pairs("test"))
        self.assertEqual(result["groups"]["recovery"]["status"], "no_eligible_training_pairs")
        self.assertIsNone(result["groups"]["recovery"]["mse"])
        self.assertEqual(evaluate_decoders(artifact, [])["groups"]["event"]["status"], "no_eligible_pairs")

    def test_pair_extraction_requires_real_contiguous_unchanged_history(self):
        public, s0 = fixture()
        s1, s2 = successor(public, s0, 1), successor(public, successor(public, s0, 1), 1)
        decisions = [dict(state=s0, after=s1, latent_index=7, latent_after=15,
                          teacher_belief=.5, completion=None, content=None, event=dict(event=True, recovery=False)),
                     dict(state=s1, after=s2, latent_index=15, latent_after=7,
                          teacher_belief=.5, completion=None, content=None, event=dict(event=False, recovery=True)),
                     dict(state=s2, latent_index=7, teacher_belief=.5)]
        episode = dict(world=public["id"], seed=3, decisions=decisions)
        runtime = SimpleNamespace(policy=SimpleNamespace(fit=7),
                                  representation=lambda public, state: np.full((17, 12), state["tick"]))
        result = extract_pairs(runtime, [episode], {public["id"]: public})
        self.assertEqual([p["group"] for p in result["pairs"]], ["event", "recovery"])
        failed = copy.deepcopy(episode)
        failed["decisions"][0]["completion"] = dict(failure=True)
        self.assertEqual(len(extract_pairs(runtime, [failed], {public["id"]: public})["pairs"]), 1)
        broken = copy.deepcopy(episode)
        broken["decisions"][0]["after"] = dict(s1, charges=.1)
        with self.assertRaisesRegex(ValueError, "contiguous"):
            extract_pairs(runtime, [broken], {public["id"]: public})


if __name__ == "__main__":
    unittest.main()
