#!/usr/bin/env python3
"""Deterministic, explicitly synthetic decision fixtures, never efficacy evidence."""
import json
import tempfile
from evaluation import OwnerContext, evaluate
from fixtures import FIXED_TEST_TIME, fixture_documents, rebind_protocol, write_fixture


def main():
    examples = {}
    for case in ("complete_synthetic_evidence", "missing_resource_exchange_rate"):
        docs = fixture_documents()
        if case == "missing_resource_exchange_rate":
            docs["protocol"]["exchange_rates"] = None
            rebind_protocol(docs)
        with tempfile.TemporaryDirectory() as directory:
            owner, owner_sha = write_fixture(directory, docs)
            examples[case] = evaluate(OwnerContext(directory, owner, owner_sha), FIXED_TEST_TIME)
    print(json.dumps({"schema": "hepta.synthetic-decision-demonstration.v1",
                      "all_inputs_synthetic": True, "deterministic_test_clock_override": True,
                      "real_model_quality_claimed": False, "production_eligible": False,
                      "examples": examples}, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
