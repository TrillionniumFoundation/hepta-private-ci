"""Audit attacks and accounting behavior; no surrogate learning experiment."""

from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from costs import FIXED, ROLES, WEIGHTS, compare, complete_matrix, weighted
from evidence import decode, digest, execute_program, verify_batch, verify_model_use
import score as score_cli


def arm_matrix():
    return [{"id": role, "resources": {"wall_ns": 100 + index, "retained_logical_byte": 10,
             "application_transport_byte": 20, "process_peak_rss_byte": 30},
             "future": {"decision_errors": 0}, "retention": {"read_error_delta": 0, "decision_error_delta": 0}}
            for index, role in enumerate(ROLES)]


def encoded_record(record):
    for name, field in (("request", "queries"), ("readout", "readouts")):
        # Preserve this deliberately noncanonical whitespace/order as bytes.
        raw = json.dumps(record[field], indent=1)
        record[f"{name}_bytes"] = raw
        record[f"{name}_digest"] = digest(raw.encode())


def prefix_fixture():
    seed, cut = "audit-only", digest(b"audit source")
    export = {"scope": "audit:scope", "owner_cut_digest": cut}
    facts, entities = {}, []
    for index in range(24):
        address = digest(f"random-owner-values:{seed}:{index}".encode())
        entity = f"entity:trained-{index}-{address[:12]}"
        entities.append(entity)
        facts[entity] = {"event": (digest(f"source {index}".encode()), index)}
    batch = {"phase": "prefix", "source_cut": cut, "queries": 96, "correct": 96, "tasks": 16,
             "decisions_correct": 16, "socket_and_native_wall_ns": 7,
             "traffic": {"rpc_attempts": 96, "transmitted_bytes": 1, "received_bytes": 1}, "records": []}
    for group in range(16):
        queries, readouts, expected = [], [], []
        for offset in range(6):
            index = (group % 4) * 6 + offset
            entity, query_id = entities[index], f"query:prospective:prefix:{group}:{offset}"
            queries.append({"schema": "hepta.memory.request.v1", "query_id": query_id, "scope": export["scope"],
                            "entity": entity, "text": "Explicit trusted resolver integration test", "at": 15, "since": 10,
                            "max_hops": 3, "max_cells": 3})
            readouts.append({"schema": "hepta.memory.readout.v1", "query_id": query_id, "operation": "current", "status": "ok",
                             "value": index, "source_ids": [facts[entity]["event"][0]], "generation": 1, "elapsed_seconds": 0.123456789012345})
            expected.append(index)
        threshold = (group % 5 - 2) * 1200
        record = {"sequence": group + 1, "family": group // 4, "task_id": f"task:prefix:{group}",
                  "queries": queries, "readouts": readouts, "expected_values": expected,
                  "addresses": sorted(digest(query["entity"].encode()) for query in queries),
                  "threshold": threshold, "action": -3 > threshold, "expected_action": -3 > threshold, "decision_correct": True}
        encoded_record(record)
        batch["records"].append(record)
    return batch, export, facts, seed


class CostAccountingTests(unittest.TestCase):
    def test_same_information_policies_pay_the_full_search_once(self):
        arms = arm_matrix()
        result = compare(arms, WEIGHTS, common_bytes=50, selector_wall_ns=17)
        expected = sum(weighted(arm["resources"], WEIGHTS) for arm in arms[:8]) + 17
        for role in ("lightweight-prefix-selector", "learned-coaccess"):
            policy = result["policies"][role]
            self.assertEqual(policy["search_resource_score"], expected)
            self.assertEqual(policy["search_trials_charged"], list(FIXED))
        self.assertEqual(result["policies"]["direct-owner"]["search_resource_score"], 0)
        self.assertEqual(result["policies"]["fixed-1"]["search_resource_score"], 0)
        self.assertLess(result["learned_comparisons"]["direct_owner"]["comparator_minus_learned_proxy_score"], 0)
        self.assertEqual(result["full_cost_gate"]["decision"], "NoChange")

    def test_missing_rss_is_not_zero_and_no_fixed_candidate_is_filtered(self):
        arms = arm_matrix()
        arms[2]["resources"]["process_peak_rss_byte"] = None
        result = compare(arms, WEIGHTS, common_bytes=0, selector_wall_ns=1)
        self.assertIsNone(result["policies"]["learned-coaccess"]["measured_proxy_score"])
        self.assertIsNone(result["learned_comparisons"]["hindsight_fixed_inventory_oracle"]["arm"])
        self.assertIn("process_peak_rss_byte", result["policies"]["lightweight-prefix-selector"]["missing_weighted_components"])
        self.assertIsNotNone(result["policies"]["direct-owner"]["measured_proxy_score"])

    def test_incomplete_duplicate_or_changed_weights_are_rejected(self):
        arms = arm_matrix()
        for incomplete in (arms[:-1], arms[:-1] + [arms[0]]):
            with self.assertRaises(ValueError):
                complete_matrix(incomplete)
        changed = dict(WEIGHTS, process_peak_rss_byte=0)
        with self.assertRaises(ValueError):
            compare(arms, changed, 0, 1)


class EvidenceRecomputationTests(unittest.TestCase):
    def test_exact_serialized_typed_batch_bytes_are_the_hash_input(self):
        batch, export, facts, seed = prefix_fixture()
        self.assertEqual(verify_batch(batch, export, facts, seed, False, 1)["correct_reads"], 96)
        forged = deepcopy(batch)
        forged["records"][0]["request_bytes"] += " "
        with self.assertRaises(ValueError):
            verify_batch(forged, export, facts, seed, False, 1)

    def test_a_real_wrong_answer_is_kept_but_relabeling_gold_is_rejected(self):
        batch, export, facts, seed = prefix_fixture()
        record = batch["records"][2]
        record["readouts"][0]["value"] += 10000
        record.update(action=True, decision_correct=False)
        encoded_record(record)
        batch.update(correct=95, decisions_correct=15)
        outcome = verify_batch(batch, export, facts, seed, False, 1)
        self.assertEqual((outcome["read_errors"], outcome["decision_errors"]), (1, 1))
        record["expected_values"][0] += 10000
        with self.assertRaises(ValueError):
            verify_batch(batch, export, facts, seed, False, 1)

    def test_registered_programs_use_values_and_preserve_clamp_sign(self):
        semantic = {"factor": -4, "label": "audit"}
        values = [execute_program(7, semantic, {"opcode": opcode, "bias": 3, "limit": 10})
                  for opcode in ("identity", "add_bias", "multiply", "affine", "clamp")]
        self.assertEqual(values, [7, 10, -28, -25, -10])

    def test_another_valid_model_cannot_replace_the_measured_candidate(self):
        models = {kind: digest(kind.encode()) for kind in ("semantic", "procedure")}
        readout = {"status": "ok", "operation": "semantic", "cell_digests": [models["semantic"]],
                   "prediction_kind": "model_prediction", "hops": 1, "reason": None, "value": "a wrong answer is scored separately"}
        batch = {"records": [{"readouts": [readout]}]}
        verify_model_use(batch, models)
        readout["cell_digests"] = [digest(b"other legal same-cut generation model")]
        with self.assertRaises(ValueError):
            verify_model_use(batch, models)

    def test_nonfinite_exponents_and_duplicate_fields_are_not_audit_numbers(self):
        for raw in ('{"cost":1e999}', '{"cost":1,"cost":2}', '{"cost":NaN}'):
            with self.assertRaises(ValueError):
                decode(raw)

    def test_malformed_input_exceptions_leave_a_failed_nochange_receipt(self):
        for error in (AttributeError("non-string batch bytes"), struct.error("invalid tensor field")):
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "score.json"
                with patch.object(score_cli, "score", side_effect=error), patch("sys.argv", ["score.py", "input.json", str(output)]), redirect_stdout(io.StringIO()):
                    self.assertEqual(score_cli.main(), 1)
                receipt = json.loads(output.read_text())
                self.assertEqual((receipt["integrity_verified"], receipt["decision"], receipt["error_type"]),
                                 (False, "NoChange", type(error).__name__))


if __name__ == "__main__":
    unittest.main()
