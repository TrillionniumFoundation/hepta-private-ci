#!/usr/bin/env python3
"""Regression guard for the single canonical Objective V1 wire definition."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class ObjectiveContractAlignmentTests(unittest.TestCase):
    def test_source_envelope_capacity_matches_native_lowering(self):
        registry = load("docs/readiness/PROTOCOLS.json")
        row = next(p for p in registry["protocols"] if p["id"] == "ObjectiveSourceEnvelopeV1")
        intent = next(f for f in row["fields"] if f["name"] == "structuredIntent")
        fields = {f["name"]: f for f in intent["properties"]}
        self.assertEqual((fields["legalActionClasses"]["minItems"], fields["legalActionClasses"]["maxItems"]), (0, 127))
        self.assertEqual(fields["confirmationActionClasses"]["maxItems"], 127)
        self.assertEqual(fields["constraints"]["maxItems"], 246)
        self.assertIn(
            {
                "fields": ["successPredicates", "terminalConditions", "evidenceRequirements"],
                "maxTotalItems": 128,
                "reason": "native ObjectiveFunction success-predicate capacity is shared by all three lowered V1 source arrays",
            },
            row["aggregateBounds"],
        )

    def test_objective_semantics_do_not_redefine_wire_fields(self):
        schemas = load("docs/contracts/PROTOCOL_SCHEMAS.json")
        schema = next(p for p in schemas["protocols"] if p["id"] == "ObjectiveFunctionV1")
        wire_fields = [field["name"] for field in schema["fields"]]

        objectives = load("docs/control-plane/OBJECTIVES.json")
        contract = objectives["objectiveFunctionContract"]
        self.assertEqual(
            contract["fieldShapeAuthority"],
            "docs/contracts/PROTOCOL_SCHEMAS.json::ObjectiveFunctionV1",
        )
        self.assertEqual(contract["immutableWireFields"], wire_fields)
        self.assertNotIn("allowedActionClasses", contract["immutableWireFields"])
        self.assertNotIn("abstentionThreshold", contract["immutableWireFields"])


if __name__ == "__main__":
    unittest.main()
