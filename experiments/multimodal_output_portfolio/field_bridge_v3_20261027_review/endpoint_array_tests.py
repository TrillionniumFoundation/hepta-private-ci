"""Constructed endpoint fixtures only; no V3 source outcomes are read."""

import copy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from endpoint_arrays import adapt, development_selection, object_sha, stack_panels, verify_panel_identity
from training_endpoint_audit import audit, same, verify_hard, verify_policy_binding


SOURCE = Path(__file__).parent.parent / "field_bridge_v3_20261027"


def fixture(seed=17, phase="development"):
    protocol = json.loads((SOURCE / "PROTOCOL.json").read_text())
    methods = ([f"ordinary_{i}" for i in range(4)] if phase == "development" else ["ordinary"]) + ["field", "generic", "richer", "h7"]
    effects = {"ordinary_0": 0., "ordinary_1": .01, "ordinary_2": .01, "ordinary_3": .03,
               "ordinary": .01, "field": .04, "generic": .02, "richer": .02, "h7": .015}
    data = {"methods": np.asarray(methods), "schedule_ids": np.asarray(protocol["training"][phase + "_schedule_ids"]),
            "observer_names": np.asarray(["reward", "audit"])}
    registry = {"roles": {}}
    identities = {}
    rng = np.random.default_rng(seed)
    for panel, pair_count in (("task", 4), ("clean", 3)):
        role = phase + "_" + panel
        ids = [f"synthetic:{role}:{i}" for i in range(2 * pair_count)]
        registry["roles"][role] = {"identities": ids}
        pairs = [ids[i:i + 2] for i in range(0, len(ids), 2)]
        conditions = protocol["training"]["conditions"] if panel == "task" else ["clean"]
        original = rng.uniform(.2, .6, (2, len(conditions) * pair_count))
        data["original_" + panel] = original
        data[panel + "_values"] = np.stack([np.broadcast_to(original + (effects[method] if panel == "task" else 0.),
                                                            (4, *original.shape)).copy() for method in methods])
        if panel == "clean" and phase == "development":
            data[panel + "_values"][methods.index("ordinary_3"), :, 1] -= .02
        data[panel + "_source_ids"] = np.asarray(pairs * len(conditions))
        data[panel + "_conditions"] = np.asarray([condition for condition in conditions for _ in pairs])
        batches = []
        role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
        for index, condition in enumerate(conditions):
            batches.append({"condition": condition, "source_ids": pairs, "batch_size": len(pairs),
                            "noise_seed": protocol["training"]["hard_forward_seed_offset"] + seed * 1009 + role_seed + index * 1000003,
                            "public_sha256": "e" * 64, "target_sha256": "f" * 64})
        identities[panel] = {"batches": batches, "sha256": object_sha(batches), "independent_of_schedule_id": True}
        data[panel + "_panel_identity"] = np.asarray(identities[panel]["sha256"])
    return data, protocol, registry, identities


class EndpointArrayTests(unittest.TestCase):
    def test_condition_major_to_pair_condition_adapter_is_exact(self):
        data, protocol, registry, identities = fixture()
        result = adapt(data, 17, "development", protocol, registry)
        for panel in ("task", "clean"):
            verify_panel_identity(identities[panel], result, panel, protocol, registry)
        values = result["panels"]["task"]["reward"]["field"]
        self.assertEqual(values.shape, (4, 4, 4))
        index = data["methods"].tolist().index("field")
        self.assertEqual(values[2, 1, 3], data["task_values"][index, 2, 0, 3 * 4 + 1])

    def test_source_role_substitution_or_permutation_rejected(self):
        for alteration in ("other_role", "reverse"):
            data, protocol, registry, _ = fixture()
            if alteration == "other_role":
                data["task_source_ids"][0] = data["clean_source_ids"][0]
            else:
                data["task_source_ids"] = data["task_source_ids"][::-1]
            with self.assertRaisesRegex(ValueError, "source order"):
                adapt(data, 17, "development", protocol, registry)

    def test_missing_path_nonfinite_and_wrong_condition_rejected(self):
        for kind in ("path", "nan", "condition"):
            data, protocol, registry, _ = fixture()
            if kind == "path":
                data["task_values"] = data["task_values"][:, :3]
            elif kind == "nan":
                data["clean_values"][0, 0, 0, 0] = np.nan
            else:
                data["task_conditions"] = data["task_conditions"][::-1]
            with self.assertRaises(ValueError):
                adapt(data, 17, "development", protocol, registry)

    def test_schedule_specific_endpoint_identity_is_rejected(self):
        data, protocol, registry, identities = fixture()
        result = adapt(data, 17, "development", protocol, registry)
        identities["task"]["batches"][0]["noise_seed"] += 1
        identities["task"]["sha256"] = object_sha(identities["task"]["batches"])
        result["panel_identity"]["task"] = identities["task"]["sha256"]
        with self.assertRaisesRegex(ValueError, "RNG alignment"):
            verify_panel_identity(identities["task"], result, "task", protocol, registry)

    def test_audit_retains_all_five_methods_and_four_paths(self):
        rows = []
        for seed in (17, 29, 43):
            data, protocol, registry, _ = fixture(seed, "audit")
            rows.append(adapt(data, seed, "audit", protocol, registry))
        stacked = stack_panels(rows, protocol)
        self.assertEqual(set(stacked["task"]["reward"]), {"frozen", "ordinary", "field", "generic", "richer", "h7"})
        self.assertEqual(stacked["task"]["reward"]["field"].shape, (3, 4, 4, 4))

    def test_final_roles_are_rejected(self):
        data, protocol, registry, _ = fixture()
        with self.assertRaisesRegex(ValueError, "does not open final"):
            adapt(data, 17, "final", protocol, registry)

    def test_no_complete_phase_fails_before_freeze_or_outcome_read(self):
        with tempfile.TemporaryDirectory(prefix="v3-endpoint-missing-", dir="/tmp") as root:
            with self.assertRaisesRegex(ValueError, "All three phase COMPLETE"):
                audit(root, "development", SOURCE, Path(root) / "nonexistent-freeze.json")


class SelectionParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.production = importlib.import_module("experiments.multimodal_output_portfolio.field_bridge_v3_20261027.training_stages")

    def parity(self, mutate=None):
        converted = []
        with tempfile.TemporaryDirectory(prefix="v3-selection-synthetic-", dir="/tmp") as root:
            for seed in (17, 29, 43):
                data, protocol, registry, _ = fixture(seed)
                if mutate is not None:
                    mutate(data)
                converted.append(adapt(data, seed, "development", protocol, registry))
                destination = Path(root) / "development" / str(seed)
                destination.mkdir(parents=True)
                np.savez_compressed(destination / "ENDPOINTS.npz", **data)
            expected = development_selection(converted, protocol)
            actual = self.production.select_development(root, protocol)
            selected_fields = {key: actual[key] for key in expected if key != "arithmetic_contract"}
            error = same(selected_fields, {key: value for key, value in expected.items() if key != "arithmetic_contract"})
            return expected, error

    def test_all_frozen_selection_arithmetic_and_eligibility_agree(self):
        result, error = self.parity()
        self.assertTrue(result["passed"])
        self.assertEqual(result["ordinary_action_indices"], {"17": 1, "29": 1, "43": 1})
        self.assertEqual(result["selected_adaptive"], "generic")
        self.assertEqual(error, 0.)

    def test_near_tie_uses_unrounded_paired_gains(self):
        def change(data):
            data["original_task"][:] = 0.
            for index in range(len(data["methods"])):
                data["task_values"][index] = 0.02
            data["task_values"][1] = .01
            data["task_values"][2] = np.nextafter(.01, np.inf)
            data["task_values"][0] = 0.
            data["task_values"][4] = .04
        result, error = self.parity(change)
        self.assertEqual(result["ordinary_action_indices"], {"17": 2, "29": 2, "43": 2})
        self.assertEqual(error, 0.)

    def test_no_eligible_adaptive_keeps_failure_and_all_arithmetic(self):
        def change(data):
            for method in ("generic", "richer", "h7"):
                data["clean_values"][data["methods"].tolist().index(method), :, 1] -= .02
        result, error = self.parity(change)
        self.assertFalse(result["passed"])
        self.assertIsNone(result["selected_adaptive"])
        self.assertEqual(error, 0.)


class HardEvidenceTests(unittest.TestCase):
    def test_frozen_controller_and_ordinary_choice_binding(self):
        heads = {"field": {"synthetic_head": [1., 2.]}}
        record = {"controller_sha256": object_sha(heads["field"]), "decisions": [{"action_index": 2}] * 6}
        verify_policy_binding(record, "field", heads)
        with self.assertRaisesRegex(ValueError, "different fitted controller"):
            verify_policy_binding(record, "field", {"field": {"synthetic_head": [2., 1.]}})
        record["controller_sha256"] = None
        verify_policy_binding(record, "ordinary", heads, 2)
        with self.assertRaisesRegex(ValueError, "registered constant"):
            verify_policy_binding(record, "ordinary", heads, 1)

    def test_exact_hard_pixel_utf8_identity_and_aggregate_values(self):
        ids, conditions = [["synthetic:a", "synthetic:b"]], ["clean"]
        pixels, captions = np.zeros((1, 1, 28, 56), dtype=np.uint8), np.asarray(["left 0 right 1"])
        values = np.asarray([[.5], [.4]])
        data = {"pixels_u8": pixels, "captions_utf8": captions, "source_ids": np.asarray(ids),
                "conditions": np.asarray(conditions), "values_reward": values[0], "values_audit": values[1],
                "output_sha256": np.asarray([hashlib.sha256(pixels[0].tobytes() + captions[0].encode()).hexdigest()])}
        with tempfile.TemporaryDirectory(prefix="v3-hard-synthetic-", dir="/tmp") as root:
            path = Path(root) / "hard.npz"
            np.savez_compressed(path, **data)
            self.assertEqual(verify_hard(path, values, ids, conditions), 1)
            data["pixels_u8"][0, 0, 0, 0] = 1
            np.savez_compressed(path, **data)
            with self.assertRaisesRegex(ValueError, "byte identities"):
                verify_hard(path, values, ids, conditions)


if __name__ == "__main__":
    unittest.main()
