"""Capacity-only positive and adversarial fixtures; no scientific values are opened."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import capacity_amendment as a, common as c


class CapacityAmendmentTests(unittest.TestCase):
    def test_old_loader_still_rejects_new_cap_and_new_validator_accepts_declared_profile(self):
        path = c.OWN / "OPS_EXECUTION08.json"
        sha = c.descriptor(path)["sha256"]
        with self.assertRaisesRegex(ValueError, "different attempt02"):
            a.ORIGINAL_LOADER(path, sha)
        value = a.load_registration(path, sha)
        self.assertEqual(value["proposed_resource_contract"]["global_raw_logical_bytes"], 6 * a.GIB)

    def test_exact_profile_hash_and_own_path_are_required(self):
        path = c.OWN / "OPS_EXECUTION08.json"
        with self.assertRaises(ValueError):
            a.load_registration(path, "0" * 64)
        with tempfile.TemporaryDirectory() as name:
            copy = Path(name) / path.name
            copy.write_bytes(path.read_bytes())
            with self.assertRaisesRegex(ValueError, "exact committed"):
                a.load_registration(copy, c.descriptor(copy)["sha256"])

    def test_other_limits_retry_rules_and_identity_cannot_change(self):
        path = c.OWN / "OPS_EXECUTION08.json"
        item = c.descriptor(path)
        real_bound = c.bound
        cases = [
            ("proposed_resource_contract", "global_raw_logical_bytes", 7 * a.GIB),
            ("proposed_resource_contract", "minimum_private_allocatable_bytes", 0),
            ("proposed_resource_contract", "C_training_evidence_bytes", a.GIB),
            ("concurrency", "max_workers", 3),
            ("durable_execution", "automatic_scientific_retry", True),
            ("durable_execution", "unknown_upload_outcome_retry", True),
            ("durable_execution", "initial_disk_headroom_bytes", 2 * a.GIB),
            ("durable_execution", "imported_jobs", ["A-17"]),
            ("durable_execution", "unchanged_numeric_resource_contract", True),
        ]
        for group, key, value in cases:
            with self.subTest(group=group, key=key):
                changed = deepcopy(real_bound(item))
                changed[group][key] = value

                def bound(desc):
                    return changed if desc == item else real_bound(desc)

                with patch.object(c, "bound", side_effect=bound), self.assertRaises(ValueError):
                    a.load_registration(path, item["sha256"])

    def test_actual_disk_headroom_must_pass_new_gate_in_addition_to_old_gate(self):
        a.require_disk_sample({"original_joint_pass": True, "disk_available": a.INITIAL_DISK})
        for sample in (
            {"original_joint_pass": True, "disk_available": a.INITIAL_DISK - 1},
            {"original_joint_pass": False, "disk_available": a.INITIAL_DISK},
            {"original_joint_pass": True},
            {"original_joint_pass": True, "disk_available": True},
        ):
            with self.subTest(sample=sample), self.assertRaises(ValueError):
                a.require_disk_sample(sample)

    def test_scoped_aliases_bind_new_profile_and_restore_even_on_failure(self):
        contract = c.read(c.OWN / "INPUT_CONTRACT.json")
        config = {"source_files": contract["source_files"],
                  "descriptors": {"amendment": c.descriptor(c.OWN / "OPS_EXECUTION08.json")}}
        names = list(a.MODULE_NAMES)
        modules = [a.importlib.import_module(a.PACKAGE + name) for name in names]
        old = [(m, m.load_registration) for m in modules if hasattr(m, "load_registration")]
        with self.assertRaisesRegex(RuntimeError, "synthetic stop"):
            with a.installed(config):
                for module, previous in old:
                    self.assertIs(previous, a.ORIGINAL_LOADER)
                    self.assertIs(module.load_registration, a.load_registration)
                with self.assertRaisesRegex(ValueError, "Nested"):
                    with a.installed(config):
                        pass
                raise RuntimeError("synthetic stop")
        for module, previous in old:
            self.assertIs(module.load_registration, previous)

    def test_original_sources_and_all_noncap_numeric_limits_stay_literal(self):
        contract = c.read(c.OWN / "INPUT_CONTRACT.json")
        for relative, sha in contract["source_files"].items():
            self.assertEqual(c.descriptor(c.SOURCE / relative)["sha256"], sha, relative)
        original = c.read(c.SOURCE / contract["original_resource_amendment"]["path"])
        current = a.load_registration(c.OWN / "OPS_EXECUTION08.json", c.descriptor(c.OWN / "OPS_EXECUTION08.json")["sha256"])
        for key, value in original["proposed_resource_contract"].items():
            if type(value) in (int, float, bool) and key != "global_raw_logical_bytes":
                self.assertEqual(current["proposed_resource_contract"][key], value)
        self.assertEqual(current["concurrency"], original["concurrency"])


if __name__ == "__main__":
    unittest.main()
