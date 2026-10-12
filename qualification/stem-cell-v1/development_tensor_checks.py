"""Explicit Torch-only mechanism tests; synthetic inputs, not pretrained quality.

Run separately from dependency-free discovery: python -m unittest
 development_tensor_checks. Missing Torch is a hard dependency failure here.
"""

from dataclasses import replace
import hashlib
import unittest

import torch
from torch.nn import functional as F

from development_tensors import (BasisCellHeads, checked_tensor, distill_shared_candidate,
                                dormancy_candidate, fit_cell_candidate,
                                merge_identical_candidate, parameter_digest, split_candidate)
from development_composition import SharedCellRecurrence, TemporalModalBridge
from development_control import (Continuation, GeneratedOutput, choose_continuation,
                                 evaluate_generated_outputs, paired_retention_diagnostic)
from development_trial import train_shared_head_trial
from shared_encoder_batch import SharedStemEngine
from test_shared_encoder_eviction import ToyBackend, request


def fixture_fit(torch_module, head, x, y, *, steps, seed):
    """Actual optimizer arithmetic, deliberately not an upstream/model claim."""
    optimizer = torch_module.optim.AdamW(head.parameters(), lr=0.03, weight_decay=0.01)
    for _ in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = F.cross_entropy(head(x), y)
        loss.backward()
        optimizer.step()


def fixture_head(torch_module, width, classes, kind, budget):
    head = torch_module.nn.Linear(width, classes)
    count = sum(p.numel() for p in head.parameters())
    if count > budget:
        raise ValueError("budget")
    return head, count


class TensorMechanisms(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.bank = BasisCellHeads(4, 2, 4, ("parent", "peer"), seed=81)
        self.x = torch.randn(32, 4, generator=torch.Generator().manual_seed(18))
        self.ids = torch.zeros(32, dtype=torch.long)

    def test_split_preserves_parent_and_child_exactly(self):
        old = parameter_digest(self.bank)
        child = split_candidate(self.bank, "parent", "child", maximum_local_parameters=27)
        self.assertTrue(torch.equal(self.bank(self.x, self.ids), child(self.x, self.ids)))
        self.assertTrue(torch.equal(child(self.x, self.ids), child(self.x, self.ids + 2)))
        self.assertEqual(parameter_digest(self.bank), old)
        self.assertEqual(child.generation, self.bank.generation + 1)
        self.assertEqual(child.parameter_counts()["shared"], self.bank.parameter_counts()["shared"])
        self.assertEqual(child.parameter_counts()["cell_local"] - self.bank.parameter_counts()["cell_local"], 9)

    def test_split_rejects_alias_and_budget(self):
        for name, budget in (("peer", 100), ("child", 26), ("", 100)):
            with self.subTest(name=name, budget=budget), self.assertRaises(ValueError):
                split_candidate(self.bank, "parent", name, maximum_local_parameters=budget)

    def test_exact_merge_recovers_function(self):
        child = split_candidate(self.bank, "parent", "child", maximum_local_parameters=27)
        merged = merge_identical_candidate(child, "child", "parent")
        self.assertEqual(merged.cell_ids, self.bank.cell_ids)
        self.assertEqual(parameter_digest(merged), parameter_digest(self.bank))

    def test_nonidentical_merge_refused(self):
        with torch.no_grad():
            self.bank.coefficients[1, 0] = 1
        with self.assertRaises(ValueError):
            merge_identical_candidate(self.bank, "peer", "parent")

    def test_dormancy_only_changes_next_candidate(self):
        candidate = dormancy_candidate(self.bank, "parent", awake=False)
        with self.assertRaises(ValueError):
            candidate(self.x, self.ids)
        self.bank(self.x, self.ids)
        awake = dormancy_candidate(candidate, "parent", awake=True)
        self.assertTrue(torch.equal(awake(self.x, self.ids), self.bank(self.x, self.ids)))

    def test_learning_changes_only_one_cell_including_weight_decay(self):
        with torch.no_grad():
            self.bank.coefficients[1].fill_(0.7)
            self.bank.gates[1].fill_(0.4)
        original = parameter_digest(self.bank)
        target = (self.x[:, 0] > 0).long()
        before = F.cross_entropy(self.bank(self.x, self.ids), target).item()
        candidate, receipt = fit_cell_candidate(self.bank, "parent", self.x, target,
                                                fit=fixture_fit, steps=150, seed=4)
        after = F.cross_entropy(candidate(self.x, self.ids), target).item()
        self.assertLess(after, before)
        self.assertEqual(parameter_digest(self.bank), original)
        self.assertTrue(torch.equal(candidate.coefficients[1], self.bank.coefficients[1]))
        self.assertTrue(torch.equal(candidate.gates[1], self.bank.gates[1]))
        self.assertTrue(torch.equal(candidate.basis, self.bank.basis))
        self.assertFalse(receipt["production_authorized"])

    def test_bad_training_labels_and_steps_rejected(self):
        for labels, steps in ((torch.zeros(32), 1), (torch.full((32,), 3), 1),
                              (torch.zeros(32, dtype=torch.long), 0)):
            with self.subTest(steps=steps), self.assertRaises(ValueError):
                fit_cell_candidate(self.bank, "parent", self.x, labels, fit=fixture_fit, steps=steps, seed=1)

    def test_distillation_reduces_teacher_kl_without_mutating_old_bank(self):
        teacher = torch.stack((-3*self.x[:, 0], 3*self.x[:, 0]), 1)
        original = parameter_digest(self.bank)
        def error(model):
            return F.kl_div(F.log_softmax(model(self.x, self.ids), 1), F.softmax(teacher, 1), reduction="batchmean").item()
        before = error(self.bank)
        candidate, report = distill_shared_candidate(self.bank, self.x, self.ids, teacher, steps=120)
        self.assertLess(error(candidate), before)
        self.assertEqual(parameter_digest(self.bank), original)
        self.assertTrue(torch.equal(candidate.coefficients, self.bank.coefficients))
        self.assertFalse(report["production_authorized"])

    def test_nonfinite_and_shape_inputs_rejected(self):
        for values in (torch.tensor([[float("nan")]]), torch.tensor([[float("inf")]]), torch.ones(0, 4)):
            with self.subTest(shape=values.shape), self.assertRaises(ValueError):
                checked_tensor(values, 2, "negative")
        with self.assertRaises(ValueError):
            self.bank(self.x, torch.ones(32, dtype=torch.long) * 99)

    def test_recurrence_reuses_parameters_and_external_state(self):
        module = SharedCellRecurrence(4)
        initial = torch.zeros(2, 4)
        tokens = self.x[:6].reshape(2, 3, 4)
        mask = torch.ones(2, 3, dtype=torch.bool)
        before = parameter_digest(module)
        a, one = module(tokens, mask, initial, depth=1)
        b, trace = module(tokens, mask, initial, depth=4)
        self.assertEqual((len(one), len(trace)), (1, 4))
        self.assertFalse(torch.equal(a, b))
        self.assertEqual(parameter_digest(module), before)
        self.assertTrue(torch.equal(initial, torch.zeros_like(initial)))
        b.sum().backward()
        self.assertIsNotNone(module.cell.weight_hh.grad)

    def test_masked_tokens_do_not_affect_recurrence(self):
        module = SharedCellRecurrence(4)
        tokens = torch.zeros(1, 2, 4)
        mask = torch.tensor([[True, False]])
        before, _ = module(tokens, mask, torch.zeros(1, 4), depth=3)
        tokens[:, 1] = 900
        after, _ = module(tokens, mask, torch.zeros(1, 4), depth=3)
        self.assertTrue(torch.equal(before, after))

    def test_recurrence_budget_and_empty_masks_rejected(self):
        module = SharedCellRecurrence(4, maximum_depth=4)
        for depth, valid in ((5, True), (0, True), (1, False)):
            with self.subTest(depth=depth), self.assertRaises(ValueError):
                module(torch.zeros(1, 1, 4), torch.tensor([[valid]]), torch.zeros(1, 4), depth=depth)

    def test_text_identity_and_nontext_connector_gradients(self):
        module = TemporalModalBridge({"text": 4, "image": 6}, 4)
        text = torch.randn(1, 2, 4, requires_grad=True)
        times = torch.tensor([[0., 1.]])
        valid = torch.ones(1, 2, dtype=torch.bool)
        output, _, _ = module({"text": (text, times, valid)}, observed_until=1)
        self.assertTrue(torch.equal(output, text))
        image = torch.randn(1, 2, 6, requires_grad=True)
        output, _, _ = module({"image": (image, times, valid)}, observed_until=1)
        output.square().mean().backward()
        self.assertIsNone(image.grad)
        self.assertIsNotNone(module.projectors["image"].weight.grad)

    def test_multimodal_tokens_and_time_order_preserved(self):
        module = TemporalModalBridge({"text": 4, "video": 4, "audio": 4}, 4)
        mask = torch.ones(1, 2, dtype=torch.bool)
        streams = {"video": (torch.ones(1, 2, 4), torch.tensor([[0., 2.]]), mask),
                   "audio": (torch.ones(1, 2, 4), torch.tensor([[1., 3.]]), mask)}
        output, times, valid = module(streams, observed_until=3)
        self.assertEqual(output.shape, (1, 4, 4))
        self.assertEqual(times.tolist(), [[0., 1., 2., 3.]])
        self.assertTrue(valid.all())

    def test_future_and_reversed_timestamps_rejected(self):
        module = TemporalModalBridge({"video": 4}, 4)
        for times in ([[0., 4.]], [[2., 1.]]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                module({"video": (torch.ones(1, 2, 4), torch.tensor(times), torch.ones(1, 2, dtype=torch.bool))}, observed_until=3)

    def test_shared_trial_reuses_encoder_and_separates_nochange(self):
        backend = ToyBackend()
        engine = SharedStemEngine(backend)
        items = tuple(request("x" if i % 2 else "longtext", f"r{i}") for i in range(40))
        labels = {f"r{i}": i % 2 for i in range(24)}
        old, new, report = train_shared_head_trial(engine, items, labels, classes=2,
            head_kind="linear", parameter_budget=64, steps=120, seed=3,
            head_factory=fixture_head, fitter=fixture_fit)
        self.assertEqual(report["physical_encoder_calls"], 1)
        self.assertEqual(report["physical_encoder_batch_widths"], [2])
        self.assertEqual(len(report["predictions"]), 16)
        self.assertEqual(sum(int(max(p["trained_logits"]) == p["trained_logits"][int(p["request_id"][1:]) % 2]) for p in report["predictions"]), 16)
        self.assertNotEqual(parameter_digest(old["cell"]), parameter_digest(new["cell"]))
        self.assertTrue(report["simulated_encoder"])
        self.assertFalse(report["production_authorized"])

    def test_whole_trial_scope_is_checked_before_any_batch(self):
        backend = ToyBackend()
        items = [request("x", str(i)) for i in range(33)]
        items[-1] = replace(items[-1], scope_digest="8"*64)
        with self.assertRaises(ValueError):
            train_shared_head_trial(SharedStemEngine(backend), tuple(items), {"0": 0}, classes=2,
                head_kind="linear", parameter_budget=64, steps=1, seed=1,
                head_factory=fixture_head, fitter=fixture_fit)
        self.assertEqual(backend.calls, [])


class ControlMechanisms(unittest.TestCase):
    def test_stop_is_real_and_cost_changes_choice(self):
        option = Continuation("refine", .9, 1., .2)
        self.assertEqual(choose_continuation((option,), stop_utility=.8, remaining_cost=1), "stop")
        self.assertEqual(choose_continuation((option,), stop_utility=.5, remaining_cost=1), "refine")
        self.assertEqual(choose_continuation((option,), stop_utility=.5, remaining_cost=.1), "stop")

    def test_conservative_lower_bound_not_optimistic_upper(self):
        options = (Continuation("speculative", .1, 100., 0), Continuation("supported", .8, .9, .1))
        self.assertEqual(choose_continuation(options, stop_utility=.5, remaining_cost=1), "supported")

    def test_invalid_values_duplicates_and_reserved_stop(self):
        for options in ((Continuation("x", float("nan"), 1, 0),),
                        (Continuation("x", 2, 1, 0),), (Continuation("stop", 0, 1, 0),),
                        (Continuation("x", 0, 1, 0), Continuation("x", 0, 1, 0))):
            with self.subTest(options=options), self.assertRaises(ValueError):
                choose_continuation(options, stop_utility=0, remaining_cost=1)

    def output(self, modality="text", ident="a", content=b"candidate"):
        return GeneratedOutput(ident, modality, "1"*64, content, hashlib.sha256(content).hexdigest(), .2)

    def test_scores_real_output_bytes_in_every_modality(self):
        observed = []
        def verifier(modality, content):
            observed.append((modality, content))
            return float(content == b"candidate")
        outputs = tuple(self.output(m, m) for m in ("text", "image", "video", "audio"))
        report = evaluate_generated_outputs(outputs, expected_request_digest="1"*64, cost_ceiling=1, verifier=verifier)
        self.assertEqual(len(observed), 4)
        self.assertEqual(report["charged_cost"], .8)
        self.assertFalse(report["production_authorized"])
        # Arbitrary bytes exercise binding only; not real generated media.

    def test_invalid_later_member_prevents_all_verifier_calls(self):
        seen = []
        with self.assertRaises(ValueError):
            evaluate_generated_outputs((self.output(), replace(self.output(ident="b"), content=b"forged")),
                expected_request_digest="1"*64, cost_ceiling=1, verifier=lambda *x: seen.append(x))
        self.assertEqual(seen, [])

    def test_failure_is_charged_and_retained(self):
        def verifier(*_):
            raise RuntimeError("fixture verifier unavailable")
        result = evaluate_generated_outputs((self.output(),), expected_request_digest="1"*64,
                                             cost_ceiling=1, verifier=verifier)
        self.assertEqual(result["charged_cost"], .2)
        self.assertEqual(result["results"][0]["status"], "verifier_failed")
        self.assertIsNone(result["results"][0]["score"])

    def test_output_budget_wrong_binding_and_invalid_score(self):
        for output, budget in ((self.output(), .1), (replace(self.output(), request_digest="2"*64), 1)):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                evaluate_generated_outputs((output,), expected_request_digest="1"*64,
                                             cost_ceiling=budget, verifier=lambda *_: 1)
        with self.assertRaises(ValueError):
            evaluate_generated_outputs((self.output(),), expected_request_digest="1"*64,
                                         cost_ceiling=1, verifier=lambda *_: float("nan"))

    def test_retention_counts_source_groups_not_repeated_cells(self):
        report = paired_retention_diagnostic([1.]*100, [1.]*100, ["same"]*100,
                                              minimum_groups=2, maximum_drop=.01)
        self.assertEqual(report["source_groups"], 1)
        self.assertFalse(report["descriptive_floor_met"])

    def test_retention_regression_cannot_hide_in_overall_gain(self):
        report = paired_retention_diagnostic([.2, .9], [.9, .7], ["new", "old"],
                                              minimum_groups=2, maximum_drop=.01)
        self.assertFalse(report["descriptive_floor_met"])
        self.assertFalse(report["statistical_superiority_established"])


if __name__ == "__main__":
    unittest.main()
