"""Reject Bellman schema drift through the existing documentation verifiers."""

import contextlib
import copy
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch


def verifier(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).with_name(filename)
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ALGORITHM = verifier("bellman_algorithm_docs", "hepta-algorithm-docs.py")
GLOBAL = verifier("bellman_global_docs", "hepta-docs.py")
SCHEMAS = "docs/contracts/PROTOCOL_SCHEMAS.json"


class BellmanSchemaDriftTests(unittest.TestCase):
    def reject_mutation(self, subject, mutate, expected_error):
        load = subject.load
        schemas = copy.deepcopy(load(SCHEMAS))
        mutate(schemas)

        def mutated_load(path):
            return schemas if path == SCHEMAS else load(path)

        with (
            patch.object(subject, "load", side_effect=mutated_load),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaisesRegex(SystemExit, expected_error),
        ):
            if subject is GLOBAL:
                subject.verify(profile="development")
            else:
                subject.verify()

    @staticmethod
    def artifact(schemas):
        return next(
            row
            for row in schemas["protocols"]
            if row["id"] == "BellmanOperatorArtifactV1"
        )

    def test_missing_bellman_schema_cannot_certify_algorithm_closure(self):
        def remove(schemas):
            schemas["protocols"] = [
                row
                for row in schemas["protocols"]
                if row["id"] != "BellmanOperatorArtifactV1"
            ]

        self.reject_mutation(ALGORITHM, remove, "required protocol schema missing")

    def test_bellman_unknown_field_policy_cannot_be_relaxed(self):
        def relax(schemas):
            self.artifact(schemas)["denyUnknownCriticalFields"] = False

        self.reject_mutation(
            ALGORITHM, relax, "BellmanOperatorArtifactV1 unknown-field policy"
        )

    def test_bellman_error_budget_cannot_lose_its_encoded_bound(self):
        def unbound(schemas):
            budget = next(
                field
                for field in self.artifact(schemas)["fields"]
                if field["name"] == "errorBudget"
            )
            del budget["maxBytes"]

        self.reject_mutation(
            GLOBAL, unbound, "unbounded field BellmanOperatorArtifactV1.errorBudget"
        )


if __name__ == "__main__":
    unittest.main()
