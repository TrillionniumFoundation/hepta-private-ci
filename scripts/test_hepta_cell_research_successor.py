"""Exercise foundation consumption binding through the actual research gate."""

import copy
import json
import unittest

import hepta_cell_research_gate as gate
import test_hepta_cell_research_gate as shared


class ResearchSuccessorTests(unittest.TestCase):
    def setUp(self):
        self.fixture = shared.ResearchGateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.legacy_configuration = copy.deepcopy(self.fixture.configuration)
        configuration = copy.deepcopy(self.legacy_configuration)
        configuration["schema"] = "hepta.cell-joint-config.v2"
        for role in (
            "state_schema",
            "encoder",
            "backend",
            "incumbent_state_schema",
            "incumbent_encoder",
            "incumbent_backend",
        ):
            configuration["artifacts"][role] = self.fixture.bind(
                role + ".bin", role.encode()
            )
        artifacts = configuration["artifacts"]
        configuration["compatibility"] = {
            "schema": "hepta.cell-model-compatibility.v1",
            "models": {
                "candidate_model": {
                    "model_sha256": artifacts["candidate_model"]["sha256"],
                    "state_schema_sha256": artifacts["state_schema"]["sha256"],
                    "encoder_sha256": artifacts["encoder"]["sha256"],
                    "backend_sha256": artifacts["backend"]["sha256"],
                },
                "incumbent_model": {
                    "model_sha256": artifacts["incumbent_model"]["sha256"],
                    "state_schema_sha256": artifacts["incumbent_state_schema"][
                        "sha256"
                    ],
                    "encoder_sha256": artifacts["incumbent_encoder"]["sha256"],
                    "backend_sha256": artifacts["incumbent_backend"]["sha256"],
                },
            },
            "state_transition": {"mode": "reset"},
        }
        self.put_configuration(configuration)
        self.integrity = gate.joint.verify(
            configuration, self.fixture.source, self.fixture.artifacts
        )
        self.fixture.put_foundation()
        self.foundation = json.loads(
            (self.fixture.artifacts / "foundation.json").read_bytes()
        )
        self.foundation.update(
            schema="hepta.cell-research-foundation.v2",
            declared_successor={
                "task_id": "successor/task-1",
                "model_role": "candidate_model",
            },
        )
        self.readback = {
            "schema": "hepta.cell-consumption-readback.v1",
            "task_id": "successor/task-1",
            "model_role": "candidate_model",
            "bundle_sha256": self.integrity["bundle_sha256"],
            **configuration["compatibility"]["models"]["candidate_model"],
        }
        self.put_foundation(self.foundation, self.readback)

    def put_configuration(self, configuration):
        self.fixture.configuration = configuration
        self.fixture.configuration_binding = self.fixture.bind(
            "joint.json", configuration
        )
        self.fixture.manifest["joint_configuration"] = (
            self.fixture.configuration_binding
        )
        self.fixture.protocol["joint_configuration_sha256"] = (
            self.fixture.configuration_binding["sha256"]
        )
        self.fixture.manifest["protocol"] = self.fixture.bind(
            "protocol.json", self.fixture.protocol
        )

    def put_foundation(self, foundation, readback):
        document = copy.deepcopy(foundation)
        document["artifacts"]["successor"] = self.fixture.bind(
            "successor.json", readback
        )
        self.fixture.manifest["foundation"] = self.fixture.bind(
            "foundation.json", document
        )
        return document

    def test_bound_successor_checks_both_roles_without_authenticating_execution(self):
        for role in ("candidate_model", "incumbent_model"):
            with self.subTest(role=role):
                foundation, readback = (
                    copy.deepcopy(self.foundation),
                    copy.deepcopy(self.readback),
                )
                foundation["declared_successor"]["model_role"] = role
                readback.update(
                    model_role=role,
                    **self.fixture.configuration["compatibility"]["models"][role],
                )
                document = self.put_foundation(foundation, readback)
                result = self.fixture.assess()
                review = result["foundation"]
                self.assertTrue(review["foundation_bytes_verified"])
                self.assertEqual(review["artifact_bindings"], document["artifacts"])
                self.assertEqual(
                    review["declared_successor"], foundation["declared_successor"]
                )
                self.assertEqual(
                    review["successor_expectation_source"], "foundation_declaration"
                )
                self.assertEqual(review["successor_binding_integrity"], "verified")
                self.assertEqual(review["successor_review"]["readback"], readback)
                for field in (
                    "successor_expectation_authenticated",
                    "successor_expectation_preregistered",
                    "consumer_readback_authenticity_verified",
                    "actual_successor_consumption_verified",
                    "model_execution_verified",
                    "trajectory_semantics_verified",
                    "source_registry_semantics_verified",
                    "recovery_verified",
                    "evaluator_owner_authenticated",
                ):
                    self.assertFalse(review[field])
                self.assertTrue(result["stages"]["S0"]["mechanical_ready"])
                self.assertEqual(
                    result["stages"]["S0"]["blockers"],
                    [
                        "OWNER_AUTHENTICATION_ADAPTER_UNSUPPORTED",
                        "RECOVERY_ADAPTER_UNSUPPORTED",
                        "ACTUAL_SUCCESSOR_CONSUMPTION_UNVERIFIED",
                    ],
                )
                self.assertTrue(
                    all(
                        not stage["substantive_evidence_ready"]
                        for stage in result["stages"].values()
                    )
                )
                for field in (
                    "research_advancement",
                    "authority_granted",
                    "production_qualification",
                    "preregistration_verified",
                ):
                    self.assertFalse(result[field])

    def test_readback_must_match_task_role_bundle_and_all_model_components(self):
        changes = {
            "task_id": "successor/another-task",
            "model_role": "incumbent_model",
            "bundle_sha256": "f" * 64,
            "model_sha256": "f" * 64,
            "state_schema_sha256": "f" * 64,
            "encoder_sha256": "f" * 64,
            "backend_sha256": "f" * 64,
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                readback = copy.deepcopy(self.readback)
                readback[field] = value
                self.put_foundation(self.foundation, readback)
                with self.assertRaises(ValueError):
                    self.fixture.assess()

    def test_expectations_are_explicit_even_without_configuration(self):
        self.fixture.manifest["joint_configuration"] = None
        for expectation in (
            None,
            {"task_id": "successor/task-1"},
            {"task_id": "", "model_role": "candidate_model"},
            {"task_id": "x" * 257, "model_role": "candidate_model"},
            {"task_id": "successor/task-1", "model_role": "unknown_model"},
            {
                "task_id": "successor/task-1",
                "model_role": "candidate_model",
                "authenticated": True,
            },
        ):
            with self.subTest(expectation=expectation):
                foundation = copy.deepcopy(self.foundation)
                if expectation is None:
                    del foundation["declared_successor"]
                else:
                    foundation["declared_successor"] = expectation
                self.put_foundation(foundation, self.readback)
                with self.assertRaises(ValueError):
                    self.fixture.assess()

    def test_legacy_foundation_keeps_opaque_bytes_and_unsupported_consumption(self):
        foundation = copy.deepcopy(self.foundation)
        foundation["schema"] = "hepta.cell-research-foundation.v1"
        del foundation["declared_successor"]
        self.put_foundation(foundation, b"opaque legacy successor\n")
        result = self.fixture.assess()
        review = result["foundation"]
        self.assertTrue(review["foundation_bytes_verified"])
        self.assertIsNone(review["declared_successor"])
        self.assertIsNone(review["successor_review"])
        self.assertEqual(review["successor_binding_integrity"], "unsupported")
        self.assertFalse(review["actual_successor_consumption_verified"])
        self.assertTrue(result["stages"]["S0"]["mechanical_ready"])
        self.assertIn(
            "SUCCESSOR_ADAPTER_UNSUPPORTED", result["stages"]["S0"]["blockers"]
        )

    def test_missing_or_legacy_configuration_keeps_typed_successor_unverified(self):
        for configuration in (None, self.legacy_configuration):
            with self.subTest(
                configuration="missing" if configuration is None else "legacy"
            ):
                foundation = copy.deepcopy(self.foundation)
                if configuration is None:
                    self.fixture.manifest["joint_configuration"] = None
                else:
                    self.put_configuration(configuration)
                    foundation["joint_configuration_sha256"] = (
                        self.fixture.configuration_binding["sha256"]
                    )
                    foundation["protocol_sha256"] = self.fixture.manifest["protocol"][
                        "sha256"
                    ]
                self.put_foundation(foundation, self.readback)
                result = self.fixture.assess()
                review = result["foundation"]
                self.assertTrue(review["foundation_bytes_verified"])
                self.assertEqual(review["successor_binding_integrity"], "unverified")
                self.assertIsNone(review["successor_review"])
                self.assertFalse(review["actual_successor_consumption_verified"])
                self.assertFalse(result["stages"]["S0"]["mechanical_ready"])
                self.assertIn(
                    "SUCCESSOR_ADAPTER_UNSUPPORTED", result["stages"]["S0"]["blockers"]
                )

    def test_corrupt_bytes_or_incomplete_readback_reject(self):
        for change in (
            "bytes",
            "json",
            "unknown_field",
            "missing_component",
            "invalid_digest",
        ):
            with self.subTest(change=change):
                readback = copy.deepcopy(self.readback)
                if change == "json":
                    readback = b"not-json\n"
                elif change == "unknown_field":
                    readback["authenticated"] = True
                elif change == "missing_component":
                    del readback["encoder_sha256"]
                elif change == "invalid_digest":
                    readback["model_sha256"] = True
                self.put_foundation(self.foundation, readback)
                if change == "bytes":
                    path = self.fixture.artifacts / "successor.json"
                    path.write_bytes(b"x" * path.stat().st_size)
                with self.assertRaises(ValueError):
                    self.fixture.assess()

    def test_successor_reads_cannot_escape_the_bound_artifact_root(self):
        for change in ("parent", "absolute", "symlink"):
            with self.subTest(change=change):
                document = self.put_foundation(self.foundation, self.readback)
                if change == "parent":
                    document["artifacts"]["successor"]["path"] = "../successor.json"
                elif change == "absolute":
                    document["artifacts"]["successor"]["path"] = str(
                        self.fixture.artifacts / "successor.json"
                    )
                else:
                    link = self.fixture.artifacts / "successor-link.json"
                    link.symlink_to(self.fixture.artifacts / "successor.json")
                    document["artifacts"]["successor"]["path"] = link.name
                self.fixture.manifest["foundation"] = self.fixture.bind(
                    "foundation.json", document
                )
                with self.assertRaises((ValueError, OSError)):
                    self.fixture.assess()

    def test_typed_foundation_still_reconciles_shared_bindings_without_originals(self):
        self.fixture.put(self.fixture.experiment())
        self.fixture.manifest["joint_configuration"] = None
        self.fixture.manifest["protocol"] = None
        for field in ("joint_configuration_sha256", "protocol_sha256"):
            with self.subTest(field=field):
                foundation = copy.deepcopy(self.foundation)
                foundation[field] = "f" * 64
                self.put_foundation(foundation, self.readback)
                with self.assertRaisesRegex(
                    ValueError, f"conflicting declared {field}"
                ):
                    self.fixture.assess()


if __name__ == "__main__":
    unittest.main()
