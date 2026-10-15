"""Tiny real-tensor interoperability of V6 variants and frozen V5 revision APIs."""
import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

import torch
from torch.nn import functional as F

from binding_continuation import continuation_plan
from bridge_reader import BridgeReader, WideReader, reader_identity
from group_loop import parameter_digest
from revision_execution import execute_revision, rollout_revision
from revision_training import fit_revision_pair
from token_protocol import build_binding_cases
from token_reader import TokenReader
from token_reader_training import TokenBatch


class BridgeRevisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.previous_threads)

    def setUp(self):
        torch.manual_seed(61)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.binding_cases = build_binding_cases("train", groups=1, seed=41)
        self.natural_cases = build_binding_cases("train", groups=1, seed=47)
        self.binding = self.data(self.binding_cases)
        self.natural = self.data(self.natural_cases)
        self.verifier = TokenReader(8, 8, max_hops=3).eval().requires_grad_(False)
        self.verifier.training_source_groups = ("independent-natural-verifier",)
        path = Path(self.temp.name) / "verifier.pt"
        torch.save(self.verifier.state_dict(), path)
        self.provenance = dict(file_path=str(path), file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            model_sha256=parameter_digest(self.verifier), training_source_groups=list(self.verifier.training_source_groups),
            synthetic_trained=False)

    @staticmethod
    def data(cases):
        size = len(cases)
        return TokenBatch(torch.randn(size, 4, 2, 8), torch.randn(size, 3, 8), torch.randn(size, 2, 8),
            torch.ones(size, 4, 2, dtype=torch.bool), torch.ones(size, 3, dtype=torch.bool),
            torch.ones(size, 2, dtype=torch.bool), torch.tensor([case.label for case in cases]),
            tuple(case.source_hash for case in cases))

    def model(self, reader_class):
        model = reader_class(8, 8, max_hops=3, residual_seed=11)
        # Emulate a nonzero trained residual without an extra fitting experiment.
        residual = model.fact_bridge if isinstance(model, BridgeReader) else model.head.local_residual
        with torch.no_grad():
            residual.output.weight.copy_(torch.eye(8) * .05)
        model.training_source_groups = tuple(sorted(set(self.binding.source_groups + self.natural.source_groups)))
        return model

    def test_feedback_and_each_added_variant_tensor_receive_real_gradients(self):
        for reader_class in (BridgeReader, WideReader):
            with self.subTest(reader=reader_class.__name__):
                model = self.model(reader_class).train().requires_grad_(True)
                before_verifier = parameter_digest(self.verifier)
                trace = rollout_revision(model, self.verifier, self.binding.features(), mode="real")
                F.cross_entropy(trace["logits_trace"][-1], self.binding.targets).backward()
                self.assertGreater(model.proposal.weight.grad[:, -4:].abs().sum().item(), 0)
                self.assertGreater(model.update_gate.weight.grad[:, -4:].abs().sum().item(), 0)
                added = model.fact_bridge if isinstance(model, BridgeReader) else model.head.local_residual
                self.assertTrue(all(p.grad is not None and torch.isfinite(p.grad).all()
                                    and p.grad.abs().sum().item() > 0 for p in added.parameters()))
                self.assertEqual(parameter_digest(self.verifier), before_verifier)
                self.assertTrue(all(p.grad is None for p in self.verifier.parameters()))
                self.assertEqual(trace["costs"]["calls"],
                    dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))
                self.assertTrue(all(not f.requires_grad for f in trace["feedback_trace"]))

    def test_actual_residual_calls_and_work_are_inside_recorded_reader_timers(self):
        for reader_class, expected_calls, scope in ((BridgeReader, 1, "reader_prepare"),
                                                   (WideReader, 3, "reader_step")):
            with self.subTest(reader=reader_class.__name__):
                model = self.model(reader_class).eval().requires_grad_(False)
                added = model.fact_bridge if isinstance(model, BridgeReader) else model.head.local_residual
                original, measured_cpu = added.forward, []

                def measured(*args, **kwargs):
                    cpu = time.process_time_ns()
                    result = original(*args, **kwargs)
                    measured_cpu.append(time.process_time_ns() - cpu)
                    return result

                with mock.patch.object(added, "forward", side_effect=measured):
                    result = execute_revision(self.binding.features(), model, self.verifier,
                                              verifier_provenance=self.provenance)
                self.assertEqual(len(measured_cpu), expected_calls)
                nested = sum(row["cpu_ns"] for row in result["cost"]["callbacks"] if row["component"] == scope)
                self.assertGreaterEqual(nested, sum(measured_cpu))
                self.assertGreaterEqual(result["cost"]["cpu_ns"], nested)
                self.assertIsNone(result["cost"]["formula_flops"])

    def test_matched_fit_preserves_variant_schema_and_common_frozen_core(self):
        plan = continuation_plan(self.natural_cases, self.binding_cases, seed=71, updates=1, batch_size=4)
        for reader_class in (BridgeReader, WideReader):
            with self.subTest(reader=reader_class.__name__):
                core = self.model(reader_class).eval().requires_grad_(False)
                identity, before = reader_identity(core), parameter_digest(core)
                models, receipt = fit_revision_pair(core, self.verifier, self.natural, self.binding,
                    self.binding_cases, plan=plan, verifier_provenance=self.provenance,
                    natural_cases=self.natural_cases)
                self.assertEqual(parameter_digest(core), before)
                self.assertTrue(receipt["feedback_training_verified"])
                for arm, model in models.items():
                    self.assertIs(type(model), reader_class)
                    self.assertEqual(reader_identity(model), identity)
                    self.assertEqual(set(model.state_dict()), set(core.state_dict()))
                    self.assertEqual(receipt["models"][arm]["parameter_count"], identity["parameter_count"])
                    self.assertEqual(receipt["models"][arm]["actual_calls"]["reader_step"], 6)
                    self.assertEqual(receipt["models"][arm]["actual_calls"]["verifier_step"], 4)
                    self.assertTrue(all(not p.requires_grad for p in model.parameters()))
                with self.assertRaises(RuntimeError):
                    TokenReader(8, 8, max_hops=3).load_state_dict(models["real"].state_dict(), strict=True)

    def test_zero_reset_fusion_and_deranged_feedback_use_same_variant_parameter_set(self):
        permutation = [1, 2, 3, 0]
        ids = [case.case_id for case in self.binding_cases]
        for reader_class in (BridgeReader, WideReader):
            with self.subTest(reader=reader_class.__name__):
                core = self.model(reader_class).eval().requires_grad_(False)
                before = parameter_digest(core)
                results = {}
                for mode in ("real", "zero", "shuffle", "reset", "late_fusion", "verifier_only"):
                    results[mode] = execute_revision(self.binding.features(), core, self.verifier,
                        mode=mode, verifier_provenance=self.provenance, case_ids=ids,
                        shuffle_indices=permutation if mode == "shuffle" else None)
                    self.assertEqual(results[mode]["reader_model_sha256"], before)
                    self.assertEqual(results[mode]["cost"]["calls"],
                        dict(reader_prepare=1, reader_step=3, verifier_prepare=1, verifier_step=2))
                expected = (torch.tensor(results["zero"]["probabilities"])
                            + torch.tensor(results["verifier_only"]["probabilities"])) / 2
                torch.testing.assert_close(torch.tensor(results["late_fusion"]["probabilities"]), expected, rtol=0, atol=0)
                self.assertEqual(parameter_digest(core), before)
                for hop in (1, 2):
                    observed = results["shuffle"]["verifier_observations"][hop - 1]
                    events = results["shuffle"]["events"][hop * 4:(hop + 1) * 4]
                    self.assertEqual([event["feedback"] for event in events], [observed[i] for i in permutation])


if __name__ == "__main__":
    unittest.main()
