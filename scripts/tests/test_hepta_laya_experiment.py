"""Synthetic protocol/optimizer tests, not checkpoint or task efficacy evidence."""
from copy import deepcopy
from dataclasses import asdict, replace
import math
import unittest
from unittest.mock import patch

from scripts.hepta_laya_experiment import Budget, dataset_rows, distribution, experiment, train_head
from scripts.hepta_laya_retrieval import Rejected, digest
from scripts.tests.test_hepta_laya_retrieval import Port, source


def inputs():
    rows, labels = [], []
    for split, when in (("train", 10), ("calibration", 100), ("future", 200), ("retention", 1)):
        for i in range(2):
            row_id = f"{split}-{i}"
            query = f"evidence for {row_id}"
            rows.append({"row_id": row_id, "group_id": row_id, "split": split,
                         "event_at_ms": when, "query": query,
                         "sources": [asdict(source(text=query))]})
            labels.append({"row_id": row_id, "correct_source": "record-1", "observed_at_ms": when + 1})
    data = {"schema": "hepta.retrieval.dataset.v1", "workspace_id": "workspace-1",
            "objective_digest": digest("objective"), "rows": rows}
    outcomes = {"schema": "hepta.retrieval.annotations.v1", "observer_id": "annotation-owner",
                "dataset_digest": digest(data), "labels": labels}
    return data, outcomes


def repin(data, outcomes):
    outcomes["dataset_digest"] = digest(data)


def port():
    model = Port()
    model.maximum_input_tokens = 512
    return model


class ExperimentTests(unittest.TestCase):
    def test_report_binds_all_decisions_and_keeps_no_change_and_no_authority(self):
        data, outcomes = inputs()
        model = port()
        report = experiment(data, outcomes, model, Budget(minimum_train=2, epochs=3))
        self.assertEqual(set(report["metrics"]), {"lexical", "classifier", "laya_no_change", "laya_head"})
        self.assertEqual(len(report["decisions"]), 8)
        self.assertEqual(len(model.calls), 8)
        self.assertEqual(report["feature_collection_input_tokens"], 240)
        self.assertTrue(report["no_change_included"])
        self.assertFalse(report["production_authority"])
        self.assertFalse(report["observer_authenticated"])
        self.assertFalse(report["causal_or_longitudinal_efficacy"])
        self.assertEqual(report["adoption"], "not_selected")
        for state, questions in model.calls:
            for secret in ("correct_source", "annotation-owner", "observed_at_ms", '\"split\"'):
                self.assertNotIn(secret, state + str(questions))
        claimed = report.pop("report_digest")
        self.assertEqual(claimed, digest(report))

    def test_annotation_for_another_dataset_never_loads_or_calls_model(self):
        data, outcomes = inputs()
        outcomes["dataset_digest"] = digest("other")
        model = port()
        with self.assertRaises(Rejected):
            experiment(data, outcomes, model, Budget())
        self.assertEqual(model.calls, [])

    def test_unknown_input_fields_do_not_smuggle_labels_to_model(self):
        data, outcomes = inputs()
        data["rows"][0]["correct_source"] = "record-1"
        repin(data, outcomes)
        with self.assertRaises(Rejected):
            dataset_rows(data, outcomes)

    def test_all_partitions_are_required(self):
        data, outcomes = inputs()
        data["rows"] = [r for r in data["rows"] if r["split"] != "retention"]
        outcomes["labels"] = [r for r in outcomes["labels"] if not r["row_id"].startswith("retention")]
        repin(data, outcomes)
        with self.assertRaises(Rejected):
            dataset_rows(data, outcomes)

    def test_groups_must_not_cross_partitions(self):
        data, outcomes = inputs()
        data["rows"][2]["group_id"] = data["rows"][0]["group_id"]
        repin(data, outcomes)
        with self.assertRaises(Rejected):
            dataset_rows(data, outcomes)

    def test_normalized_queries_must_not_cross_partitions(self):
        data, outcomes = inputs()
        data["rows"][2]["query"] = '  ' + data["rows"][0]["query"].upper() + '  '
        repin(data, outcomes)
        with self.assertRaises(Rejected):
            dataset_rows(data, outcomes)

    def test_event_time_and_delayed_labels_are_checked(self):
        for label_index, timestamp in ((0, 100), (2, 201), (4, 199)):
            data, outcomes = inputs()
            outcomes["labels"][label_index]["observed_at_ms"] = timestamp
            with self.subTest(case=label_index), self.assertRaises(Rejected):
                dataset_rows(data, outcomes)

    def test_unmatched_duplicate_or_invalid_annotation_rejected(self):
        for mutate in (
            lambda labels: labels.append(deepcopy(labels[0])),
            lambda labels: labels.pop(),
            lambda labels: labels[0].update(correct_source="outside-candidate-set"),
            lambda labels: labels[0].update(observed_at_ms=True),
        ):
            data, outcomes = inputs()
            mutate(outcomes["labels"])
            with self.subTest(mutate=mutate), self.assertRaises(Rejected):
                dataset_rows(data, outcomes)

    def test_no_data_no_update_reuses_no_change_prediction(self):
        data, outcomes = inputs()
        report = experiment(data, outcomes, port(), Budget(minimum_train=100))
        self.assertEqual(report["head"]["status"], "no_update_insufficient_data")
        for split in ("future", "retention"):
            before, after = (report["metrics"][arm][split] for arm in ("laya_no_change", "laya_head"))
            for key in ("correct", "accuracy", "log_loss", "brier", "abstained"):
                self.assertEqual(before[key], after[key])

    def test_token_reservation_rejects_before_any_forward(self):
        data, outcomes = inputs()
        model = port()
        with self.assertRaises(Rejected):
            experiment(data, outcomes, model, Budget(max_total_input_tokens=511))
        self.assertEqual(model.calls, [])

    def test_token_budget_cannot_reset_between_rows(self):
        data, outcomes = inputs()
        model = port()
        with self.assertRaises(Rejected):
            experiment(data, outcomes, model, Budget(max_total_input_tokens=541))
        self.assertEqual(len(model.calls), 1)

    def test_model_cannot_understate_declared_token_limit(self):
        data, outcomes = inputs()
        model = port()
        model.raw["usage"]["input_tokens"] = 513
        with self.assertRaises(Rejected):
            experiment(data, outcomes, model, Budget())
        self.assertEqual(len(model.calls), 1)

    def test_budget_types_and_bounds(self):
        for changed in ({"epochs": 0}, {"minimum_train": True}, {"max_elapsed_ms": -1}):
            with self.subTest(changed=changed), self.assertRaises(Rejected):
                replace(Budget(), **changed).validate()

    def test_lost_model_response_stops_without_retry_or_partial_report(self):
        data, outcomes = inputs()
        model = port()
        with patch.object(model, "predict", side_effect=RuntimeError("unknown")) as call:
            with self.assertRaises(RuntimeError):
                experiment(data, outcomes, model, Budget())
            self.assertEqual(call.call_count, 1)


class HeadTests(unittest.TestCase):
    def records(self):
        return [{"split": split, "labels": (None, "source"), "correct_source": None,
                 "model_features": [(math.log(.1), 0., 1., 0.), (math.log(.9), 1., 0., 1.)],
                 "lexical_features": [(0., 0., 1., 0.), (0., 1., 0., 1.)]}
                for split in ("train", "train", "calibration", "future", "retention")]

    def test_candidate_is_real_parameter_update_reducing_training_loss(self):
        records = self.records()
        before = -math.log(distribution([1., 0., 0., 0.], records[0]["model_features"])[0])
        candidate = train_head(records, use_model=True, budget=Budget(minimum_train=2, epochs=20))
        after = -math.log(distribution(candidate["weights"], records[0]["model_features"])[0])
        self.assertLess(after, before)
        self.assertEqual(candidate["status"], "candidate_only")
        self.assertTrue(all(math.isfinite(w) and abs(w) <= 8 for w in candidate["weights"]))

    def test_future_and_retention_labels_never_train_or_calibrate_candidate(self):
        records = self.records()
        candidate = train_head(records, use_model=True, budget=Budget(minimum_train=2))
        for record in records:
            if record["split"] in ("future", "retention"):
                record["correct_source"] = "source"
        altered = train_head(records, use_model=True, budget=Budget(minimum_train=2))
        self.assertEqual(candidate["weights"], altered["weights"])
        self.assertEqual(candidate["temperature"], altered["temperature"])

    def test_simple_classifier_does_not_use_model_feature(self):
        candidate = train_head(self.records(), use_model=False, budget=Budget(minimum_train=2))
        self.assertEqual(candidate["weights"][0], 0.0)

    def test_training_deadline_is_checked_between_epochs(self):
        with self.assertRaises(Rejected):
            train_head(self.records(), use_model=True, budget=Budget(minimum_train=2), deadline_ns=0)

    def test_training_does_not_mutate_source_records(self):
        records = self.records()
        original = deepcopy(records)
        train_head(records, use_model=True, budget=Budget(minimum_train=2))
        self.assertEqual(records, original)


if __name__ == "__main__":
    unittest.main()
