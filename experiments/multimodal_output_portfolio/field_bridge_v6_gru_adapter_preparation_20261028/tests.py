"""Tiny stock CPU GRU preparation tests; never imports scientific kernels."""

import argparse
import copy
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
import unittest
from unittest.mock import patch
import weakref

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028 import adapter, contract, equivalence

strict, codec, state = contract.strict, contract.codec, contract.strict.branch_state
WORK = {"toy_fixture_module_objects": 0, "toy_fixture_optimizer_constructions": 0,
        "toy_gru_forwards": 0, "toy_backward_calls": 0, "toy_optimizer_steps": 0, "toy_explicit_random_draw_calls": 0,
        "scientific_model_calls": 0, "scientific_training_steps": 0, "fresh_holdout_reads": 0}
EVIDENCE = {}


def fixture():
    torch.manual_seed(31); random.seed(37); np.random.seed(41)
    WORK["toy_fixture_module_objects"] += 3
    model = torch.nn.GRU(2, 2, num_layers=1, bias=True, batch_first=True, dropout=0., bidirectional=False)
    original = copy.deepcopy(model).eval().requires_grad_(False)
    observer = torch.nn.Linear(2, 1, bias=False).eval().requires_grad_(False)
    parameters = list(model.parameters())
    WORK["toy_fixture_optimizer_constructions"] += 1
    optimizer = torch.optim.SGD([{"params": parameters[:2]}, {"params": parameters[2:], "lr": .02}], lr=.01, momentum=.9)
    parameters[0].grad = torch.zeros_like(parameters[0])
    optimizer.state[parameters[0]] = {"momentum_buffer": torch.full_like(parameters[0], .125)}
    digest = hashlib.sha256(b"engineering-gru-toy-NOT_REGISTERED").hexdigest()
    binding = {"study_id": "gru-engineering-toy-NOT_REGISTERED", **{key: digest for key in
        ("proposal_sha256", "source_freeze_sha256", "prospective_protocol_sha256", "global_resource_limits_sha256")},
        "runtime_sha256": codec.digest(strict.runtime_descriptor())}
    context = {"source_ids": [("toy-a", "toy-b")], "inputs": np.arange(4, dtype=np.float32).reshape(2, 2)}
    guard = {"panel_sha256": codec.digest(context), "source_ids": [("toy-a", "toy-b")],
             "output_sha256": [digest], "values": np.asarray([.25], dtype=np.float64)}
    a = adapter.GRUAdapter(model, optimizer, binding=binding, architecture={"toy": "gru-2-by-2", "scientific": False},
        original_generator=original, reward_observer=observer, context_inputs=context, guard_baseline=guard,
        named_generators={"torch": torch.Generator(device="cpu").manual_seed(43)})
    tape = [{"step": step, "adapt_seed": step + 1, "clean_seed": step + 2, "noise_seed": step + 3, "condition": "clean"}
            for step in range(240, 288)]
    cursor = {"seed": 17, "schedule_id": 6000, "path_kind": "baseline", "clock": 240, "total_steps": 288,
              "remaining_steps": 48, "decision_index": 5, "guard_grain": 48, "baseline_action_index": 2,
              "schedule_sha256": codec.digest(tape)}
    return a, cursor, tape


def seal(a, cursor, tape):
    record = a.capture(cursor, tape)
    raw, checksum = state.seal(record, a.environment_sha256)
    if len(raw) >= 65536: raise AssertionError("Tiny checkpoint exceeded 64 KiB")
    return record, raw, checksum


def next_step(a):
    WORK["toy_explicit_random_draw_calls"] += 4
    inputs = torch.randn(2, 2, 2) + torch.rand(2, 2, 2, generator=a.generators["torch"])
    inputs += float(random.random()) + torch.from_numpy(np.random.standard_normal((2, 2, 2))).float()
    hidden = torch.full((1, 2, 2), .125)
    a.optimizer.zero_grad(set_to_none=True)
    WORK["toy_gru_forwards"] += 1
    output, final_hidden = a.model(inputs, hidden)
    loss = output.square().mean() + final_hidden.square().mean()
    WORK["toy_backward_calls"] += 1
    loss.backward()
    WORK["toy_optimizer_steps"] += 1
    a.optimizer.step()
    return {"input": strict.array(inputs), "initial_hidden": strict.array(hidden), "output": strict.array(output.detach().contiguous()),
            "final_hidden": strict.array(final_hidden), "loss": strict.array(loss)}


def public_fingerprint(a):
    params = dict(a.model.named_parameters())
    return codec.digest({"parameters": {name: strict.array(p.detach()) for name, p in params.items()}, "buffers": strict.native(dict(a.model.named_buffers())),
        "gradients": {name: None if p.grad is None else strict.array(p.grad) for name, p in params.items()},
        "optimizer": strict.native(a.optimizer.state_dict()), "references": {key: strict.native(m.state_dict()) for key, m in a.references.items()},
        "modes": {name: m.training for name, m in a.model.named_modules()}, "context": strict.native(a.context_inputs),
        "guard": strict.native(a.guard_baseline), "rng": {"torch": strict.array(torch.get_rng_state()), "python": random.getstate(),
        "numpy": strict.native(np.random.get_state()), "named": {key: strict.generator_state(g, strict.generator_kind(g)) for key, g in a.generators.items()}}})


def object_identity(a):
    return {"model": id(a.model), "optimizer": id(a.optimizer), "state": id(a.optimizer.state), "groups": id(a.optimizer.param_groups),
        "parameters": {name: id(p) for name, p in a.model.named_parameters()},
        "gradients": {name: None if p.grad is None else id(p.grad) for name, p in a.model.named_parameters()},
        "cache": [id(value) for value in a.model._flat_weights], "weakrefs": [id(value) for value in a.model._flat_weight_refs]}


class GRUTests(unittest.TestCase):
    def setUp(self):
        self.rng = (torch.get_rng_state(), random.getstate(), np.random.get_state())

    def tearDown(self):
        torch.set_rng_state(self.rng[0]); random.setstate(self.rng[1]); np.random.set_state(self.rng[2])

    def reject_unchanged(self, a, raw, checksum):
        before, objects = public_fingerprint(a), object_identity(a)
        versions = {name: p._version for name, p in a.model.named_parameters()}
        with patch.object(a, "_apply") as apply, self.assertRaises((ValueError, TypeError, RuntimeError)):
            a.restore(raw, checksum, 65536)
        apply.assert_not_called()
        self.assertEqual(public_fingerprint(a), before)
        self.assertEqual(object_identity(a), objects)
        self.assertEqual({name: p._version for name, p in a.model.named_parameters()}, versions)

    def test_copied_source_ast_globals_and_stock_methods(self):
        contract.verify_stock_methods()
        self.assertEqual(equivalence.verify(adapter.GRUAdapter), adapter.EQUIVALENCE)
        self.assertEqual(len(contract.EXPECTED_METHODS), 18)
        EVIDENCE["copy_equivalence"] = adapter.EQUIVALENCE
        EVIDENCE["stock_methods"] = [{"source": key, "class": cls, "name": name, "code_sha256": value["code_sha256"]}
                                     for (key, cls, name), value in contract.EXPECTED_METHODS.items()]

    def test_literal_restore_and_actual_next_step_equal(self):
        a, cursor, tape = fixture()
        record, raw, sha = seal(a, cursor, tape)
        first_output = next_step(a)
        first_state = codec.dumps(a.capture(cursor, tape))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny-gru.state"
            receipt = codec.save(path, record, 65536)
            restored = a.restore(path.read_bytes(), receipt["sha256"], 65536)
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), raw)
        self.assertEqual(codec.dumps(next_step(a)), codec.dumps(first_output))
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), first_state)
        for name, cached, reference in zip(a.model._flat_weights_names, a.model._flat_weights, a.model._flat_weight_refs, strict=True):
            self.assertIs(cached, getattr(a.model, name)); self.assertIs(reference(), cached)
        self.assertFalse(restored["scientific_kernel_replay"])
        EVIDENCE["literal_replay"] = {"checkpoint_bytes": len(raw), "checkpoint_sha256": sha, "serializer": codec.measure(record),
            "next_output_hidden_input_loss_sha256": codec.digest(first_output), "next_full_state_sha256": hashlib.sha256(first_state).hexdigest(),
            "output_hidden_loss_state_bitwise_equal": True, "same_live_target": True, "cache_aliases_valid": True,
            "hidden_is_explicit_local_input_not_cross_step_state": True, "temporary_file_only": True}

    def test_none_zero_grad_and_sgd_restore_without_cache_replacement(self):
        a, cursor, tape = fixture()
        record, raw, sha = seal(a, cursor, tape)
        self.assertTrue(np.all(record["gradients"]["weight_ih_l0"] == 0))
        self.assertIsNone(record["gradients"]["bias_hh_l0"])
        cached = [id(value) for value in a.model._flat_weights]
        with torch.no_grad(): a.model.weight_ih_l0.add_(1)
        a.model.weight_ih_l0.grad = None
        a.model.bias_hh_l0.grad = torch.ones_like(a.model.bias_hh_l0)
        a.optimizer.param_groups[0]["lr"] = .4
        a.optimizer.state[a.model.weight_ih_l0]["momentum_buffer"].add_(2)
        a.restore(raw, sha, 65536)
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), raw)
        self.assertEqual([id(value) for value in a.model._flat_weights], cached)

    def test_corrupt_cache_layout_rejected_before_first_write(self):
        for change in ("wrong_parameter", "names_order", "names_tuple", "all_weights_order", "all_weights_tuple", "cache_count", "cache_tuple"):
            with self.subTest(change=change):
                a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
                if change == "wrong_parameter": a.model._flat_weights[0] = torch.nn.Parameter(a.model.weight_ih_l0.detach().clone())
                elif change == "names_order": a.model._flat_weights_names.reverse()
                elif change == "names_tuple": a.model._flat_weights_names = tuple(a.model._flat_weights_names)
                elif change == "all_weights_order": a.model._all_weights[0].reverse()
                elif change == "all_weights_tuple": a.model._all_weights = (a.model._all_weights[0],)
                elif change == "cache_count": a.model._flat_weights.pop()
                else: a.model._flat_weights = tuple(a.model._flat_weights)
                self.reject_unchanged(a, raw, sha)

    def test_stale_custom_callback_and_wrong_container_weakrefs_rejected(self):
        for change in ("stale", "callable", "callback", "container"):
            with self.subTest(change=change):
                a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
                foreign = torch.nn.Parameter(a.model.weight_ih_l0.detach().clone())
                if change == "stale": a.model._flat_weight_refs[0] = weakref.ref(foreign)
                elif change == "callable": a.model._flat_weight_refs[0] = lambda: a.model.weight_ih_l0
                elif change == "callback": a.model._flat_weight_refs[0] = weakref.ref(a.model.weight_ih_l0, lambda value: None)
                else: a.model._flat_weight_refs = tuple(a.model._flat_weight_refs)
                self.reject_unchanged(a, raw, sha)

    def test_instance_and_class_dispatch_overrides_reject_before_apply(self):
        for method in ("forward", "_update_flat_weights", "permute_hidden", "check_forward_args",
                       "check_input", "get_expected_hidden_size", "check_hidden_size"):
            a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
            with patch.object(a.model, method, lambda *args: None): self.reject_unchanged(a, raw, sha)
            with patch.object(torch.nn.GRU, method, lambda *args: None): self.reject_unchanged(a, raw, sha)
        a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
        function = contract.RNN.RNNBase._weights_have_changed
        code = function.__code__
        try:
            function.__code__ = (lambda self: False).__code__
            self.reject_unchanged(a, raw, sha)
        finally: function.__code__ = code
        defaults = torch.nn.GRU.forward.__defaults__
        try:
            torch.nn.GRU.forward.__defaults__ = (False,)
            self.reject_unchanged(a, raw, sha)
        finally: torch.nn.GRU.forward.__defaults__ = defaults
        function = contract.RNN.RNNBase.__init__
        defaults = function.__defaults__
        self.assertIs(type(defaults[0]), int)
        try:
            function.__defaults__ = (True, *defaults[1:])
            self.reject_unchanged(a, raw, sha)
        finally: function.__defaults__ = defaults

    def test_hooks_storage_and_reference_aliases_rejected_before_apply(self):
        for change in ("parameter_hook", "module_hook", "weight_alias", "reference_alias"):
            a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
            handle = None
            if change == "parameter_hook": handle = a.model.weight_ih_l0.register_hook(lambda *args: None)
            elif change == "module_hook": handle = a.model.register_forward_hook(lambda *args: None)
            elif change == "weight_alias": a.model.weight_hh_l0.data = a.model.weight_ih_l0.data
            else: a.references["original_generator"].weight_ih_l0.data = a.model.weight_ih_l0.data
            try: self.reject_unchanged(a, raw, sha)
            finally:
                if handle is not None: handle.remove()

    def test_unsupported_gru_profiles_and_subclasses_fail_closed(self):
        for key, value in (("batch_first", False), ("num_layers", 2), ("dropout", .25), ("hidden_size", 2.0)):
            a, cursor, tape = fixture(); unused, raw, sha = seal(a, cursor, tape)
            setattr(a.model, key, value)
            self.reject_unchanged(a, raw, sha)
        class DerivedGRU(torch.nn.GRU): pass
        WORK["toy_fixture_module_objects"] += 1
        model = DerivedGRU(2, 2, batch_first=True)
        with self.assertRaisesRegex(ValueError, "attributes"): contract.model_parts(model)

    def test_non_gru_strict_inspector_is_unchanged(self):
        WORK["toy_fixture_module_objects"] += 1
        model = torch.nn.Linear(2, 2)
        self.assertEqual(codec.dumps(strict.native(contract.model_parts(model))), codec.dumps(strict.native(strict.model_parts(model))))
        model.unregistered_array = torch.zeros(1)
        for inspect in (contract.model_parts, strict.model_parts):
            with self.assertRaisesRegex(ValueError, "attributes"): inspect(model)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--preflight-only", action="store_true", help="Skip the actual next-step test when rechecking an inspection-only change.")
    args = parser.parse_args()
    output = io.StringIO()
    names = unittest.defaultTestLoader.getTestCaseNames(GRUTests)
    if args.preflight_only: names.remove("test_literal_restore_and_actual_next_step_equal")
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.TestSuite(GRUTests(name) for name in names))
    print(output.getvalue(), end="")
    allowed = ("experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028",
        "experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028",
        "experiments.multimodal_output_portfolio.field_bridge_v6_gru_adapter_preparation_20261028")
    forbidden = [name for name in sys.modules if name.startswith("experiments.multimodal_output_portfolio.") and not name.startswith(allowed)]
    report = {"status": "NOT_REGISTERED / NOT_EXECUTED", "engineering_passed": result.wasSuccessful() and not forbidden,
        "scientific_status": "FAIL", "admission": False, "scientific_kernel_replay": False, "work": WORK, "evidence": EVIDENCE,
        "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "output": output.getvalue(),
                  "selection": "preflight_only" if args.preflight_only else "full_tiny_suite"},
        "sources": {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in Path(__file__).parent.glob("*.py")},
        "forbidden_scientific_imports": forbidden, "runtime": strict.runtime_descriptor(),
        "boundary": "No pending autograd graph or concurrent writer; no carried hidden state; stock CPU float32 single-layer 2-by-2 synthetic GRU only.",
        "count_scope": "Explicit test module constructions/draws/forward/backward/SGD steps. Inherited isolated preflight SGD/RNG constructors perform no forward or step and are not pipeline counts."}
    if args.report:
        with args.report.open("x") as stream: json.dump(report, stream, sort_keys=True, indent=2); stream.write("\n")
    raise SystemExit(0 if report["engineering_passed"] else 1)


if __name__ == "__main__": main()
