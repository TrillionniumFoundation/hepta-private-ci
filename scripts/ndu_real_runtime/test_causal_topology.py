"""Adversarial D evidence checks; fixture consistency is not scientific evidence."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from .causal_protocol import COMMON_MATCHES, COST_STAGES, COST_UNITS
from .causal_topology import (
    ARMS,
    COUNTERS,
    validate_topology_pair,
    validate_topology_receipt,
)
from .metering import atomic_json, canonical_sha, file_sha


class TopologyEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fixture(self, kind="split", prefix="dynamic", *, state_value=1.0):
        def graph(names, edges, generation):
            return {
                "generation": generation,
                "nodes": [
                    {"id": n, "state_owner": "owner-" + n, "bundle_sha256": "b" * 64}
                    for n in sorted(names)
                ],
                "edges": sorted(edges),
            }

        before = graph(["a", "b"], [["a", "b"]], 1)
        if kind == "split":
            after = graph(["a0", "a1", "b"], [["a0", "b"], ["a1", "b"]], 2)
        elif kind == "merge":
            before = graph(["a0", "a1", "b"], [["a0", "b"], ["a1", "b"]], 1)
            after = graph(["a", "b"], [["a", "b"]], 2)
        elif kind == "rewire":
            after = graph(["a", "b"], [["b", "a"]], 2)
        else:
            after = copy.deepcopy(before)
        old, new = {n["id"] for n in before["nodes"]}, {n["id"] for n in after["nodes"]}
        removed, added = old - new, new - old
        transition = {
            "kind": kind,
            "consumed": sorted(removed),
            "produced": sorted(added),
        }
        state_before = {
            "generation": before["generation"],
            "states": {n: [state_value] for n in sorted(old)},
        }
        state_after = {
            "generation": after["generation"],
            "states": {n: [state_value] for n in sorted(new)},
        }
        receipt = {
            "schema": "hepta.cell-causal.topology.v1",
            "arm_id": ARMS[kind != "no_change"],
            "run_id": prefix,
            "paired_fit_id": "fit-1",
            "adaptation_task_id": "task-1",
            "next_task_id": "task-2",
            "adaptive_scheduler_sha256": "a" * 64,
            "max_nodes": 8,
            "transition": transition,
            "matches": {key: "c" * 64 for key in COMMON_MATCHES},
            "artifacts": {},
        }
        evidence = {
            "before_graph": before,
            "after_graph": after,
            "before_state": state_before,
            "after_state": state_after,
        }
        for key, value in evidence.items():
            self.write(receipt, key, value)
        sources, targets = (removed, added) if removed or added else (old, new)
        migration = {
            "mode": "migrate" if removed else "preserve",
            "policy_sha256": "d" * 64,
            "before_state_sha256": receipt["artifacts"]["before_state"]["sha256"],
            "after_state_sha256": receipt["artifacts"]["after_state"]["sha256"],
            "source_values": {
                n: canonical_sha(state_before["states"][n]) for n in sources
            },
            "target_values": {
                n: canonical_sha(state_after["states"][n]) for n in targets
            },
        }
        self.write(receipt, "migration", migration)
        trace = []
        for node in after["nodes"]:
            trace.append(
                {
                    "type": "dispatch",
                    "node_id": node["id"],
                    "state_owner": node["state_owner"],
                }
            )
        for source, target in after["edges"]:
            trace.append(
                {
                    "type": "message",
                    "from": source,
                    "to": target,
                    "bytes": 4,
                    "cost_event_id": "messages",
                }
            )
        trace.append(
            {"type": "encode", "input_sha256": "e" * 64, "cost_event_id": "reencoding"}
        )
        for sequence, event in enumerate(trace):
            event.update(
                sequence=sequence,
                run_id=prefix,
                task_id="task-2",
                generation=after["generation"],
                graph_sha256=canonical_sha(after),
            )
        self.write(receipt, "trace", trace)
        costs = [
            {
                "event_id": stage,
                "stage": stage,
                "methods": [receipt["arm_id"]],
                "parent_event_id": None,
                "measurements": {unit: 0.0 for unit in COST_UNITS},
                "provider_charges_unit": "USD",
                "counters": {key: 100 for key in COUNTERS.get(stage, ())},
            }
            for stage in COST_STAGES
        ]
        self.write(receipt, "costs", costs)
        self.write(
            receipt,
            "recovery",
            {
                "original_job_id": "fixture-recovery-job",
                "injected_failure": "migration",
                "restored_graph": before,
                "restored_state": state_before,
                "events": [
                    "failure_observed",
                    "rollback_completed",
                    "restored_state_readback",
                ],
            },
        )
        return self.seal(receipt)

    def write(self, receipt, key, value):
        path = self.root / (
            receipt["run_id"]
            + "-"
            + key
            + "-"
            + canonical_sha(value)[:16]
            + (".jsonl" if key == "trace" else ".json")
        )
        if not path.exists():
            if key == "trace":
                path.write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in value)
                )
            else:
                atomic_json(path, value)
        receipt["artifacts"][key] = {
            "path": path.name,
            "bytes": path.stat().st_size,
            "sha256": file_sha(path),
        }

    def read(self, receipt, key):
        path = self.root / receipt["artifacts"][key]["path"]
        return (
            [json.loads(line) for line in path.read_text().splitlines()]
            if key == "trace"
            else json.loads(path.read_text())
        )

    def seal(self, receipt):
        comparison = {
            key: receipt[key]
            for key in (
                "matches",
                "adaptive_scheduler_sha256",
                "max_nodes",
                "paired_fit_id",
            )
        }
        owner = {
            "schema": "hepta.cell-causal.topology-owner.v1",
            "host": "fixture-only",
            "original_job_id": "fixture-job",
            "terminal": "completed",
            "run_id": receipt["run_id"],
            "arm_id": receipt["arm_id"],
            "comparison_sha256": canonical_sha(comparison),
            "transition_sha256": canonical_sha(receipt["transition"]),
            "installed_graph_sha256": canonical_sha(self.read(receipt, "after_graph")),
            "artifact_sha256s": {
                k: v["sha256"] for k, v in receipt["artifacts"].items() if k != "owner"
            },
        }
        self.write(receipt, "owner", owner)
        return receipt

    def validate(self, receipt):
        return validate_topology_receipt(
            receipt,
            self.root,
            trusted_observer_sha256=[receipt["artifacts"]["owner"]["sha256"]],
        )

    def test_concrete_split_merge_rewire_and_fixed_fixtures_are_only_evidence_checks(
        self,
    ):
        for kind in ("split", "merge", "rewire", "no_change"):
            with self.subTest(kind=kind):
                result = self.validate(self.fixture(kind, prefix=kind))
                self.assertEqual(
                    (
                        result["status"],
                        result["scientific_acceptance"],
                        result["benefit_proven"],
                    ),
                    ("EVIDENCE_CONSISTENT", "HOLD", False),
                )

    def test_manifest_and_untrusted_observer_cannot_claim_execution(self):
        result = validate_topology_receipt({"artifacts": {}}, self.root)
        self.assertEqual((result["status"], len(result["blockers"])), ("BLOCKED", 9))
        result = validate_topology_receipt(self.fixture(), self.root)
        self.assertIn("independently pinned", result["blockers"][0])

    def test_old_generation_trace_and_unconsumed_rewire_are_blocked(self):
        receipt = self.fixture("rewire")
        trace = self.read(receipt, "trace")
        trace[0]["generation"] = 1
        self.write(receipt, "trace", trace)
        self.assertIn("next task", self.validate(self.seal(receipt))["blockers"][0])
        trace[0]["generation"] = 2
        trace = [e for e in trace if e["type"] != "message"]
        for i, row in enumerate(trace):
            row["sequence"] = i
        self.write(receipt, "trace", trace)
        self.assertIn("new edge", self.validate(self.seal(receipt))["blockers"][0])

    def test_state_mapping_and_real_rollback_readback_are_required(self):
        receipt = self.fixture()
        migration = self.read(receipt, "migration")
        migration["target_values"]["a0"] = "0" * 64
        self.write(receipt, "migration", migration)
        self.assertIn(
            "actual state bytes", self.validate(self.seal(receipt))["blockers"][0]
        )
        receipt = self.fixture(prefix="other")
        recovery = self.read(receipt, "recovery")
        recovery["restored_state"]["states"]["a"] = [99.0]
        self.write(receipt, "recovery", recovery)
        self.assertIn("recovery", self.validate(self.seal(receipt))["blockers"][0])

    def test_unknown_cost_and_undercharged_messages_block_completeness(self):
        receipt = self.fixture()
        costs = self.read(receipt, "costs")
        costs[0]["measurements"]["provider_charges"] = None
        self.write(receipt, "costs", costs)
        self.assertIn("unknown", self.validate(self.seal(receipt))["blockers"][0])
        costs[0]["measurements"]["provider_charges"] = 0
        next(c for c in costs if c["stage"] == "messages")["counters"]["messages"] = 0
        self.write(receipt, "costs", costs)
        self.assertIn(
            "exceeds charged", self.validate(self.seal(receipt))["blockers"][0]
        )

    def test_pair_rejects_different_actual_starting_state(self):
        for kind in ("split", "rewire"):
            with self.subTest(kind=kind):
                fixed = self.fixture("no_change", "fixed-" + kind)
                dynamic = self.fixture(kind, "dynamic-" + kind, state_value=7.0)
                for receipt in (fixed, dynamic):
                    self.assertEqual(
                        self.validate(receipt)["status"], "EVIDENCE_CONSISTENT"
                    )
                self.assertEqual(
                    self.read(fixed, "before_graph"), self.read(dynamic, "before_graph")
                )
                pins = [r["artifacts"]["owner"]["sha256"] for r in (fixed, dynamic)]
                result = validate_topology_pair(
                    fixed, dynamic, self.root, trusted_observer_sha256=pins
                )
                self.assertEqual(result["status"], "BLOCKED")
                self.assertIn(
                    "paired arms did not start with the same actual state",
                    result["blockers"],
                )
                self.assertEqual(
                    (result["scientific_acceptance"], result["benefit_proven"]),
                    ("HOLD", False),
                )

    def test_pair_rejects_scheduler_and_recovery_contract_asymmetry(self):
        fixed, dynamic = self.fixture("no_change", "fixed"), self.fixture()
        pins = [r["artifacts"]["owner"]["sha256"] for r in (fixed, dynamic)]
        self.assertEqual(
            validate_topology_pair(
                fixed, dynamic, self.root, trusted_observer_sha256=pins
            )["status"],
            "EVIDENCE_CONSISTENT",
        )
        dynamic["matches"]["recovery_mechanism"] = "f" * 64
        dynamic["adaptive_scheduler_sha256"] = "1" * 64
        self.seal(dynamic)
        pins[1] = dynamic["artifacts"]["owner"]["sha256"]
        result = validate_topology_pair(
            fixed, dynamic, self.root, trusted_observer_sha256=pins
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("scheduler" in b for b in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
