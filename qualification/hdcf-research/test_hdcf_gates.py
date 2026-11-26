"""Adversarial tests for the authority-free Stem/graph shadow audit."""
import copy
import json
import unittest

from hdcf_gates import Denied, audit, graph_gate, stem_cost, strict_json

SHA = "a" * 64


def example_cost():
    return {
        "cells": 4096, "encoder_params": 421000000, "head_params": 6914,
        "organ_params": 0, "bytes_per_weight": 2, "same_input": True,
        "principal": "research-only", "encoder_digest": SHA,
        "input_digest": SHA, "generation": 1,
    }


def item(name, parents, fi, fo, bi, bo, cost=1):
    return {
        "id": name, "parents": parents, "forward_in": fi, "forward_out": fo,
        "backward_in": bi, "backward_out": bo,
        "forward_residual": 0, "backward_residual": 0, "cost": cost,
    }


def example_graph():
    return {
        "objective_digest": SHA, "source_digest": SHA, "generation": 1,
        "tolerance": 0, "budget": 3, "declared_terminal_value": 10,
        "nodes": [
            item("root", [], 0, 1, 9, 0),
            item("leaf", ["root"], 1, 2, 10, 9),
        ],
        "terminal_ids": ["leaf"],
    }


class GatesTest(unittest.TestCase):
    def test_resource_math_and_nonclaims(self):
        result = stem_cost(example_cost())
        self.assertEqual(result["duplicate_weight_bytes"], 4096 * 421000000 * 2)
        self.assertEqual(result["shared_weight_bytes"], (421000000 + 4096 * 6914) * 2)
        self.assertIsNone(result["encoder_forward_count"])
        self.assertIsNone(result["rss_bytes"])
        self.assertFalse(result["production_authorized"])

    def test_explicit_rejection_of_invalid_identity_and_count(self):
        for field, invalid in [("cells", 4097), ("cells", True),
                               ("encoder_digest", "deadbeef"),
                               ("generation", 0), ("principal", "")]:
            candidate = example_cost()
            candidate[field] = invalid
            with self.subTest(field=field), self.assertRaises(Denied):
                stem_cost(candidate)

    def test_identical_cost_claim_is_not_automatic_reuse(self):
        candidate = example_cost()
        candidate["same_input"] = False
        result = stem_cost(candidate)
        self.assertFalse(result["same_input_claimed"])
        self.assertIsNone(result["encoder_forward_count"])

    def test_valid_contiguous_graph_is_numeric_only(self):
        result = graph_gate(example_graph())
        self.assertEqual(result["nodes_checked"], 2)
        self.assertEqual(result["edges_checked"], 1)
        self.assertFalse(result["global_solution_verified"])
        self.assertFalse(result["external_effect_authorized"])

    def test_local_zero_residuals_but_bad_forward_glue(self):
        p = example_graph()
        p["nodes"][1]["forward_in"] = 99
        with self.assertRaisesRegex(Denied, "forward interface"):
            graph_gate(p)

    def test_local_zero_residuals_but_bad_backward_glue(self):
        p = example_graph()
        p["nodes"][1]["backward_out"] = 8
        with self.assertRaisesRegex(Denied, "backward interface"):
            graph_gate(p)

    def test_local_zero_residuals_but_wrong_terminal(self):
        p = example_graph()
        p["nodes"][1]["backward_in"] = 11
        with self.assertRaisesRegex(Denied, "terminal condition"):
            graph_gate(p)

    def test_budget_failure_and_no_missing_terminals(self):
        p = example_graph()
        p["budget"] = 1
        with self.assertRaisesRegex(Denied, "budget"):
            graph_gate(p)
        p = example_graph()
        p["terminal_ids"] = ["root"]
        with self.assertRaisesRegex(Denied, "terminal coverage"):
            graph_gate(p)

    def test_no_orphan_forward_references(self):
        p = example_graph()
        p["nodes"][0]["parents"] = ["leaf"]
        with self.assertRaises(Denied):
            graph_gate(p)

    def test_unsupported_nan_duplicate_key_and_bool_numbers(self):
        for text in ['{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}']:
            with self.assertRaises(Denied):
                strict_json(text)
        p = example_graph()
        p["nodes"][0]["cost"] = True
        with self.assertRaises(Denied):
            graph_gate(p)

    def test_no_unknown_fields_and_no_activation_mode(self):
        request = {"schema": "hepta.hdcf.shadow.v1", "mode": "stem_cost",
                   "payload": example_cost()}
        result = json.loads(audit(json.dumps(request)))
        self.assertEqual(result["claim"], "WEIGHTS_ONLY_NOT_PHYSICAL_EFFICACY")
        for mode in ("native_execute", "promote", "split_live"):
            request["mode"] = mode
            with self.subTest(mode=mode), self.assertRaises(Denied):
                audit(json.dumps(request))
        request["mode"] = "stem_cost"
        request["grant"] = "pretend"
        with self.assertRaises(Denied):
            audit(json.dumps(request))

    def test_bounded_chain(self):
        p = example_graph()
        p["nodes"] = [item("n0", [], 0, 1, 9, 0)]
        for i in range(1, 33):
            p["nodes"].append(item(f"n{i}", [f"n{i-1}"], i, i+1, 9+i, 9+i-1))
        p["terminal_ids"] = ["n32"]
        p["budget"] = 100
        with self.assertRaisesRegex(Denied, "deep"):
            graph_gate(p)


if __name__ == "__main__":
    unittest.main()
