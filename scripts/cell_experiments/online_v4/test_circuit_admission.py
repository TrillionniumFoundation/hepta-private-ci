"""Admission controls on synthetic groups and actual bounded fixture execution."""

import copy
from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest

from .. import data
from .circuit_admission import GROUPS, evaluation_admission
from .circuit_contract import Budget, Graph, digest
from .circuit_router import FrozenRouter, RouterPlan, fit_router
from .circuit_study import evaluate_suite
from .circuit_runtime import run_graph
from .test_circuit_runtime import ScriptedCells, cells, task


class CircuitAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.cells, cls.budget = cells(), Budget(max_output_tokens_per_call=1024)
        cls.records = [task(1, "blue calibration"), task(2, "red calibration")]
        cls.router, _ = fit_router(
            cls.records,
            [Graph("first", ("first", "first")), Graph("second", ("second", "second"))],
            cls.cells,
            cls.budget,
            ScriptedCells(cls.cells, mode="context"),
            data.verify_answer,
            cls.root / "fit",
            plan=RouterPlan(
                execution_binding_digest="e" * 64, message_style="native_turn_v1"
            ),
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def panel(self):
        # These distinct declarations test the admission algorithm, not new data.
        rows = copy.deepcopy(self.records)
        for i, row in enumerate(rows):
            row["split"] = "selection"
            row["authorization"]["training_allowed"] = False
            for key in GROUPS:
                row[key] = f"synthetic-heldout-{key}-{i}"
            row["source"]["sha256"] = digest(["synthetic-heldout", i])
            row["task"]["input"] += " synthetic heldout"
        return rows

    def evaluate(self, rows, **kwargs):
        calls = ScriptedCells(self.cells, mode="context")
        options = dict(
            router=self.router,
            single_cell="first",
            fixed_graph=Graph("fixed", ("first", "second")),
            random_seed=1729,
            execution_binding_digest="e" * 64,
            message_style="native_turn_v1",
        )
        options.update(kwargs)
        output = self.root / self.id().split(".")[-1]
        report = evaluate_suite(
            rows, self.cells, self.budget, calls, data.verify_answer, output, **options
        )
        return calls, report

    def test_changed_split_does_not_hide_fit_overlap(self):
        rows = copy.deepcopy(self.records)
        for row in rows:
            row["split"] = "selection"
        with self.assertRaisesRegex(ValueError, "source-group overlap"):
            self.evaluate(rows)
        self.assertFalse((self.root / self.id().split(".")[-1]).exists())

    def test_each_source_group_blocks_dispatch_even_with_new_task_ids(self):
        for key in (*GROUPS, "source_bytes", "input"):
            with self.subTest(group=key):
                rows = self.panel()
                if key == "source_bytes":
                    rows[0]["source"]["sha256"] = self.records[0]["source"]["sha256"]
                elif key == "input":
                    rows[0]["task"]["input"] = self.records[0]["task"]["input"]
                else:
                    rows[0][key] = self.records[0][key]
                with self.assertRaisesRegex(ValueError, "source-group overlap"):
                    self.evaluate(rows)

    def test_disjoint_declared_panel_executes_all_arms_and_records_messages(self):
        calls, report = self.evaluate(self.panel())
        self.assertFalse(report["evaluation_admission"]["selection_on_this_panel"])
        self.assertFalse(report["evaluation_admission"]["independent_confirmation"])
        self.assertEqual(
            report["all_actual_execution_cost"]["model_calls"], len(calls.requests)
        )
        self.assertEqual(
            report["all_actual_execution_cost"]["verifier_calls"], len(calls.requests)
        )
        raw = [
            json.loads(Path(r["result_path"]).read_text())
            for rows in (*report["arms"].values(), *report["interventions"].values())
            for r in rows
        ]
        measured = 0
        for result in raw:
            for node in result["nodes"]:
                if node["status"] == "COMPLETE":
                    request = json.loads(Path(node["request_path"]).read_text())
                    measured += sum(
                        len(m["content"].encode())
                        for m in request["task"]["messages"][1:]
                    )
        self.assertEqual(
            report["all_actual_execution_cost"]["relay_content_bytes"], measured
        )
        self.assertGreater(measured, 0)

    def test_exposed_panel_requires_explicit_diagnostic_scope(self):
        rows = self.panel()
        rows[0]["exposure"] = "previously_exposed"
        # Synthetic scope declaration; it is never counted as a real agent trace.
        rows[0]["origin_kind"] = "authorized_agent_run"
        rows[0]["trajectory"] = []
        with self.assertRaisesRegex(ValueError, "explicit diagnostic"):
            self.evaluate(rows)
        admission = evaluation_admission(self.router, rows, "exposed_diagnostic")
        self.assertTrue(admission["diagnostic_only"])
        self.assertFalse(admission["independent_confirmation"])

    def test_style_change_is_refused_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "message style"):
            self.evaluate(self.panel(), message_style="bundled_v4")

    def test_message_binding_survives_rebound_registry_attack(self):
        changed = dict(self.cells)
        changed = {k: replace(v, protocol_digest="f" * 64) for k, v in changed.items()}
        record = copy.deepcopy(self.router.record)
        record["cell_registry_digest"] = digest(
            {k: asdict(v) for k, v in sorted(changed.items())}
        )
        router = FrozenRouter(record, digest(record))
        with self.assertRaisesRegex(ValueError, "message style"):
            evaluate_suite(
                self.panel(),
                changed,
                self.budget,
                None,
                None,
                self.root / "bad-abi",
                router=router,
                single_cell="first",
                fixed_graph=Graph("fixed", ("first", "second")),
                random_seed=1729,
                execution_binding_digest="e" * 64,
                message_style="native_turn_v1",
            )

    def test_legacy_router_without_group_bindings_is_not_implicitly_heldout(self):
        record = copy.deepcopy(self.router.record)
        del record["training_group_bindings"]
        router = FrozenRouter(record, digest(record))
        with self.assertRaisesRegex(ValueError, "lacks frozen training group"):
            self.evaluate(self.panel(), router=router)

    def test_failed_relay_is_unknown_not_zero_total_cost(self):
        provider = ScriptedCells(self.cells, mode="context")

        def fail_second(cell, request, directory):
            if directory.name == "node-1":
                raise RuntimeError("delivery unknown")
            return provider(cell, request, directory)

        output = self.root / "failed-relay"
        with self.assertRaisesRegex(RuntimeError, "delivery unknown"):
            run_graph(
                self.records[0],
                Graph("relay", ("first", "second")),
                self.cells,
                self.budget,
                fail_second,
                data.verify_answer,
                output,
                message_style="native_turn_v1",
            )
        failed = json.loads((output / "FAILED.json").read_text())
        request = json.loads((output / "node-1/REQUEST.json").read_text())
        self.assertGreater(
            sum(len(m["content"].encode()) for m in request["task"]["messages"][1:]), 0
        )
        self.assertIsNone(failed["relay_content_bytes"])
        self.assertIsNone(failed["physical_transmitted_bytes"])
        self.assertEqual(failed["completed_node_relay_content_bytes_lower_bound"], 0)
        self.assertEqual(failed["relay_unaccounted_dispatches"], 1)
        self.assertFalse(failed["cost_complete"])


if __name__ == "__main__":
    unittest.main()
