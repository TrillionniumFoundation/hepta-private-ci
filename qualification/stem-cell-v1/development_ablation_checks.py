"""Explicit Torch/LLVM tests: no optional-dependency skip or pretrained claim."""

from copy import deepcopy
from dataclasses import replace
import io
import math
import unittest
import wave

import torch
from torch import nn

from development_ablation import (
    ChanceEdge, ComputeOption, FoldIdentity, InformationState, RecurrentClassifier, RouteAwareUnsplit, RoutedBasis,
    finite_compute_allocation, fit_candidate, paired_predictions, run_depth_candidates, incremental_depth_candidates,
    structural_arms, validate_folds,
)
from development_generation import (
    BOS, EOS, CodecSpec, SharedByteGenerator, decode_bytes, fit_generator, render_generated,
)
from development_native import DecisionIR, NativeDecisionCache, Rule, benchmark_fixed_policy, interpret
from development_tensors import BasisCellHeads, dormancy_candidate, merge_identical_candidate, parameter_digest, split_candidate


class ControlledLearningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.threads = torch.get_num_threads()
        torch.set_num_threads(1)

    @classmethod
    def tearDownClass(cls):
        torch.set_num_threads(cls.threads)

    def setUp(self):
        self.context = torch.random.fork_rng(devices=[])
        self.context.__enter__()
        torch.manual_seed(55)

    def tearDown(self):
        self.context.__exit__(None, None, None)

    def test_trainable_head_improves_without_mutating_initial_or_inputs(self):
        x = torch.randn(32, 4, requires_grad=True)
        y = (x[:, 0] > 0).long()
        initial = nn.Linear(4, 2)
        digest = parameter_digest(initial)
        trained, report = paired_predictions(initial, x, y, x.detach(), steps=100)
        old = torch.nn.functional.cross_entropy(report['frozen_logits'], y)
        new = torch.nn.functional.cross_entropy(report['trained_logits'], y)
        self.assertLess(new, old)
        self.assertIsNone(x.grad)
        self.assertEqual(digest, parameter_digest(initial))
        self.assertNotEqual(digest, parameter_digest(trained))
        self.assertFalse(report['encoder_execution_observed'])
        self.assertEqual(report['fit']['examples_processed'], 3200)

    def test_invalid_optimizer_and_labels(self):
        x = torch.randn(8, 4)
        for steps in (True, 0, 1001):
            with self.assertRaises(ValueError):
                fit_candidate(nn.Linear(4, 2), x, torch.zeros(8, dtype=torch.long), steps=steps)
        with self.assertRaises(ValueError):
            fit_candidate(nn.Linear(4, 2), x, torch.ones(8, dtype=torch.long) * 2)

    def test_group_time_scope_isolation(self):
        a = FoldIdentity('scope', ('a', 'a'), (0, 1))
        b = FoldIdentity('scope', ('b', 'c'), (2, 3))
        validate_folds(a, b, 2, 2)
        for bad in (replace(b, groups=('a', 'c')), replace(b, scope='other'),
                    replace(b, observed_at=(1, 3)), replace(b, observed_at=(True, 3))):
            with self.assertRaises(ValueError):
                validate_folds(a, bad, 2, 2)

    def test_actual_structural_controls_and_selected_parent_unchanged(self):
        bank = BasisCellHeads(4, 2, 8, ('parent',))
        x = torch.cat((torch.randn(32, 4), torch.arange(32).remainder(2)[:, None]), 1)
        y = ((x[:, 0] > 0).long() ^ x[:, -1].long())
        before = parameter_digest(bank)
        reports = structural_arms(bank, x, y, torch.randn(8, 5).sign().abs(), steps=3,
                                  train_fold=FoldIdentity('fixture', tuple(f't{i}' for i in range(32)), (1,)*32),
                                  holdout_fold=FoldIdentity('fixture', tuple(f'h{i}' for i in range(8)), (2,)*8))
        self.assertEqual(set(reports), {'parent', 'split', 'wide_head', 'more_data',
                                        'route_aware_unsplit', 'route_aware_more_data'})
        self.assertEqual(reports['more_data']['training_rows_available'], 32)
        self.assertEqual(reports['parent']['training_rows_available'], 16)
        self.assertLessEqual(reports['wide_head']['fit']['trainable_parameters'], 34)
        self.assertEqual(before, parameter_digest(bank))
        self.assertEqual(reports['more_data']['fit']['examples_processed'], 96)
        self.assertEqual(reports['split']['fit']['examples_processed'], 48)

    def test_split_sleep_wake_merge_preserve_function(self):
        bank = BasisCellHeads(4, 2, 4, ('p',))
        x = torch.randn(6, 4)
        original = parameter_digest(bank)
        split = split_candidate(bank, 'p', 'c', maximum_local_parameters=18)
        self.assertTrue(torch.equal(split(x, torch.ones(6, dtype=torch.long)), bank(x, torch.zeros(6, dtype=torch.long))))
        asleep = dormancy_candidate(split, 'c', awake=False)
        with self.assertRaises(ValueError):
            asleep(x, torch.ones(6, dtype=torch.long))
        awake = dormancy_candidate(asleep, 'c', awake=True)
        merged = merge_identical_candidate(awake, 'c', 'p')
        self.assertTrue(torch.equal(merged(x, torch.zeros(6, dtype=torch.long)), bank(x, torch.zeros(6, dtype=torch.long))))
        self.assertEqual(original, parameter_digest(bank))

    def test_shared_causal_depth_cost_and_parameter_invariance(self):
        model = RecurrentClassifier(8, 2, depth=2)
        x = torch.randn(4, 3, 8)
        before = parameter_digest(model)
        out = run_depth_candidates(model, x)
        self.assertEqual([out[d]['cell_transitions'] for d in (1, 2, 4)], [4, 8, 16])
        self.assertEqual(model.depth, 2)
        self.assertEqual(parameter_digest(model), before)
        self.assertFalse(torch.equal(out[1]['logits'], out[4]['logits']))

    def test_train_recurrent_core_real_backward(self):
        model = RecurrentClassifier(4, 2, depth=3)
        x = torch.randn(16, 3, 4)
        y = (x[:, :, 0].sum(1) > 0).long()
        out, receipt = fit_candidate(model, x, y, steps=5)
        self.assertNotEqual(parameter_digest(model), parameter_digest(out))
        self.assertEqual(receipt['steps'], 5)

    def test_incremental_depth_reuses_only_own_prefix_and_matches_fixed(self):
        model = RecurrentClassifier(8, 2, depth=2)
        x = torch.randn(4, 3, 8)
        before = parameter_digest(model)
        fixed = run_depth_candidates(model, x, depths=(1, 2, 4))
        shared = incremental_depth_candidates(model, x, depths=(1, 2, 4))
        for depth in (1, 2, 4):
            self.assertTrue(torch.equal(fixed[depth]['logits'], shared['depths'][depth]))
        self.assertEqual(shared['cell_transitions'], 16)
        self.assertEqual(sum(v['cell_transitions'] for v in fixed.values()), 28)
        self.assertEqual(shared['readout_calls'], 3)
        self.assertEqual(model.depth, 2)
        self.assertEqual(before, parameter_digest(model))

    def test_invalid_incremental_depths(self):
        for depths in ((0,), (1, 1), (True,), (33,), ()):
            with self.assertRaises(ValueError):
                incremental_depth_candidates(RecurrentClassifier(4, 2, depth=1),
                                             torch.zeros(2, 3, 4), depths=depths)


class FairStructureTests(unittest.TestCase):
    setUpClass = classmethod(ControlledLearningTests.setUpClass.__func__)
    tearDownClass = classmethod(ControlledLearningTests.tearDownClass.__func__)
    setUp = ControlledLearningTests.setUp
    tearDown = ControlledLearningTests.tearDown

    def test_unsplit_contains_split_function_and_same_trainable_budget(self):
        bank = BasisCellHeads(4, 2, 8, ('p',))
        split = RoutedBasis(split_candidate(bank, 'p', 'c', maximum_local_parameters=34), split=True)
        unsplit = RouteAwareUnsplit(bank)
        with torch.no_grad():
            split.bank.coefficients.normal_()
            split.bank.gates.normal_()
            unsplit.coefficients.copy_(split.bank.coefficients)
            unsplit.gates.copy_(split.bank.gates)
        x = torch.cat((torch.randn(32, 4), torch.arange(32).remainder(2)[:, None]), 1)
        self.assertTrue(torch.equal(split(x), unsplit(x)))
        self.assertEqual(sum(p.numel() for p in split.parameters() if p.requires_grad),
                         sum(p.numel() for p in unsplit.parameters() if p.requires_grad))
        self.assertFalse(hasattr(unsplit, 'cell_ids'))

    def test_equal_information_and_training_remove_spurious_split_advantage(self):
        bank = BasisCellHeads(4, 2, 8, ('p',))
        x = torch.cat((torch.randn(32, 4), torch.arange(32).remainder(2)[:, None]), 1)
        y = (x[:, 0] > 0).long() ^ x[:, -1].long()
        split = RoutedBasis(split_candidate(bank, 'p', 'c', maximum_local_parameters=34), split=True)
        unsplit = RouteAwareUnsplit(bank)
        a, _ = fit_candidate(split, x, y, steps=20)
        b, _ = fit_candidate(unsplit, x, y, steps=20)
        self.assertTrue(torch.allclose(a(x), b(x), atol=1e-6, rtol=0))

    def test_structure_fold_overlap_fails_before_optimizer(self):
        from unittest.mock import patch
        x = torch.zeros(8, 5)
        fold = FoldIdentity('s', tuple(str(i) for i in range(8)), (1,)*8)
        with patch('development_ablation.paired_predictions') as fit:
            with self.assertRaises(ValueError):
                structural_arms(BasisCellHeads(4, 2, 8, ('p',)), x,
                                torch.zeros(8, dtype=torch.long), x,
                                train_fold=fold, holdout_fold=fold)
            fit.assert_not_called()


class AllocationTests(unittest.TestCase):
    def graph(self):
        return (
            InformationState('root', .5, (ComputeOption('observe-a', .1, (ChanceEdge(.5, 'a0'), ChanceEdge(.5, 'a1'))),)),
            InformationState('a0', .5, (ComputeOption('observe-b', .1, (ChanceEdge(.5, 'l0'), ChanceEdge(.5, 'l1'))),)),
            InformationState('a1', .5, (ComputeOption('observe-b', .1, (ChanceEdge(.5, 'l0'), ChanceEdge(.5, 'l1'))),)),
            InformationState('l0', 1., ()), InformationState('l1', 1., ()),
        )

    def test_complementary_two_step_acquisition(self):
        report = finite_compute_allocation(self.graph(), 'root', budget=.2)
        self.assertEqual(report['action'], 'observe-a')
        self.assertAlmostEqual(report['value'], .8)
        self.assertEqual(finite_compute_allocation(self.graph(), 'root', budget=.1)['action'], 'stop')
        self.assertFalse(report['production_authorized'])

    def test_decimal_budget_has_no_subtraction_false_rejection(self):
        graph = (InformationState('r', 0, (ComputeOption('first', .1, (ChanceEdge(1, 'a'),)),)),
                 InformationState('a', 0, (ComputeOption('second', .2, (ChanceEdge(1, 'b'),)),)),
                 InformationState('b', 1, ()))
        self.assertAlmostEqual(finite_compute_allocation(graph, 'r', budget=.3)['value'], .7)

    def test_chance_uses_expectation_not_best_leaf(self):
        graph = (InformationState('r', .7, (ComputeOption('try', 0, (ChanceEdge(.5, 'a'), ChanceEdge(.5, 'b'))),)),
                 InformationState('a', 1, ()), InformationState('b', 0, ()))
        self.assertEqual(finite_compute_allocation(graph, 'r', budget=1)['action'], 'stop')

    def test_duplicate_public_history_rejected(self):
        with self.assertRaises(ValueError):
            finite_compute_allocation(self.graph() + (self.graph()[0],), 'root', budget=1)

    def test_malformed_probability_missing_state_and_cycle(self):
        for edges in ((ChanceEdge(.6, 'r'),), (ChanceEdge(1, 'missing'),), (ChanceEdge(1, 'r'),)):
            graph = (InformationState('r', .5, (ComputeOption('try', .1, edges),)),)
            with self.assertRaises(ValueError):
                finite_compute_allocation(graph, 'r', budget=1)

    def test_long_depth_rejected_even_with_reverse_topological_input(self):
        graph = [InformationState('35', 1, ())]
        for i in reversed(range(35)):
            graph.append(InformationState(str(i), 0, (ComputeOption('next', 0, (ChanceEdge(1, str(i+1)),)),)))
        with self.assertRaises(ValueError):
            finite_compute_allocation(tuple(graph), '0', budget=1)

    def test_budget_monotone_and_analytic_oracle(self):
        for cost in (.02, .1, .2, .3):
            graph = tuple(replace(s, options=tuple(replace(o, cost=cost) for o in s.options)) for s in self.graph())
            value = finite_compute_allocation(graph, 'root', budget=4 * cost)['value']
            self.assertAlmostEqual(value, max(.5, 1 - 2 * cost))


# Avoid duplicating the learning tests while keeping common Torch setup explicit.
class GenerationMechanismTests(unittest.TestCase):
    setUpClass = classmethod(ControlledLearningTests.setUpClass.__func__)
    tearDownClass = classmethod(ControlledLearningTests.tearDownClass.__func__)
    setUp = ControlledLearningTests.setUp
    tearDown = ControlledLearningTests.tearDown

    def test_prefix_causality_and_frozen_condition(self):
        model = SharedByteGenerator(8, maximum_bytes=4)
        condition = torch.randn(2, 8, requires_grad=True)
        modality = torch.tensor([0, 3])
        prefix = torch.tensor([[BOS, 1, 2], [BOS, 3, 4]])
        changed = prefix.clone()
        changed[:, 2] = 9
        a, b = model(condition, modality, prefix), model(condition, modality, changed)
        self.assertTrue(torch.equal(a[:, :2], b[:, :2]))
        a.sum().backward()
        self.assertIsNone(condition.grad)
        self.assertIsNotNone(model.recurrence.cell.weight_hh.grad)

    def test_real_next_token_fit_preserves_source(self):
        model = SharedByteGenerator(8, maximum_bytes=4)
        c = torch.randn(4, 8)
        m = torch.arange(4)
        candidate, receipt = fit_generator(model, c, m, (b'ab', b'cd', b'ef', b'gh'), steps=45)
        self.assertLess(receipt['last_loss'], receipt['initial_loss'])
        self.assertEqual(receipt['initial_digest'], parameter_digest(model))
        self.assertNotEqual(parameter_digest(candidate), parameter_digest(model))
        self.assertFalse(receipt['pretrained_generator'])

    def test_stopped_rows_have_no_extra_computation(self):
        model = SharedByteGenerator(8, maximum_bytes=4)
        with torch.no_grad():
            model.readout.weight.zero_()
            model.readout.bias.fill_(-100)
            model.readout.bias[EOS] = 100
        out = model.generate(torch.zeros(2, 8), torch.tensor([0, 1]), maximum_bytes=4)
        self.assertEqual(out['tokens'], ((), ()))
        self.assertEqual(out['cell_transitions'], 2)
        self.assertEqual(out['decoder_batches'], 1)
        self.assertEqual(out['terminated'], (True, True))

    def test_no_eos_is_not_silent_success_or_extra_output(self):
        model = SharedByteGenerator(8, maximum_bytes=2)
        with torch.no_grad():
            model.readout.weight.zero_()
            model.readout.bias.fill_(-100)
            model.readout.bias[65] = 100
        out = model.generate(torch.zeros(1, 8), torch.tensor([0]), maximum_bytes=2)
        self.assertEqual(out['tokens'], ((65, 65),))
        self.assertEqual(out['terminated'], (False,))
        self.assertEqual(render_generated(out, (CodecSpec('text', 2),))[0]['status'], 'unterminated')

    def test_output_batch_cannot_silently_drop_missing_terminal_rows(self):
        batch = {'tokens': ((65,), (66,)), 'terminated': (True,)}
        with self.assertRaises(ValueError):
            render_generated(batch, (CodecSpec('text', 1), CodecSpec('text', 1)))

    def test_real_media_codecs(self):
        self.assertEqual(decode_bytes(CodecSpec('text', 2), (104, 105))[1], b'hi')
        image = decode_bytes(CodecSpec('image', 4, 2, 2), (0, 100, 200, 255))[1]
        self.assertTrue(image.startswith(b'P5\n2 2\n255\n'))
        video = decode_bytes(CodecSpec('video', 8, 2, 2, 2, 24), (0,) * 8)[1]
        self.assertEqual(video.count(b'FRAME\n'), 2)
        audio = decode_bytes(CodecSpec('audio', 4, rate=8000), (0, 64, 128, 255))[1]
        with wave.open(io.BytesIO(audio), 'rb') as wav:
            self.assertEqual(wav.getframerate(), 8000)
            self.assertEqual(wav.readframes(4), bytes((0, 64, 128, 255)))

    def test_codec_rejects_invalid_shape_and_text(self):
        for spec, tokens in ((CodecSpec('image', 4, 3, 2), (0,) * 4),
                             (CodecSpec('text', 1), (255,)), (CodecSpec('text', 1), (True,))):
            with self.assertRaises((ValueError, UnicodeError)):
                decode_bytes(spec, tokens)


class NativeExecutionTests(unittest.TestCase):
    def program(self):
        return DecisionIR(2, (Rule((1., -2.), .5, 2), Rule((0., 1.), 0., 1)), 0)

    def test_actual_native_function_and_object_bytes(self):
        program = self.program()
        cache = NativeDecisionCache()
        native, hit = cache.compile(program)
        self.assertFalse(hit)
        self.assertGreater(native.manifest['object_bytes'], 0)
        for x in ((0., 0.), (1., 0.), (-3., -2.), (1000., -1000.), (.5, 0.)):
            self.assertEqual(native(x), interpret(program, x))
        self.assertFalse(native.manifest['effects_permitted'])

    def test_cache_identity_capacity_and_changed_ir(self):
        cache = NativeDecisionCache(capacity=1)
        native, _ = cache.compile(self.program())
        again, hit = cache.compile(self.program())
        self.assertTrue(hit)
        self.assertIs(native, again)
        changed = replace(self.program(), default_action=8)
        cache.compile(changed)
        self.assertEqual(len(cache._cache), 1)
        self.assertEqual(cache.compilations, 2)
        self.assertEqual(native((0., -1.)), interpret(self.program(), (0., -1.)))

    def test_invalid_ir_and_nonfinite_values_rejected(self):
        cache = NativeDecisionCache()
        for program in ('raw machine code', replace(self.program(), width=True),
                        replace(self.program(), rules=(Rule((math.nan, 0.), 0, 1),))):
            with self.assertRaises(ValueError):
                cache.compile(program)
        native, _ = cache.compile(self.program())
        for values in ((math.nan, 0), (math.inf, 0), (True, 0), (1001, 0), (0,)):
            with self.assertRaises(ValueError):
                native(values)

    def test_many_numeric_boundaries_match_without_fastmath(self):
        import random
        rng = random.Random(701)
        program = self.program()
        native, _ = NativeDecisionCache().compile(program)
        for _ in range(500):
            y = rng.uniform(-100, 100)
            x = .5 + 2*y
            for value in (x, math.nextafter(x, math.inf), math.nextafter(x, -math.inf)):
                self.assertEqual(native((value, y)), interpret(program, (value, y)))

    def test_fixed_policy_latency_receipts_not_fake_mcp(self):
        report = benchmark_fixed_policy(self.program(), ((0., 0.), (2., 0.)), repeats=4, warmup=1)
        self.assertTrue(report['all_actions_equal'])
        self.assertEqual(report['timings']['cpu_native']['count'], 8)
        self.assertEqual(report['mcp_status'], 'not_run')
        self.assertEqual(report['gpu_status'], 'not_run')
        self.assertFalse(report['production_authorized'])


# Explicit modules are used by CI so absent Torch/LLVM dependencies fail, never skip.
if __name__ == '__main__':
    unittest.main()
