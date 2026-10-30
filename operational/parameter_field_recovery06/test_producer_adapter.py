"""Context-reconstructed producer tests; synthetic metadata, no science work."""

import copy
import importlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from operational.parameter_field_recovery06 import ancestry, producer_adapter as adapter
from operational.parameter_field_recovery06 import controller
from operational.parameter_field_recovery06.test_ancestry import Fixture, tagged, write


def original(name):
    package = "supplements.parameter_field_fullstudy_20261030." if name == "postseal_supplement" else "experiments.parameter_field_fullstudy_20261029."
    return importlib.import_module(package + name)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="producer-metadata-")
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(temporary.name)
        fixture = self.fixture
        for key, value in (("FIXED_ANCHORS", {name: fixture.a[name]["sha256"] for name in ancestry.FIXED_ANCHORS}),
                           ("PROTOCOL_SHA", fixture.protocol_sha), ("PARENT_SHA", fixture.parent_sha)):
            change = patch.object(ancestry, key, value)
            change.start()
            self.addCleanup(change.stop)
        receipt = ancestry.materialize_import(fixture.validate(), fixture.fresh)
        fresh = fixture.fresh_registration()
        self.mapping = ancestry.producer_map(receipt, fresh)
        self.map_descriptor = write(fixture.base / "PRODUCERS.json", self.mapping)
        old_job = {"id": "A-17", "phase": "A", "seed": 17, "completion": "operations/A-seed-17.COMPLETE.json",
            "freeze_sha256": fixture.a["source_freeze"]["sha256"],
            "argv": ["--root", str(fixture.fresh), "--freeze", fixture.a["source_freeze"]["path"]]}
        imported = {"schema": "synthetic.controller.import", "imported": True, "executed_here": False,
                    "import_receipt": receipt, "job": old_job, "new_scheduled_gradient_microsteps": 0}
        result = {"complete": True, "exit_code": 0, "imported": True, "executed_here": False,
                  "origin": imported, "completion": {**fixture.a["operation_complete"], "path": old_job["completion"]}}
        self.core = types.SimpleNamespace(imported_job=old_job, import_record=imported, imported_result=result)
        with patch.object(controller, "ControllerCore", return_value=self.core):
            self.adapter = adapter.ProducerAdapter(self.map_descriptor, receipt, fresh)
        self.fresh_registration = fresh
        for seed in (29, 43):
            row = self.mapping[str(seed)]
            science = write(fixture.fresh / f"stage_A/seed-{seed}/COMPLETE.json", {
                "complete": True, "phase": "A", "seed": seed, "registered_commit": row["registered_commit"],
                "source_freeze_sha256": row["source_freeze"]["sha256"]})
            operation = ancestry.archive.read(fixture.a["operation_complete"]["path"])
            operation.update({"seed": seed, "registered_commit": row["registered_commit"],
                "source_freeze_sha256": row["source_freeze"]["sha256"], "operational_amendment_sha256": row["profile"]["sha256"],
                "scientific_parent": row["scientific_parent"], "scientific_complete": {**science, "path": f"stage_A/seed-{seed}/COMPLETE.json"}})
            write(fixture.fresh / f"operations/A-seed-{seed}.COMPLETE.json", operation)
        self.registration = self.adapter.profiles[29]

    def test_external_map_must_equal_the_independently_validated_ancestry(self):
        wrong = copy.deepcopy(self.mapping)
        wrong["29"]["profile"] = wrong["17"]["profile"]
        changed = write(self.fixture.base / "WRONG_PRODUCERS.json", wrong)
        with self.assertRaises(ValueError):
            adapter.ProducerAdapter(changed, self.adapter.import_receipt, self.fresh_registration)

    def test_all_exact_adaptations_compile_without_touching_original_globals(self):
        before_modules, changed = set(sys.modules), {}
        for name in adapter.MODULE_SHA:
            module = original(name)
            before = dict(module.__dict__)
            clone = adapter.isolated_module(module, self.adapter)
            self.assertIsNot(clone.__dict__, module.__dict__)
            self.assertEqual(before, module.__dict__)
            changed[name] = clone.producer_adapter_audit
            for key, value in before.items():
                if isinstance(value, types.FunctionType) and value.__globals__ is module.__dict__ and key not in adapter.REWRITES.get(name, {}):
                    self.assertIs(clone.__dict__[key].__code__, value.__code__)
                    self.assertIs(clone.__dict__[key].__globals__, clone.__dict__)
        self.assertEqual(sum(row["metadata_expressions_replaced"] for rows in changed.values() for row in rows.values()), 10)
        self.assertFalse({"torch", "numpy"} & (set(sys.modules) - before_modules))

    def test_modified_source_is_rejected_before_expression_specialization(self):
        path = self.fixture.base / "report_results.py"
        path.write_bytes(Path(original("report_results").__file__).read_bytes() + b"\n# unexpected change\n")
        with self.assertRaises(ValueError):
            adapter.isolated_module(types.SimpleNamespace(__file__=str(path)), self.adapter)

    def test_a_jobs_use_own_seed_sources_and_other_phases_keep_single_source(self):
        jobs = [self.core.imported_job]
        for seed in (29, 43):
            source = self.adapter.source(seed)
            jobs.append({"id": f"A-{seed}", "phase": "A", "seed": seed, "freeze_sha256": source["sha256"], "argv": ["--freeze", source["path"]]})
        self.assertTrue(self.adapter.training_jobs_match(jobs, self.adapter.source(29), "A"))
        wrong = copy.deepcopy(jobs)
        wrong[0]["freeze_sha256"] = wrong[1]["freeze_sha256"]
        with self.assertRaises(ValueError):
            self.adapter.training_jobs_match(wrong, self.adapter.source(29), "A")
        source = {"path": str(self.fixture.base / "B.json"), "sha256": "b" * 64}
        self.assertTrue(self.adapter.training_jobs_match([{"freeze_sha256": "b" * 64, "argv": ["--freeze", source["path"]]}], source, "B"))
        self.assertFalse(self.adapter.training_jobs_match([{"freeze_sha256": "c" * 64, "argv": ["--freeze", source["path"]]}], source, "B"))

    def test_only_canonical_a17_job_uses_old_profile(self):
        calls = []
        gate = self.adapter.verify_job(lambda job, registration: calls.append((job, registration["_sha256"])))
        gate(self.core.imported_job, self.registration)
        gate({"id": "A-29"}, self.registration)
        self.assertEqual([row[1] for row in calls], [self.mapping["17"]["profile"]["sha256"], self.mapping["29"]["profile"]["sha256"]])
        with self.assertRaises(ValueError):
            gate({**self.core.imported_job, "completion": "operations/A-seed-29.COMPLETE.json"}, self.registration)

    def test_controller_gate_requires_import_record_and_forbids_fabricated_start(self):
        root = self.fixture.fresh
        write(root / "controller/A-17.IMPORT.json", self.core.import_record)
        self.assertTrue(self.adapter.controller_start_matches(root, self.core.imported_job, self.core.imported_result, ancestry.archive.read))
        write(root / "controller/A-17.START.json", {"job": self.core.imported_job})
        with self.assertRaises(ValueError):
            self.adapter.controller_start_matches(root, self.core.imported_job, self.core.imported_result, ancestry.archive.read)
        ordinary = {"id": "A-29"}
        write(root / "controller/A-29.START.json", {"job": ordinary})
        self.assertTrue(self.adapter.controller_start_matches(root, ordinary, {}, ancestry.archive.read))
        self.assertFalse(self.adapter.controller_start_matches(root, {"id": "A-29", "tampered": True}, {}, ancestry.archive.read))

    def test_report_rejects_old_profile_on_every_non_a17_operation(self):
        operations = {("A", seed): ancestry.archive.read(self.fixture.fresh / f"operations/A-seed-{seed}.COMPLETE.json") for seed in (17, 29, 43)}
        spec = {"producer_map": self.map_descriptor, "import_receipt": self.adapter.import_receipt,
                "raw_root": str(self.fixture.fresh), "amendment": self.adapter.current_profile}
        operations[("W", None)] = {"operational_amendment_sha256": self.adapter.current_profile["sha256"]}
        self.assertTrue(self.adapter.report_profiles(operations, spec))
        operations[("W", None)]["operational_amendment_sha256"] = self.adapter.old_profile["sha256"]
        with self.assertRaises(ValueError):
            self.adapter.report_profiles(operations, spec)
        operations.pop(("W", None))
        operations[("A", 17)]["source_freeze_sha256"] = self.mapping["29"]["source_freeze"]["sha256"]
        with self.assertRaises(ValueError):
            self.adapter.report_profiles(operations, spec)

    def test_freeze_map_must_be_pinned_and_legacy_single_parent_is_scoped(self):
        freeze = self.adapter.bind_freeze({"schema": "hepta.fullstudy.source-freeze.1", "artifacts": {}, "actual_source_A": self.adapter.source(29)})
        self.assertTrue(self.adapter.followup_parent_matches(freeze, self.adapter.source(29)))
        self.assertEqual(self.adapter.additional_parents(freeze), [self.adapter.source(17), self.adapter.source(29)])
        freeze["actual_sources_A_by_seed"]["17"] = self.adapter.source(29)
        with self.assertRaises(ValueError):
            self.adapter.require_bound(freeze)

    def test_independent_namespaces_preserve_unmodified_report_pending_behavior(self):
        module = original("report_results")
        left, right = self.adapter.for_report(module), self.adapter.for_report(module)
        left.prior_costs, right.prior_costs = lambda spec: {"synthetic": "left"}, lambda spec: {"synthetic": "right"}
        spec = {"schema": module.SCHEMA, "attempt_id": "attempt02", "stages": {phase: {"status": "PENDING"} for phase in module.PHASES}}
        self.assertEqual(left.assemble(spec)["prior_attempt_costs"], {"synthetic": "left"})
        self.assertEqual(right.assemble(spec)["prior_attempt_costs"], {"synthetic": "right"})
        self.assertFalse(left.assemble(spec)["efficacy_artifacts_opened"])
        self.assertIsNot(left.prior_costs, module.prior_costs)

    def test_b_and_r_input_gates_preserve_a17_old_state_binding(self):
        freeze = self.adapter.bind_freeze({"artifacts": {}})
        bank = self.fixture.fresh / "stage_A/seed-17/bank"
        for path in bank.iterdir():
            freeze["artifacts"][str(path)] = ancestry.archive.descriptor(path)["sha256"]
        for phase in ("B", "R"):
            self.adapter.verify_training_inputs(types.SimpleNamespace(phase=phase, seed=17, root=self.fixture.fresh), freeze, self.registration)
        state = bank / "schedule-6000-baseline-step-48.state"
        before = ancestry.archive.descriptor(state)
        binding = ancestry.state_metadata(state)["binding"]
        self.assertEqual(binding["source_freeze_sha256"], self.mapping["17"]["source_freeze"]["sha256"])
        self.assertNotEqual(binding["source_freeze_sha256"], self.mapping["29"]["source_freeze"]["sha256"])
        self.assertEqual(ancestry.archive.descriptor(state), before)
        freeze["artifacts"][str(state)] = "0" * 64
        with self.assertRaises(ValueError):
            self.adapter.verify_training_inputs(types.SimpleNamespace(phase="R", seed=17, root=self.fixture.fresh), freeze, self.registration)

    def test_w_input_gate_accepts_three_literal_seed_bindings_without_unifying_them(self):
        freeze = self.adapter.bind_freeze({"artifacts": {}})
        for seed in (17, 29, 43):
            bank = self.fixture.fresh / f"stage_A/seed-{seed}/bank"
            if seed != 17:
                row = self.mapping[str(seed)]
                header = ancestry.canonical({"arrays": [], "tree": tagged({"binding": {
                    "source_freeze_sha256": row["source_freeze"]["sha256"], "protocol_sha256": row["protocol_sha256"],
                    "runtime_sha256": row["runtime_sha256"], "study_id": ancestry.STUDY}, "cursor": {
                    "seed": seed, "schedule_id": 6000, "path_kind": "baseline", "clock": 48, "remaining_steps": 240,
                    "total_steps": 288, "guard_grain": 48, "baseline_action": 3}})})
                write(bank / "schedule-6000-baseline-step-48.state", ancestry.MAGIC + struct.pack(">Q", len(header)) + header)
                for name in ("BANK.json", "trace.jsonl.gz", "field12-head.npz"):
                    write(bank / name, b"synthetic frozen input")
            for path in bank.iterdir():
                freeze["artifacts"][str(path)] = ancestry.archive.descriptor(path)["sha256"]
        args = types.SimpleNamespace(phase="W", seed=None, root=self.fixture.fresh)
        self.adapter.verify_training_inputs(args, freeze, self.registration)
        source = self.fixture.fresh / "stage_A/seed-17/bank/schedule-6000-baseline-step-48.state"
        target = self.fixture.fresh / "stage_A/seed-29/bank/schedule-6000-baseline-step-48.state"
        write(target, source.read_bytes())
        freeze["artifacts"][str(target)] = ancestry.archive.descriptor(target)["sha256"]
        with self.assertRaises(ValueError):
            self.adapter.verify_training_inputs(args, freeze, self.registration)

    def test_endpoint_b_keeps_original_collector_and_a_requires_old_runtime(self):
        module = original("endpoint_v2")
        factory = self.adapter.for_endpoint(module)
        with self.assertRaises(ValueError):
            factory.collect_ab(self.fixture.fresh, "A", "0" * 64, self.adapter.source(29), {})
        factory.ab = types.SimpleNamespace(SEEDS=(), collect_checkpoints=lambda *args: {"completions": {}, "entries": []})
        self.assertEqual(factory.collect_ab(self.fixture.fresh, "B", "synthetic-runtime", {}, {}), {"completions": {}, "entries": []})
        self.assertIs(module.ab, None)


    def test_finalizer_destination_is_bound_before_serialization_and_checked_before_io(self):
        value = {"schema": "hepta.fullstudy.source-freeze.1", "execution_kind": "evidence_finalization", "artifacts": {}}
        encoded = self.adapter.encoding(ancestry.canonical)
        freeze = json.loads(encoded(value))
        self.assertEqual((freeze["evidence_id"], freeze["evidence_relative"]), ("verification06", "evidence_v2/verification06"))
        self.assertNotIn("evidence_id", value)
        with self.assertRaises(ValueError):
            encoded({**value, "evidence_id": "verification02"})
        item = write(self.fixture.base / "FINALIZER_FREEZE.json", freeze)
        module = original("finalize_v2")
        with patch.object(module, "verify_source_freeze", return_value=freeze):
            with patch.object(module, "finalize", return_value={"synthetic_literal_result": True}) as literal:
                factory = self.adapter.for_finalizer(module)
                storage = types.SimpleNamespace(root=self.fixture.fresh)
                binding = {"source_freeze_sha256": item["sha256"]}
                with self.assertRaises(ValueError):
                    factory.finalize(storage, binding, "verification06")
                factory.verify_source_freeze(item["path"], self.registration)
                with self.assertRaises(ValueError):
                    factory.finalize(storage, binding, "verification02")
                self.assertEqual(factory.finalize(storage, binding, "verification06"), {"synthetic_literal_result": True})
                literal.assert_called_once_with(storage, binding, "verification06")



if __name__ == "__main__":
    unittest.main()
