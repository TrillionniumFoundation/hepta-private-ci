"""Seven-lineage integration through real producers and the retained SQLite owner.

The numerical LEARN component is an evaluation-summary fixture, not a trainer.
"""

from dataclasses import asdict, replace
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from hepta_cells.bundle import Bundle, OPTIONAL, REQUIRED
from hepta_cells.deterministic import NumericAlgorithm, RuleVerifier, ToolCell, ToolReply
from hepta_cells.lifecycle import Budget, CellError, CellOwner, OwnerLimits, Partition, Qualification
from hepta_cells.population import CellSpec, PopulationPlan
from hepta_cells.semantic import (
    CallableFeatureBackend, LocalHead, LocalObjective, SemanticBinding, SemanticCell,
    SharedSemanticPool, _digest,
)
from hepta_cells.semantic_component import SemanticComponent, semantic_bundle
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


class RecordingPort:
    def __init__(self):
        self.invocations = []

    def invoke(self, invocation):
        self.invocations.append(invocation)
        return ToolReply({"recorded": invocation.arguments}, 1)


class PopulationOwnerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "owner.sqlite"
        weights = np.eye(2)
        self.binding = SemanticBinding(
            hashlib.sha256(weights.tobytes()).hexdigest(),
            *(fingerprint(name) for name in ("model", "encoder", "tokenizer", "numeric")),
        )
        pool = SharedSemanticPool()
        pool.register_backend(CallableFeatureBackend(
            self.binding, 2, lambda inputs: np.stack(inputs) @ weights,
            lambda: hashlib.sha256(weights.tobytes()).hexdigest(), resident_arrays=(weights,),
        ))
        self.components = {}
        for name in ("perc", "mem"):
            cell = SemanticCell(name, self.binding, LocalHead.initialize(2, 1, seed=7),
                                LocalObjective("mse", 1, "next-feature"))
            self.components[name] = SemanticComponent(pool, cell, semantic_bundle(cell, name + "-initial"))
        for name in ("pred", "ctrl"):
            kernel = TemporalKernel(name, TemporalConfig(3, 2, 2, hidden_dim=3, seed=5))
            parts = {field: fingerprint(name + field) for field in REQUIRED}
            parts.update({field: None for field in OPTIONAL})
            parts.update(base=kernel.kernel_sha256, heads=kernel.heads_sha256,
                         composition=kernel.config.sha256)
            self.components[name] = TemporalComponent(kernel, Bundle(name + "-initial", 1, parts), "run-1")
        self.port = RecordingPort()
        self.components.update(
            verify=RuleVerifier([{"field": "allowed", "op": "equal", "value": True}], fingerprint("rules")),
            act=ToolCell("record", fingerprint("test-port"), self.port, fingerprint("tool-bundle")),
            learn=NumericAlgorithm("mean_variance", fingerprint("evaluation-summary-fixture")),
        )
        self.evaluation = fingerprint("frozen-independent-evaluation-profile")
        self.temporal_rule = fingerprint("adam-lr0.003-clip5-updates3")
        self.semantic_rule = _digest("local-head-sgd-v1", 3, 0.01, "mse")
        routes = {
            "perc": ("shared_semantic", "shared_head", "frozen"),
            "mem": ("shared_semantic", "shared_head", "heads"),
            "pred": ("stateful_temporal", "gru", "kernel_and_heads"),
            "ctrl": ("stateful_temporal", "gru", "frozen"),
            "verify": ("deterministic", "rule_verifier", "frozen"),
            "act": ("deterministic", "tool_wrapper", "frozen"),
            "learn": ("deterministic", "numerical", "frozen"),
        }
        self.plan = PopulationPlan("principal", "agent", tuple(
            CellSpec(name, name.upper(), family, kernel, self.components[name].identity.digest,
                     "objective:" + name, trainable,
                     (self.semantic_rule if name == "mem" else self.temporal_rule) if trainable != "frozen" else None,
                     self.evaluation if trainable != "frozen" else None,
                     min_observations=2, budget=Budget(max_work_units=1000))
            for name, (family, kernel, trainable) in routes.items()
        ))
        self.owner = self.new_owner(self.database)

    def tearDown(self):
        self.owner.close()
        self.temporary.cleanup()

    def partition(self, name="pred", run="run-1"):
        return Partition("principal", "agent", name, run)

    def new_owner(self, database, limits=None):
        owner = CellOwner(database, qualify=lambda qualification: True, population=self.plan, limits=limits)
        for spec in self.plan.cells:
            owner.create(self.partition(spec.cell_id), self.components[spec.cell_id],
                         budget=spec.budget, total_work_units=spec.total_work_units)
        return owner

    def population_snapshot(self, owner=None):
        owner = owner or self.owner
        return {table: [tuple(row) for row in owner.db.execute(f"SELECT * FROM {table} ORDER BY 1,2")]
                for table in ("population_current", "population_partitions", "population_consumed")}

    def observe(self, request, cursor, owner=None, partition=None):
        return (owner or self.owner).step(
            partition or self.partition(), self.components["pred"], request,
            {"operation": "observe", "observation": [1.0, 0.2, -0.1], "cursor": cursor},
        )

    def temporal_candidate(self, name="pred"):
        source = self.components[name]
        x = np.zeros((4, 3, 3))
        x[:, 0, 0] = [-1, -1, 1, 1]
        kernel, receipt = source.kernel.train_candidate(x, np.zeros((4, 2)),
                                                      np.eye(2, dtype=bool)[[0, 0, 1, 1]], updates=3)
        parts = {**source.bundle.components, "base": kernel.kernel_sha256, "heads": kernel.heads_sha256}
        bundle = source.bundle.successor(name + "-trained", parts, receipt["data_sha256"],
                                         self.temporal_rule, self.evaluation)
        return TemporalComponent(kernel, bundle, "run-1")

    def qualification(self, source, candidate):
        return Qualification(source.identity.digest, candidate.identity.digest, fingerprint("host-evaluation-result"))

    def adopt_prediction(self, candidate, owner=None, partition=None):
        return (owner or self.owner).adopt(partition or self.partition(), candidate,
                                         self.qualification(self.components["pred"], candidate))

    def test_all_seven_lineages_execute_and_semantic_successor_keeps_shared_base(self):
        payloads = {"perc": {"inputs": [[1.0, 0.0]]}, "mem": {"inputs": [[0.0, 1.0]]},
                    "pred": {"operation": "observe", "observation": [1, 0, 0], "cursor": 0},
                    "ctrl": {"operation": "predict", "action": [0, 1]},
                    "verify": {"allowed": True}, "act": {"message": "fixture"},
                    "learn": {"values": [1, 2, 3]}}
        for name, payload in payloads.items():
            receipt = self.owner.step(self.partition(name), self.components[name], "first", payload)
            self.assertEqual(receipt["population"]["lineage"], name.upper())
            self.assertEqual(receipt["status"], "committed")
        self.assertEqual(len(self.port.invocations), 1)
        source = self.components["mem"]
        candidate, training = source.propose([np.array([1.0, 0.0]), np.array([0.0, 1.0])],
                                            np.array([[1.0], [-1.0]]), artifact_id="mem-trained",
                                            evaluation_profile=self.evaluation, steps=3)
        self.assertNotEqual(candidate.bundle.components["heads"], source.bundle.components["heads"])
        self.assertEqual(candidate.bundle.components["base"], source.bundle.components["base"])
        self.owner.step(self.partition("mem"), source, "second", {"inputs": [[1.0, 0.0]]})
        adopted = self.owner.adopt(self.partition("mem"), candidate, self.qualification(source, candidate))
        self.assertEqual(adopted["state"], candidate.initial_state())
        self.assertEqual(candidate.bundle.training_lineage["dataset"], training.dataset_digest)

    def test_reopen_without_plan_cannot_bypass_frozen_cadence_or_family(self):
        self.owner.close()
        self.owner = CellOwner(self.database, qualify=lambda qualification: True)
        self.assertEqual(self.owner.population_plan, self.plan)
        before = self.population_snapshot()
        frozen = self.temporal_candidate("ctrl")
        with self.assertRaisesRegex(CellError, "frozen"):
            self.owner.adopt(self.partition("ctrl"), frozen, self.qualification(self.components["ctrl"], frozen))
        with self.assertRaisesRegex(CellError, "not enough"):
            self.adopt_prediction(self.temporal_candidate())
        wrong = NumericAlgorithm("dot", fingerprint("wrong-family"))
        with self.assertRaisesRegex(CellError, "family or kernel"):
            self.owner.adopt(self.partition(), wrong, self.qualification(self.components["pred"], wrong))
        self.assertEqual(self.population_snapshot(), before)

    def test_only_fresh_committed_observations_enable_reset_adoption_and_new_run(self):
        candidate, partition, source = self.temporal_candidate(), self.partition(), self.components["pred"]
        first = self.observe("observe-0", 0)
        self.assertEqual(self.observe("observe-0", 0), first)
        self.owner.step(partition, source, "prediction", {"operation": "predict", "action": [0, 1]})
        self.owner.reset(partition, source, source.identity.digest)
        original_step = source.step

        def overrun(payload, state, context):
            return replace(original_step(payload, state, context), work_units=context.budget.max_work_units + 1)

        with patch.object(source, "step", overrun):
            rejected = self.observe("overrun", 0)
        self.assertEqual((rejected["status"], rejected["state_applied"]), ("budget_exceeded", False))
        with self.assertRaisesRegex(CellError, "not enough"):
            self.adopt_prediction(candidate)
        self.observe("observe-1", 0)
        remaining = self.owner.status(partition)["remaining_work_units"]
        adopted = self.adopt_prediction(candidate)
        self.assertEqual(adopted["state"], candidate.initial_state())
        self.assertEqual(adopted["remaining_work_units"], remaining)
        new_run = self.partition(run="run-2")
        current = TemporalComponent(candidate.kernel, candidate.bundle, new_run.run_id)
        spec = self.plan.spec(new_run)
        self.owner.create(new_run, current, budget=spec.budget, total_work_units=spec.total_work_units)
        before = self.population_snapshot()
        obsolete = TemporalComponent(source.kernel, source.bundle, "run-old")
        with self.assertRaisesRegex(CellError, "currently admitted"):
            self.owner.create(self.partition(run="run-old"), obsolete, budget=spec.budget,
                              total_work_units=spec.total_work_units)
        self.assertEqual(self.population_snapshot(), before)

    def test_rollback_does_not_refund_consumed_observations_or_work(self):
        candidate, source, partition = self.temporal_candidate(), self.components["pred"], self.partition()
        first = self.observe("one", 0)
        self.observe("two", 1)
        self.adopt_prediction(candidate)
        consumed = self.population_snapshot()["population_consumed"]
        before = self.owner.status(partition)["remaining_work_units"]
        self.owner.rollback(partition, source, candidate.identity.digest)
        self.assertEqual(self.owner.status(partition)["remaining_work_units"], before)
        self.assertEqual(self.observe("one", 0), first)
        self.owner.reset(partition, source, source.identity.digest)
        with self.assertRaisesRegex(CellError, "not enough"):
            self.adopt_prediction(candidate)
        self.assertEqual(self.population_snapshot()["population_consumed"], consumed)
        self.observe("fresh-one", 0)
        self.observe("fresh-two", 1)
        self.adopt_prediction(candidate)
        self.assertEqual(len(self.population_snapshot()["population_consumed"]), 4)
        self.assertLess(self.owner.status(partition)["remaining_work_units"], before)

    def test_real_candidate_cannot_change_frozen_training_or_evaluation_rule(self):
        candidate = self.temporal_candidate()
        self.observe("one", 0)
        self.observe("two", 1)
        before = self.population_snapshot()
        for field in ("update_rule", "evaluation_profile"):
            bundle = replace(candidate.bundle, training_lineage={**candidate.bundle.training_lineage,
                                                                  field: fingerprint("changed-profile")})
            altered = TemporalComponent(candidate.kernel, bundle, "run-1")
            with self.subTest(field=field), self.assertRaisesRegex(CellError, "frozen update or evaluation"):
                self.adopt_prediction(altered)
            self.assertEqual(self.population_snapshot(), before)
        self.adopt_prediction(candidate)

    def test_failed_cutover_rolls_back_current_version_and_consumption(self):
        candidate = self.temporal_candidate()
        self.observe("one", 0)
        self.observe("two", 1)
        before = self.population_snapshot()
        status = self.owner.status(self.partition())
        self.owner.db.execute("CREATE TRIGGER fail_history BEFORE INSERT ON history WHEN NEW.generation > 0 BEGIN SELECT RAISE(ABORT,'injected history failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "history failure"):
            self.adopt_prediction(candidate)
        self.assertEqual(self.population_snapshot(), before)
        self.assertEqual(self.owner.status(self.partition()), status)
        self.owner.db.execute("DROP TRIGGER fail_history")
        self.adopt_prediction(candidate)

    def test_capacity_and_stale_run_cannot_change_current_version(self):
        candidate = self.temporal_candidate()
        for field in ("max_epochs", "max_checkpoints"):
            with self.subTest(capacity=field):
                owner = self.new_owner(Path(self.temporary.name) / (field + ".sqlite"), OwnerLimits(**{field: 7}))
                try:
                    self.observe("one", 0, owner)
                    self.observe("two", 1, owner)
                    before = self.population_snapshot(owner)
                    with self.assertRaisesRegex(CellError, "capacity"):
                        self.adopt_prediction(candidate, owner)
                    self.assertEqual(self.population_snapshot(owner), before)
                finally:
                    owner.close()
        stale = self.partition(run="stale-run")
        source = self.components["pred"]
        stale_component = TemporalComponent(source.kernel, source.bundle, stale.run_id)
        spec = self.plan.spec(stale)
        self.owner.create(stale, stale_component, budget=spec.budget, total_work_units=spec.total_work_units)
        self.observe("one", 0)
        self.observe("two", 1)
        self.adopt_prediction(candidate)
        before = self.population_snapshot()
        stale_candidate = TemporalComponent(candidate.kernel, candidate.bundle, stale.run_id)
        with self.assertRaisesRegex(CellError, "another run"):
            self.owner.adopt(stale, stale_candidate, self.qualification(stale_component, stale_candidate))
        self.assertEqual(self.population_snapshot(), before)

    def test_aba_fences_stale_run_and_excludes_its_observations_from_new_epoch(self):
        source, successor = self.components["pred"], self.temporal_candidate()
        stale = self.partition(run="stale-a")
        stale_component = TemporalComponent(source.kernel, source.bundle, stale.run_id)
        spec = self.plan.spec(stale)
        self.owner.create(stale, stale_component, budget=spec.budget, total_work_units=spec.total_work_units)
        self.observe("first-a", 0)
        self.observe("second-a", 1)
        self.adopt_prediction(successor)
        # A second run retains A while the logical cell has already adopted B.
        for cursor in range(2):
            receipt = self.owner.step(stale, stale_component, f"stale-{cursor}",
                                      {"operation": "observe", "observation": [1, 0, 0], "cursor": cursor})
            self.assertEqual(receipt["population"]["logical_epoch"], 0)
        self.owner.rollback(self.partition(), source, successor.identity.digest)
        current = self.owner.db.execute("SELECT epoch FROM population_current WHERE cell_id='pred'").fetchone()
        self.assertEqual(current["epoch"], 2)
        # C is another explicitly identified A successor; matching A's weights
        # after rollback cannot revive a run admitted under the earlier epoch.
        next_bundle = replace(successor.bundle, artifact_id="pred-successor-c")
        stale_candidate = TemporalComponent(successor.kernel, next_bundle, stale.run_id)
        before = self.population_snapshot()
        with self.assertRaisesRegex(CellError, "another run"):
            self.owner.adopt(stale, stale_candidate, self.qualification(stale_component, stale_candidate))
        self.assertEqual(self.population_snapshot(), before)
        fresh = self.partition(run="fresh-a")
        fresh_source = TemporalComponent(source.kernel, source.bundle, fresh.run_id)
        fresh_candidate = TemporalComponent(successor.kernel, next_bundle, fresh.run_id)
        self.owner.create(fresh, fresh_source, budget=spec.budget, total_work_units=spec.total_work_units)
        qualification = self.qualification(fresh_source, fresh_candidate)
        for cursor in range(2):
            with self.assertRaisesRegex(CellError, "not enough"):
                self.owner.adopt(fresh, fresh_candidate, qualification)
            receipt = self.owner.step(fresh, fresh_source, f"fresh-{cursor}",
                                      {"operation": "observe", "observation": [1, 0, 0], "cursor": cursor})
            self.assertEqual(receipt["population"]["logical_epoch"], 2)
        adopted = self.owner.adopt(fresh, fresh_candidate, qualification)
        self.assertEqual(adopted["state"], fresh_candidate.initial_state())
        self.assertEqual(adopted["population"]["logical_epoch"], 3)
        consumed = self.population_snapshot()["population_consumed"]
        self.assertFalse(any(row[0] == stale.digest for row in consumed))

    def test_reopen_refuses_missing_policy_or_corrupt_population_admission(self):
        corruptions = (
            ("policy", "DELETE FROM population_plan", (), "lost their original policy"),
            ("current", "DELETE FROM population_current WHERE cell_id=?", ("pred",), "incomplete"),
            ("partition", "DELETE FROM population_partitions WHERE partition=?", (self.partition().digest,), "incomplete"),
            ("epoch", "UPDATE population_partitions SET epoch=1 WHERE partition=?", (self.partition().digest,), "incomplete"),
        )
        for name, command, arguments, message in corruptions:
            with self.subTest(corruption=name):
                database = Path(self.temporary.name) / ("corrupt-" + name + ".sqlite")
                with sqlite3.connect(database) as corrupted:
                    self.owner.db.backup(corrupted)
                    corrupted.execute(command, arguments)
                with self.assertRaisesRegex(CellError, message):
                    CellOwner(database, qualify=lambda qualification: True)
                with sqlite3.connect(database) as retained:
                    self.assertEqual(retained.execute("SELECT count(*) FROM cells").fetchone()[0], 7)
                    if name == "policy":
                        self.assertEqual(retained.execute("SELECT count(*) FROM population_plan").fetchone()[0], 0)

    def test_fresh_process_loads_adopted_parameters_but_resets_new_run_hidden_state(self):
        candidate = self.temporal_candidate()
        self.observe("one", 0)
        self.observe("two", 1)
        self.adopt_prediction(candidate)
        self.owner.step(self.partition(), candidate, "adopted-observation",
                        {"operation": "observe", "observation": [1.0, 0.2, -0.1], "cursor": 0})
        previous_state = self.owner.checkpoint(self.partition())["state"]
        checkpoint = Path(self.temporary.name) / "adopted-kernel.npz"
        checkpoint_sha = candidate.kernel.checkpoint(checkpoint, previous_state)
        metadata = Path(self.temporary.name) / "adopted-candidate.json"
        metadata.write_text(json.dumps({"config": asdict(candidate.kernel.config),
                                        "bundle": candidate.bundle.record(),
                                        "checkpoint": str(checkpoint),
                                        "checkpoint_sha256": checkpoint_sha}), encoding="utf-8")
        program = """
import json
import os
from pathlib import Path
import sys
from hepta_cells.bundle import Bundle
from hepta_cells.lifecycle import CellOwner, Partition
from hepta_cells.temporal import TemporalConfig, TemporalKernel
from hepta_cells.temporal_component import TemporalComponent

saved = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
kernel, previous = TemporalKernel.restore_checkpoint(
    saved["checkpoint"], expected_sha256=saved["checkpoint_sha256"],
    cell_id="pred", config=TemporalConfig(**saved["config"]))
component = TemporalComponent(kernel, Bundle(**saved["bundle"]), "cold-run")
partition = Partition("principal", "agent", "pred", "cold-run")
owner = CellOwner(sys.argv[2])
try:
    spec = owner.population_plan.spec(partition)
    created = owner.create(partition, component, budget=spec.budget,
                           total_work_units=spec.total_work_units)
    receipt = owner.step(partition, component, "cold-observation",
                         {"operation": "observe", "observation": [0.0, 0.5, -0.25], "cursor": 0})
    final = owner.checkpoint(partition)
    print(json.dumps({"pid": os.getpid(), "identity": component.identity.digest,
                      "plan_digest": owner.population_plan.digest,
                      "logical_epoch": receipt["population"]["logical_epoch"],
                      "cursor": receipt["output"]["cursor"],
                      "loaded_previous_state": previous,
                      "created_state": created["state"], "final_state": final["state"]}))
finally:
    owner.close()
"""
        self.owner.close()
        try:
            process = subprocess.run([sys.executable, "-c", program, str(metadata), str(self.database)],
                                     env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parent)},
                                     capture_output=True, text=True, timeout=30, check=False)
        finally:
            self.owner = CellOwner(self.database)
        self.assertEqual(process.returncode, 0, process.stderr)
        observed = json.loads(process.stdout)
        self.assertNotEqual(observed["pid"], os.getpid())
        self.assertEqual((observed["identity"], observed["plan_digest"], observed["logical_epoch"], observed["cursor"]),
                         (candidate.identity.digest, self.plan.digest, 1, 1))
        self.assertEqual(observed["loaded_previous_state"], previous_state)
        self.assertEqual(previous_state["cursor"], 1)
        fresh = candidate.kernel.initial_state("cold-run")
        self.assertEqual(observed["created_state"], fresh)
        self.assertNotEqual(observed["created_state"]["hidden"], previous_state["hidden"])
        expected = candidate.kernel.observe(fresh, [0.0, 0.5, -0.25], episode_id="cold-run", cursor=0)
        self.assertEqual(observed["final_state"], expected)
        self.assertEqual(self.owner.checkpoint(self.partition(run="cold-run"))["state"], expected)


if __name__ == "__main__":
    unittest.main()
