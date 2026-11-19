"""Prospective control-only fixtures: no provider, model, dataset or training."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from . import rawdiff_guard as guard


ROOT = Path(__file__).resolve().parents[3]
PARENT = ROOT / "qualification/hcsn_regenerative/studies/s81-20261107/plan.json"


class ResourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.parent = guard.read(PARENT, guard.PARENT_SHA)
        self.child = copy.deepcopy(self.parent)
        self.child.update(study_id=guard.STUDY_ID, frozen_at="FIXTURE_NOT_AN_ACTUAL_FREEZE")
        for index, row in enumerate(self.child["qualification_receipts"].values()):
            row["sha256"] = guard.digest(("FIXTURE_FRESH_RECEIPT_"+str(index)).encode())
        guard.add_prospective_pins(self.child, ROOT)
        self.child["resource_migration"] = dict(parent_plan_sha256=guard.PARENT_SHA,
            parent_study_id=self.parent["study_id"], account_selector="tomas", expected_username="braynttomas",
            prior_v1_state_unchanged=True, v1_fit_completion_credit=0,
            qualification_request_id=guard.amendment()["qualification_request_id"],
            native_producer=dict(notebook_ref="braynttomas/fixture-not-a-real-producer", notebook_version=1),
            native_receipt_sha256="1"*64, qualification_payload_sha256="2"*64,
            qualification_manifest_sha256="3"*64, amendment_sha256="4"*64)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)

    def test_only_resource_identity_changes_preserve_all_budgets(self):
        result = guard.audit_diff(self.parent, self.child)
        self.assertEqual(result["unchanged_parent_source_files"], 42)
        self.assertEqual(result["added_source_files"], 5)
        self.assertEqual(result["registered_training_attempts"], 160)
        self.assertEqual(result["registered_optimizer_updates"], 64000)
        self.assertEqual(result["statistical_family_size"], 20)
        self.assertEqual(result["original_campaign_completion_credit"], 0)
        self.assertEqual(result["expansion_admission"], "HOLD")
        self.assertIsNone(result["full_physical_energy_joules"])

    def test_changed_training_budget_arm_data_and_seed_rejected(self):
        mutations = dict(train_updates=399, max_fit_wall_seconds=600, batch_size=32,
            training_seeds=[1103], test_episode_seeds=[1103], learning_rates=[.001],
            split_seed=1, arms=self.child["arms"][:-1], state_count=25, expected_parameter_count=986,
            ordered_fit_roster_sha256="0"*64, original_campaign_completion_credit=1)
        for key, value in mutations.items():
            with self.subTest(field=key):
                candidate = copy.deepcopy(self.child); candidate[key] = value
                with self.assertRaisesRegex(ValueError, "Scientific/budget/statistical"):
                    guard.audit_diff(self.parent, candidate)

    def test_mud_holm_family_retention_and_energy_cannot_change(self):
        for key, value in (("useful_absolute_mse_reduction", .001), ("family_size", 18),
                           ("alpha", .1), ("retention", 0), ("registered_independent_seeds", 8)):
            candidate = copy.deepcopy(self.child); candidate["statistical_contract"][key] = value
            with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)
        candidate = copy.deepcopy(self.child); candidate["full_physical_energy_joules"] = 0
        with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)

    def test_undeclared_top_level_addition_or_removal_rejected(self):
        candidate = copy.deepcopy(self.child); candidate["capacity_padding"] = True
        with self.assertRaisesRegex(ValueError, "Plan keys"):
            guard.audit_diff(self.parent, candidate)
        candidate = copy.deepcopy(self.child); candidate.pop("external_retention_status")
        with self.assertRaisesRegex(ValueError, "Plan keys"):
            guard.audit_diff(self.parent, candidate)

    def test_original42_cannot_be_changed_deleted_or_replaced(self):
        key = next(iter(self.parent["source_pins"]))
        for mode in ("changed", "deleted", "extra"):
            candidate = copy.deepcopy(self.child)
            if mode == "changed": candidate["source_pins"][key] = "0"*64
            elif mode == "deleted": candidate["source_pins"].pop(key)
            else: candidate["source_pins"]["unreviewed.py"] = "0"*64
            with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)

    def test_old_qualification_identity_is_not_fresh(self):
        for name in guard.SLOTS:
            candidate = copy.deepcopy(self.child)
            candidate["qualification_receipts"][name] = self.parent["qualification_receipts"][name]
            with self.subTest(slot=name), self.assertRaisesRegex(ValueError, "Old qualification"):
                guard.audit_diff(self.parent, candidate)

    def test_fixed_s81_grid_and_error_thresholds_are_not_reselected(self):
        for key, value in (("active_cells", 128), ("phase_cells", 32), ("eligible", False),
                           ("maximum_state_l1_error", .0200001), ("maximum_hit_relative_error", .0300001)):
            candidate = copy.deepcopy(self.child); candidate["numerical_resolution"][key] = value
            with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)

    def test_old_namespace_and_old_owner_credit_rejected(self):
        for key, value in (("account_selector", "qiqian"), ("expected_username", "alexqipku"),
                           ("v1_fit_completion_credit", 1), ("prior_v1_state_unchanged", False)):
            candidate = copy.deepcopy(self.child); candidate["resource_migration"][key] = value
            with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)
        candidate = copy.deepcopy(self.child)
        candidate["resource_migration"]["native_producer"]["notebook_ref"] = "alexqipku/old-private"
        with self.assertRaises(ValueError): guard.audit_diff(self.parent, candidate)

    def archive(self, member="evidence/fresh.json", data=b"FIXTURE_FRESH_BYTES"):
        path = self.path / "suite.zip"
        with zipfile.ZipFile(path, "x") as archive: archive.writestr(member, data)
        supplied = self.path / "fresh.json"; supplied.write_bytes(data)
        return path, supplied, dict(bytes=path.stat().st_size, sha256=guard.digest(path.read_bytes()))

    def test_fresh_supplied_receipt_must_be_exact_archive_bytes(self):
        archive, supplied, expected = self.archive()
        guard.verify_archive(archive, expected, dict(unit=supplied), self.parent)
        supplied.write_bytes(b"self-reported authenticated true")
        with self.assertRaisesRegex(ValueError, "not an actual fresh archive member"):
            guard.verify_archive(archive, expected, dict(unit=supplied), self.parent)

    def test_new_output_path_is_not_read_as_an_input_archive_member(self):
        paths = {name: self.path / (name+".json") for name in guard.SLOTS}
        paths.update(bundle=self.path/"operators.npz", output=self.path/"DOES_NOT_EXIST_PLAN.json")
        result = guard.archive_inputs(paths)
        self.assertFalse(paths["output"].exists())
        self.assertNotIn("output", result)
        self.assertEqual(set(result), set(guard.SLOTS) | {"bundle", "metadata"})
        self.assertEqual(result["metadata"], self.path/"operators.json")

    def test_old_receipt_cannot_be_repacked_as_fresh(self):
        archive, supplied, expected = self.archive(data=b"FIXTURE_OLD_QUALIFICATION_BYTES")
        parent = copy.deepcopy(self.parent)
        parent["qualification_receipts"]["unit"]["sha256"] = guard.digest(supplied.read_bytes())
        with self.assertRaisesRegex(ValueError, "Old receipt relabelled"):
            guard.verify_archive(archive, expected, dict(unit=supplied), parent)

    def test_archive_corruption_and_path_traversal_rejected(self):
        archive, supplied, expected = self.archive("../unsafe.json")
        with self.assertRaisesRegex(ValueError, "Unsafe qualification member"):
            guard.verify_archive(archive, expected, dict(unit=supplied), self.parent)

    def test_archive_replacement_after_hash_cannot_supply_different_receipt(self):
        archive, supplied, expected = self.archive(data=b"FIXTURE_ORIGINAL_ARCHIVE")
        replacement = self.path/"replacement.zip"
        with zipfile.ZipFile(replacement, "x") as z:
            z.writestr("evidence/fresh.json", b"FIXTURE_UNVERIFIED_REPLACEMENT")
        supplied.write_bytes(b"FIXTURE_UNVERIFIED_REPLACEMENT")
        original_raw = guard.raw
        replaced = []
        def changed_after_read(path, limit=268435456):
            data = original_raw(path, limit)
            if Path(path) == archive and not replaced:
                archive.write_bytes(replacement.read_bytes()); replaced.append(True)
            return data
        with patch.object(guard, "raw", side_effect=changed_after_read):
            with self.assertRaisesRegex(ValueError, "not an actual fresh archive member"):
                guard.verify_archive(archive, expected, dict(unit=supplied), self.parent)
        self.assertTrue(replaced)
        archive.write_bytes(archive.read_bytes()+b"corrupt")
        with self.assertRaisesRegex(ValueError, "archive differs"):
            guard.verify_archive(archive, expected, dict(unit=supplied), self.parent)

    def test_all_original42_actual_bytes_still_match_parent(self):
        for name, expected in self.parent["source_pins"].items():
            self.assertEqual(guard.digest(guard.raw(ROOT/name)), expected, name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
