import copy
import json
from pathlib import Path
import tempfile
import unittest

from cell_cost_ledger import canonical, sha_file, summarize


def timed(pointer):
    return {"pointer": pointer, "unit": "ns"}


class CellCostLedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.registry = {"schema": "hepta.cell-cost-registry.v1", "datasets": {}, "receipts": {},
                         "timing_context": "fixture shared CPU; not isolated latency", "owners": [], "features": []}
        self.data = self.write("dataset.json", {"rows": []})
        self.registry["datasets"]["data"] = self.data
        for name, calls, wall, cpu in (("image", 2, 100, 50), ("audio", 3, 200, 80)):
            self.receipt(name, {"dataset_sha256": self.data["sha256"], "feature_identity": "same-space",
                "encoding": {"calls": calls, "wall_ns": wall, "cpu_ns": cpu},
                "forwards": [{"forward_ms": .00001}] * calls}, bound=True)
        owner = {"instances": 1, "calls": 5, "load": {"wall_ns": 10, "cpu_ns": 5,
            "loaded_model": {"resident_tensor_storage_bytes": 1000}},
            "reports": {n: self.registry["receipts"][n]["sha256"] for n in ("image", "audio")}}
        self.receipt("owner", owner)
        self.registry["owners"] = [{"id": "one-process", "receipt": "owner", "instances_pointer": "/instances",
            "load_pointer": "/load", "forward_calls_pointer": "/calls",
            "members": {n: "/reports/" + n for n in ("image", "audio")}}]
        self.registry["features"] = [self.feature(n, "one-process") for n in ("image", "audio")]

    def write(self, name, value):
        path = self.root / name
        path.write_bytes(canonical(value))
        return {"path": name, "sha256": sha_file(path)}

    def receipt(self, name, value, *, bound=False):
        spec = self.write(name + ".json", value)
        if bound:
            spec["dataset_bindings"] = {"/dataset_sha256": "data"}
        self.registry["receipts"][name] = spec

    def feature(self, name, owner):
        return {"id": name, "receipt": name, "owner": owner, "forward_calls": "/encoding/calls",
            "stage_wall": timed("/encoding/wall_ns"), "stage_cpu": timed("/encoding/cpu_ns"),
            "forward_wall": {"pointer": "/forwards/*/forward_ms", "unit": "ms"}}

    def run_ledger(self):
        self.write("registry.json", self.registry)
        return summarize(self.root / "registry.json", self.root / "ledger.json")

    def test_image_audio_share_one_actual_load_and_controls_must_be_accounted(self):
        result = self.run_ledger()
        self.assertEqual(result["measured_work_totals"], {
            "wall_ns": {"sum_measured": 310, "unmeasured_components": []},
            "cpu_ns": {"sum_measured": 135, "unmeasured_components": []}})
        self.assertEqual(len(result["owners"]), 1)
        self.assertEqual(result["owners"]["one-process"]["accounted_physical_forward_calls"], 5)
        (self.root / "ledger.json").unlink()
        self.registry["features"].pop()
        with self.assertRaisesRegex(ValueError, "not fully accounted"):
            self.run_ledger()

    def test_different_processes_with_same_feature_identity_are_both_charged(self):
        other = json.loads((self.root / "image.json").read_bytes()) | {"physical_run": "different"}
        self.receipt("second-image", other, bound=True)
        self.receipt("second-owner", {"instances": 1, "calls": 2, "load": {"wall_ns": 20, "cpu_ns": 7},
            "reports": {"image": self.registry["receipts"]["second-image"]["sha256"]}})
        self.registry["owners"].append({"id": "different-process", "receipt": "second-owner",
            "instances_pointer": "/instances", "forward_calls_pointer": "/calls", "load_pointer": "/load",
            "members": {"second-image": "/reports/image"}})
        self.registry["features"].append(self.feature("second-image", "different-process"))
        result = self.run_ledger()
        self.assertEqual((len(result["owners"]), result["measured_work_totals"]["wall_ns"]["sum_measured"]), (2, 430))

    def test_duplicate_owner_or_changed_missing_receipt_is_rejected(self):
        base = copy.deepcopy(self.registry)
        duplicate = copy.deepcopy(base["owners"][0]) | {"id": "alias"}
        self.registry["owners"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "unique physical owner"):
            self.run_ledger()
        self.registry = base
        path = self.root / "audio.json"
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            self.run_ledger()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "missing or changed"):
            self.run_ledger()

    def test_inclusive_rollup_replaces_nested_costs_and_rss_observations_are_not_summed(self):
        self.receipt("inclusive", {"wall_ns": 400, "cpu_ns": 200, "rss": [900, 800]})
        self.registry["inclusive_rollups"] = [{"id": "all-cache-work", "receipt": "inclusive",
            "covers": ["owner:one-process", "feature:image", "feature:audio"],
            "wall": timed("/wall_ns"), "cpu": timed("/cpu_ns"), "scope": "inclusive reconstruction"}]
        self.registry["observations"] = [{"id": "peaks", "receipt": "inclusive", "pointer": "/rss",
                                          "scope": "distinct non-simultaneous process peaks"}]
        result = self.run_ledger()
        self.assertEqual(result["measured_work_totals"]["wall_ns"]["sum_measured"], 400)
        self.assertEqual(result["observations"][0]["value"], [900, 800])
        self.assertFalse(result["rss_peaks_summed"])

    def test_study_search_is_not_added_again_and_label_counts_stay_per_condition(self):
        h = {"full_preparation_wall_ns": 20, "full_preparation_cpu_ns": 10,
             "evaluation_wall_ns": 8, "evaluation_parent_cpu_ns": 3, "fresh_process_child_cpu_ns": 4,
             "all_path_training_wall_ns": 15, "calibration_wall_ns": 2}
        for i in (1, 2):
            self.receipt("study" + str(i), {"schema": "hepta.calibrated-label-resource-ledger.v1",
                "dataset_sha256": self.data["sha256"], "study_plan_sha256": str(i) * 64,
                "summary_sha256": str(i) * 64, "head_cost": h,
                "per_task_seed_budget": [{"task": "same-task", "family": "operational"}],
                "label_stages": {"selected_gradient_training": {"unique_source_groups": 8}},
                "gradient_source_selection_sha256": "f" * 64}, bound=True)
        self.registry["studies"] = [{"id": str(i), "receipt": "study" + str(i), "task_namespace": "same-data"} for i in (1, 2)]
        result = self.run_ledger()
        self.assertEqual(result["measured_work_totals"], {
            "wall_ns": {"sum_measured": 366, "unmeasured_components": []},
            "cpu_ns": {"sum_measured": 169, "unmeasured_components": []}})
        self.assertEqual(result["logical_task_count"], 1)
        self.assertFalse(result["label_stage_counts_are_summed_across_conditions"])

    def test_dataset_mismatch_boolean_counter_and_unmeasured_cpu_are_explicit(self):
        original = json.loads((self.root / "image.json").read_bytes())
        for changed in (original | {"dataset_sha256": "0" * 64},
                        original | {"encoding": original["encoding"] | {"calls": True}}):
            self.receipt("image", changed, bound=True)
            owner = json.loads((self.root / "owner.json").read_bytes())
            owner["reports"]["image"] = self.registry["receipts"]["image"]["sha256"]
            self.receipt("owner", owner)
            with self.assertRaises(ValueError):
                self.run_ledger()
        self.receipt("image", original, bound=True)
        owner["reports"]["image"] = self.registry["receipts"]["image"]["sha256"]
        self.receipt("owner", owner)
        del self.registry["features"][1]["stage_cpu"]
        result = self.run_ledger()
        self.assertEqual(result["measured_work_totals"]["cpu_ns"]["unmeasured_components"], ["feature:audio"])

    def test_cross_receipt_binding_and_overlapping_inclusive_costs_are_rejected(self):
        self.receipt("linked", {"parent": "0" * 64, "wall_ns": 300, "cpu_ns": 100})
        self.registry["receipts"]["linked"]["receipt_bindings"] = {"/parent": "owner"}
        with self.assertRaisesRegex(ValueError, "receipt-to-receipt"):
            self.run_ledger()
        self.receipt("linked", {"parent": self.registry["receipts"]["owner"]["sha256"],
                                "wall_ns": 300, "cpu_ns": 100})
        self.registry["receipts"]["linked"]["receipt_bindings"] = {"/parent": "owner"}
        self.registry["inclusive_rollups"] = [{"id": str(i), "receipt": "linked", "scope": "same-work",
            "covers": ["owner:one-process"], "wall": timed("/wall_ns"), "cpu": timed("/cpu_ns")} for i in (1, 2)]
        with self.assertRaisesRegex(ValueError, "already covered"):
            self.run_ledger()


if __name__ == "__main__":
    unittest.main()
