"""Bounded inference regressions. Synthetic tensors are not model outcomes."""
from copy import deepcopy
from unittest.mock import patch
import unittest

import torch

from bounded_cell_execution import forward_tiled, tile_plan, _checked_comparison, _fold
from bounded_multicell_probe import probe_bounded, METHODS
from development_tensors import BasisCellHeads, parameter_digest
from shared_cell_execution import forward_shared


class BoundedCellTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads(); torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.bank = BasisCellHeads(16, 4, 8, ("a", "b", "c", "d"), seed=7)
        rng = torch.Generator().manual_seed(13)
        with torch.no_grad():
            self.bank.coefficients.copy_(torch.randn(4, 8, generator=rng))
            self.bank.gates.copy_(torch.randn(4, 9, generator=rng))
        self.x = torch.randn(3, 16, generator=rng)
        self.f = torch.tensor([2, 0, 1, 2, 1, 0]); self.c = torch.tensor([3, 0, 1, 2, 0, 1])

    def test_tiled_matches_original_order_and_shared_formula(self):
        before = parameter_digest(self.bank)
        with torch.no_grad():
            actual, work = forward_tiled(self.bank, self.x, self.f, self.c)
            expected = self.bank(self.x[self.f], self.c)
            torch.testing.assert_close(actual, expected, atol=1e-5, rtol=1e-5)
            torch.testing.assert_close(actual, forward_shared(self.bank, self.x, self.f, self.c), atol=1e-5, rtol=1e-5)
        self.assertEqual(parameter_digest(self.bank), before)
        self.assertEqual(work["compiled_cell_matrices"], 4)

    def test_double_precision(self):
        self.bank.double(); x = self.x.double()
        with torch.no_grad():
            actual, _ = forward_tiled(self.bank, x, self.f, self.c)
            torch.testing.assert_close(actual, self.bank(x[self.f], self.c), atol=1e-10, rtol=1e-10)

    def test_no_autograd_memory_claim(self):
        with self.assertRaisesRegex(ValueError, "disabled autograd"):
            forward_tiled(self.bank, self.x, self.f, self.c)
        with torch.inference_mode():
            output, _ = forward_tiled(self.bank, self.x, self.f, self.c)
        self.assertFalse(output.requires_grad)

    def test_byte_limit_and_one_lane_tiles(self):
        # First find a byte budget just sufficient for one declared lane.
        cap = (len(self.f)+len(self.x))*4*4 + (3*16*4+8*16+4*8+12*4+16)*4
        with torch.no_grad():
            actual, work = forward_tiled(self.bank, self.x, self.f, self.c, maximum_scratch_bytes=cap)
            torch.testing.assert_close(actual, self.bank(self.x[self.f], self.c), atol=1e-5, rtol=1e-5)
        self.assertEqual(work["tile_count"], 6)
        self.assertEqual(work["compiled_cell_matrices"], 6)
        self.assertEqual(work["explicit_scratch_upper_bytes"], cap)
        self.assertEqual(work["retained_compiled_bytes_after_call"], 0)

    def test_impossible_cap_refuses_before_base_projection(self):
        seen = []
        hook = self.bank.base.register_forward_pre_hook(lambda *_: seen.append(True))
        try:
            with torch.no_grad(), self.assertRaisesRegex(ValueError, "scratch"):
                forward_tiled(self.bank, self.x, self.f, self.c, maximum_scratch_bytes=1)
            self.assertEqual(seen, [])
        finally:
            hook.remove()

    def test_invalid_caps(self):
        for cap in (True, 0, -1, 1.5, 16*1024*1024+1):
            with self.subTest(cap=cap), torch.no_grad(), self.assertRaises(ValueError):
                forward_tiled(self.bank, self.x, self.f, self.c, maximum_scratch_bytes=cap)

    def test_invalid_references_cannot_reach_any_kernel(self):
        with patch("bounded_cell_execution._fold", side_effect=AssertionError("kernel reached")):
            for f, c in ((self.f, self.c+4), (self.f.float(), self.c), (self.f[:-1], self.c),
                         (torch.zeros_like(self.f), self.c), (self.f-3, self.c)):
                with self.subTest(f=f), torch.no_grad(), self.assertRaises(ValueError):
                    forward_tiled(self.bank, self.x, f, c)

    def test_dormancy_all_four_arms_before_execution(self):
        with torch.no_grad():
            folded = (*_fold(self.bank, torch.arange(4)), torch.arange(4))
            self.bank.awake = (True, True, True, False)
            for m in METHODS:
                with self.subTest(method=m), self.assertRaisesRegex(ValueError, "dormant"):
                    _checked_comparison(self.bank, self.x, self.f, self.c, m, folded, 1024*1024)

    def test_all_arms_reject_nonfinite_inputs(self):
        with torch.no_grad():
            folded = (*_fold(self.bank, torch.arange(4)), torch.arange(4))
            x = self.x.clone(); x[0,0] = torch.nan
            for m in METHODS:
                with self.subTest(method=m), self.assertRaises(ValueError):
                    _checked_comparison(self.bank, x, self.f, self.c, m, folded, 1024*1024)

    def test_finite_operands_cannot_hide_overflow_with_sigmoid(self):
        with torch.no_grad():
            self.bank.gate_axes.fill_(2)
            self.bank.gates.fill_(torch.finfo(torch.float32).max)
            for m in ("expanded_checked", "shared_checked", "tiled_folded"):
                with self.subTest(method=m), self.assertRaisesRegex(ValueError, "nonfinite"):
                    _checked_comparison(self.bank, self.x.abs()+1, self.f, self.c, m, None, 1024*1024)
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                _fold(self.bank, torch.arange(4))

    def test_folded_gate_scores_checked_after_compilation(self):
        # Valid finite folded weights can overflow only when multiplied by input.
        with torch.no_grad():
            folded = (torch.zeros(4,16,4), torch.full((4,16), torch.finfo(torch.float32).max), torch.zeros(4), torch.arange(4))
            with self.assertRaisesRegex(ValueError, "nonfinite"):
                _checked_comparison(self.bank, self.x.abs()+1, self.f, self.c, "full_folded_checked", folded, 1024*1024)

    def test_later_tile_failure_returns_no_success(self):
        import bounded_cell_execution as module
        original = module._fold
        calls = []
        def fail_second(bank, cells):
            calls.append(len(cells))
            if len(calls) == 2:
                raise ValueError("injected second tile failure")
            return original(bank, cells)
        with torch.no_grad(), patch.object(module, "_fold", side_effect=fail_second):
            with self.assertRaisesRegex(ValueError, "second tile"):
                forward_tiled(self.bank, self.x, self.f, self.c, maximum_scratch_bytes=2000)
        self.assertEqual(len(calls), 2)

    def test_no_stale_compilation_after_parameter_update(self):
        with torch.no_grad():
            old, _ = forward_tiled(self.bank, self.x, self.f, self.c)
            self.bank.coefficients[0] += 3
            new, _ = forward_tiled(self.bank, self.x, self.f, self.c)
            torch.testing.assert_close(new, self.bank(self.x[self.f], self.c), atol=1e-5, rtol=1e-5)
        self.assertFalse(torch.equal(old, new))

    def test_noncontiguous_basis_cannot_allocate_uncharged_copy(self):
        self.bank.basis = torch.nn.Parameter(self.bank.basis.transpose(1,2).contiguous().transpose(1,2))
        with torch.no_grad(), self.assertRaisesRegex(ValueError, "noncontiguous"):
            forward_tiled(self.bank, self.x, self.f, self.c)

    def test_4096_distinct_cells_keep_matrix_tiles_bounded(self):
        bank = BasisCellHeads(384,4,8,tuple(f"c{i}" for i in range(4096)), seed=7)
        with torch.no_grad():
            bank.coefficients[:,0] = torch.arange(4096)/4096
            x = torch.ones(1,384); f = torch.zeros(4096,dtype=torch.long); c = torch.arange(4096)
            y, work = forward_tiled(bank,x,f,c)
            reference = forward_shared(bank,x,f,c)
        torch.testing.assert_close(y,reference,atol=1e-5,rtol=1e-5)
        self.assertEqual(work["compiled_cell_matrices"],4096)
        self.assertLessEqual(work["maximum_live_compiled_cells"],32)
        self.assertLessEqual(work["explicit_scratch_upper_bytes"],1024*1024)
        self.assertLess(work["folded_matrices_upper_bytes"],250_000)
        self.assertEqual(len(torch.unique(y,dim=0)),4096)

    def test_balanced_comparison_same_preflight_census(self):
        with torch.no_grad():
            result = probe_bounded(self.bank,self.x,self.f.repeat(6),self.c.repeat(6))
        self.assertEqual(len(result["trials"]),16)
        for m in METHODS:
            trials=[t for t in result["trials"] if t["method"]==m]
            self.assertEqual(sorted(t["position"] for t in trials),[0,1,2,3])
            self.assertEqual({t["input_preflight_calls"] for t in trials},{2})
            self.assertEqual({t["output_checked_rows"] for t in trials},{36})
        self.assertEqual(result["full_folded_measured_invocations"],9)
        self.assertGreater(result["total_wall_ns"],sum(t["wall_ns"] for t in result["trials"]))
        self.assertEqual(result["full_folded_compilation"]["additional_tensor_bytes"],4*(16*4+16+1)*4)
        self.assertFalse(result["equal_memory_envelopes"])
        self.assertFalse(result["production_authorized"])

    def test_probe_uses_each_validation_once_per_batch(self):
        import bounded_cell_execution as module
        with torch.no_grad():
            folded=(*_fold(self.bank,torch.arange(4)),torch.arange(4))
            for m in METHODS:
                with self.subTest(method=m), patch.object(module,"_validate_request",wraps=module._validate_request) as validator:
                    _checked_comparison(self.bank,self.x,self.f,self.c,m,folded,1024*1024)
                    self.assertEqual(validator.call_count,1)

    def test_probe_does_not_mutate_bank_or_inputs(self):
        original=parameter_digest(self.bank); x=self.x.clone()
        with torch.no_grad():
            probe_bounded(self.bank,self.x,self.f,self.c)
        self.assertEqual(parameter_digest(self.bank),original)
        self.assertTrue(torch.equal(x,self.x))

    def test_invalid_probe_repeats(self):
        for count in (True, 0, 3, 5, 20):
            with torch.no_grad(), self.subTest(repeats=count), self.assertRaises(ValueError):
                probe_bounded(self.bank,self.x,self.f,self.c,repeats=count)


    def test_single_cell_fold_is_reused_only_within_current_invocation(self):
        import bounded_cell_execution as module
        f = torch.arange(96)%3; c = torch.full((96,),2,dtype=torch.long)
        with torch.no_grad(), patch.object(module,"_fold",wraps=module._fold) as fold:
            output, work = forward_tiled(self.bank,self.x,f,c)
            self.assertEqual(fold.call_count,1)
            self.assertEqual(work["compiled_cell_matrices"],1)
            self.assertEqual(work["tile_count"],3)
            torch.testing.assert_close(output,self.bank(self.x[f],c),atol=1e-5,rtol=1e-5)
            forward_tiled(self.bank,self.x,f,c)
            self.assertEqual(fold.call_count,2)

    def test_full_control_does_not_compile_unused_cells(self):
        with torch.no_grad():
            result=probe_bounded(self.bank,self.x,torch.arange(96)%3,torch.full((96,),2,dtype=torch.long))
        self.assertEqual(result["full_folded_compilation"]["compiled_active_cells"],1)
        self.assertEqual(result["full_folded_compilation"]["additional_tensor_bytes"],(16*4+16+1)*4)
        self.assertEqual(result["full_folded_compilation"]["registered_cells"],4)
        self.assertTrue(all(t["tile_work"]["compiled_cell_matrices"]==3 for t in result["trials"] if t["method"]=="tiled_folded"))


class BoundedIntegrationTests(unittest.TestCase):
    def test_existing_population_entrypoint_binds_sidecar_and_preserves_predictions(self):
        import tempfile
        import json
        import hashlib
        from pathlib import Path
        from multicell_execution_checks import PopulationStudyTests
        from multicell_learning_study import execute, review
        rows, x, config = PopulationStudyTests().fixture()
        old_threads = torch.get_num_threads(); torch.set_num_threads(1)
        try:
            with tempfile.TemporaryDirectory() as tmp, patch("multicell_learning_study.load_reference", return_value=({}, [], x, {}, {})), patch("multicell_learning_study.derive_study", return_value=(rows, x, config)):
                old, new = Path(tmp)/"v6", Path(tmp)/"v7"
                execute("fixture", old)
                execute("fixture", new, bounded_serving=True)
                for name in ("learned.safetensors", "inherited.safetensors", "normalizer.safetensors", "predictions.json"):
                    self.assertEqual((old/name).read_bytes(), (new/name).read_bytes())
                run = json.loads((new/"result.json").read_bytes())
                raw = (new/"bounded-trained-serving.json").read_bytes()
                self.assertEqual(run["all_files_sha256"]["bounded-trained-serving.json"], hashlib.sha256(raw).hexdigest())
                self.assertEqual(len(json.loads(raw)["trials"]), 16)
                review("fixture", new, Path(tmp)/"score.json")
                (new/"bounded-trained-serving.json").write_bytes(raw + b" ")
                with self.assertRaisesRegex(ValueError, "sealed"):
                    review("fixture", new, Path(tmp)/"altered.json")
        finally:
            torch.set_num_threads(old_threads)


if __name__ == "__main__":
    unittest.main()
