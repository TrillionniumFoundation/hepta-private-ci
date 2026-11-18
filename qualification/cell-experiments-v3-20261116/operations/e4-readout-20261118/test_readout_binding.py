"""Synthetic receipt consistency tests: no models, tools, or business verifiers."""

from contextlib import redirect_stdout
from copy import deepcopy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


TARGET = Path(
    os.environ.get(
        "HEPTA_E4_READER_TARGET",
        Path(__file__).with_name("readout_extended_circuit.py"),
    )
)
SPEC = importlib.util.spec_from_file_location("e4_readout_under_test", TARGET)
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)
D = READER.digest
SELECTION = "earliest_business_success_else_last_surviving"


class SyntheticRun:
    """Two synthetic two-step graphs, with opposite success transitions."""

    def __init__(self, root, pool_model=None, call_model=None):
        self.root = root
        self.protocol = {
            "output_root": str(root),
            "output_selection": SELECTION,
            "original_comparison_digest": "1" * 64,
            "original_B_source_inventory_sha256": "2" * 64,
            "models": {c: {"manifest_digest": D(c)} for c in "FTC"},
            "panels": {
                "old_A": [
                    {"record_digest": D(i), "task_id": f"synthetic-{i}"}
                    for i in range(2)
                ],
                "old_B": [],
            },
            "budget": {
                "max_input_tokens_per_call": 4096,
                "max_output_tokens_per_call": 384,
                "max_relay_bytes": 2048,
                "model_calls": 2,
            },
            "planned_counts_only": {"graph_results": 2, "total_model_calls": 4},
            "source_sha256": {"shared_pool_v4.py": "3" * 64},
            "adapter_precision_repair": {"expected_pool_class_module": "fixture.pool"},
            "prior_cost_history": {
                "old_owner_wall_seconds": 110.117,
                "diagnostic_wall_seconds": [24.5, 22.8],
            },
            "fixture_only": True,
        }
        self.write("PROTOCOL.json", self.protocol)
        self.protocol_sha = hashlib.sha256(
            (root / "PROTOCOL.json").read_bytes()
        ).hexdigest()
        inventory = {
            "source_sha256": "3" * 64,
            "cells": {c: {"model_digest": D(c)} for c in "FTC"},
        }
        if pool_model:
            inventory["cells"]["F"]["model_digest"] = pool_model
        self.pool_id = D(inventory)
        self.write(
            "circuit/POOL.json",
            {
                "inventory": inventory,
                "pool_identity": self.pool_id,
                "initialization_cost": {"wall_seconds": 1, "complete": False},
            },
        )
        self.write(
            "circuit/POOL_BINDING.json",
            {
                "class_module": "fixture.pool",
                "class_name": "SharedAdapterPool",
                "source_sha256": "3" * 64,
                "protocol_digest": self.protocol_sha,
            },
        )
        self.write(
            "WORKER_INTENT.json",
            {
                "protocol_sha256": self.protocol_sha,
                "comparison_digest": "1" * 64,
                "source_inventory_sha256": "2" * 64,
                "actual_pool_source_sha256": "3" * 64,
                "actual_pool_class_module": "fixture.pool",
            },
        )
        self.graphs = []
        for number, transitions in enumerate(((True, False), (False, True))):
            base = f"circuit/search/task-{number:04d}/ff_both"
            contract = {
                "output_selection": SELECTION,
                "graph": {"graph_id": "ff_both", "path": ["F", "F"]},
                "cells": {c: {"model_digest": D(c)} for c in "FTC"},
                "budget": self.protocol["budget"],
            }
            self.write(base + "/CONTRACT.json", contract)
            nodes = []
            for slot, success in enumerate(transitions):
                call = base + f"/node-{slot}"
                request = {
                    "messages": [
                        {"role": "user", "content": f"synthetic {number} {slot}"}
                    ]
                }
                output = {
                    "answer": f"synthetic answer {number} {slot}",
                    "input_tokens": 10 + slot,
                    "output_tokens": 2 + slot,
                    "loaded_model_digest": call_model or D("F"),
                    "pool_identity": self.pool_id,
                }
                verification = {"success": success, "synthetic": True}
                items = {
                    "request": request,
                    "output": output,
                    "verification": verification,
                }
                node = {
                    "slot": slot,
                    "cell_id": "F",
                    "status": "COMPLETE",
                    "output": output,
                    "verification": verification,
                    "business": {
                        "business_success": success,
                        "verifier_executed": True,
                        "format_admitted": True,
                    },
                }
                for key, value in items.items():
                    relative = call + "/" + key.upper() + ".json"
                    self.write(relative, value)
                    node[key + "_path"], node[key + "_digest"] = (
                        str(root / relative),
                        D(value),
                    )
                self.write(call + "/STEP.json", node)
                self.write(
                    call + "/POOL_INTENT.json",
                    {
                        "request_digest": D(request),
                        "pool_identity": self.pool_id,
                        "cell_id": "F",
                        "model_digest": output["loaded_model_digest"],
                        "started_at_ns": number * 2 + slot,
                    },
                )
                self.write(call + "/POOL_REQUEST.json", request)
                self.write(call + "/POOL_RAW_OUTPUT.json", output)
                self.write(call + "/POOL_RESULT.json", output)
                nodes.append(node)
            selected = nodes[transitions.index(True)]
            graph = {
                "schema": "hepta.online-message-circuit.result.v4",
                "status": "COMPLETE",
                "task_id": f"synthetic-{number}",
                "record_digest": D(number),
                "contract_digest": D(contract),
                "graph_id": "ff_both",
                "nodes": nodes,
                "output_selection": SELECTION,
                "success": True,
                "first_success": transitions[0],
                "final_slot": selected["slot"],
                "last_executed_slot": 1,
                "final_answer_sha256": hashlib.sha256(
                    selected["output"]["answer"].encode()
                ).hexdigest(),
                "intervention": {"effective_on_graph": False},
                "cost": {
                    "model_calls": 2,
                    "verifier_calls": 2,
                    "business_executions": 2,
                    "format_rejections": 0,
                    "input_tokens": 21,
                    "output_tokens": 5,
                    "wall_seconds": 2,
                    "provider_seconds_sum": 1,
                    "verifier_wall_seconds_sum": 0.1,
                },
            }
            self.graphs.append(base + "/RESULT.json")
            self.write(self.graphs[-1], graph)
        for kind in ("original", "additional"):
            for panel in ("old_A", "old_B"):
                name = f"circuit/{kind}/{panel}"
                plan = {"selections": []}
                self.write(name + "/PLAN.json", plan)
                self.write(
                    name + "/STUDY.json",
                    {"plan_digest": D(plan), "arms": {}, "interventions": {}},
                )
        self.write("circuit/STATIC_SELECTION.json", {"synthetic": True})
        self.refresh()

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True) + "\n")

    def read(self, name):
        return json.loads((self.root / name).read_text())

    def refresh(self):
        self.write(
            "circuit/search/SEARCH.json",
            {
                "observations": [
                    {
                        "result_path": str(self.root / name),
                        "result_digest": D(self.read(name)),
                    }
                    for name in self.graphs
                ]
            },
        )
        job = {
            "status": "COMPLETE",
            "protocol_digest": self.protocol_sha,
            "comparison_digest": "1" * 64,
            "pool_digest": D(self.read("circuit/POOL.json")),
            "search_digest": D(self.read("circuit/search/SEARCH.json")),
            "static_selection_digest": D(self.read("circuit/STATIC_SELECTION.json")),
            "panel_study_digests": {
                panel: {
                    kind: D(self.read(f"circuit/{kind}/{panel}/STUDY.json"))
                    for kind in ("original", "additional")
                }
                for panel in ("old_A", "old_B")
            },
        }
        self.write("circuit/RESULT.json", job)
        self.write(
            "COMPLETE.json",
            {
                "status": "COMPLETE",
                "protocol_sha256": self.protocol_sha,
                "result_digest": D(job),
                "worker_wall_seconds": 10,
            },
        )

    def run(self):
        output = self.root / "READOUT.json"
        with (
            patch.object(
                sys,
                "argv",
                [
                    str(TARGET),
                    "--run-root",
                    str(self.root),
                    "--protocol",
                    str(self.root / "PROTOCOL.json"),
                    "--protocol-sha",
                    self.protocol_sha,
                    "--output",
                    str(output),
                ],
            ),
            redirect_stdout(io.StringIO()),
        ):
            READER.main()
        return json.loads(output.read_text())


class ReadoutBindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="e4-synthetic-receipts-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def rejected(self, fixture, issue):
        result = fixture.run()
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertTrue(
            any(issue in item for item in result["issues"]), result["issues"]
        )
        self.assertTrue(
            all(
                value is None
                for value in result["complete_call_and_token_totals"].values()
            )
        )
        self.assertIsNone(result["energy_joules"])
        self.assertFalse(result["full_system_cost_known"])
        return result

    def test_complete_opposite_transitions_keep_earliest_success_and_separate_costs(
        self,
    ):
        result = SyntheticRun(self.root).run()
        self.assertEqual(result["status"], "COMPLETE", result["issues"])
        summary = result["summaries"]["search/ff_both"]
        self.assertEqual(
            [
                summary[key]
                for key in (
                    "selected_success",
                    "first_success",
                    "last_success",
                    "recovery_0_to_1",
                    "regression_1_to_0",
                )
            ],
            [2, 1, 1, 1, 1],
        )
        self.assertEqual(result["complete_call_and_token_totals"]["model_calls"], 4)
        self.assertEqual(
            result["nested_cost_scopes_do_not_add"]["observed_graph_wall_seconds_sum"],
            4,
        )
        self.assertEqual(
            result["pre_execution_cost_history"]["old_owner_wall_seconds"], 110.117
        )

    def test_worker_protocol_comparison_and_source_inventory_are_bound(self):
        for key in ("protocol_sha256", "comparison_digest", "source_inventory_sha256"):
            with self.subTest(key=key):
                fixture = SyntheticRun(self.root / key)
                value = fixture.read("WORKER_INTENT.json")
                value[key] = "a" * 64
                fixture.write("WORKER_INTENT.json", value)
                self.rejected(fixture, "worker " + key)

    def test_completion_status_and_protocol_are_bound(self):
        for key in ("status", "protocol_sha256"):
            with self.subTest(key=key):
                fixture = SyntheticRun(self.root / key)
                value = fixture.read("COMPLETE.json")
                value[key] = "wrong"
                fixture.write("COMPLETE.json", value)
                self.rejected(fixture, "worker completion")

    def test_equal_counts_do_not_hide_duplicate_and_unreferenced_call(self):
        fixture = SyntheticRun(self.root)
        graph = fixture.read(fixture.graphs[0])
        graph["nodes"][1] = deepcopy(graph["nodes"][0])
        graph["nodes"][1]["slot"] = 1
        graph["cost"]["input_tokens"], graph["cost"]["output_tokens"] = 20, 4
        fixture.write(fixture.graphs[0], graph)
        fixture.refresh()
        result = self.rejected(fixture, "duplicate or misplaced call")
        self.assertEqual(result["pool_call_receipt_coverage"]["POOL_RESULT.json"], 4)
        self.assertFalse(result["observed_completed_graph_cost_integrity"])
        self.assertTrue(
            all(
                value is None
                for value in result[
                    "observed_completed_graph_cost_lower_bound"
                ].values()
            )
        )

    def test_summary_selection_and_answer_are_derived_from_nodes(self):
        for key, value in {
            "success": False,
            "first_success": False,
            "final_slot": 1,
            "last_executed_slot": 0,
            "final_answer_sha256": "a" * 64,
            "output_selection": "last_only",
        }.items():
            with self.subTest(key=key):
                fixture = SyntheticRun(self.root / key)
                graph = fixture.read(fixture.graphs[0])
                graph[key] = value
                fixture.write(fixture.graphs[0], graph)
                fixture.refresh()
                self.rejected(fixture, "graph " + key + " differs")

    def test_frozen_model_identity_is_not_only_self_consistent(self):
        for source in ("pool", "call"):
            with self.subTest(source=source):
                fixture = SyntheticRun(
                    self.root / source, **{source + "_model": "a" * 64}
                )
                self.rejected(fixture, source + " frozen model differs")

    def test_node_order_and_unique_slots_follow_contract(self):
        for change in ("reorder", "duplicate_slot"):
            with self.subTest(change=change):
                fixture = SyntheticRun(self.root / change)
                graph = fixture.read(fixture.graphs[0])
                if change == "reorder":
                    graph["nodes"].reverse()
                else:
                    graph["nodes"][1]["slot"] = 0
                fixture.write(fixture.graphs[0], graph)
                fixture.refresh()
                self.rejected(fixture, "graph slots differ")

    def test_original_pool_source_and_module_gates_remain(self):
        for key in ("class_module", "source_sha256", "protocol_digest"):
            with self.subTest(key=key):
                fixture = SyntheticRun(self.root / key)
                value = fixture.read("circuit/POOL_BINDING.json")
                value[key] = "wrong"
                fixture.write("circuit/POOL_BINDING.json", value)
                self.rejected(fixture, "pool binding " + key)

    def test_contract_and_output_counts_obey_frozen_budget(self):
        for key in ("contract", "input_tokens", "output_tokens"):
            with self.subTest(key=key):
                fixture = SyntheticRun(self.root / key)
                graph = fixture.read(fixture.graphs[0])
                if key == "contract":
                    name = str(Path(fixture.graphs[0]).with_name("CONTRACT.json"))
                    contract = fixture.read(name)
                    contract["budget"]["model_calls"] = 3
                    fixture.write(name, contract)
                    graph["contract_digest"] = D(contract)
                else:
                    node = graph["nodes"][0]
                    graph["cost"][key] += 10000 - node["output"][key]
                    node["output"][key] = 10000
                    node["output_digest"] = D(node["output"])
                    call = Path(node["output_path"]).parent.relative_to(fixture.root)
                    for name in (
                        "OUTPUT.json",
                        "POOL_RESULT.json",
                        "POOL_RAW_OUTPUT.json",
                    ):
                        fixture.write(call / name, node["output"])
                    fixture.write(call / "STEP.json", node)
                fixture.write(fixture.graphs[0], graph)
                fixture.refresh()
                self.rejected(fixture, "budget differs")

    def test_task_identity_and_group_coverage_are_bound(self):
        for change in ("rename", "duplicate"):
            with self.subTest(change=change):
                fixture = SyntheticRun(self.root / change)
                graph = fixture.read(fixture.graphs[1])
                graph["task_id"] = "synthetic-0"
                if change == "duplicate":
                    graph["record_digest"] = D(0)
                fixture.write(fixture.graphs[1], graph)
                fixture.refresh()
                self.rejected(
                    fixture,
                    "task identity differs"
                    if change == "rename"
                    else "duplicate group task",
                )

    def test_duplicate_graph_summary_reference_is_rejected(self):
        fixture = SyntheticRun(self.root)
        fixture.graphs.append(fixture.graphs[0])
        fixture.refresh()
        self.rejected(fixture, "duplicate result reference")

    def test_missing_completion_never_reports_complete_zero_cost(self):
        fixture = SyntheticRun(self.root)
        (fixture.root / "COMPLETE.json").unlink()
        result = self.rejected(fixture, "missing:")
        self.assertEqual(
            result["observed_completed_graph_cost_lower_bound"]["model_calls"], 4
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
