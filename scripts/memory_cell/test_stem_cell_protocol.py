"""Accounting and protocol regressions; fixtures cannot certify task benefit."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from selector_head import Supervision
from stem_cell import StemHead
from stem_cell_cache import SharedFeatureCache
from stem_cell_protocol import (
    ARMS,
    CURVE,
    PHASES,
    oracle_sources,
    score_attempt,
    summarize,
    validate_census,
)
from test_stem_cell import Encoder, Pool, Query, features, training_cut


def attempt(arm="frozen_rerank", qid="q", source=0, answer=0.0, status="succeeded"):
    return dict(
        stage=16,
        phase="test",
        question_id=qid,
        family="family",
        arm=arm,
        status=status,
        source_choice_correct=source,
        diagnostic_answer_f1=answer,
        citation_structure=dict(
            markers=0, delivered_markers=0, semantic_precision=None
        ),
    )


class ProtocolTests(unittest.TestCase):
    def test_no_new_prototype_data_is_explicit_noop_not_fake_update(self):
        head = StemHead(4, "encoder-v1", kind="prototype")
        row = Supervision(features(), (0,))
        head.fit((row,), training_cut(), revoked=set())
        before = head.export()
        receipt = head.fit((row,), training_cut(), revoked=set())
        self.assertEqual(head.export(), before)
        self.assertEqual(receipt["consumed_steps"], 0)
        self.assertEqual(receipt["tensor_delta_squared_norm"], 0.0)
        self.assertEqual(receipt["no_update_reason"], "no-new-prototype-examples")
        self.assertFalse(head.quarantined)

    def test_counter_change_is_not_weight_learning(self):
        head = StemHead(4, "encoder-v1", kind="linear")
        row = Supervision(features(), (0,))
        receipt = head.fit((row,), training_cut(), revoked=set(), steps=8)
        self.assertGreater(receipt["tensor_delta_squared_norm"], 0)
        self.assertTrue(receipt["state_changed"])
        self.assertEqual(receipt["trainable_parameters"], 10)

    def test_cache_hit_checks_encoder_training_lineage_not_just_current_evidence(self):
        encoder = Encoder()
        encoder.roots = {"old-training-root"}
        cache = SharedFeatureCache(encoder)
        cache.encode(Query(), "family", Pool(), revoked=set())
        with self.assertRaises(ValueError):
            cache.encode(Query(), "family", Pool(), revoked={"old-training-root"})
        self.assertEqual(encoder.calls, 1)

    def test_reader_failure_does_not_erase_observed_selector_success(self):
        item = dict(status="failed", selected=0)
        with patch("stem_cell_protocol.correctness", return_value=1):
            result = score_attempt(item, object(), object())
        self.assertEqual(result["source_choice_correct"], 1)
        self.assertEqual(result["diagnostic_answer_f1"], 0.0)
        self.assertIsNone(result["citation_structure"]["semantic_precision"])

    def test_failed_attempt_stays_in_answer_denominator(self):
        rows = [attempt(answer=1.0, source=1), attempt(qid="other", status="failed")]
        metrics = summarize(rows)["metrics"]["16/test/frozen_rerank"]
        self.assertEqual(metrics["attempted"], 2)
        self.assertEqual(metrics["failed"], 1)
        self.assertEqual(metrics["diagnostic_f1"], 0.5)
        self.assertEqual(metrics["answer_all_planned_bounds"], [0.5, 0.5])
        self.assertIsNone(metrics["citation_structural_precision"])

    def test_unknown_scores_expand_bounds_without_dropping_family(self):
        rows = [
            attempt(source=None, answer=None),
            attempt(arm="gated", source=1, answer=1),
        ]
        result = summarize(rows)
        base = result["metrics"]["16/test/frozen_rerank"]
        contrast = result["contrasts"]["16/test/gated"]
        self.assertEqual(base["source_all_planned_bounds"], [0.0, 1.0])
        self.assertEqual(contrast["family_count"], 1)
        self.assertEqual(contrast["all_planned_family_delta_bounds"], [0.0, 1.0])
        self.assertEqual(contrast["simultaneous_conditional_95_interval"], [-1.0, 1.0])
        self.assertFalse(contrast["superiority_claim"])

    def test_repeated_questions_do_not_become_independent_families(self):
        rows = [
            attempt(arm=arm, qid=f"q-{i}", source=int(arm == "gated"))
            for arm in ("frozen_rerank", "gated")
            for i in range(20)
        ]
        contrast = summarize(rows)["contrasts"]["16/test/gated"]
        self.assertEqual(contrast["family_count"], 1)
        self.assertEqual(contrast["simultaneous_conditional_95_interval"], [-1.0, 1.0])

    def test_missing_duplicate_and_relabelled_census_rejects(self):
        plan = dict(
            questions={p: [p] for p in PHASES},
            question_families={p: "family" for p in PHASES},
        )
        rows = [
            dict(
                stage=s, phase=p, question_id=p, arm=a, family="family", status="failed"
            )
            for s in CURVE
            for p in PHASES
            for a in ARMS
        ]
        self.assertEqual(validate_census(rows, plan)["recorded"], 72)
        invalid = [
            rows[:-1],
            rows + [rows[0]],
            [dict(rows[0], family="other")] + rows[1:],
        ]
        for bad in invalid:
            with self.assertRaises(ValueError):
                validate_census(bad, plan)

    def test_reference_span_is_original_source_not_inserted_answer(self):
        doc = SimpleNamespace(
            identity="source",
            root="root",
            scope="scope",
            observed_at=1,
            content="The planned destination was Paris. Keep the original statement.",
        )
        source = SimpleNamespace(history=lambda q: [doc])
        query = SimpleNamespace(observed_at=2)
        target = SimpleNamespace(
            unanswerable=False,
            unresolved_evidence=(),
            evidence=("source",),
            answer="Paris",
        )
        evidence, kind = oracle_sources(source, query, target)
        self.assertEqual(kind, "native-source-literal-span")
        item = evidence[0]
        self.assertEqual(
            item["excerpt"], doc.content[item["source_start"] : item["source_end"]]
        )
        target.answer = "Tokyo"
        missing, kind = oracle_sources(source, query, target)
        self.assertIsNone(missing)
        self.assertEqual(kind, "no-admitted-literal-reference-span")

    def test_future_source_cannot_be_privileged_reference(self):
        doc = SimpleNamespace(identity="source", observed_at=3, content="Paris")
        source = SimpleNamespace(history=lambda q: [doc])
        query = SimpleNamespace(observed_at=2)
        target = SimpleNamespace(
            unanswerable=False,
            unresolved_evidence=(),
            evidence=("source",),
            answer="Paris",
        )
        self.assertIsNone(oracle_sources(source, query, target)[0])


if __name__ == "__main__":
    unittest.main()
