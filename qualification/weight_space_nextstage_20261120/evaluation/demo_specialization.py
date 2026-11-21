#!/usr/bin/env python3
"""Synthetic preservation/savings demonstration, no measured runtime forecasts."""
import json
import tempfile
from evaluation import OwnerContext, evaluate
from fixtures import FIXED_TEST_TIME, rebind_protocol, specialization_fixture_documents, write_fixture


def main():
    examples = {}
    for case in ("equal_quality_bounded_savings", "unknown_original_future_bound", "unknown_conversion"):
        docs = specialization_fixture_documents()
        if case == "unknown_original_future_bound":
            docs["costs"]["original"]["resources_lower_bound"]["CPU_second"] = None
        if case == "unknown_conversion":
            docs["protocol"]["exchange_rates"] = None
        rebind_protocol(docs)
        with tempfile.TemporaryDirectory() as directory:
            name, sha = write_fixture(directory, docs)
            examples[case] = evaluate(OwnerContext(directory, name, sha), FIXED_TEST_TIME)
    print(json.dumps({"schema": "hepta.specialization-synthetic-demonstration.v1",
                      "all_inputs_synthetic": True, "deterministic_test_clock_override": True,
                      "future_resource_bounds_are_fixture_assumptions": True,
                      "production_eligible": False, "examples": examples}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
