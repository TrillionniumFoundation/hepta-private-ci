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

    def test_missing_rollback_cannot_certify_the_design_contract(self):
        def remove(schemas):
            artifact = self.artifact(schemas)
            artifact["fields"] = [
                field
                for field in artifact["fields"]
                if field["name"] != "rollbackDigest"
            ]

        for subject in (ALGORITHM, GLOBAL):
            with self.subTest(verifier=subject.__name__):
                self.reject_mutation(
                    subject,
                    remove,
                    "required protocol field missing BellmanOperatorArtifactV1.rollbackDigest",
                )

    def test_rank_cannot_change_numeric_type(self):
        def change(schemas):
            field = next(
                field
                for field in self.artifact(schemas)["fields"]
                if field["name"] == "rank"
            )
            field["type"] = "i32"

        for subject in (ALGORITHM, GLOBAL):
            with self.subTest(verifier=subject.__name__):
                self.reject_mutation(
                    subject,
                    change,
                    "protocol field type drift BellmanOperatorArtifactV1.rank",
                )

    def test_required_training_identity_cannot_become_optional(self):
        def relax(schemas):
            field = next(
                field
                for field in self.artifact(schemas)["fields"]
                if field["name"] == "trainingDatasetDigest"
            )
            field["required"] = False

        for subject in (ALGORITHM, GLOBAL):
            with self.subTest(verifier=subject.__name__):
                self.reject_mutation(
                    subject,
                    relax,
                    "protocol field requiredness drift BellmanOperatorArtifactV1.trainingDatasetDigest",
                )

    def test_initial_artifact_cannot_be_forced_to_have_a_predecessor(self):
        def change(schemas):
            field = next(
                field
                for field in self.artifact(schemas)["fields"]
                if field["name"] == "predecessorArtifactId"
            )
            field["required"] = True

        for subject in (ALGORITHM, GLOBAL):
            with self.subTest(verifier=subject.__name__):
                self.reject_mutation(
                    subject,
                    change,
                    "protocol field requiredness drift BellmanOperatorArtifactV1.predecessorArtifactId",
                )

    def test_error_budget_bound_cannot_drift_from_the_design(self):
        def enlarge(schemas):
            field = next(
                field
                for field in self.artifact(schemas)["fields"]
                if field["name"] == "errorBudget"
            )
            field["maxBytes"] *= 2

        for subject in (ALGORITHM, GLOBAL):
            with self.subTest(verifier=subject.__name__):
                self.reject_mutation(
                    subject,
                    enlarge,
                    "protocol field bound drift BellmanOperatorArtifactV1.errorBudget",
                )

    def test_requirement_guard_is_generic_and_rejects_malformed_declarations(self):
        fields = [
            {
                "name": "payload",
                "type": "bounded_object",
                "required": True,
                "maxBytes": 16,
            }
        ]
        requirements = {"FixtureV1": fields}
        protocols = {"FixtureV1": {"fields": copy.deepcopy(fields)}}
        ALGORITHM.validate_protocol_field_requirements(
            requirements, ["FixtureV1"], protocols
        )
        for invalid, message in (
            (None, "nonempty object"),
            ({"FixtureV1": fields * 2}, "duplicate field requirement"),
            ({"FixtureV1": [fields[0] | {"required": 1}]}, "invalid field semantics"),
            (
                {"FixtureV1": [fields[0] | {"maxBytes": True}]},
                "invalid field bound requirement",
            ),
            ({"OtherV1": fields}, "nonrequired protocol"),
        ):
            with (
                self.subTest(requirements=invalid),
                self.assertRaisesRegex(ValueError, message),
            ):
                ALGORITHM.validate_protocol_field_requirements(
                    invalid, ["FixtureV1"], protocols
                )


if __name__ == "__main__":
    unittest.main()
