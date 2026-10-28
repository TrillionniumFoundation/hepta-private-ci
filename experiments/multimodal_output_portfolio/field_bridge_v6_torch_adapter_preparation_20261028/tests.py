"""Tiny real CPU Torch engineering checks; no scientific assets or kernel."""

import argparse
import hashlib
import io
import json
from pathlib import Path
import random
import sys
import tempfile
from unittest.mock import patch
import unittest

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028 import adapter

codec, state = adapter.codec, adapter.branch_state
WORK = {"toy_module_constructions": 0, "toy_pipeline_forwards": 0, "toy_dropout_forwards": 0,
        "toy_backward_calls": 0, "toy_optimizer_steps": 0, "toy_random_draw_calls": 0,
        "scientific_model_calls": 0, "scientific_training_steps": 0, "fresh_holdout_reads": 0}
EVIDENCE = {}


class Toy(torch.nn.Module):
    def __init__(self):
        super().__init__()
        self.p = torch.nn.Parameter(torch.tensor([.25, -.5]))
        self.q = torch.nn.Parameter(torch.tensor([.75, .125]))
        self.frozen = torch.nn.Parameter(torch.tensor([.0625]), requires_grad=False)
        self.register_buffer("counter", torch.tensor([3], dtype=torch.int64))
        self.drop = torch.nn.Dropout(.25)

    def forward(self, inputs):
        WORK["toy_pipeline_forwards"] += 1
        WORK["toy_dropout_forwards"] += 1
        with torch.no_grad(): self.counter.add_(1)
        return (self.drop(inputs) * self.p).sum() + .1 * self.q.square().sum() + self.frozen.sum()


def fixture():
    torch.manual_seed(7)
    random.seed(3)
    np.random.seed(5)
    model = Toy()
    optimizer = torch.optim.SGD([{"params": [model.p]}, {"params": [model.q], "lr": .02, "momentum": .75, "nesterov": True}], lr=.01, momentum=.9)
    model.p.grad = torch.tensor([.125, -.25])
    model.q.grad = None
    optimizer.state[model.p] = {"momentum_buffer": torch.tensor([.5, -.125])}
    original = torch.nn.Linear(2, 1, bias=False).eval().requires_grad_(False)
    observer = torch.nn.Linear(2, 1, bias=False).eval().requires_grad_(False)
    WORK["toy_module_constructions"] += 4
    generators = {"torch": torch.Generator(device="cpu").manual_seed(11), "python": random.Random(13),
                  "numpy": np.random.default_rng(17), "randomstate": np.random.RandomState(19)}
    h = hashlib.sha256(b"engineering-only-not-a-study-registration").hexdigest()
    binding = {"study_id": "engineering-toy-NOT_REGISTERED", **{key: h for key in
               ("proposal_sha256", "source_freeze_sha256", "prospective_protocol_sha256", "global_resource_limits_sha256")},
               "runtime_sha256": codec.digest(adapter.runtime_descriptor())}
    context = {"source_ids": [("synthetic-a", "synthetic-b")], "inputs": np.arange(4, dtype=np.float32).reshape(2, 2)}
    guard = {"panel_sha256": codec.digest(context), "source_ids": [("synthetic-a", "synthetic-b")],
             "output_sha256": [h], "values": np.asarray([.125], dtype=np.float64)}
    a = adapter.Adapter(model, optimizer, binding=binding, architecture={"toy": "two-vector-dropout-counter", "scientific": False},
                        original_generator=original, reward_observer=observer, context_inputs=context, guard_baseline=guard, named_generators=generators)
    tape = [{"step": step, "adapt_seed": step + 1, "clean_seed": step + 2, "noise_seed": step + 3, "condition": "clean"} for step in range(240, 288)]
    cursor = {"seed": 17, "schedule_id": 6000, "path_kind": "baseline", "clock": 240, "total_steps": 288,
              "remaining_steps": 48, "decision_index": 5, "guard_grain": 48, "baseline_action_index": 2, "schedule_sha256": codec.digest(tape)}
    return a, cursor, tape


def seal(a, cursor, tape):
    record = a.capture(cursor, tape)
    raw, checksum = state.seal(record, a.environment_sha256)
    if len(raw) >= 65536: raise AssertionError("Toy evidence exceeds its 64 KiB cap")
    return record, raw, checksum


def next_step(a):
    WORK["toy_random_draw_calls"] += 7
    inputs = torch.randn(2) + torch.rand(2, generator=a.generators["torch"])
    extra = np.random.standard_normal(2) + a.generators["numpy"].normal(size=2) + a.generators["randomstate"].normal(size=2)
    inputs += torch.from_numpy(extra).to(torch.float32) + random.random() + a.generators["python"].random()
    output = a.model(inputs)
    loss = (output - .25).square()
    WORK["toy_backward_calls"] += 1
    loss.backward()
    WORK["toy_optimizer_steps"] += 1
    a.optimizer.step()
    return {"input": adapter.array(inputs), "output": adapter.array(output), "loss": adapter.array(loss)}


def object_identity(a):
    return {"model": id(a.model), "optimizer": id(a.optimizer), "state": id(a.optimizer.state), "groups": id(a.optimizer.param_groups),
            "parameters": {name: id(p) for name, p in a.model.named_parameters()}, "buffers": {name: id(b) for name, b in a.model.named_buffers()},
            "gradients": {name: None if p.grad is None else id(p.grad) for name, p in a.model.named_parameters()}}


def public_fingerprint(a):
    params = dict(a.model.named_parameters())
    return codec.digest({"parameters": adapter.native(params), "gradients": {name: None if p.grad is None else adapter.array(p.grad) for name, p in params.items()},
                         "buffers": adapter.native(dict(a.model.named_buffers())), "optimizer": adapter.native(a.optimizer.state_dict()),
                         "requires_grad": {name: p.requires_grad for name, p in params.items()}, "modes": {name: module.training for name, module in a.model.named_modules()},
                         "references": {name: adapter.native(module.state_dict()) for name, module in a.references.items()},
                         "context": adapter.native(a.context_inputs), "guard": adapter.native(a.guard_baseline),
                         "rng": {"torch": adapter.array(torch.get_rng_state()), "python": random.getstate(), "numpy": adapter.native(np.random.get_state()),
                                 "named": {name: adapter.generator_state(g, adapter.generator_kind(g)) for name, g in a.generators.items()}}})


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.saved_rng = (torch.get_rng_state(), random.getstate(), np.random.get_state())

    def tearDown(self):
        torch.set_rng_state(self.saved_rng[0]); random.setstate(self.saved_rng[1]); np.random.set_state(self.saved_rng[2])

    def reject_unchanged(self, a, raw, checksum):
        before, identities = public_fingerprint(a), object_identity(a)
        versions = {name: p._version for name, p in a.model.named_parameters()}
        with self.assertRaises((ValueError, TypeError, RuntimeError, KeyError)):
            a.restore(raw, checksum, 65536)
        self.assertEqual(public_fingerprint(a), before)
        self.assertEqual(object_identity(a), identities)
        self.assertEqual({name: p._version for name, p in a.model.named_parameters()}, versions)

    def test_real_next_step_and_rng_are_bitwise_equal_after_literal_roundtrip(self):
        a, cursor, tape = fixture()
        record, raw, sha = seal(a, cursor, tape)
        first_output = next_step(a)
        first_state = codec.dumps(a.capture(cursor, tape))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "toy.state"
            receipt = codec.save(path, record, 65536)
            restored = a.restore(path.read_bytes(), receipt["sha256"], 65536)
        self.assertEqual(restored["state_sha256"], sha)
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), raw)
        self.assertEqual(codec.dumps(next_step(a)), codec.dumps(first_output))
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), first_state)
        self.assertFalse(restored["scientific_kernel_replay"])
        EVIDENCE["literal_roundtrip"] = {"checkpoint_bytes": len(raw), "checkpoint_sha256": sha,
            "serializer_measurement": codec.measure(record), "next_step_output_sha256": codec.digest(first_output),
            "next_step_full_state_sha256": hashlib.sha256(first_state).hexdigest(), "next_step_output_and_full_state_equal": True,
            "temporary_file_only": True, "scientific_kernel_replay": False}

    def test_none_grad_zero_grad_groups_momentum_and_buffers_restore(self):
        a, cursor, tape = fixture()
        a.model.p.grad.zero_()
        record, raw, sha = seal(a, cursor, tape)
        self.assertIsNone(record["gradients"]["q"])
        self.assertEqual(record["gradients"]["p"].tolist(), [0., 0.])
        with torch.no_grad(): a.model.p.add_(10); a.model.counter.add_(3)
        a.model.p.grad = None; a.model.q.grad = torch.ones_like(a.model.q)
        a.optimizer.param_groups[0]["lr"] = .375
        a.optimizer.state[a.model.p]["momentum_buffer"].add_(7)
        a.restore(raw, sha, 65536)
        self.assertEqual(codec.dumps(a.capture(cursor, tape)), raw)
        self.assertIsNone(a.model.q.grad)

    def test_all_rng_setters_validate_on_isolated_instances_before_writing(self):
        for kind in ("torch_cpu", "python", "numpy", "named"):
            a, cursor, tape = fixture()
            record, unused, unused_sha = seal(a, cursor, tape)
            if kind == "torch_cpu": record["rng"][kind] = np.zeros(17, dtype=np.uint8)
            elif kind in ("python", "numpy"): record["rng"][kind] = ()
            else: record["rng"]["named"]["numpy"]["kind"] = "numpy_generator:Philox"
            raw, sha = state.seal(record, a.environment_sha256)
            self.reject_unchanged(a, raw, sha)

    def test_wrong_optimizer_name_mapping_and_invalid_group_reject_before_writing(self):
        for change in ("mapping", "nesterov", "fused"):
            a, cursor, tape = fixture()
            record, unused, unused_sha = seal(a, cursor, tape)
            if change == "mapping": record["optimizer_parameter_names"] = {0: "q", 1: "p"}
            elif change == "nesterov": record["optimizer"]["param_groups"][0].update(nesterov=True, momentum=0.)
            else: record["optimizer"]["param_groups"][0]["fused"] = True
            raw, sha = state.seal(record, a.environment_sha256)
            self.reject_unchanged(a, raw, sha)

    def test_immutable_models_context_modes_and_requires_grad_drift_reject(self):
        for change in ("reference", "frozen", "context", "guard", "mode", "requires_grad", "plain_attribute"):
            a, cursor, tape = fixture()
            unused, raw, sha = seal(a, cursor, tape)
            with torch.no_grad():
                if change == "reference": next(a.references["original_generator"].parameters()).add_(1)
                elif change == "frozen": a.model.frozen.add_(1)
                elif change == "context": a.context_inputs["inputs"][0, 0] += 1
                elif change == "guard": a.guard_baseline["values"][0] += 1
                elif change == "mode": a.model.drop.eval()
                elif change == "requires_grad": a.model.p.requires_grad_(False)
                else: a.model.drop.p = .5
            self.reject_unchanged(a, raw, sha)

    def test_target_tensor_dtype_and_optimizer_order_incompatibility_are_atomic(self):
        for change in ("dtype", "order"):
            a, cursor, tape = fixture()
            unused, raw, sha = seal(a, cursor, tape)
            if change == "dtype": a.model.p.data = a.model.p.detach().to(torch.float64)
            else: a.optimizer.param_groups.reverse()
            self.reject_unchanged(a, raw, sha)

    def test_shared_storage_and_registered_hooks_are_rejected(self):
        a, cursor, tape = fixture()
        a.model.q.data = a.model.p.data
        with self.assertRaisesRegex(ValueError, "Shared"):
            a.capture(cursor, tape)
        a, cursor, tape = fixture()
        handle = a.model.register_forward_hook(lambda *args: None)
        with self.assertRaisesRegex(ValueError, "hooks"):
            a.capture(cursor, tape)
        handle.remove()
        for register in ("register_hook", "register_post_accumulate_grad_hook"):
            a, cursor, tape = fixture()
            handle = getattr(a.model.p, register)(lambda *args: None)
            versions = a.model.p._version
            with self.assertRaisesRegex(ValueError, "hooks"):
                a.capture(cursor, tape)
            self.assertEqual(a.model.p._version, versions)
            handle.remove()

    def test_reference_context_guard_storage_alias_is_rejected_before_apply(self):
        for location in ("reference", "context", "guard"):
            a, cursor, tape = fixture()
            unused, raw, sha = seal(a, cursor, tape)
            if location == "reference": a.references["original_generator"].weight.data = a.model.p.detach().reshape(1, 2)
            elif location == "context": a.context_inputs["bad_alias"] = a.model.p.detach().numpy()
            else: a.guard_baseline["bad_alias"] = a.model.p.detach()
            self.reject_unchanged(a, raw, sha)

    def test_underlying_numpy_rng_alias_and_autograd_buffers_are_rejected(self):
        a, cursor, tape = fixture()
        a.generators["duplicate"] = np.random.Generator(a.generators["numpy"].bit_generator)
        with self.assertRaisesRegex(ValueError, "alias"):
            a.capture(cursor, tape)
        a, cursor, tape = fixture()
        a.generators["global_alias"] = np.random.Generator(np.random.mtrand._rand._bit_generator)
        with self.assertRaisesRegex(ValueError, "alias"):
            a.capture(cursor, tape)
        for field in ("buffer", "momentum"):
            a, cursor, tape = fixture()
            if field == "buffer": a.model.register_buffer("bad", a.model.p * 2)
            else: a.optimizer.state[a.model.p]["momentum_buffer"] = a.model.p * 2
            with self.assertRaisesRegex(ValueError, "autograd"):
                a.capture(cursor, tape)
        a, cursor, tape = fixture()
        handle = a.optimizer.register_step_pre_hook(lambda *args: None)
        with self.assertRaisesRegex(ValueError, "hooks"):
            a.capture(cursor, tape)
        handle.remove()

    def test_runtime_and_record_identity_reject_without_mutation(self):
        a, cursor, tape = fixture()
        record, raw, sha = seal(a, cursor, tape)
        self.reject_unchanged(a, raw, "0" * 64)
        record["binding"]["prospective_protocol_sha256"] = "f" * 64
        raw = codec.dumps(record)
        self.reject_unchanged(a, raw, hashlib.sha256(raw).hexdigest())
        unused, raw, sha = seal(a, cursor, tape)
        with patch.dict(adapter.os.environ, {"ATEN_CPU_CAPABILITY": "deliberately-incompatible-test-marker"}):
            self.reject_unchanged(a, raw, sha)

    def test_apply_failure_restores_public_state_and_original_objects_but_reports_versions(self):
        a, cursor, tape = fixture()
        unused, raw, sha = seal(a, cursor, tape)
        next_step(a)
        before, identities = public_fingerprint(a), object_identity(a)
        real_apply, attempts = a._apply, []
        def interrupted(prepared):
            attempts.append(1)
            real_apply(prepared)
            if len(attempts) == 1: raise RuntimeError("synthetic apply interruption")
        with patch.object(a, "_apply", interrupted), self.assertRaises(adapter.RestoreError) as caught:
            a.restore(raw, sha, 65536)
        self.assertTrue(caught.exception.rollback_equal)
        self.assertFalse(caught.exception.versions_equal)
        self.assertEqual(public_fingerprint(a), before)
        self.assertEqual(object_identity(a), identities)

    def test_sparse_meta_and_named_rng_alias_are_rejected(self):
        for tensor in (torch.sparse_coo_tensor([[0]], [1.], (2,)), torch.empty(2, device="meta")):
            with self.assertRaises(ValueError): adapter.array(tensor)
        a, cursor, tape = fixture()
        a.generators["duplicate"] = a.generators["torch"]
        with self.assertRaisesRegex(ValueError, "alias"):
            a.capture(cursor, tape)

    def test_custom_tensor_and_optimizer_array_attributes_reject_before_apply(self):
        for change in ("tensor", "optimizer"):
            a, cursor, tape = fixture()
            unused, raw, sha = seal(a, cursor, tape)
            if change == "tensor": a.model.p.scale = .75
            else: a.optimizer.some_reference = a.model.p
            version = a.model.p._version
            before = a.model.p.detach().clone()
            with patch.object(a, "_apply") as apply, self.assertRaisesRegex(ValueError, "attributes"):
                a.restore(raw, sha, 65536)
            apply.assert_not_called()
            self.assertEqual(a.model.p._version, version)
            self.assertTrue(torch.equal(a.model.p, before))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    output = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(AdapterTests)
    result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    print(output.getvalue(), end="")
    sources = {path.name: {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in Path(__file__).parent.glob("*.py")}
    allowed = ("experiments.multimodal_output_portfolio.field_bridge_v6_preparation_20261028", "experiments.multimodal_output_portfolio.field_bridge_v6_torch_adapter_preparation_20261028")
    forbidden_imports = [name for name in sys.modules if name.startswith("experiments.multimodal_output_portfolio.") and not name.startswith(allowed)]
    report = {"status": "NOT_REGISTERED / NOT_EXECUTED", "engineering_passed": result.wasSuccessful() and not forbidden_imports,
              "scientific_status": "FAIL", "admission": False, "scientific_kernel_replay": False, "work": WORK,
              "evidence": EVIDENCE,
              "tests": {"run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "output": output.getvalue()},
              "sources": sources, "foundation_sources": adapter.FOUNDATION, "forbidden_scientific_imports": forbidden_imports,
              "runtime": adapter.runtime_descriptor(), "boundary": "Between steps, no pending autograd graph or concurrent writer. Successful restore advances autograd version counters; unexpected apply failure reports whether public state rollback succeeded."}
    if args.report:
        with args.report.open("x") as stream: json.dump(report, stream, sort_keys=True, indent=2); stream.write("\n")
    raise SystemExit(0 if report["engineering_passed"] else 1)


if __name__ == "__main__":
    main()
