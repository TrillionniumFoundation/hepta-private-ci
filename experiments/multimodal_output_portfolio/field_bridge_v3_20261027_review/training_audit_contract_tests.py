"""Synthetic corruption contracts for the independent V3 evidence readers."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from .training_audit_common import (SCIENCE, bound, checkpoint, cost_check, digest, expected_schedule,
                                    hard_output, inventory, paired_block)


class TrainingAuditContracts(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hepta-v3-audit-contract-")
        self.root = Path(self.temporary.name)
        self.protocol = json.loads((SCIENCE / "PROTOCOL.json").read_text())
        self.p = self.protocol["training"]

    def tearDown(self):
        self.temporary.cleanup()

    def block(self, action=2, delta=.03, accepted=True):
        before, candidate = {"parameters": "p0", "optimizer": "m0"}, {"parameters": "p1", "optimizer": "m1"}
        if action == 0:
            candidate = before.copy()
        schedule = bound(expected_schedule(17, 5000, 0, 48, self.p))
        decision = {"record_index": 0, "committed_monotonic_ns": 100, "seed": 17, "step": 0,
                    "schedule_id": 5000, "action_index": action, "before": before, "schedule_sha256": schedule}
        edge = {"loss": .5, "unclipped_gradient_norm": .2, "optimizer_advanced": action != 0}
        receipt = {"start": 0, "end": 48, "schedule_id": 5000, "action_index": action,
            "schedule_sha256": schedule, "before": before, "candidate": candidate,
            "after": candidate if accepted else before, "clock_advances_on_rejection": True,
            "multiplier": self.p["multipliers"][action], "guard_values": [.4 + delta, .6 + delta],
            "guard_output_sha256": ["x", "y"], "guard_delta": delta, "accepted": accepted,
            "first_gradient": edge, "last_gradient": edge,
            "resources": {"scheduled_gradient_microsteps": 48, "gradient_backward_calls": 48,
                          "gradient_backward_examples": 4608, "transaction_snapshots": 1}}
        return decision, {"record_index": 1, "committed_monotonic_ns": 200, "receipt": receipt}

    def test_guard_acceptance_rollback_clock_and_chronology(self):
        for settings in ({}, {"delta": -.03, "accepted": False}, {"action": 0, "delta": 0.}):
            decision, outcome = self.block(**settings)
            paired_block(decision, outcome, np.array([.4, .6]), 17, self.p)
        decision, outcome = self.block(delta=-.03, accepted=False)
        cases = []
        changed = deepcopy(outcome); changed["receipt"]["after"] = changed["receipt"]["candidate"]; cases.append(changed)
        changed = deepcopy(outcome); changed["receipt"]["end"] = 0; cases.append(changed)
        changed = deepcopy(outcome); changed["committed_monotonic_ns"] = 90; cases.append(changed)
        changed = deepcopy(outcome); changed["receipt"]["guard_delta"] = .5; cases.append(changed)
        changed = deepcopy(outcome); changed["receipt"]["resources"]["gradient_backward_examples"] = 3072; cases.append(changed)
        for changed in cases:
            with self.assertRaises(ValueError):
                paired_block(decision, changed, np.array([.4, .6]), 17, self.p)

    def test_quantized_output_hash_and_source_alignment(self):
        registry = {"roles": {"test_fixture": {"identities": ["a", "b", "c", "d"]}}}
        pixels = np.zeros((2, 1, 28, 56), dtype=np.uint8)
        captions = np.asarray(["left 1 right 2 relation less", "left 3 right 3 relation equal"])
        hashes = [hashlib.sha256(pixel.tobytes() + caption.encode()).hexdigest() for pixel, caption in zip(pixels, captions)]
        arrays = {"pixels_u8": pixels, "captions_utf8": captions, "source_ids": np.asarray([["a", "b"], ["c", "d"]]),
                  "conditions": np.asarray(["clean", "clean"]), "output_sha256": np.asarray(hashes), "values_reward": np.asarray([.5, .7])}
        path = self.root / "hard.npz"
        np.savez_compressed(path, **arrays)
        self.assertAlmostEqual(hard_output(path, registry, "test_fixture", ["clean"])["mean"], .6)
        changed = {**arrays, "pixels_u8": pixels.copy()}; changed["pixels_u8"][0, 0, 0, 0] = 1
        np.savez_compressed(path, **changed)
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            hard_output(path, registry, "test_fixture", ["clean"])
        changed = {**arrays, "source_ids": arrays["source_ids"][::-1]}
        np.savez_compressed(path, **changed)
        with self.assertRaisesRegex(ValueError, "alignment differs"):
            hard_output(path, registry, "test_fixture", ["clean"])

    def test_checkpoint_tensor_and_complete_optimizer_hashes(self):
        import torch
        from ..v6.neural import NeuralPortfolio
        from ..field_bridge_v3_20261027.learning import make_model, new_optimizer, save_checkpoint
        torch.set_num_threads(2)
        original = NeuralPortfolio(hidden=16).eval().requires_grad_(False)
        model = make_model(original, 17, self.protocol)
        optimizer = new_optimizer(model, self.protocol)
        for group in optimizer.param_groups:
            for parameter in group["params"]:
                parameter.grad = torch.ones_like(parameter) * .01
        optimizer.step()
        path = self.root / "checkpoint.pt"
        save_checkpoint(path, model, optimizer, self.protocol, {"seed": 17})
        self.assertGreater(checkpoint(path, self.protocol, 17)["momentum_rms"], 0)
        record = torch.load(path, weights_only=True)
        record["optimizer"]["state"][0]["momentum_buffer"].add_(1.)
        torch.save(record, path)
        with self.assertRaisesRegex(ValueError, "optimizer hash differs"):
            checkpoint(path, self.protocol, 17)

    def test_completed_inventory_rejects_changed_and_additional_files(self):
        source = self.root / "portfolio" / "science"; source.mkdir(parents=True)
        (source / "PROTOCOL.json").write_text("{}")
        (source / "registered.py").write_text("registered = True\n")
        freeze = {"registered_commit": "a" * 40, "protocol_sha256": digest(source / "PROTOCOL.json"),
                  "allowed_phases": ["reference"], "source_files": {"science/registered.py": digest(source / "registered.py")}}
        frozen = self.root / "FREEZE.json"; frozen.write_text(json.dumps(freeze))
        directory = self.root / "reference"; directory.mkdir()
        start = {"phase": "reference", "seed": 17, "freeze_sha256": digest(frozen),
                 "registered_commit": freeze["registered_commit"], "protocol_sha256": freeze["protocol_sha256"],
                 "source_files": freeze["source_files"]}
        (directory / "START.json").write_text(json.dumps(start))
        (directory / "data.bin").write_bytes(b"original")
        complete = {"phase": "reference", "stage": "reference", "seed": 17,
                    "files": {name: digest(directory / name) for name in ("START.json", "data.bin")}}
        (directory / "COMPLETE.json").write_text(json.dumps(complete))
        inventory(directory, frozen, "reference", 17, source)
        (directory / "unregistered.bin").write_bytes(b"extra")
        with self.assertRaisesRegex(ValueError, "inventory changed"):
            inventory(directory, frozen, "reference", 17, source)
        (directory / "unregistered.bin").unlink()
        (directory / "data.bin").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "member changed"):
            inventory(directory, frozen, "reference", 17, source)

    def test_underreported_resource_ledger_is_rejected(self):
        registry = {"roles": {role: {"identities": list(range(count))} for role, count in
                    (("fit_guard", 512), ("reference_task", 512), ("reference_clean", 512))}}
        blocks = [{"action_index": action, "accepted": True} for action in range(4) for _ in range(6)]
        with self.assertRaisesRegex(ValueError, "gradient_generator_calls"):
            cost_check({"scheduled_gradient_microsteps": 1152}, "reference", 17, blocks, registry, self.p)

    def test_independent_augmented_ridge_reconstruction_and_normalizer_corruption(self):
        from ..field_bridge_v3_20261027.training_policy import fit_head
        from ..field_bridge_v3_20261027.training_features import NAMES
        from .training_fit_audit import check_head
        rng = np.random.default_rng(47019)
        raw, target = rng.normal(size=(18, 30)), rng.normal(size=(18, 4))
        for mode in ("field", "generic", "richer", "h7"):
            head = fit_head(raw, target, mode, .0001, self.protocol)
            error = check_head(head, raw, target, mode, .0001, self.p, list(NAMES))
            self.assertLess(error, 1e-8)
            changed = deepcopy(head); changed["raw_mean"][0] += .01
            with self.assertRaisesRegex(ValueError, "reconstruction differs"):
                check_head(changed, raw, target, mode, .0001, self.p, list(NAMES))

    def test_replay_sample_cannot_change_and_exact_guard_comparison_is_enforced(self):
        from .training_replay import REPLAY_PROTOCOL, compare_receipt, validate_plan
        plan = validate_plan()
        self.assertEqual(plan["sample"]["candidate_action_indices"], [0, 1, 2, 3])
        changed = deepcopy(plan); changed["sample"]["seed"] = 29
        path = self.root / "changed-replay.json"; path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(ValueError, "prespecified replay sample"):
            validate_plan(path)
        _, outcome = self.block()
        receipt = outcome["receipt"]
        compare_receipt(deepcopy(receipt), receipt)
        changed = deepcopy(receipt); changed["guard_values"][0] += 1e-15
        with self.assertRaisesRegex(ValueError, "exact state"):
            compare_receipt(changed, receipt)

    def test_replay_inputs_bind_completion_and_output_avoids_every_frozen_phase(self):
        from .training_replay import sample_inputs, validate_output
        directory = self.root / "bank/17"; directory.mkdir(parents=True)
        names = ["BANK.json", "decisions-and-outcomes.jsonl.gz", "trajectory-0-step-0-state.pt",
                 "trajectory-0-step-0-current.npz"]
        names += [f"trajectory-0-step-0-action-{action}-terminal.npz" for action in range(4)]
        for name in names:
            (directory / name).write_bytes(("synthetic:" + name).encode())
        complete = {"files": {name: digest(directory / name) for name in names}}
        self.assertEqual(sample_inputs(directory, complete), complete["files"])
        missing = deepcopy(complete); del missing["files"][names[0]]
        with self.assertRaisesRegex(ValueError, "absent from the completed bank: BANK.json"):
            sample_inputs(directory, missing)
        (directory / names[-1]).write_bytes(b"changed synthetic terminal output")
        with self.assertRaisesRegex(ValueError, "differs from the completed bank: trajectory-0-step-0-action-3-terminal.npz"):
            sample_inputs(directory, complete)
        for phase in ("reference", "bank", "fit", "development", "audit", "final"):
            with self.assertRaisesRegex(ValueError, "every frozen phase inventory"):
                validate_output(self.root, self.root / phase / "new-replay")
        validate_output(self.root, self.root / "review/new-replay")


if __name__ == "__main__":
    unittest.main()
