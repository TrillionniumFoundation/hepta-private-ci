"""Adversarial tests for truly delivered candidate extraction and seal replay.

Synthetic source fixtures test mechanisms ONLY, not fresh model competence.
"""

import copy
import json
import unittest

from delivered_candidate_reader import frozen_selection, strict_rank, validate_raw_rows
from local_causal_reader import ABSTAIN, answer
from offline_event_reader_trial import ARMS
from offline_smol_reader import PROFILE


def source(
    identity,
    entity,
    attribute,
    value,
    *,
    scope="scope_a",
    revision=3,
    observed="2026-10-01T00:00:00Z",
    supersedes=None,
):
    payload = dict(
        schema="hepta.controlled-event.v1",
        id=identity,
        entity=entity,
        attribute=attribute,
        value=value,
        revision=revision,
        supersedes=supersedes if supersedes is not None else [],
    )
    return dict(
        identity=identity,
        root="root_a",
        scope=scope,
        session="session_a",
        observed_at=observed,
        content=json.dumps(payload),
    )


def pair():
    docs = {
        "first": source("first", "service_11111111", "component", "component_22222222"),
        "second": source("second", "component_22222222", "location", "site_33333333"),
        "distractor": source(
            "distractor", "component_99999999", "location", "site_77777777"
        ),
    }
    q = dict(
        identity="question-0",
        scope="scope_a",
        observed_at="2026-10-02T00:00:00Z",
        content=(
            "For service_11111111 at logical revision 3, "
            "what is the location of the assigned component?"
            " Reply with only the source-supported result."
        ),
    )
    controls = {arm: {"selected": ["first", "second"]} for arm in ARMS}
    controls["empty"]["selected"] = []
    controls["without_prerequisite"]["selected"] = ["second"]
    return dict(query=q, kind="composition", controls=controls), docs


def sealed_fixture():
    case, sources = pair()
    plan = dict(
        arms=list(ARMS),
        cases=[],
    )
    rows = []
    for i in range(8):
        current = copy.deepcopy(case)
        current["query"]["identity"] = f"question-{i}"
        plan["cases"].append(current)
        for arm in ARMS:
            control = frozen_selection(current, arm, sources)
            ranked = control["forced_choices"]
            scores = [
                dict(
                    value=v,
                    mean_log_likelihood=-0.25 - (index * 0.1),
                    token_count=1,
                    log_likelihood=-0.25 - index * 0.1,
                    token_digest="a" * 64,
                )
                for index, v in enumerate(ranked)
            ]
            rows.append(
                dict(
                    question_id=current["query"]["identity"],
                    arm=arm,
                    reader_identity="reader_a",
                    reader_profile=PROFILE,
                    status="succeeded",
                    selected=control["selected"],
                    original_source_hashes=control["original_source_hashes"],
                    evidence_only_candidates=control["evidence_only_candidates"],
                    forced_choices=ranked,
                    selection_digest=control["selection_digest"],
                    scores=scores,
                    chosen=strict_rank(scores, ranked)[0],
                    input_tokens=40,
                    input_digest="a" * 64,
                )
            )
    return plan, sources, rows


class DeliveredCandidatesTests(unittest.TestCase):
    def test_no_evidence_cannot_receive_scope_oracle(self):
        case, sources = pair()
        empty = frozen_selection(case, "empty", sources)
        self.assertEqual(empty["forced_choices"], [ABSTAIN])
        self.assertEqual(empty["evidence_only_candidates"], [])
        self.assertTrue(empty["no_global_answer_space_oracle"])

    def test_each_arm_only_sees_its_own_source_content(self):
        case, sources = pair()
        lesion = frozen_selection(case, "without_prerequisite", sources)
        self.assertEqual(lesion["evidence_only_candidates"], ["site_33333333"])
        self.assertEqual(len(lesion["original_source_hashes"]), 1)
        self.assertEqual(
            answer(case["query"], lesion["selected"], sources)["status"], "abstained"
        )
        # A missing prerequisite may still expose a plausible terminal answer.
        # Its candidate hit cannot be counted as a complete supported task.
        normal = frozen_selection(case, "organized", sources)
        self.assertEqual(normal["evidence_only_candidates"], ["site_33333333"])
        self.assertEqual(
            answer(case["query"], normal["selected"], sources)["status"], "answered"
        )

    def test_hidden_originals_have_no_effect_or_validation_side_channel(self):
        case, sources = pair()
        baseline = frozen_selection(case, "without_prerequisite", sources)
        sources["unseen"] = source(
            "unseen",
            "service_11111111",
            "location",
            "site_aaaaaaaa",
            observed="2999-01-01T00:00:00Z",
        )
        sources["first"]["content"] = "bad json"
        self.assertEqual(
            frozen_selection(case, "without_prerequisite", sources), baseline
        )

    def test_selected_future_and_scope_mismatch_fail_closed(self):
        case, docs = pair()
        case["controls"]["hybrid"]["selected"] = ["second"]
        for change, message in (
            ({"observed_at": "2999-01-01T00:00:00Z"}, "future observation"),
            ({"scope": "other_scope"}, "source scope"),
        ):
            altered = copy.deepcopy(docs)
            altered["second"].update(change)
            with self.subTest(change=change):
                with self.assertRaisesRegex(ValueError, message):
                    frozen_selection(case, "hybrid", altered)

    def test_logical_revision_filters_future_values(self):
        case, sources = pair()
        sources["second"]["content"] = source(
            "second", "component_22222222", "location", "site_eeeeeeee", revision=4
        )["content"]
        out = frozen_selection(case, "hybrid", sources)
        self.assertEqual(out["evidence_only_candidates"], [])
        self.assertEqual(out["forced_choices"], [ABSTAIN])

    def test_duplicate_selected_and_unknown_evidence_denied(self):
        case, sources = pair()
        case["controls"]["organized"]["selected"] = ["second", "second"]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            frozen_selection(case, "organized", sources)
        case["controls"]["organized"]["selected"] = ["not-found"]
        with self.assertRaisesRegex(ValueError, "not in original"):
            frozen_selection(case, "organized", sources)

    def test_forged_event_id_and_duplicate_field_denied(self):
        case, sources = pair()
        corrupt = copy.deepcopy(sources)
        corrupt["second"]["content"] = corrupt["second"]["content"].replace(
            '"id": "second"', '"id": "other"'
        )
        with self.assertRaisesRegex(ValueError, "invalid original controlled event"):
            frozen_selection(case, "hybrid", corrupt)
        corrupt = copy.deepcopy(sources)
        corrupt["second"]["content"] = (
            corrupt["second"]["content"][:-1] + ', "value": "site_ffffffff"}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            frozen_selection(case, "hybrid", corrupt)

    def test_option_ranking_protects_full_choice_census(self):
        values = ["site_00000000", ABSTAIN]
        scores = [
            dict(value=values[0], mean_log_likelihood=-0.2, token_count=2),
            dict(value=values[1], mean_log_likelihood=-0.1, token_count=5),
        ]
        self.assertEqual(strict_rank(scores, values)[0], ABSTAIN)
        with self.assertRaisesRegex(ValueError, "incomplete or duplicate"):
            strict_rank(scores[:1], values)
        tampered = copy.deepcopy(scores)
        tampered[0]["mean_log_likelihood"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid original"):
            strict_rank(tampered, values)

    def test_equal_likelihood_ties_are_precommitted_to_candidate_order(self):
        values = ["site_00000000", ABSTAIN]
        scores = [
            dict(value=v, mean_log_likelihood=-1.0, token_count=1) for v in values
        ]
        self.assertEqual(strict_rank(scores, values), values)

    def test_old_authored_48_source_only_replay_mechanics(self):
        plan, docs, rows = sealed_fixture()
        readback = validate_raw_rows(plan, docs, rows)
        self.assertEqual(readback["original_model_attempts"], 48)
        self.assertEqual(readback["new_model_calls"], 0)
        self.assertFalse(readback["production_accepted"])

    def test_original_journal_mutations_fail_closed(self):
        for mutant, expected in (
            (
                lambda v: v[0].update(forced_choices=["site_badbad01", ABSTAIN]),
                "answer-space tampered",
            ),
            (lambda v: v[0].update(chosen="site_ffffffff"), "score/ranking tampering"),
            (lambda v: v[0].update(reader_profile="other"), "model profile"),
            (lambda v: v[0].update(expected="site_33333333"), "annotation leaked"),
            (lambda v: v[0].update(status="failed"), "successful model scores"),
        ):
            plan, docs, rows = sealed_fixture()
            mutant(rows)
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    validate_raw_rows(plan, docs, rows)

    def test_missing_or_duplicate_original_model_call_denied(self):
        plan, docs, rows = sealed_fixture()
        with self.assertRaisesRegex(ValueError, "incomplete"):
            validate_raw_rows(plan, docs, rows[:-1])
        rows[1] = copy.deepcopy(rows[0])
        with self.assertRaisesRegex(ValueError, "missing/duplicate"):
            validate_raw_rows(plan, docs, rows)


if __name__ == "__main__":
    unittest.main()
