"""Address and semantic-plan boundaries, exercised through the serving API."""

import copy
import unittest

from addressing.contracts import OwnerRegistry
from addressing.planner import AddressPlanner


class ProbeModel:
    identity = "a" * 64
    calibration = {"independent": True}

    def __init__(self, operation="current", supported=True):
        self.operation, self.supported = operation, supported
        self.seen = []

    def input_supported(self, value):
        return self.supported

    def hypotheses(self, texts):
        self.seen.extend(texts)
        return [{"raw_operation": self.operation}]

    def decide(self, hypothesis):
        return {**hypothesis, "operation": self.operation}


def registry():
    return {
        "schema": "hepta.memory.v7.owner-registry.v1",
        "scope": "owner:alpha",
        "source_cut": "7" * 64,
        "entities": [
            {"entity": "meter-orion", "aliases": ["Orion", "奥瑞安", "shared"]},
            {"entity": "meter-vega", "aliases": ["Vega", "织女星", "shared"]},
            {"entity": "meter-predict", "aliases": ["predict"]},
        ],
    }


def request(**changes):
    return {
        "query_id": "request-1",
        "scope": "owner:alpha",
        "text": "Read the latest value of Orion.",
        "at": 20250201,
        "since": 20250101,
        "max_hops": 4,
        "max_cells": 3,
        **changes,
    }


class PlannerTests(unittest.TestCase):
    def test_reversed_typed_time_range_is_rejected_before_inference(self):
        model = ProbeModel()
        self.rejected(
            AddressPlanner(model, registry()).plan(request(at=1, since=2)),
            "historical-range-is-reversed",
        )
        self.assertEqual(model.seen, [])

    def rejected(self, result, reason):
        self.assertEqual(
            (
                result["status"],
                result["reason"],
                result["request"],
                result["plan"],
                result["authority"],
            ),
            ("rejected", reason, None, None, False),
        )

    def test_unique_new_alias_is_resolved_and_bound_to_owner_cut(self):
        model = ProbeModel()
        owner = registry()
        owner["entities"].append(
            {"entity": "sensor-new-842", "aliases": ["Ｎｅｗ Ｇａｕｇｅ"]}
        )
        result = AddressPlanner(model, owner).plan(
            request(text="Read the latest measurement for new gauge.")
        )
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["request"]["entity"], "sensor-new-842")
        self.assertEqual(result["plan"]["source_cut"], "7" * 64)
        self.assertEqual(model.seen, ["read the latest measurement for entity ."])

    def test_ambiguous_unknown_and_conflicting_entities_never_reach_model(self):
        model = ProbeModel()
        planner = AddressPlanner(model, registry())
        self.rejected(
            planner.plan(request(text="Read shared's newest reading.")),
            "ambiguous-entity-alias",
        )
        self.rejected(
            planner.plan(request(text="Read the latest value for an-unlisted-object.")),
            "entity-not-resolved",
        )
        self.rejected(
            planner.plan(request(entity="meter-vega")),
            "text-entity-conflicts-with-slot",
        )
        self.rejected(
            planner.plan(request(text="Compare Orion and Vega.")),
            "multiple-entities-not-supported",
        )
        self.rejected(
            planner.plan(request(entity="missing-canonical-id")),
            "unknown-or-ambiguous-entity",
        )
        self.assertEqual(model.seen, [])

    def test_explicit_owner_entity_can_supply_context_without_textual_name(self):
        result = AddressPlanner(ProbeModel("semantic"), registry()).plan(
            request(entity="奥瑞安", text="Recall this object's stored attribute.")
        )
        self.assertEqual(
            (
                result["status"],
                result["request"]["entity"],
                result["plan"]["operation"],
            ),
            ("accepted", "meter-orion", "semantic"),
        )

    def test_alias_text_is_not_executed_as_an_intent_and_multiple_aliases_agree(self):
        model = ProbeModel()
        planner = AddressPlanner(model, registry())
        result = planner.plan(request(text="Get the current reading for predict."))
        self.assertEqual(result["request"]["entity"], "meter-predict")
        self.assertEqual(model.seen, ["get the current reading for entity ."])
        result = planner.plan(request(text="Read Orion (奥瑞安)'s latest event."))
        self.assertEqual(result["request"]["entity"], "meter-orion")

    def test_scope_cut_and_unregistered_override_fail_before_semantic_inference(self):
        model = ProbeModel()
        planner = AddressPlanner(model, registry())
        self.rejected(
            planner.plan(request(scope="owner:other")), "scope-not-in-owner-registry"
        )
        self.rejected(
            planner.plan(request(source_cut="6" * 64)), "registry-cut-mismatch"
        )
        self.rejected(planner.plan(request(source_cut=77.0)), "invalid source cut")
        self.rejected(
            planner.plan(request(operation="apply")), "invalid-request-fields"
        )
        self.assertEqual(model.seen, [])

    def test_history_and_change_require_matching_textual_times(self):
        historical = AddressPlanner(ProbeModel("history"), registry())
        accepted = historical.plan(request(text="Read Orion as of 2025-02-01."))
        self.assertEqual(accepted["status"], "accepted")
        self.rejected(
            historical.plan(request(text="Read Orion as of 2025-01-01.")),
            "text-time-conflicts-with-operation-or-slot",
        )
        change = AddressPlanner(ProbeModel("change"), registry())
        result = change.plan(request(text="How much has Orion changed since 20250101?"))
        self.assertEqual(result["plan"]["read_hops"], 2)
        self.rejected(
            change.plan(request(text="Compare Orion at 2025-01-01 and 2025-02-01.")),
            "multiple-historical-cutoffs-not-supported",
        )
        self.rejected(
            change.plan(request(text="Read Orion at 2025-02-31.")),
            "invalid-date-in-text",
        )

    def test_rejected_intents_budgets_and_truncation_leave_no_executable_plan(self):
        self.rejected(
            AddressPlanner(ProbeModel(None), registry()).plan(request()),
            "unsupported-or-low-confidence-intent",
        )
        self.rejected(
            AddressPlanner(ProbeModel("forecast"), registry()).plan(request()),
            "unregistered-operation",
        )
        self.rejected(
            AddressPlanner(ProbeModel("apply"), registry()).plan(request(max_cells=2)),
            "typed-plan-exceeds-budget",
        )
        self.rejected(
            AddressPlanner(ProbeModel("change"), registry()).plan(request(max_hops=1)),
            "typed-plan-exceeds-budget",
        )
        model = ProbeModel(supported=False)
        self.rejected(
            AddressPlanner(model, registry()).plan(request()), "text-would-be-truncated"
        )
        self.assertEqual(model.seen, [])

    def test_registry_and_request_are_not_mutated_by_resolution(self):
        owner, query = registry(), request(text="读取奥瑞安的最新值。")
        before = copy.deepcopy((owner, query))
        AddressPlanner(ProbeModel(), owner).plan(query)
        self.assertEqual((owner, query), before)
        with self.assertRaises(ValueError):
            OwnerRegistry({**owner, "entities": [{"entity": "entity", "aliases": []}]})


if __name__ == "__main__":
    unittest.main()
