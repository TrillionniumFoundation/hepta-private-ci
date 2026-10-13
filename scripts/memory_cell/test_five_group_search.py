"""Group-controller regression tests. All weights/observations are FIXTURES.

These tests never assert pretrained reasoning, human review or model efficacy.
"""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

import torch
from torch import nn

import five_group_search as g
import five_causal_experiments as c
from experiments.shared_stem_cell.execution import parameters


def request(n=3):
    return {"question": "Fixture question", "options": [], "evidence": [
        {"id": f"E{i}", "modality": "text", "text": f"Fixture evidence {i}",
         "asset_sha256": None, "position": i} for i in range(n)]}


def example(identifier="r1", split="train"):
    return {"id": identifier, "split": split, "history": [[0.1, 0.2]],
            "view": [0.3, 0.4], "answer": [0.7, 0.8], "outcome": 0.95,
            "outcome_receipt_sha256": c.digest("fixture-outcome")}


class FixedCell(nn.Module):
    """Instrumented controller for exact control/call-budget unit tests."""
    width, hidden = 2, 2
    def __init__(self):
        super().__init__()
        self.anchor = nn.Parameter(torch.tensor(0.8), requires_grad=False)
        self.histories, self.advances = [], 0

    def initial(self):
        return torch.zeros(2)

    def advance(self, observed, state):
        self.advances += 1
        return state + 1

    def predict(self, candidates, state):
        self.histories.append(state.clone())
        return self.anchor.expand(len(candidates))

    def judge(self, view, answer):
        return torch.tensor(0.2)


class Ports:
    def __init__(self, fail_at=None):
        self.encodes, self.reads, self.events = [], [], []
        self.fail_at = fail_at

    def encode(self, texts):
        self.encodes.append(list(texts))
        return torch.tensor([[0.2, 0.4] for _ in texts], dtype=torch.float32)

    def read(self, view):
        self.reads.append(deepcopy(view))
        if len(self.reads) == self.fail_at:
            raise RuntimeError("fixture post-dispatch failure")
        return {"answer": "fixture raw answer " + str(len(self.reads))}

    def run(self, cell=None, mode="learned_recurrent", maximum_calls=3, **kw):
        return g.search_views(request(), cell or FixedCell(), self.encode, self.read,
                              mode=mode, maximum_calls=maximum_calls,
                              call_cost=kw.get("call_cost", 0.1), threshold=kw.get("threshold", 0.8),
                              seed=17, deadline=kw.get("deadline", time.perf_counter()+30), emit=self.events.append)


class GroupTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)

    def test_geometry_is_bounded(self):
        for width, hidden in ((0, 2), (8193, 2), (2, 0), (2, 129), (True, 2)):
            with self.assertRaises(c.Invalid):
                g.GroupValueCell(width, hidden)

    def test_shared_recurrent_geometry_and_finite_outputs(self):
        model = g.GroupValueCell(4, 3)
        state = model.advance(torch.ones(4), model.initial())
        self.assertEqual(tuple(state.shape), (3,))
        predicted = model.predict(torch.randn(5, 4), state)
        self.assertEqual(tuple(predicted.shape), (5,))
        self.assertTrue(bool(((predicted >= 0) & (predicted <= 1)).all()))
        self.assertEqual(model.judge(torch.ones(4), torch.zeros(4)).ndim, 0)

    def test_real_optimizer_changes_candidate_not_selected(self):
        model = g.GroupValueCell(2, 3).eval().requires_grad_(False)
        before = parameters(model)
        candidate, receipt = g.fit_group(model, [example()], steps=8, learning_rate=0.02)
        self.assertEqual(parameters(model), before)
        self.assertNotEqual(parameters(candidate), before)
        self.assertEqual(receipt["steps"], 8)
        self.assertEqual(receipt["new_reader_calls"], 0)
        self.assertEqual(receipt["optimizer_state_tensor_bytes"], 0)
        self.assertTrue(all(not p.requires_grad and p.grad is None for p in candidate.parameters()))
        self.assertFalse(receipt["general_fbsde"])
        self.assertFalse(receipt["independent_outcome_authenticity_verified"])

    def test_future_labels_never_enter_optimizer(self):
        for split in ("validation", "confirmation", "retention"):
            with self.assertRaises(c.Invalid):
                g.fit_group(g.GroupValueCell(2), [example(split=split)], steps=1)

    def test_duplicate_observations_rejected(self):
        with self.assertRaises(c.Invalid):
            g.fit_group(g.GroupValueCell(2), [example(), example()], steps=1)

    def test_unknown_unobserved_outcome_not_imputed(self):
        for outcome in (None, True, -0.1, 1.1, float("nan")):
            row = example(); row["outcome"] = outcome
            with self.assertRaises(c.Invalid):
                g.fit_group(g.GroupValueCell(2), [row], steps=1)

    def test_outcome_receipt_required(self):
        row = example(); row["outcome_receipt_sha256"] = ""
        with self.assertRaises(c.Invalid):
            g.fit_group(g.GroupValueCell(2), [row], steps=1)

    def test_inference_tensor_is_copied_before_learning(self):
        with torch.inference_mode():
            value = torch.tensor([1.0, 2.0])
        owned = g.checked_tensor(value, 2)
        self.assertFalse(owned.is_inference())
        owned.add_(1)
        self.assertTrue(torch.equal(value, torch.tensor([1.0, 2.0])))

    def test_training_support_cannot_contain_nan_or_wrong_dimensions(self):
        for bad in ([0.1], [float("nan"), 0.2]):
            row = example(); row["view"] = bad
            with self.assertRaises(c.Invalid):
                g.fit_group(g.GroupValueCell(2), [row], steps=1)

    def test_history_is_bounded(self):
        row = example(); row["history"] *= 17
        with self.assertRaises(c.Invalid):
            g.fit_group(g.GroupValueCell(2), [row], steps=1)

    def test_empty_history_is_valid(self):
        row = example(); row["history"] = []
        _, receipt = g.fit_group(g.GroupValueCell(2), [row], steps=1)
        self.assertEqual(receipt["examples"], 1)

    def test_train_plan_saves_and_reloads_exact_tensors(self):
        rows = [example()]
        plan = {"schema": "hepta.five-group.training.v1", "data_kind": "historical_development",
                "examples": rows, "dataset_sha256": c.digest(rows), "encoder_snapshot_sha256": c.digest("fixture-encoder"),
                "seed": 17, "width": 2, "hidden": 3, "steps": 2, "learning_rate": 0.02}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "candidate"
            receipt = g.train_plan(plan, output)
            self.assertEqual(receipt["checkpoint_sha256"], c.file_sha(output/"group.safetensors"))
            self.assertTrue(receipt["reload_verified"])
            with self.assertRaises(FileExistsError):
                g.train_plan(plan, output)

    def test_training_hash_must_bind_actual_examples(self):
        plan = {"schema": "hepta.five-group.training.v1", "data_kind": "historical_development",
                "examples": [example()], "dataset_sha256": "a"*64, "encoder_snapshot_sha256": "b"*64}
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(c.Invalid):
                g.train_plan(plan, Path(directory)/"out")


class EvidenceMenuTests(unittest.TestCase):
    def test_actual_views_and_original_source_identifiers(self):
        original = request(4); saved = deepcopy(original)
        views = g.evidence_views(original)
        self.assertEqual(len(views), 11)
        self.assertEqual(views[0]["evidence"], [])
        self.assertEqual([e["id"] for e in views[-1]["evidence"]], ["E2", "E3"])
        views[-1]["evidence"][0]["text"] = "changed private view"
        self.assertEqual(original, saved)

    def test_all_controls_have_real_distinct_action_inputs(self):
        views = g.evidence_views(request(8))
        self.assertEqual(len(views), 37)
        self.assertEqual(len({c.digest(v) for v in views}), 37)

    def test_gold_or_review_annotations_are_rejected(self):
        for key in ("gold_answer", "human_sufficient", "arm"):
            r = request(); r[key] = "fixture"
            with self.assertRaises(c.Invalid):
                g.evidence_views(r)

    def test_no_silent_media_to_text_conversion(self):
        r = request(); r["evidence"][0].update(modality="video", text="", asset_sha256="a"*64)
        with self.assertRaises(c.Invalid):
            g.evidence_views(r)

    def test_zero_or_excessive_sources_are_rejected(self):
        for n in (0, 9):
            with self.assertRaises(c.Invalid):
                g.evidence_views(request(n))


class ControlTests(unittest.TestCase):
    def choose(self, mode, values=(0.4, 0.9), incumbent=0.2, cost=0.1, threshold=0.8):
        return g.choose_next(mode, [1, 2], list(values), incumbent, cost=cost, threshold=threshold,
                             seed=17, round_index=0, views=g.evidence_views(request()))

    def test_ndu_one_step_gain_minus_registered_cost(self):
        self.assertEqual(self.choose("ndu_allocation"), 2)
        self.assertIsNone(self.choose("ndu_allocation", incumbent=0.8, cost=0.2))

    def test_fixed_budget_does_not_stop_on_utility(self):
        self.assertEqual(self.choose("fixed_budget", incumbent=0.95, cost=1), 2)

    def test_threshold_control_is_independent_of_ndu_cost(self):
        self.assertIsNone(self.choose("threshold_rule", incumbent=0.9))
        self.assertEqual(self.choose("threshold_rule", cost=1), 2)

    def test_shuffled_value_control_changes_ranking_without_new_values(self):
        self.assertEqual(self.choose("fixed_budget"), 2)
        self.assertEqual(self.choose("shuffled_utility"), 1)

    def test_unregistered_control_and_nonfinite_values_rejected(self):
        for mode, values in (("something_no_ndu", [0.1, 0.2]), ("ndu_allocation", [float("nan"), 0.2])):
            with self.assertRaises(c.Invalid):
                self.choose(mode, values)

    def test_deterministic_independent_attempt_order(self):
        self.assertEqual(self.choose("independent_attempts"), self.choose("independent_attempts"))

    def test_each_system2_arm_pays_same_reader_request_cap(self):
        for mode in c.ARMS["system2"]:
            ports = Ports()
            report = ports.run(mode=mode)
            self.assertEqual(len(ports.reads), 3)
            self.assertEqual(ports.reads[0]["evidence"], [])
            self.assertEqual(len({c.digest(r) for r in ports.reads}), 3)
            self.assertEqual(report["reader_requests"], 3)
            self.assertFalse(report["reasoning_gain_established"])

    def test_actual_answer_observation_updates_group_state(self):
        cell = FixedCell(); ports = Ports(); ports.run(cell=cell)
        self.assertEqual(cell.advances, 3)
        self.assertTrue(torch.equal(cell.histories[0], torch.ones(2)))
        self.assertTrue(torch.equal(cell.histories[1], torch.full((2,), 2.0)))
        self.assertTrue(any("fixture raw answer" in t for batch in ports.encodes for t in batch))

    def test_stateless_and_independent_controls_do_not_accumulate_memory(self):
        for mode in ("stateless", "independent_attempts", "fixed_search"):
            cell = FixedCell(); Ports().run(cell=cell, mode=mode)
            self.assertEqual(cell.advances, 0)
            self.assertTrue(all(torch.equal(h, torch.zeros(2)) for h in cell.histories))

    def test_ndu_stops_without_filling_budget_with_dummy_calls(self):
        ports = Ports(); report = ports.run(mode="ndu_allocation", call_cost=0.9)
        self.assertEqual(len(ports.reads), 1)
        self.assertEqual(report["stop_reason"], "estimated_value_stop")

    def test_threshold_stops_without_artificial_padding(self):
        ports = Ports(); report = ports.run(mode="threshold_rule", threshold=0.1)
        self.assertEqual(len(ports.reads), 1)
        self.assertEqual(report["stop_reason"], "fixed_confidence_stop")

    def test_final_raw_answer_selection_uses_common_judge_not_gold(self):
        ports = Ports(); report = ports.run()
        # Equal judged values keep the first raw answer deterministically.
        self.assertEqual(report["answer"], "fixture raw answer 1")
        self.assertEqual(report["selected_view"], 0)
        self.assertFalse(any("gold_answer" in r for r in ports.reads))

    def test_failed_reader_is_retained_and_never_retried(self):
        ports = Ports(fail_at=2)
        with self.assertRaises(RuntimeError):
            ports.run()
        self.assertEqual(len(ports.reads), 2)
        failed = [e for e in ports.events if e["event"] == "reader_failed_or_unknown"]
        self.assertEqual(len(failed), 1)
        self.assertFalse(failed[0]["retry_permitted"])

    def test_expired_deadline_makes_zero_neural_calls(self):
        ports = Ports()
        with self.assertRaises(c.Invalid):
            ports.run(deadline=time.perf_counter()-1)
        self.assertEqual(ports.encodes, [])
        self.assertEqual(ports.reads, [])

    def test_post_dispatch_deadline_is_not_a_success(self):
        ports = Ports()
        with patch.object(g.time, "perf_counter", side_effect=[1, 1, 1, 5, 5]):
            with self.assertRaises(c.Invalid):
                g.search_views(request(), FixedCell(), ports.encode, ports.read,
                               mode="fixed_budget", maximum_calls=3, call_cost=0.1, threshold=0.8,
                               seed=17, deadline=4, emit=ports.events.append)
        self.assertEqual(len(ports.reads), 1)
        self.assertTrue(any(e["event"] == "reader_failed_or_unknown" for e in ports.events))

    def test_invalid_budget_rejected_before_encode(self):
        for calls in (0, 9, True):
            ports = Ports()
            with self.assertRaises(c.Invalid):
                ports.run(maximum_calls=calls)
            self.assertEqual(ports.encodes, [])

    def test_input_feature_geometry_cannot_be_silently_changed(self):
        ports = Ports(); ports.encode = lambda texts: torch.zeros(len(texts), 3)
        with self.assertRaises(c.Invalid):
            ports.run()
        self.assertEqual(ports.reads, [])

    def test_runtime_parameters_remain_frozen(self):
        model = g.GroupValueCell(2, 3).eval().requires_grad_(False)
        before = parameters(model)
        Ports().run(cell=model)
        self.assertEqual(parameters(model), before)

    def test_actual_neural_controller_can_process_different_views(self):
        model = g.GroupValueCell(2, 3).eval().requires_grad_(False)
        report = Ports().run(cell=model, mode="fixed_search")
        self.assertEqual(report["reader_requests"], 3)
        self.assertEqual(report["profile"], g.PROFILE)


class AdmissionTests(unittest.TestCase):
    def test_missing_native_materials_are_not_replaced_with_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(c.Invalid):
                g.NativeGroupOwner(Path(directory), "a"*64)

    def test_unknown_stage_cannot_invoke_group_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(c.Invalid):
                g.run_registered({}, {}, {}, Path(directory), Path(directory)/"out", "multimodal")

    def test_full_existing_reader_gate_is_required(self):
        from test_five_causal_experiments import bundle_fixture, review_fixture
        bundle = bundle_fixture()
        review = review_fixture(bundle)
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(c.Invalid):
                g.run_registered(bundle, review, None, Path(directory), Path(directory)/"out", "ndu")
            self.assertFalse((Path(directory)/"out").exists())


if __name__ == "__main__":
    unittest.main()
