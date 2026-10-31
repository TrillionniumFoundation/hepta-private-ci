"""Synthetic inventory, duplicate-cost, authority and missing-cost contracts."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from .execution_ledger import aggregate, jobs, sha, template


class ExecutionLedgerContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hepta-v3-ledger-contract-")
        self.base = Path(self.temp.name)
        self.run, self.source = self.base / "run", self.base / "sources"
        self.run.mkdir(); self.source.mkdir()
        self.protocol = {"seeds": [17], "runtime": {"profiles": ["frozen"],
            "authority": "DENY_ALL", "native_owner_integration": False}}
        self.protocol_path = self.write(self.source / "PROTOCOL.json", self.protocol)
        (self.source / "registered.py").write_text("# Synthetic registered producer\n")
        self.native = self.base / "synthetic-native.so"; self.native.write_bytes(b"synthetic native identity")
        self.sources = {name: sha(self.source / name) for name in ("PROTOCOL.json", "registered.py")}
        self.index = template(self.run, self.source, self.protocol_path)

    def tearDown(self):
        self.temp.cleanup()

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True))
        return path

    def binding(self, path):
        return {"path": str(path), "sha256": sha(path)}

    def item(self, identifier):
        return next(item for item in self.index["stages"] if item["id"] == identifier)

    def begin(self, identifier):
        spec = jobs(self.protocol)[identifier]
        directory = self.run / spec["directory"]
        phase = spec["phase"] if spec["kind"] == "training" else "runtime-" + spec["phase"]
        freeze = {"registered_commit": "a" * 40, "protocol_sha256": sha(self.protocol_path),
            "source_files": self.sources, "allowed_phases": [phase], "artifacts": {},
            "native_library_sha256": sha(self.native)}
        frozen = self.write(self.base / (identifier.replace(":", "-") + "-freeze.json"), freeze)
        start = {"phase": phase, "seed": 17, "registered_commit": freeze["registered_commit"],
            "source_files": self.sources, "freeze_sha256": sha(frozen), "protocol_sha256": sha(self.protocol_path),
            "started_monotonic_ns": 100, "profile": spec.get("profile"), "role": spec.get("role"),
            "native_library_sha256": sha(self.native)}
        start_path = self.write(directory / "START.json", start)
        item = self.item(identifier)
        item.update(status="in_progress", start=self.binding(start_path), freeze=self.binding(frozen), native=self.binding(self.native))
        return directory, item

    def finish(self, directory, item, record, children=None):
        for name, child in (children or {}).items():
            self.write(directory / name, child)
        record = {**record, "files": {str(p.relative_to(directory)): sha(p) for p in directory.rglob("*") if p.is_file()}}
        path = self.write(directory / "COMPLETE.json", record)
        item.update(status="complete", complete=self.binding(path))
        return path

    def test_training_parent_resources_are_not_added_to_child_path_receipts(self):
        directory, item = self.begin("training:development:17")
        self.finish(directory, item, {"resources": {"scheduled_gradient_microsteps": 96}, "wall_ns": 1000},
                    {"field/6000/COMPLETE.json": {"resources": {"scheduled_gradient_microsteps": 48}, "wall_ns": 900}})
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["training"]["counters"]["scheduled_gradient_microsteps"], 96)
        self.assertEqual(result["scientific_costs"]["training"]["recorded_component_wall_sum_ns"], 1000)
        self.assertFalse(result["all_stage_dispositions_terminal"])
        self.assertFalse(result["scientific_outcome_claims"])

    def test_runtime_bank_sums_only_two_named_children(self):
        directory, item = self.begin("runtime:bank:17:frozen")
        children = {f"{role}/COMPLETE.json": {"resources": {"transition_examples": count}, "wall_ns": count}
                    for role, count in (("runtime_fit", 100), ("runtime_select", 50))}
        self.finish(directory, item, {"source_roles": ["runtime_fit", "runtime_select"]}, children)
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["runtime"]["counters"]["transition_examples"], 150)
        self.assertEqual(result["scientific_costs"]["runtime"]["recorded_component_wall_sum_ns"], 150)

    def test_runtime_selected_parent_and_child_charge_once_and_must_agree(self):
        directory, item = self.begin("runtime:audit:17:frozen")
        inner = {"resources": {"native_tick_calls": 12, "native_ns": 10}, "wall_ns": 100,
                 "authority": "DENY_ALL", "native_owner_integration": False, "files": {}}
        self.finish(directory, item, inner, {"selected/COMPLETE.json": inner})
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["runtime"]["counters"]["native_tick_calls"], 12)
        outer = json.loads((directory / "COMPLETE.json").read_text())
        outer["resources"]["native_tick_calls"] = 24
        self.write(directory / "COMPLETE.json", outer)
        item["complete"] = self.binding(directory / "COMPLETE.json")
        with self.assertRaisesRegex(ValueError, "Parent and selected runtime"):
            aggregate(self.index, self.base)

    def test_runtime_fit_counts_actual_heads_ticks_and_requires_deny_all(self):
        directory, item = self.begin("runtime:fit:17:frozen")
        fitted = {"candidate_policies": 48, "stage_head_fits": 144, "native_tick_calls": 42,
            "native_ns": 7, "fit_wall_ns": 120, "fit_python_cpu_ns": 90,
            "models": {"native": {"authority": "DENY_ALL", "native_owner_integration": False}}}
        outer = {key: fitted[key] for key in ("candidate_policies", "stage_head_fits", "native_tick_calls", "fit_wall_ns")}
        self.finish(directory, item, outer, {"READOUTS.json": fitted})
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["runtime"]["counters"]["stage_head_fits"], 144)
        fitted["models"]["native"]["authority"] = "ALLOW_ALL"
        self.write(directory / "READOUTS.json", fitted)
        outer = json.loads((directory / "COMPLETE.json").read_text())
        outer["files"]["READOUTS.json"] = sha(directory / "READOUTS.json")
        self.write(directory / "COMPLETE.json", outer); item["complete"] = self.binding(directory / "COMPLETE.json")
        with self.assertRaisesRegex(ValueError, "excess authority"):
            aggregate(self.index, self.base)

    def test_failure_unknown_cost_and_observed_lower_bound_are_distinct(self):
        directory, item = self.begin("training:bank:17")
        failure = self.write(directory / "FAILED.json", {"error": "synthetic interrupted work"})
        item.update(status="failed", failure=self.binding(failure))
        result = aggregate(self.index, self.base)
        row = next(row for row in result["stages"] if row["id"] == item["id"])
        self.assertEqual(row["cost_completeness"], "unknown_failed_work")
        self.assertEqual(row["components"], [])
        self.assertIn(item["id"], result["unknown_or_lower_bound_cost_attempts"])
        lower = self.write(self.base / "observed-failure-cost.json", {"failure_sha256": sha(failure),
            "accounting_scope": "observed_lower_bound", "resources": {"scheduled_gradient_microsteps": 48}})
        item["failure_cost"] = self.binding(lower)
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["training"]["counters"]["scheduled_gradient_microsteps"], 48)
        self.assertIn(item["id"], result["unknown_or_lower_bound_cost_attempts"])

    def test_omission_requires_bound_negative_decision(self):
        item = self.item("training:audit:17")
        decision = self.write(self.base / "qualification.json", {"passed": False})
        item.update(status="skipped_unqualified", reason="Registered development gate failed", decision=self.binding(decision),
                    decision_field=["passed"], decision_value=False)
        result = aggregate(self.index, self.base)
        self.assertEqual(result["stage_status_counts"]["skipped_unqualified"], 1)
        self.write(decision, {"passed": True}); item["decision"] = self.binding(decision)
        with self.assertRaisesRegex(ValueError, "unsupported by its qualification"):
            aggregate(self.index, self.base)

    def test_duplicate_jobs_or_unregistered_attempts_are_rejected(self):
        self.index["stages"].append(deepcopy(self.index["stages"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one disposition"):
            aggregate(self.index, self.base)
        self.index["stages"].pop()
        self.write(self.run / "unregistered-retry/START.json", {"attempt": 2})
        with self.assertRaisesRegex(ValueError, "Unaccounted execution attempt"):
            aggregate(self.index, self.base)

    def test_verification_actual_observer_cost_is_separate_from_logical_work(self):
        artifact = self.write(self.base / "verified-input.json", {"synthetic": True})
        producer = self.source / "registered.py"
        receipt = self.write(self.base / "score-audit.json", {"passed": True, "script_sha256": sha(producer),
            "input_sha256": sha(artifact), "actual_observer_batch_calls": {"reward": 2, "audit": 2},
            "actual_observer_digit_examples": {"reward": 256, "audit": 256},
            "logical_observer_batch_calls": {"reward": 20, "audit": 20},
            "observer_batch_cache_hits": {"reward": 18, "audit": 18},
            "generator_forward_calls": 0, "verification_wall_ns": 90, "verification_cpu_ns": 70})
        item = {"id": "hard-score-audit", "kind": "training_hard_scores", "status": "complete",
            "receipt": self.binding(receipt), "sources": [self.binding(producer)], "artifacts": [self.binding(artifact)]}
        self.index["verification"] = [item]
        result = aggregate(self.index, self.base)
        actual = result["verification_costs"]["training_hard_scores"]["counters"]
        self.assertEqual(actual["actual_observer_batch_calls.reward"], 2)
        self.assertNotIn("logical_observer_batch_calls.reward", actual)
        self.assertEqual(result["verification"][0]["logical_work_and_cache"]["logical_observer_batch_calls.reward"], 20)
        self.index["verification"].append(deepcopy(item))
        with self.assertRaisesRegex(ValueError, "charged twice"):
            aggregate(self.index, self.base)

    def test_recorded_wall_sums_are_not_elapsed_and_bindings_reject_changes(self):
        for phase in ("reference", "bank"):
            directory, item = self.begin("training:" + phase + ":17")
            self.finish(directory, item, {"resources": {"scheduled_gradient_microsteps": 48}, "wall_ns": 80})
        span = self.write(self.base / "operational-span.json", {"schema": "hepta.field-bridge.v3.operational-span.1",
            "run_root": str(self.run), "clock_domain": "synthetic-common-host-boot", "scope": "Two concurrent synthetic jobs",
            "started_monotonic_ns": 100, "finished_monotonic_ns": 200})
        self.index["operational_timing"] = self.binding(span)
        result = aggregate(self.index, self.base)
        self.assertEqual(result["scientific_costs"]["training"]["recorded_component_wall_sum_ns"], 160)
        self.assertEqual(result["operational_elapsed"]["elapsed_ns"], 100)
        (self.source / "registered.py").write_text("# Mutated producer\n")
        with self.assertRaisesRegex(ValueError, "Bound artifact changed"):
            aggregate(self.index, self.base)

    def test_replay_fit_and_native_verification_are_separately_charged(self):
        artifact = self.write(self.base / "verified-bank.json", {"synthetic": True})
        producer = self.source / "registered.py"
        declarations = {
            "bank_replay": {"verification_resources": {"scheduled_gradient_microsteps": 1200,
                "gradient_backward_examples": 115200, "directional_gradient_measurements": 1},
                "verification_gradient_microsteps": 1200},
            "training_fit": {"verification_least_squares_solves": 60, "verification_gradient_microsteps": 0},
            "native_session": {"verification_native_ticks": 42, "generator_forward_calls": 0,
                               "authority": "DENY_ALL", "native_owner_integration": False},
        }
        for name, cost in declarations.items():
            receipt = self.write(self.base / (name + ".json"), {"passed": True, "input_sha256": sha(artifact),
                "script_sha256": sha(producer), **cost})
            self.index["verification"].append({"id": name, "kind": name, "status": "complete",
                "receipt": self.binding(receipt), "sources": [self.binding(producer)], "artifacts": [self.binding(artifact)]})
        result = aggregate(self.index, self.base)
        costs = result["verification_costs"]
        self.assertEqual(costs["bank_replay"]["counters"]["scheduled_gradient_microsteps"], 1200)
        self.assertEqual(costs["training_fit"]["counters"]["least_squares_solves"], 60)
        self.assertEqual(costs["native_session"]["counters"]["native_tick_calls"], 42)
        path = self.base / "bank_replay.json"
        receipt = json.loads(path.read_text()); receipt["verification_gradient_microsteps"] = 1199
        self.write(path, receipt); self.index["verification"][0]["receipt"] = self.binding(path)
        with self.assertRaisesRegex(ValueError, "Duplicated verification counters conflict"):
            aggregate(self.index, self.base)

    def test_compatible_zero_aliases_per_seed_timers_and_unmeasured_join(self):
        artifact = self.write(self.base / "verified-input.json", {"synthetic": True})
        producer = self.source / "registered.py"
        shared = {"passed": True, "input_sha256": sha(artifact), "script_sha256": sha(producer)}
        records = {
            "metadata": {"generator_forwards": 0, "observer_forwards": 0},
            "selected_media": {"native_tick_calls": 0, "generator_forward_calls": 0},
            "join": {"additional_generator_or_observer_calls": 0},
            "native_session": {"verification_native_ticks": 12, "seeds": {
                "17": {"verification_native_ns": 3, "verification_bridge_roundtrip_ns": 5},
                "29": {"verification_native_ns": 7, "verification_bridge_roundtrip_ns": 11}}},
        }
        for name, fields in records.items():
            receipt = self.write(self.base / (name + ".json"), {**shared, **fields})
            self.index["verification"].append({"id": name, "kind": name, "status": "complete",
                "receipt": self.binding(receipt), "sources": [self.binding(producer)], "artifacts": [self.binding(artifact)]})
        result = aggregate(self.index, self.base)
        costs = result["verification_costs"]
        self.assertEqual(costs["metadata"]["counters"]["generator_forward_calls"], 0)
        self.assertEqual(costs["metadata"]["counters"]["observer_forward_calls"], 0)
        self.assertEqual(costs["selected_media"]["counters"]["native_tick_calls"], 0)
        self.assertEqual(costs["join"]["counters"]["metadata_join_generator_or_observer_calls"], 0)
        join = next(row for row in result["verification"] if row["id"] == "join")
        self.assertIsNone(join["components"][0]["recorded_component_wall_ns"])
        self.assertEqual(costs["native_session"]["nested_timers_ns"], {"native_ns": 10, "bridge_roundtrip_ns": 16})


if __name__ == "__main__":
    unittest.main()
