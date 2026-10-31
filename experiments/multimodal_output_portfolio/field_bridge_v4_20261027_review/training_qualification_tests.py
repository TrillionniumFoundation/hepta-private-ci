"""Synthetic V4 contracts. No original generator, observer, or corpus is loaded."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace

import numpy as np

from ..field_bridge_v4_20261027 import training_qualification as q
from ..field_bridge_v4_20261027 import training_run as cli
from ..field_bridge_v3_20261027.training_common import Journal, file_hash, object_hash, write_json

HERE = Path(__file__).resolve().parent
PROTOCOL_PATH = HERE.parent / "field_bridge_v4_20261027/PROTOCOL.json"
OLD_ROOT = Path("/tmp/hepta-field-v3-run")
PROTOCOL = json.loads(PROTOCOL_PATH.read_text())


def historical_inputs(seed):
    bank_path = OLD_ROOT / "bank" / str(seed) / "BANK.json"
    head_path = OLD_ROOT / "fit" / str(seed) / "CONTROLLERS.json"
    reference_path = OLD_ROOT / "reference" / str(seed) / "REFERENCE.json"
    scope = {"study_id": PROTOCOL["study_id"], "protocol_sha256": file_hash(PROTOCOL_PATH),
             "source_allocation_sha256": PROTOCOL["source_allocation_sha256"],
             "source_manifest_sha256": PROTOCOL["source_manifest_sha256"],
             "bank_sha256": file_hash(bank_path), "controller_file_sha256": file_hash(head_path),
             "reference_file_sha256": file_hash(reference_path), "synthetic_fixture": True}
    return json.loads(head_path.read_text()), json.loads(bank_path.read_text()), scope


def build_tree(root):
    """Artificial numeric traces with real released frozen-head math; fake checkpoint bytes."""
    root = Path(root)
    for seed in q.SEEDS:
        fitted, bank, scope = historical_inputs(seed)
        directory, paths = root / "train" / str(seed), {}
        directory.mkdir(parents=True)
        write_json(directory / "START.json", {"synthetic_fixture": True, "study_id": PROTOCOL["study_id"],
            "phase": "train", "seed": seed, "scope": scope, "requested_roles": list(q.ADAPTATION_ROLES),
            "loaded_observer_names": ["reward"]})
        for policy in q.policies(fitted, bank, PROTOCOL, scope):
            for sid in PROTOCOL["qualification"]["schedule_ids"]:
                out = directory / policy["name"] / ("schedule-" + str(sid))
                out.mkdir(parents=True)
                observed = np.array(policy["identity"]["fit_initial"])
                observed[list(q.PANEL_INDICES)] += .01
                realized = {**policy["identity"], "observed_initial": observed.tolist(), "schedule_id": sid}
                policy_sha, decisions = object_hash(realized), []
                state = {"parameters": "p0", "optimizer": "o0"}
                with Journal(out / "decisions-and-outcomes.jsonl.gz") as journal:
                    for index, step in enumerate(range(0, 288, 48)):
                        raw = observed.copy()
                        raw[4] += index * .001
                        raw[6] = step / 288 if index else observed[6]
                        mapped, prediction, action = q.choose(policy, raw, observed)
                        digest = journal.append({"schema": q.SCHEMA + ".decision.1", "study_id": PROTOCOL["study_id"],
                            "kind": "decision_before_update", "seed": seed, "method": policy["name"], "step": step,
                            "schedule_id": sid, "before": dict(state), "action_index": action, "raw_state": raw.tolist(),
                            "mapped_state": mapped.tolist(), "observed_initial": observed.tolist(),
                            "fit_initial": policy["identity"]["fit_initial"], "panel_indices": list(q.PANEL_INDICES),
                            "calibration_context": observed[list(q.PANEL_INDICES)].tolist(),
                            "predictions": None if prediction is None else prediction.tolist(),
                            "prediction_state_kind": "mapped" if policy["identity"]["uses_translated_prediction_state"] else "raw",
                            "base_policy_sha256": policy["base_policy_sha256"], "policy_sha256": policy_sha,
                            "schedule_sha256": object_hash([seed, sid, step]), "feature_receipt": {"state_grad_rng_invariant": True},
                            "current_reward_values": [0.], "current_output_sha256": ["synthetic"]})
                        accepted = action == 0 or index % 2 == 0
                        after = dict(state) if not accepted or action == 0 else {"parameters": f"p{index+1}", "optimizer": f"o{index+1}"}
                        receipt = {"start": step, "end": step + 48, "action_index": action, "schedule_id": sid,
                            "schedule_sha256": object_hash([seed, sid, step]), "before": dict(state), "after": after,
                            "accepted": accepted, "clock_advances_on_rejection": True,
                            "resources": {"scheduled_gradient_microsteps": 48, "gradient_backward_calls": 48,
                                          "gradient_backward_examples": 4608}}
                        journal.append({"schema": q.SCHEMA + ".block-outcome.1", "study_id": PROTOCOL["study_id"],
                            "kind": "block_outcome", "decision_sha256": digest, "policy_sha256": policy_sha, "receipt": receipt})
                        decisions.append({"step": step, "action_index": action, "accepted": accepted, "decision_sha256": digest})
                        state = after
                (out / "checkpoint.pt").write_bytes(b"synthetic-only-not-a-torch-checkpoint")
                metadata = {"study_id": PROTOCOL["study_id"], "seed": seed, "method": policy["name"], "schedule_id": sid,
                            "policy_sha256": policy_sha, "base_policy_sha256": policy["base_policy_sha256"],
                            "source_roles": list(q.ADAPTATION_ROLES), "endpoint_accessed": False}
                record = {"schema": q.SCHEMA + ".trained-path.1", **metadata, "policy_identity": realized,
                          "checkpoint": {"file_sha256": file_hash(out / "checkpoint.pt"), "metadata": metadata},
                          "decisions": decisions, "final_step": 288, "final_identity": state, "files": q.inventory(out),
                          "resources": {"scheduled_gradient_microsteps": 288, "gradient_backward_examples": 27648}}
                write_json(out / "COMPLETE.json", record)
                paths[str(out.relative_to(directory))] = {"complete_sha256": file_hash(out / "COMPLETE.json"), "policy_sha256": policy_sha}
        write_json(directory / "COMPLETE.json", {"schema": q.SCHEMA + ".trained-seed.1", "study_id": PROTOCOL["study_id"],
            "seed": seed, "source_roles": list(q.ADAPTATION_ROLES), "observer_names": ["reward"], "methods": list(q.METHODS),
            "schedule_ids": PROTOCOL["qualification"]["schedule_ids"], "scope": scope, "paths": paths,
            "endpoint_accessed": False, "files": q.inventory(directory)})
        write_json(root / "PHASE_RECEIPTS" / f"train-{seed}.json", {
            "schema": q.SCHEMA + ".phase-cost-receipt.1", "study_id": PROTOCOL["study_id"], "phase": "train",
            "seed": seed, "scope": scope, "complete_sha256": file_hash(directory / "COMPLETE.json"),
            "preflight_verification_wall_ns": 0, "preflight_verification_cpu_ns": 0,
            "postflight_verification_wall_ns": 0, "postflight_verification_cpu_ns": 0, "phase_wall_ns": 1, "phase_cpu_ns": 1,
            "synthetic_fixture": True})
    return root


def freeze_fixture(path, root, phase, artifacts=None):
    old = {"DEVELOPMENT_SELECTION.json": file_hash(OLD_ROOT / "DEVELOPMENT_SELECTION.json")}
    for seed in q.SEEDS:
        for name in (f"bank/{seed}/BANK.json", f"bank/{seed}/COMPLETE.json",
                     f"fit/{seed}/CONTROLLERS.json", f"fit/{seed}/COMPLETE.json",
                     f"reference/{seed}/REFERENCE.json", f"reference/{seed}/COMPLETE.json"):
            old[name] = file_hash(OLD_ROOT / name)
    value = {"study_id": PROTOCOL["study_id"], "registered_commit": "0" * 40,
        "allowed_phases": [phase], "protocol_sha256": file_hash(PROTOCOL_PATH), "source_files": cli.source_files(),
        "old_artifacts": old, "artifacts": artifacts or {}, "synthetic_fixture_only": True}
    path.write_text(json.dumps(value))
    return value


class OriginContracts(unittest.TestCase):
    def test_nine_policies_and_frozen_weights(self):
        fitted, bank, scope = historical_inputs(43)
        before = object_hash(fitted)
        policies = q.policies(fitted, bank, PROTOCOL, scope)
        self.assertEqual([p["name"] for p in policies], list(q.METHODS))
        self.assertEqual(object_hash(fitted), before)
        first = np.asarray(policies[0]["identity"]["fit_initial"])
        observed = first.copy(); observed[list(q.PANEL_INDICES)] += .02
        for policy in policies:
            mapped, scores, action = q.choose(policy, observed, observed)
            np.testing.assert_array_equal(mapped[list(q.PANEL_INDICES)], first[list(q.PANEL_INDICES)])
            if policy["head"] is None:
                self.assertEqual(action, int(policy["name"][-1]))
            else:
                expected = first if policy["name"].startswith("origin_") else observed
                np.testing.assert_array_equal(scores, q.predict(policy["head"], expected))

    def test_policy_identity_binds_origin_rule_head_and_scope(self):
        fitted, bank, scope = historical_inputs(17)
        first = q.policies(fitted, bank, PROTOCOL, scope)[5]
        changed = dict(scope, controller_file_sha256="f" * 64)
        second = q.policies(fitted, bank, PROTOCOL, changed)[5]
        self.assertNotEqual(first["base_policy_sha256"], second["base_policy_sha256"])
        with self.assertRaises(ValueError):
            q.policies(fitted, bank, PROTOCOL, dict(scope, reference_file_sha256="a" * 64))
        bad = deepcopy(PROTOCOL); bad["panel_origin"]["translated_indices"] = [0]
        with self.assertRaises(ValueError):
            q.settings(bad)

    def test_new_configuration_rejects_reselection_and_old_schedules(self):
        for key, value in [("schedule_ids", [6000, 6001, 6002, 6003]), ("adaptive_comparator", "origin_h7"),
                           ("ordinary_action_indices", {"17": 1, "29": 3, "43": 3}), ("family_alpha", .1)]:
            bad = deepcopy(PROTOCOL); bad["qualification"][key] = value
            with self.assertRaises(ValueError):
                q.settings(bad)

    def test_pure_import_has_no_torch(self):
        result = subprocess.run([sys.executable, "-c",
            "import sys; import experiments.multimodal_output_portfolio.field_bridge_v4_20261027.training_run; assert 'torch' not in sys.modules"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


class SealContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="training-synthetic-", dir=HERE)
        cls.root = build_tree(Path(cls.temporary.name) / "run")
        cls.scope = {"study_id": PROTOCOL["study_id"], "protocol_sha256": file_hash(PROTOCOL_PATH),
                     "synthetic_fixture": True}
        cls.seal = q.seal_training(cls.root, PROTOCOL, cls.scope)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_all_108_paths_are_required_before_seal(self):
        self.assertEqual(q.verify_seal(self.root, PROTOCOL)["paths"], 108)
        path = self.root / "train/43/origin_h7/schedule-14003/COMPLETE.json"
        saved = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaises((ValueError, FileNotFoundError)):
                q.verify_seal(self.root, PROTOCOL)
        finally:
            path.write_bytes(saved)


    def test_all_three_postflight_receipts_required_before_seal(self):
        path = self.root / "PHASE_RECEIPTS/train-43.json"
        saved = path.read_bytes()
        try:
            path.unlink()
            with self.assertRaisesRegex(ValueError, "three successful training postflight"):
                q.seal_training(self.root, PROTOCOL, self.scope)
        finally:
            path.write_bytes(saved)

    def test_postflight_receipts_bound_to_seed_scope_and_complete(self):
        path = self.root / "PHASE_RECEIPTS/train-17.json"
        saved = path.read_bytes()
        try:
            original = json.loads(saved)
            for key, value in [("seed", 29), ("schema", "wrong"), ("complete_sha256", "0" * 64),
                               ("scope", {"wrong": "scope"})]:
                changed = deepcopy(original); changed[key] = value
                path.write_text(json.dumps(changed))
                with self.assertRaisesRegex(ValueError, "not bound"):
                    q.training_inventory(self.root, PROTOCOL)
        finally:
            path.write_bytes(saved)

    def test_checkpoint_change_and_unlisted_file_rejected(self):
        path = self.root / "train/17/ordinary_0/schedule-14000/checkpoint.pt"
        saved = path.read_bytes()
        try:
            path.write_bytes(saved + b"mutation")
            with self.assertRaises(ValueError):
                q.verify_seal(self.root, PROTOCOL)
        finally:
            path.write_bytes(saved)
        extra = self.root / "train/17/unlisted.txt"
        try:
            extra.write_text("unexpected")
            with self.assertRaises(ValueError):
                q.verify_seal(self.root, PROTOCOL)
        finally:
            extra.unlink()

    def test_initial_origin_and_rollback_recomputed_independently(self):
        path = self.root / "train/17/ordinary_1/schedule-14000"
        done = json.loads((path / "COMPLETE.json").read_text())
        with gzip.open(path / "decisions-and-outcomes.jsonl.gz", "rt") as stream:
            original = [json.loads(line) for line in stream]
        probe = Path(self.temporary.name) / "tampered-trace.gz"
        for change in ("origin", "rollback", "pair"):
            rows = deepcopy(original)
            if change == "origin":
                rows[2]["observed_initial"][0] += .1
            elif change == "rollback":
                rows[3]["receipt"]["after"]["optimizer"] = "changed-after-rejection"
            else:
                rows[1]["decision_sha256"] = "not-the-committed-decision"
            with gzip.open(probe, "wt") as stream:
                stream.write("\n".join(json.dumps(row) for row in rows) + "\n")
            with self.assertRaises(ValueError):
                q.verify_trace(probe, done)
        probe.unlink()

    def test_external_freeze_must_bind_every_training_file(self):
        path = Path(self.temporary.name) / "freeze.json"
        freeze_fixture(path, self.root, "evaluate", {"TRAINING_SEAL.json": file_hash(self.root / "TRAINING_SEAL.json")})
        with self.assertRaisesRegex(ValueError, "every training artifact"):
            cli.verify_freeze(path, PROTOCOL_PATH, "evaluate", self.root, OLD_ROOT)
        full = {"TRAINING_SEAL.json": file_hash(self.root / "TRAINING_SEAL.json"), **self.seal["files"]}
        freeze_fixture(path, self.root, "evaluate", full)
        cli.verify_freeze(path, PROTOCOL_PATH, "evaluate", self.root, OLD_ROOT)

    def test_dependency_and_historical_pins_checked_before_scientific_import(self):
        path = Path(self.temporary.name) / "freeze.json"
        value = freeze_fixture(path, self.root, "train")
        del value["source_files"]["field_bridge_v3_20261027/source_roles.py"]
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, "required dependency"):
            cli.verify_freeze(path, PROTOCOL_PATH, "train", self.root, OLD_ROOT)
        value = freeze_fixture(path, self.root, "train")
        value["old_artifacts"]["reference/17/REFERENCE.json"] = "0" * 64
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            cli.verify_freeze(path, PROTOCOL_PATH, "train", self.root, OLD_ROOT)

    def test_evaluation_cannot_start_without_all_path_seal(self):
        empty = Path(self.temporary.name) / "empty"
        empty.mkdir(exist_ok=True)
        freeze = Path(self.temporary.name) / "empty-freeze.json"
        freeze_fixture(freeze, empty, "evaluate")
        with self.assertRaises((FileNotFoundError, ValueError)):
            cli.verify_freeze(freeze, PROTOCOL_PATH, "evaluate", empty, OLD_ROOT)


class TinyTorchCheckpointContract(unittest.TestCase):

    def test_actual_train_path_freezes_first_origin_and_restores_rejections(self):
        import torch
        from ..field_bridge_v3_20261027 import learning, training_features
        from ..field_bridge_20261027.adapters import local_parameters
        original = torch.nn.Module()
        for name in PROTOCOL["training"]["adapter_modules"]:
            parent, _, leaf = name.rpartition(".")
            if parent:
                if not hasattr(original, parent):
                    setattr(original, parent, torch.nn.Sequential(torch.nn.Linear(2, 2)))
            else:
                setattr(original, leaf, torch.nn.Linear(2, 2))
        fitted, bank, scope = historical_inputs(17)
        policy = q.policies(fitted, bank, PROTOCOL, scope)[1]
        calls, first = [], np.array(policy["identity"]["fit_initial"])
        first[list(q.PANEL_INDICES)] += .01
        context = SimpleNamespace(original=original, seed=17, protocol=PROTOCOL, costs=q.Costs())
        def measure(context, model, optimizer, step, sid):
            calls.append(step)
            raw = first.copy(); raw[list(q.PANEL_INDICES)] += step * .00001
            context.costs.add("directional_gradient_measurements")
            return raw.tolist(), {"values": {"reward": np.array([0.])}, "output_sha256": ["synthetic"]}, {
                "before": learning.state_identity(model, optimizer), "state_grad_rng_invariant": True}
        def block(context, model, optimizer, start, action, sid):
            saved, costs = learning.snapshot(model, optimizer), context.costs
            costs.add("transaction_snapshots")
            for _ in range(48):
                optimizer.zero_grad(set_to_none=True)
                for parameter in local_parameters(model):
                    parameter.grad = torch.full_like(parameter, .0001)
                for group in optimizer.param_groups:
                    group["lr"] = .2 * PROTOCOL["training"]["multipliers"][action]
                optimizer.step()
            costs.add("scheduled_gradient_microsteps", 48)
            costs.add("gradient_backward_calls", 48)
            costs.add("gradient_backward_examples", 4608)
            costs.add("optimizer_steps", 48)
            accepted = start % 96 == 0
            if not accepted:
                learning.restore(model, optimizer, saved)
                costs.add("rejected_blocks"); costs.add("discarded_gradient_microsteps", 48)
            else:
                costs.add("accepted_blocks")
            return {"start": start, "end": start + 48, "action_index": action, "schedule_id": sid,
                "schedule_sha256": object_hash(learning.schedule(context.seed, sid, start, 48, context.protocol)),
                "before": saved["identity"], "after": learning.state_identity(model, optimizer), "accepted": accepted}
        with tempfile.TemporaryDirectory(prefix="training-path-synthetic-", dir=HERE) as directory:
            path = Path(directory) / "path"
            with mock.patch.object(training_features, "measure_state", side_effect=measure), \
                 mock.patch.object(learning, "guarded_block", side_effect=block):
                record = q.train_path(context, policy, path, 14000)
            q.verify_trace(path / "decisions-and-outcomes.jsonl.gz", record)
            self.assertEqual(calls, list(range(0, 288, 48)))
            self.assertEqual(record["resources"]["scheduled_gradient_microsteps"], 288)
            self.assertEqual(record["resources"]["discarded_gradient_microsteps"], 144)
            self.assertEqual(record["resources"]["panel_origin_captures"], 1)
            self.assertEqual(record["resources"]["panel_origin_calibration_context_bytes"], 112)
            self.assertEqual(record["resources"]["panel_origin_translation_calls"], 6)
            np.testing.assert_array_equal(record["policy_identity"]["observed_initial"], first)

    def test_parameters_sgd_gradients_rng_and_metadata_roundtrip(self):
        import torch
        from ..field_bridge_v3_20261027.learning import make_model, new_optimizer, snapshot, state_identity
        from ..field_bridge_20261027.adapters import local_parameters
        original = torch.nn.Module()
        for name in PROTOCOL["training"]["adapter_modules"]:
            parent_name, _, leaf = name.rpartition(".")
            if parent_name:
                if not hasattr(original, parent_name):
                    setattr(original, parent_name, torch.nn.Sequential(torch.nn.Linear(2, 2)))
            else:
                setattr(original, leaf, torch.nn.Linear(2, 2))
        model = make_model(original, 17, PROTOCOL)
        optimizer = new_optimizer(model, PROTOCOL)
        loss = sum((p.square() + .01 * p).sum() for p in local_parameters(model))
        loss.backward(); optimizer.step()
        expected = snapshot(model, optimizer)
        with tempfile.TemporaryDirectory(prefix="training-checkpoint-synthetic-", dir=HERE) as directory:
            path = Path(directory) / "checkpoint.pt"
            q.save_checkpoint(path, model, optimizer, PROTOCOL, {"seed": 17, "policy_sha256": "a" * 64})
            restored, restored_optimizer = q.load_checkpoint(path, original, 17, PROTOCOL, "a" * 64)
            self.assertEqual(state_identity(restored, restored_optimizer), expected["identity"])
            for parameter, gradient in zip(local_parameters(restored), expected["gradients"], strict=True):
                self.assertTrue(torch.equal(parameter.grad, gradient))
            self.assertTrue(torch.equal(torch.get_rng_state(), expected["rng"]))
            with self.assertRaises(ValueError):
                q.load_checkpoint(path, original, 17, PROTOCOL, "b" * 64)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seal-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit("Refusing to overwrite an existing test receipt")
    started = time.perf_counter_ns()
    coverage = (unittest.defaultTestLoader.loadTestsFromTestCase(SealContracts) if args.seal_only
                else unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    result = unittest.TextTestRunner(verbosity=2).run(coverage)
    files = [Path(__file__), HERE.parent / "field_bridge_v4_20261027/training_qualification.py",
             HERE.parent / "field_bridge_v4_20261027/training_run.py", HERE / "training_panel_origin.py"]
    receipt = {"schema": q.SCHEMA + ".runner-synthetic-contract.1", "passed": result.wasSuccessful(),
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "original_generators_observers_corpus_loaded": False, "new_scientific_optimizer_steps": 0,
        "synthetic_tiny_optimizer_steps": 0 if args.seal_only else 289,
        "verification_scope": "seal contracts after concrete postflight race fix" if args.seal_only else "full runner synthetic suite", "real_inputs": "Only already released frozen fit-head/bank/reference metadata",
        "wall_ns": time.perf_counter_ns() - started, "source_files": {str(p.relative_to(HERE.parent)): file_hash(p) for p in files}}
    write_json(args.output, receipt)
    raise SystemExit(0 if result.wasSuccessful() else 1)
