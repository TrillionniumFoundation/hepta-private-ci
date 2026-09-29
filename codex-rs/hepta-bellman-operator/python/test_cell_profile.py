"""The numerical scorer profile binds behavior, not just tensor bytes.

No callback is allowed to execute as a side effect of schema admission. This is
an in-process compatibility check, not isolation from arbitrary Python code.
"""
import copy
import unittest
from unittest.mock import patch

import torch
from torch import nn

import test_cell_head as fixtures
from cell_head import HeadRejected, head_schema, restore_candidate, state_digest


class ProfileTests(unittest.TestCase):
    setUp = fixtures.HeadTests.setUp
    fit = fixtures.HeadTests.fit

    def rejected_without_call(self, install):
        called = []
        handle = install(lambda *args, **kwargs: called.append(True))
        try:
            with self.assertRaises(HeadRejected):
                self.fit()
            self.assertEqual(called, [])
        finally:
            handle.remove()

    def test_top_level_forward_hook_is_not_part_of_the_admitted_profile(self):
        self.rejected_without_call(self.head.register_forward_hook)

    def test_nested_forward_pre_hook_is_not_part_of_the_admitted_profile(self):
        self.rejected_without_call(self.head[1].register_forward_pre_hook)

    def test_full_backward_hook_is_rejected_before_training(self):
        self.rejected_without_call(self.head[1].register_full_backward_hook)

    def test_state_dict_hook_must_not_execute_during_hashing(self):
        called = []
        handle = self.head.register_state_dict_pre_hook(lambda *args: called.append(True))
        try:
            with self.assertRaises(HeadRejected):
                state_digest(self.head)
            self.assertEqual(called, [])
        finally:
            handle.remove()

    def test_load_state_dict_hook_is_not_inherited_by_candidate(self):
        self.rejected_without_call(self.head.register_load_state_dict_pre_hook)

    def test_parameter_gradient_hook_is_not_declared_sgd(self):
        self.rejected_without_call(self.head[1].weight.register_hook)

    def test_global_module_hook_is_rejected_without_running_it(self):
        self.rejected_without_call(nn.modules.module.register_module_forward_hook)

    def test_instance_forward_override_is_not_hidden_in_state_digest(self):
        called = []
        original = self.head[1].forward
        def changed(x):
            called.append(True)
            return original(x)
        self.head[1].forward = changed
        with self.assertRaises(HeadRejected):
            self.fit()
        self.assertEqual(called, [])

    def test_compiled_call_override_is_not_an_eager_scorer(self):
        called = []
        self.head._compiled_call_impl = lambda *args: called.append(True)
        with self.assertRaises(HeadRejected):
            head_schema(self.head)
        self.assertEqual(called, [])

    def test_instance_state_serializer_override_is_not_invoked(self):
        called = []
        original = self.head.state_dict
        def changed(*args, **kwargs):
            called.append(True)
            return original(*args, **kwargs)
        self.head.state_dict = changed
        with self.assertRaises(HeadRejected):
            state_digest(self.head)
        self.assertEqual(called, [])

    def test_aliasing_parameter_storage_is_not_an_independent_scorer(self):
        self.head[1].bias = self.head[0].weight
        with self.assertRaises(HeadRejected):
            self.fit()

    def test_distinct_parameters_aliasing_the_same_storage_also_reject(self):
        self.head[1].bias = nn.Parameter(self.head[0].weight.detach())
        self.assertIsNot(self.head[1].bias, self.head[0].weight)
        with self.assertRaises(HeadRejected):
            head_schema(self.head)

    def test_supported_head_digest_and_sgd_are_unchanged_after_hook_removal(self):
        expected = self.fit()
        handle = self.head.register_forward_hook(lambda *args: None)
        handle.remove()
        actual = self.fit()
        self.assertEqual(actual.candidate_head_digest, expected.candidate_head_digest)
        self.assertEqual(actual.payload, expected.payload)

    def test_unsupported_gelu_rejects_at_admission_not_later_forward(self):
        self.head[2].approximate = "undeclared"
        with self.assertRaises(HeadRejected):
            head_schema(self.head)

    def test_restore_rejects_callback_on_actual_copy_before_loading(self):
        fit = self.fit()
        called = []
        original = copy.deepcopy
        def install_after_copy(obj):
            candidate = original(obj)
            candidate.register_load_state_dict_pre_hook(lambda *args: called.append(True))
            return candidate
        with patch("cell_head.copy.deepcopy", side_effect=install_after_copy):
            with self.assertRaises(HeadRejected):
                restore_candidate(self.head, fit, bundle=fit.base_bundle_digest,
                                  scope=fit.scope_id, objective=fit.objective_digest)
        self.assertEqual(called, [])

    def test_copy_boundary_cannot_install_callback_after_validation(self):
        called = []
        original = copy.deepcopy
        def install_before_copy(obj):
            handle = self.head.register_forward_hook(lambda *args: called.append(True))
            self.addCleanup(handle.remove)
            return original(obj)
        with patch("cell_head.copy.deepcopy", side_effect=install_before_copy):
            with self.assertRaises(HeadRejected):
                self.fit()
        self.assertEqual(called, [])


if __name__ == "__main__":
    unittest.main()
