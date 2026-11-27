"""Synthetic controls for the N256 terminal publication bridge."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from qualification.hcsn_currentstate_n256_execution_admission_bridge.test_admission_bridge import (
    _records,
)
from qualification.hcsn_currentstate_n256_execution_receipt_publisher_intent import (
    publisher,
)
from qualification.hcsn_currentstate_n256_terminal_publication_intent import (
    static_inspector,
    terminal_publication,
)


ROOT = Path(__file__).parent


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _seal(value, field):
    value[field] = hashlib.sha256(_canonical(value)).hexdigest()
    return value


def _fixture(folder):
    admission, freeze, manifest = _records()
    observation = _seal(
        {
            "schema": terminal_publication.OBSERVATION_SCHEMA,
            "execution_key": admission["execution_key"],
            "capture_session_id": freeze["capture_session_id"],
            "host_alias": freeze["host_alias"],
            "job_id": "synthetic-terminal-job-001",
            "execution_request_sha256": freeze["execution_request_sha256"],
            "result_manifest_sha256": hashlib.sha256(_canonical(manifest)).hexdigest(),
            "stdout_sha256": "a" * 64,
            "stderr_sha256": "b" * 64,
            "execution_started_at_utc": "2026-11-15T01:12:00Z",
            "execution_completed_at_utc": "2026-11-15T01:58:00Z",
            "process_exit_code": 0,
            "timed_out": False,
            "execution_complete": True,
            "historical_negative_and_unknown_preserved": True,
            "largegrid_qualification": False,
            "production_adoption": False,
        },
        "observation_sha256",
    )
    paths = {}
    for name, value in (
        ("admission", admission),
        ("freeze", freeze),
        ("manifest", manifest),
        ("observation", observation),
    ):
        path = folder / f"{name}.json"
        path.write_text(json.dumps(value))
        paths[name] = path
    return paths, observation


def _arguments(paths):
    return {
        "provider_admission_path": paths["admission"],
        "execution_freeze_path": paths["freeze"],
        "result_manifest_path": paths["manifest"],
        "terminal_observation_path": paths["observation"],
    }


class TerminalPublicationIntentTests(unittest.TestCase):
    def test_missing_terminal_original_rejects_before_receipt_publisher(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, _ = _fixture(Path(temporary))
            with mock.patch.object(publisher, "build_receipt_record") as receipt_builder:
                with self.assertRaisesRegex(
                    terminal_publication.TerminalOriginalRequired,
                    "terminal observation",
                ):
                    terminal_publication.build_terminal_publication(
                        provider_admission_path=paths["admission"],
                        execution_freeze_path=paths["freeze"],
                        result_manifest_path=paths["manifest"],
                        terminal_observation_path=None,
                    )
                receipt_builder.assert_not_called()

    def test_synthetic_terminal_original_is_bound_into_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, observation = _fixture(Path(temporary))
            result = terminal_publication.build_terminal_publication(**_arguments(paths))
        self.assertEqual(
            result.publication["terminal_observation_sha256"],
            observation["observation_sha256"],
        )
        self.assertEqual(
            result.publication["execution_receipt_sha256"],
            result.receipt["receipt_sha256"],
        )
        self.assertFalse(result.publication["largegrid_qualification"])
        self.assertFalse(result.publication["production_adoption"])

    def test_terminal_observation_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, observation = _fixture(Path(temporary))
            observation["stdout_sha256"] = "c" * 64
            paths["observation"].write_text(json.dumps(observation))
            with self.assertRaisesRegex(
                terminal_publication.TerminalPublicationError, "digest"
            ):
                terminal_publication.build_terminal_publication(**_arguments(paths))

    def test_publication_mutation_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, observation = _fixture(Path(temporary))
            result = terminal_publication.build_terminal_publication(**_arguments(paths))
            admission, freeze, manifest = _records()
            changed = dict(result.publication)
            changed["stdout_sha256"] = "c" * 64
            with self.assertRaisesRegex(
                terminal_publication.TerminalPublicationError, "field set"
            ):
                terminal_publication.validate_terminal_publication(
                    changed,
                    result.receipt,
                    observation,
                    admission,
                    freeze,
                    manifest,
                )

    def test_boolean_exit_code_cannot_alias_integer_zero(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, observation = _fixture(Path(temporary))
            observation["process_exit_code"] = False
            observation.pop("observation_sha256")
            _seal(observation, "observation_sha256")
            paths["observation"].write_text(json.dumps(observation))
            with self.assertRaisesRegex(
                terminal_publication.TerminalPublicationError, "integer"
            ):
                terminal_publication.build_terminal_publication(**_arguments(paths))

    def test_timeout_rejects_before_receipt_construction(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths, observation = _fixture(Path(temporary))
            observation["timed_out"] = True
            observation.pop("observation_sha256")
            _seal(observation, "observation_sha256")
            paths["observation"].write_text(json.dumps(observation))
            with mock.patch.object(publisher, "build_receipt_record") as receipt_builder:
                with self.assertRaisesRegex(
                    terminal_publication.TerminalPublicationError, "timed out"
                ):
                    terminal_publication.build_terminal_publication(**_arguments(paths))
                receipt_builder.assert_not_called()

    def test_request_and_static_inspector_preserve_hold(self):
        request = json.loads((ROOT / "REQUEST.json").read_text())
        self.assertTrue(all(value is None for value in request["future_originals"].values()))
        self.assertIsNone(request["execution_key"])
        self.assertIsNone(request["terminal_publication_sha256"])
        self.assertFalse(request["numerical_execution_allowed"])
        self.assertFalse(request["all_closed"])
        report = static_inspector.inspect(
            ROOT / "terminal_publication.py", ROOT / "REQUEST.json"
        )
        self.assertEqual(report["status"], "PASS_TERMINAL_PUBLICATION_SOURCE_HOLD")
        self.assertEqual(report["authentic_terminal_originals"], 0)
        self.assertEqual(report["authentic_publications"], 0)
        self.assertEqual(report["dynamic_runs"], 0)


if __name__ == "__main__":
    unittest.main()
