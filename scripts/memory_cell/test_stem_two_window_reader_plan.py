"""Synthetic research controls; never count fixture outputs as QA gains."""

from dataclasses import asdict
import unittest

import torch

from native import Question, digest
from selector_head import Features
from selector_windows import Window, WindowBudget, WindowPool
from selector_answering import selected_window
from stem_two_window_reader_plan import prepare_second_window, compare_capacity_rows


def sample(*, same_root=False, scores=(8.0, 3.0)):
    q = Question("q", "family", "scope", "What happened?", "2024-01-01")
    inspected, windows = [], []
    for i, txt in enumerate(("Original alpha", "Original beta")):
        sid = "s" + str(i)
        root = "root0" if same_root else "root" + str(i)
        sha = digest(txt)
        inspected.append(dict(
            id=sid, root=root, scope="scope", observed_at="2023-01-01",
            excerpt=txt, inspected_sha256=sha,
        ))
        windows.append(Window(
            sid, root, "scope", "2023-01-01",
            0, len(txt.encode()), txt, sha,
        ))
    pool = WindowPool(
        query_digest=digest(asdict(q)), profile="query_windows",
        windows=tuple(windows), inspected=tuple(inspected),
        scanned_bytes=32, enumerated_windows=2, budget=WindowBudget(),
    )
    feature = Features(
        "q", "family", "frozen-encoder", pool.seal(),
        tuple(w.identity() for w in windows),
        frozenset(x["root"] for x in inspected),
        torch.zeros(2, 4), torch.tensor(scores),
    )
    first = list(selected_window(q, pool, feature, 0, set()))
    sessions = {"s0": "session-0", "s1": "session-1"}
    return q, pool, feature, first, sessions


def capacity_records():
    original, repeated, extended, targets = [], [], [], {}
    for phase in ("test", "transfer"):
        for n in range(8):
            q = phase + "-" + str(n)
            targets[q] = "correct"
            original.append(dict(phase=phase, question_id=q))
            base = dict(
                phase=phase, question_id=q,
                reader_identity="same-reader",
                reader_profile="same-prompt",
                reader_prompt_budget=dict(max_new_tokens=96, input_ceiling=1024),
                original_E1="pinned-first-window",
            )
            repeated.append(dict(base, status="succeeded", answer="wrong",
                                 delivered_sources=[{"id": "a"}]))
            extended.append(dict(base, status="succeeded", answer="correct",
                                 delivered_sources=[{"id": "a"}, {"id": "b"}]))
    return original, repeated, extended, targets


def score(answer, target):
    return float(answer == target)


class TwoWindowTests(unittest.TestCase):
    def test_same_frozen_top1_and_distinct_second_window(self):
        q, pool, f, first, sessions = sample()
        original, two, plan = prepare_second_window(q, pool, f, 0, first, sessions)
        self.assertEqual(original, tuple(first))
        self.assertEqual(len(two), 2)
        self.assertEqual(two[0]["label"], "E1")
        self.assertEqual(two[1]["label"], "E2")
        self.assertNotEqual(two[0]["root"], two[1]["root"])
        self.assertFalse(plan["second_selection_uses_gold"])

    def test_no_distinct_source_yields_unavailable_not_fake_gain(self):
        q, pool, f, first, sessions = sample(same_root=True)
        original, two, plan = prepare_second_window(q, pool, f, 0, first, sessions)
        self.assertEqual(tuple(first), original)
        self.assertEqual(two, ())
        self.assertEqual(plan["status"], "unavailable")

    def test_different_root_same_native_session_is_not_an_extra_session(self):
        q, pool, f, first, sessions = sample()
        sessions["s1"] = sessions["s0"]
        original, two, plan = prepare_second_window(
            q, pool, f, 0, first, sessions,
        )
        self.assertEqual(original, tuple(first))
        self.assertEqual(two, ())
        self.assertEqual(plan["status"], "unavailable")
        self.assertTrue(plan["selection_requires_distinct_native_sessions"])

    def test_selected_window_or_original_evidence_drift_fails(self):
        q, pool, f, first, sessions = sample()
        with self.assertRaisesRegex(ValueError, "top-1"):
            prepare_second_window(q, pool, f, 1, first, sessions)
        first[0]["excerpt"] = "rewritten"
        with self.assertRaisesRegex(ValueError, "E1"):
            prepare_second_window(q, pool, f, 0, first, sessions)

    def test_old_reader_context_binds_original_e1_and_same_budget(self):
        original, one, two, target = capacity_records()
        out = compare_capacity_rows(original, one, two, diagnose=score, targets=target)
        self.assertEqual(out["by_phase"]["transfer"]["attempted"], 8)
        self.assertEqual(out["by_phase"]["transfer"]["conditional_f1_delta_mean"], 1)
        self.assertEqual(out["by_phase"]["test"]["all_planned_f1_delta_bounds"], [1, 1])
        self.assertFalse(out["production_accepted"])

    def test_failure_or_no_second_window_remains_in_all_planned(self):
        original, one, two, target = capacity_records()
        two[0] = dict(two[0], status="failed")
        out = compare_capacity_rows(original, one, two, diagnose=score, targets=target)
        self.assertEqual(out["by_phase"]["test"]["reader_comparable_scored_pairs"], 7)
        self.assertEqual(out["by_phase"]["test"]["all_planned_f1_delta_bounds"],
                         [0.75, 1])
        two[0] = dict(two[0], status="unavailable")
        out = compare_capacity_rows(original, one, two, diagnose=score, targets=target)
        self.assertEqual(out["by_phase"]["test"]["second_window_unavailable"], 1)

    def test_changing_reader_prompt_or_existing_e1_is_not_causal_pair(self):
        for key, value in (("reader_profile", "wrong"),
                           ("original_E1", "altered"),
                           ("reader_prompt_budget", dict(max_new_tokens=200))):
            original, one, two, target = capacity_records()
            two[0] = dict(two[0], **{key: value})
            with self.subTest(field=key), self.assertRaises(ValueError):
                compare_capacity_rows(original, one, two, diagnose=score, targets=target)

    def test_missing_duplicate_and_corrupt_score_fail_closed(self):
        original, one, two, target = capacity_records()
        with self.assertRaises(ValueError):
            compare_capacity_rows(original, one[:-1], two, diagnose=score, targets=target)
        with self.assertRaises(ValueError):
            compare_capacity_rows(original, one, two[:-1]+[two[0]],
                                  diagnose=score, targets=target)
        q, pool, f, first, sessions = sample(scores=(float("nan"), 3.0))
        with self.assertRaisesRegex(ValueError, "logits"):
            prepare_second_window(q, pool, f, 0, first, sessions)


if __name__ == "__main__":
    unittest.main()
