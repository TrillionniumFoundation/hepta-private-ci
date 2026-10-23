"""Behavioral checks for real sparse memory retrieval and evidence isolation."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from audit_memory_retrieval import (
    _audit_summary,
    _verify_audit_summary,
    verify_report_slices,
    verify_row_scoring,
)
from memory_retrieval_data import Corpus, Gold, Query, Turn, decode_source, load_source
from memory_retrieval_probe import MAX_CONTEXT_BYTES, MAX_TURNS, RetrievalIndex, pack_context
from memory_retrieval_scoring import paired_group_interval, score_query, summarize


def source():
    return [{"sample_id": "conversation-a", "conversation": {
        "speaker_a": "Ada", "speaker_b": "Ben", "session_1_date_time": "3 May 2023",
        "session_1": [{"dia_id": "D1:1", "speaker": "Ada", "text": "I planted oak trees by the library."},
                      {"dia_id": "D1:2", "speaker": "Ben", "text": "That was on Tuesday."},
                      {"dia_id": "D1:3", "speaker": "Ada", "text": "The sailing club is open."}],
        "session_2_date_time": "4 May 2023",
        "session_2": [{"dia_id": "D2:1", "speaker": "Ben", "text": "I cooked pasta."}]},
        "qa": [{"question": "When were the oak trees planted?", "category": 2,
                "answer": "Tuesday", "evidence": ["D1:1", "D1:2"]}],
        "observation": {"hidden": "canary-answer"}, "session_summary": {}, "event_summary": {}}]


class MemoryRetrievalProbeTests(unittest.TestCase):
    def test_gold_mutation_cannot_change_query_index_or_predictions(self):
        raw, changed = source(), source()
        changed[0]["qa"][0].update(answer="poison", category=5, evidence=["unknown"])
        changed[0]["observation"] = {"hidden": "poison"}
        a_corpus, a_query, _ = decode_source(raw)
        b_corpus, b_query, _ = decode_source(changed)
        self.assertEqual((a_corpus, a_query), (b_corpus, b_query))
        first, second = RetrievalIndex(a_corpus["conversation-a"]), RetrievalIndex(b_corpus["conversation-a"])
        a, b = first.retrieve(a_query[0], .5, episodic=True), second.retrieve(b_query[0], .5, episodic=True)
        a.pop("query_latency_ns")
        b.pop("query_latency_ns")
        self.assertEqual(a, b)
        first.db.close()
        second.db.close()

    def test_real_fts_stemming_and_episodic_neighbor_behavior(self):
        corpora, queries, _ = decode_source(source())
        index = RetrievalIndex(corpora["conversation-a"])
        turn = index.retrieve(queries[0], 0)
        episode = index.retrieve(queries[0], 0, episodic=True)
        self.assertEqual(turn["selected_ids"], ["D1:1"])
        self.assertEqual(episode["selected_ids"], ["D1:1", "D1:2"])
        self.assertNotIn("D2:1", episode["selected_ids"])
        index.db.close()

    def test_context_budget_counts_utf8_frames_and_never_truncates_sources(self):
        turns = tuple(Turn(f"D1:{i}", "session_1", i, "名字", "today", "海" * 100, False) for i in range(20))
        corpus = Corpus("g", turns)
        result, text = pack_context(corpus, list(range(20)))
        self.assertEqual(result["context_bytes"], len(text.encode()))
        self.assertLessEqual(result["context_bytes"], MAX_CONTEXT_BYTES)
        self.assertEqual(result["selected_turns"], MAX_TURNS)
        huge = replace(turns[0], text="x" * (MAX_CONTEXT_BYTES + 1))
        result, _ = pack_context(Corpus("g", (huge, turns[1])), [0, 1])
        self.assertEqual(result["selected_ids"], [turns[1].source_id])
        self.assertEqual(result["budget_skipped_candidates"], 1)

    def test_source_scope_and_empty_query_do_not_fall_back_to_other_memory(self):
        corpora, queries, _ = decode_source(source())
        index = RetrievalIndex(corpora["conversation-a"])
        with self.assertRaises(ValueError):
            index.retrieve(replace(queries[0], group="wrong-conversation"), 1)
        self.assertEqual(index.retrieve(replace(queries[0], text="the and what"), 1)["selected_ids"], [])
        index.db.close()

    def test_unresolved_and_adversarial_annotations_preserve_question_census(self):
        raw = source()
        raw[0]["qa"].extend([
            {"question": "Malformed reference?", "category": 1, "evidence": ["D1:1; D1:2"]},
            {"question": "Adversarial question?", "category": 5, "evidence": ["D1:1"]},
            {"question": "Missing annotation?", "category": 4, "evidence": []}])
        _, queries, gold = decode_source(raw)
        rows = [score_query(q, gold[q.query_id], ["D1:1", "D1:2"]) for q in queries]
        metrics = summarize(rows)
        self.assertEqual(metrics["planned_questions"], 4)
        self.assertEqual(metrics["scorable_support_questions"], 1)
        self.assertEqual(metrics["unresolved_or_missing_questions"], 2)
        self.assertEqual(rows[1]["unresolved_evidence"], ["D1:1; D1:2"])
        self.assertIsNone(rows[2]["support_recall"])

    def test_duplicate_source_ids_and_changed_source_pin_reject(self):
        raw = source()
        raw[0]["conversation"]["session_1"][1]["dia_id"] = "D1:1"
        with self.assertRaises(ValueError):
            decode_source(raw)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            path.write_text("[]")
            with self.assertRaises(ValueError):
                load_source(path)

    def test_independent_audit_rejects_partial_support_score_tampering(self):
        row = {"accepted": True, "gold_evidence_count": 2,
               "support_recall": 0.5, "all_support_recalled": 0,
               "any_support_recalled": 1, "answerability_screen_correct": 1}
        def verify(candidate):
            verify_row_scoring(candidate, {"D1:1", "D1:2"}, ["D1:1"], "scorable", 2)
        verify(row)
        for field, value in (
                ("support_recall", 1.0), ("all_support_recalled", 1),
                ("any_support_recalled", 0), ("any_support_recalled", True),
                ("gold_evidence_count", 1), ("gold_evidence_count", True),
                ("answerability_screen_correct", 0),
                ("answerability_screen_correct", True),
                ("accepted", False), ("accepted", 1), ("accepted", "true")):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                changed = deepcopy(row)
                changed[field] = value
                verify(changed)

    def test_independent_audit_rejects_boolean_full_recall(self):
        full = {"accepted": True, "gold_evidence_count": 1,
                "support_recall": 1.0, "all_support_recalled": 1,
                "any_support_recalled": 1, "answerability_screen_correct": 1}
        verify_row_scoring(full, {"D1:1"}, ["D1:1"], "scorable", 2)
        for value in (True, 1):
            with self.subTest(value=value), self.assertRaises(ValueError):
                verify_row_scoring({**full, "support_recall": value},
                                   {"D1:1"}, ["D1:1"], "scorable", 2)

    def test_independent_audit_preserves_unscored_and_abstained_rows(self):
        adversarial = {"accepted": False, "gold_evidence_count": 1,
            "support_recall": None, "all_support_recalled": None,
            "any_support_recalled": None, "answerability_screen_correct": 1}
        verify_row_scoring(adversarial, {"D1:1"}, [], "adversarial", 5)
        verify_row_scoring({**adversarial, "answerability_screen_correct": 0},
                           {"D1:1"}, [], "unresolved", 2)
        for field, value in (("support_recall", 0.0),
                             ("all_support_recalled", 0),
                             ("any_support_recalled", 0)):
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_row_scoring({**adversarial, field: value},
                                   {"D1:1"}, [], "adversarial", 5)
        missing = {**adversarial, "gold_evidence_count": 0,
                   "answerability_screen_correct": 0}
        verify_row_scoring(missing, set(), [], "missing", 2)
        with self.assertRaises(ValueError):
            verify_row_scoring({**missing, "all_support_recalled": 1},
                               set(), [], "missing", 2)

    def test_cluster_interval_is_paired_and_uses_source_groups(self):
        query = Query("a:1", "a", "x")
        expected = Gold(4, ("D1:1",), (), False)
        # Different questions can share one source family; repeated query
        # identities cannot masquerade as additional paired observations.
        cohort = [replace(query, query_id=f"a:{i}") for i in range(100)]
        left = [score_query(q, expected, ["D1:1"]) for q in cohort]
        right = [score_query(q, expected, []) for q in cohort]
        result = paired_group_interval(left, right, samples=100)
        self.assertEqual(result["groups"], 1)
        self.assertEqual(result["percentile_95_interval"], [1.0, 1.0])
        self.assertFalse(result["superiority_established"])
        changed = deepcopy(right)
        changed[0]["query_id"] = "changed"
        with self.assertRaises(ValueError):
            paired_group_interval(left, changed)
        # Same question IDs alone cannot authenticate a paired cohort.
        for field, value in (("group", "different-root"), ("category", 5),
                             ("annotation_status", "adversarial"),
                             ("gold_evidence_count", 2), ("evidence_has_image", True),
                             ("unresolved_evidence", ["forged-source"])):
            altered = deepcopy(right)
            altered[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                paired_group_interval(left, altered, samples=100)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            paired_group_interval([left[0], left[0]], [right[0], right[0]], samples=100)
        for count in (0, -1, 10001, False, 1.0):
            with self.subTest(samples=count), self.assertRaises(ValueError):
                paired_group_interval(left[:1], right[:1], samples=count)


    @staticmethod
    def _summary_fixture():
        def row(arm, group, category, recall, accepted, image=False):
            scorable = category != 5
            return {
                "arm": arm, "group": group, "category": category,
                "annotation_status": "scorable" if scorable else "adversarial",
                "support_recall": recall if scorable else None,
                "all_support_recalled": int(recall == 1) if scorable else None,
                "any_support_recalled": int(recall > 0) if scorable else None,
                "accepted": accepted, "evidence_has_image": image,
            }

        rows = [
            row("a", "source1", 2, 1.0, True, True),
            row("a", "source2", 2, 0.0, False),
            row("a", "source2", 5, None, False),
            row("b", "source1", 2, 0.5, True, True),
            row("b", "source2", 5, None, True),
        ]
        partitions = {"train": ["source1"], "holdout": ["source2"]}
        arms = ["a", "b"]
        results = {}
        for split, groups in {**partitions,
                              "full_census": ["source1", "source2"]}.items():
            results[split] = {}
            for arm in arms:
                subset = [r for r in rows if r["arm"] == arm and r["group"] in groups]
                results[split][arm] = {
                    "overall": _audit_summary(subset),
                    "by_category": {
                        str(c): _audit_summary([r for r in subset if r["category"] == c])
                        for c in {r["category"] for r in subset}
                    },
                    "by_source_group": {
                        group: _audit_summary([r for r in subset if r["group"] == group])
                        for group in {r["group"] for r in subset}
                    },
                    "image_evidence_slice": _audit_summary(
                        [r for r in subset if r["evidence_has_image"]]
                    ),
                }
        return rows, partitions, arms, results

    def test_independent_summary_hand_computed_and_complete_slices(self):
        rows, partitions, arms, result = self._summary_fixture()
        first = _audit_summary(rows[:3])
        self.assertEqual(first["planned_questions"], 3)
        self.assertEqual(first["scorable_support_questions"], 2)
        self.assertEqual(first["adversarial_questions"], 1)
        self.assertEqual(first["support_recall"], 0.5)
        self.assertEqual(first["group_macro_all_support"], 0.5)
        self.assertEqual(first["acceptance_rate"], 1 / 3)
        self.assertEqual(first["answerability_balanced_accuracy"], 0.75)
        verify_report_slices(result, rows, partitions, arms)

    def test_independent_audit_rejects_forged_report_slices(self):
        rows, partitions, arms, original = self._summary_fixture()
        tampering = [
            ("full_census", "a", "overall", "acceptance_rate"),
            ("full_census", "a", "overall", "support_recall"),
            ("full_census", "a", "overall", "answerability_balanced_accuracy"),
            ("holdout", "b", "by_category", "5", "adversarial_questions"),
            ("holdout", "a", "by_source_group", "source2", "all_support_recalled"),
            ("train", "a", "image_evidence_slice", "support_recall"),
        ]
        for path in tampering:
            altered = deepcopy(original)
            record = altered
            for item in path[:-1]:
                record = record[item]
            value = record[path[-1]]
            record[path[-1]] = 0.3 if value is None else value + 0.123
            with self.subTest(path=path), self.assertRaises(ValueError):
                verify_report_slices(altered, rows, partitions, arms)
        for slice_name in (
            "overall", "by_category", "by_source_group", "image_evidence_slice"
        ):
            altered = deepcopy(original)
            altered["full_census"]["a"].pop(slice_name)
            with self.subTest(missing=slice_name), self.assertRaises(ValueError):
                verify_report_slices(altered, rows, partitions, arms)

    def test_independent_audit_rejects_wrong_types_and_missingness(self):
        rows, partitions, arms, result = self._summary_fixture()
        original = result["full_census"]["a"]["overall"]
        for name, value in (
            ("planned_questions", True), ("acceptance_rate", True),
            ("acceptance_rate", "1.0"), ("support_recall", float("nan")),
        ):
            altered = {**original, name: value}
            with self.subTest(field=name, value=value), self.assertRaises(ValueError):
                _verify_audit_summary(
                    altered, [r for r in rows if r["arm"] == "a"], "test"
                )
        empty = result["holdout"]["a"]["image_evidence_slice"]
        self.assertEqual(empty["planned_questions"], 0)
        self.assertIsNone(empty["support_recall"])
        altered = deepcopy(result)
        altered["holdout"]["a"]["image_evidence_slice"]["support_recall"] = 0.0
        with self.assertRaises(ValueError):
            verify_report_slices(altered, rows, partitions, arms)


if __name__ == "__main__":
    unittest.main()
