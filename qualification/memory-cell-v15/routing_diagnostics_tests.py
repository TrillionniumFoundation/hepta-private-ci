"""Behavioral checks for attribution, missingness, identity and scope boundaries."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

import routing_diagnostics as routing


def seal(data):
    identities = data["identities"]
    for query in data["queries"]:
        query["input_sha256"] = routing.digest(query["input"])
    identities["budget_sha256"] = routing.digest(data["budget"])
    identities["dataset_sha256"] = routing.digest(routing.project(data["queries"], routing.GOLD))
    identities["candidate_pools_sha256"] = routing.digest(routing.project(data["queries"], routing.POOLS))
    for query in data["queries"]:
        for arm, trace in query["traces"].items():
            trace["context_sha256"] = routing.context_digest(identities, query, arm, data["arms"][arm])
    return data


def fixture():
    records = {rid: {"content_sha256": routing.digest(rid), "authorized": True, "current": True}
               for rid in ("first-v1", "second-v1", "distractor-v1", "revoked-v1", "old-v1")}
    records["revoked-v1"]["authorized"] = False
    records["old-v1"]["current"] = False
    trace = {"context_sha256": "", "local_selected": {"left": ["first-v1"], "right": ["second-v1"]},
             "routed_cells": ["left", "right"], "reader": {"evidence": ["first-v1", "second-v1"],
             "output": {"sum": 3}, "abstained": False, "error": None}}
    query = {"id": "two-hop", "answerable": True, "support_sets": [["first-v1", "second-v1"]],
             "input": {"query": "Combine the two current records.",
                       "payload": {"records": ["first-v1", "second-v1"], "phase": "read"}},
             "expected_output": {"sum": 3}, "records": records, "cells": {
                 "left": {"available": ["first-v1", "distractor-v1", "revoked-v1", "old-v1"],
                          "candidates": ["first-v1", "distractor-v1", "revoked-v1", "old-v1"]},
                 "right": {"available": ["second-v1"], "candidates": ["second-v1"]}},
             "traces": {"a": deepcopy(trace), "b": deepcopy(trace)}}
    return seal({"schema": routing.SCHEMA,
        "identities": {key: "a" * (40 if key == "source_commit" else 64) for key in routing.IDENTITIES},
        "budget": {"max_candidates_per_cell": 8, "max_local_per_cell": 4,
                   "max_routed_cells": 3, "max_executor_evidence": 4},
        "arms": {name: {key: routing.digest(name + key) for key in
                 ("model_sha256", "scorer_sha256", "router_sha256")} for name in ("a", "b")},
        "queries": [query]})


class RoutingDiagnosticsTests(unittest.TestCase):
    def test_same_common_pools_give_same_diagnostics_and_no_promotion(self):
        report = routing.analyze(fixture())
        self.assertEqual(report["arms"]["a"], report["arms"]["b"])
        self.assertEqual(report["arms"]["a"]["nested_events"], {
            stage: {"count": 1, "conditional_denominator": 1, "conditional_rate": 1.0}
            for stage in routing.STAGES})
        self.assertEqual((report["production_activation_allowed"], report["all_cells_upper_bound_is_deployable"],
                          report["new_model_runs"], report["qualification"]), (False, False, 0, "not_evaluated"))

    def test_each_nested_failure_is_attributed_without_marginal_multiplication(self):
        rows = []
        for stage in routing.STAGES:
            query = deepcopy(fixture()["queries"][0])
            query["id"] = stage
            trace = query["traces"]["a"]
            if stage in ("eligible_memory", "candidate_coverage", "local_scoring_all_cells"):
                if stage == "eligible_memory":
                    query["cells"]["right"]["available"] = []
                if stage != "local_scoring_all_cells":
                    query["cells"]["right"]["candidates"] = []
                trace["local_selected"]["right"] = []
                trace["reader"]["evidence"] = ["first-v1"]
            elif stage == "cross_expert_routing":
                trace["routed_cells"] = ["left"]
                trace["reader"]["evidence"] = ["first-v1"]
            elif stage == "executor_input":
                trace["reader"]["evidence"] = ["first-v1"]
            else:
                trace["reader"]["output"] = {"sum": 4}
            query["traces"]["b"] = deepcopy(trace)
            rows.append(query)
        data = fixture()
        data["queries"] = rows
        arm = routing.analyze(seal(data))["arms"]["a"]
        self.assertEqual([r["first_failed_event"] for r in arm["rows"]], list(routing.STAGES))
        self.assertEqual([e["count"] for e in arm["nested_events"].values()], [5, 4, 3, 2, 1, 0])
        self.assertEqual([e["conditional_denominator"] for e in arm["nested_events"].values()], [6, 5, 4, 3, 2, 1])
        self.assertEqual(arm["correct_without_complete_support"], 5)

    def test_alternative_complete_support_is_allowed_but_one_of_two_hops_is_not(self):
        data = fixture()
        query = data["queries"][0]
        query["support_sets"].append(["distractor-v1"])
        trace = query["traces"]["a"]
        trace["local_selected"] = {"left": ["distractor-v1"], "right": []}
        trace["routed_cells"] = ["left"]
        trace["reader"]["evidence"] = ["distractor-v1"]
        self.assertTrue(routing.analyze(seal(data))["arms"]["a"]["rows"][0]["grounded_correct"])

    def test_duplicate_support_pool_route_and_reader_ids_never_add_successes(self):
        data = fixture()
        query = data["queries"][0]
        query["support_sets"][0].append("first-v1")
        query["cells"]["left"]["candidates"].append("first-v1")
        trace = query["traces"]["a"]
        trace["local_selected"]["left"].append("first-v1")
        trace["routed_cells"].append("left")
        trace["reader"]["evidence"].append("first-v1")
        arm = routing.analyze(seal(data))["arms"]["a"]
        self.assertEqual(arm["accuracy_bounds_all_expected"], [1.0, 1.0])
        self.assertEqual(arm["rows"][0]["duplicate_references"],
                         {"candidates": 1, "local": 1, "routed_cells": 1, "reader": 1})

    def test_stale_or_unauthorized_gold_is_not_counted_as_eligible_memory(self):
        for field in ("authorized", "current"):
            with self.subTest(field=field):
                data = fixture()
                data["queries"][0]["records"]["second-v1"][field] = False
                row = routing.analyze(seal(data))["arms"]["a"]["rows"][0]
                self.assertEqual(row["first_failed_event"], "eligible_memory")
                self.assertTrue(row["actual_correct"])
                self.assertFalse(row["grounded_correct"])

    def test_unauthorized_or_stale_extra_evidence_invalidates_reader_even_with_all_support(self):
        for rid in ("revoked-v1", "old-v1"):
            with self.subTest(rid=rid):
                data = fixture()
                trace = data["queries"][0]["traces"]["a"]
                trace["local_selected"]["left"].append(rid)
                trace["reader"]["evidence"].append(rid)
                row = routing.analyze(seal(data))["arms"]["a"]["rows"][0]
                self.assertEqual((row["first_failed_event"], row["ineligible_references"]["reader"]),
                                 ("executor_input", 1))

    def test_missing_trace_or_missing_unrouted_cell_stays_unknown_in_full_denominator(self):
        for missing in ("arm", "local"):
            data = fixture()
            other = deepcopy(data["queries"][0])
            other["id"] = "unavailable"
            if missing == "arm":
                del other["traces"]["a"]
            else:
                del other["traces"]["a"]["local_selected"]["right"]
            data["queries"].append(other)
            report = routing.analyze(seal(data))
            arm = report["arms"]["a"]
            self.assertEqual((report["status"], arm["expected_queries"], arm["unavailable_traces"],
                arm["accuracy_bounds_all_expected"]), ("diagnostic_incomplete", 2, 1, [0.5, 1.0]))

    def test_no_answer_is_separate_and_errors_or_nonempty_abstentions_fail(self):
        data = fixture()
        query = data["queries"][0]
        query.update(answerable=False, support_sets=[], expected_output=None)
        for trace in query["traces"].values():
            trace["reader"].update(output=None, abstained=True)
        report = routing.analyze(seal(data))
        arm = report["arms"]["a"]
        self.assertEqual((arm["no_answer_complete"], arm["no_answer_correct"]), (1, 1))
        self.assertTrue(all(e == {"count": 0, "conditional_denominator": 0, "conditional_rate": None}
                            for e in arm["nested_events"].values()))
        for bad in ({"error": "Timeout"}, {"output": "leaked answer"}, {"abstained": False}):
            changed = deepcopy(data)
            changed["queries"][0]["traces"]["a"]["reader"].update(bad)
            self.assertEqual(routing.analyze(changed)["arms"]["a"]["no_answer_correct"], 0)

    def test_executor_type_confusion_is_not_correctness(self):
        data = fixture()
        data["queries"][0]["expected_output"] = 1
        data["queries"][0]["traces"]["a"]["reader"]["output"] = True
        self.assertFalse(routing.analyze(seal(data))["arms"]["a"]["rows"][0]["actual_correct"])

    def test_shared_pool_gold_budget_and_context_tampering_is_detected(self):
        for kind, message in (("pool", "pool_identity"), ("gold", "dataset_identity"), ("budget", "budget_identity")):
            data = fixture()
            if kind == "pool":
                data["queries"][0]["cells"]["left"]["candidates"].reverse()
            elif kind == "gold":
                data["queries"][0]["expected_output"] = 4
            else:
                data["budget"]["max_routed_cells"] = 4
            with self.assertRaisesRegex(ValueError, message):
                routing.analyze(data)
        data = fixture()
        data["queries"][0]["traces"]["a"]["context_sha256"] = "f" * 64
        self.assertEqual(routing.analyze(data)["arms"]["a"]["unavailable_traces"], 1)

    def test_actual_query_payload_and_declared_input_hash_cannot_be_substituted(self):
        for mutation in ("query", "payload", "hash"):
            with self.subTest(mutation=mutation):
                data = fixture()
                query = data["queries"][0]
                if mutation == "query":
                    query["input"]["query"] += " "
                elif mutation == "payload":
                    query["input"]["payload"]["phase"] = "write"
                else:
                    query["input_sha256"] = "f" * 64
                with self.assertRaisesRegex(ValueError, "query_input_identity_mismatch"):
                    routing.analyze(data)
        data = fixture()
        query = data["queries"][0]
        query["input"]["payload"] = dict(reversed(list(query["input"]["payload"].items())))
        self.assertEqual(routing.analyze(data), routing.analyze(fixture()),
                         "object key order must not alter canonical input identity")

    def test_new_input_digest_cannot_reuse_the_old_dataset_or_trace_binding(self):
        data = fixture()
        query = data["queries"][0]
        query["input"]["query"] = "A different actual request with the same gold answer."
        query["input_sha256"] = routing.digest(query["input"])
        with self.assertRaisesRegex(ValueError, "dataset_identity_mismatch"):
            routing.analyze(data)
        data["identities"]["dataset_sha256"] = routing.digest(routing.project(data["queries"], routing.GOLD))
        report = routing.analyze(data)
        self.assertEqual(report["status"], "diagnostic_incomplete")
        for arm in report["arms"].values():
            self.assertEqual((arm["unavailable_traces"], arm["rows"][0]["reason"],
                              arm["accuracy_bounds_all_expected"]), (1, "trace_context_mismatch", [0.0, 1.0]))

    def test_evidence_invented_after_candidate_or_route_stage_is_not_attributed(self):
        for stage in ("local", "route", "reader"):
            data = fixture()
            trace = data["queries"][0]["traces"]["a"]
            if stage == "local":
                trace["local_selected"]["right"] = ["first-v1"]
            elif stage == "route":
                trace["routed_cells"] = ["invented"]
            else:
                trace["reader"]["evidence"] = ["distractor-v1"]
            self.assertEqual(routing.analyze(data)["arms"]["a"]["accuracy_bounds_all_expected"], [0.0, 1.0])

    def test_old_trace_cannot_be_rebound_to_other_model_scorer_router_or_arm_name(self):
        for field in ("model_sha256", "scorer_sha256", "router_sha256"):
            with self.subTest(field=field):
                data = fixture()
                data["arms"]["a"][field] = "f" * 64
                result = routing.analyze(data)["arms"]["a"]
                self.assertEqual((result["unavailable_traces"], result["rows"][0]["reason"]),
                                 (1, "trace_context_mismatch"))
        data = fixture()
        data["arms"]["renamed"] = data["arms"].pop("a")
        traces = data["queries"][0]["traces"]
        traces["renamed"] = traces.pop("a")
        self.assertEqual(routing.analyze(data)["arms"]["renamed"]["unavailable_traces"], 1)

    def test_duplicate_query_and_conflicting_record_identity_are_rejected(self):
        data = fixture()
        data["queries"].append(deepcopy(data["queries"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate_query"):
            routing.analyze(seal(data))
        data["queries"][1]["id"] = "other"
        data["queries"][1]["records"]["first-v1"]["content_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "immutable_record"):
            routing.analyze(seal(data))

    def test_duplicate_slots_count_toward_budget_and_caller_state_is_detached(self):
        data = fixture()
        data["budget"]["max_routed_cells"] = 2
        data["queries"][0]["traces"]["a"]["routed_cells"].append("left")
        report = routing.analyze(seal(data))
        self.assertEqual(report["arms"]["a"]["unavailable_traces"], 1)
        data["identities"]["memory_sha256"] = "e" * 64
        self.assertEqual(report["identities"]["memory_sha256"], "a" * 64)

    def test_nonfinite_duplicate_keys_and_excess_bytes_are_rejected(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "bad.json"
            for raw in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b' ' * (routing.MAX_BYTES + 1)):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    routing.load_json(path)

    def test_cli_checks_frozen_raw_identity_and_cannot_overwrite_input(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "traces.json"
            raw = json.dumps(fixture()).encode()
            path.write_bytes(raw)
            command = [sys.executable, str(Path(routing.__file__)), str(path), "--expected-sha256"]
            good = subprocess.run([*command, hashlib.sha256(raw).hexdigest()], capture_output=True, text=True, check=False)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(json.loads(good.stdout)["status"], "diagnostic_complete")
            bad = subprocess.run([*command, "0" * 64], capture_output=True, text=True, check=False)
            self.assertEqual((bad.returncode, json.loads(bad.stdout)["status"]), (2, "invalid_input"))
            same = subprocess.run([*command, "0" * 64, "--output", str(path)], capture_output=True, text=True, check=False)
            self.assertNotEqual(same.returncode, 0)
            self.assertEqual(path.read_bytes(), raw)

    def test_historical_modified_bytes_cannot_get_an_availability_receipt(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "semantic-17.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "historical_git_blob"):
                routing.audit_historical(directory)


if __name__ == "__main__":
    unittest.main()
