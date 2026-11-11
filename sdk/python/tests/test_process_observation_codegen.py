"""Synthetic codegen tests; these are not generated protocol fixtures."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import ValidationError  # noqa: E402

from scripts._process_observation.schema import METHODS, render_overlay  # noqa: E402
from scripts._process_observation.source import sha256  # noqa: E402
from scripts.update_sdk_artifacts import (  # noqa: E402
    _normalized_schema_bundle_text,
    schema_bundle_path,
    sdk_pyproject_path,
    sdk_root,
)


def synthetic_overlay():
    definitions = {
        "ProcessExitedNotification": {
            "type": "object",
            "properties": {"processHandle": {"type": "string"}, "exitCode": {"type": "integer"}},
            "required": ["processHandle", "exitCode"],
        },
        "ProcessIndeterminateNotification": {
            "type": "object",
            "properties": {
                "processHandle": {"type": "string"},
                "reason": {"$ref": "#/definitions/ProcessIndeterminateReason"},
            },
            "required": ["processHandle", "reason"],
        },
        "ProcessIndeterminateReason": {"type": "string", "enum": ["exitObservationLost"]},
        "ProcessOutputDeltaNotification": {
            "type": "object",
            "properties": {
                "processHandle": {"type": "string"},
                "stream": {"$ref": "#/definitions/ProcessOutputStream"},
                "deltaBase64": {"type": "string"},
            },
            "required": ["processHandle", "stream", "deltaBase64"],
        },
        "ProcessOutputStream": {"type": "string", "enum": ["stdout", "stderr"]},
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "ProcessObservation",
        "anyOf": [{"$ref": f"#/definitions/{name}"} for name in METHODS.values()],
        "definitions": definitions,
    }


class ProcessOverlayCodegenTests(unittest.TestCase):
    def test_stable_normalizer_still_requires_its_account_compatibility_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            schema_bundle_path(root).write_text(json.dumps(synthetic_overlay()))
            with self.assertRaisesRegex(RuntimeError, "Account definition"):
                _normalized_schema_bundle_text(root)

    def test_finite_overlay_uses_real_normalization_and_datamodel_codegen(self):
        schema_bytes = (json.dumps(synthetic_overlay(), sort_keys=True) + "\n").encode()
        provenance = {
            "format": 1,
            "methods": METHODS,
            "source_commit": "1" * 40,
            "source_tree": "2" * 40,
            "schema_sha256": sha256(schema_bytes),
        }
        for key in (
            "experimental_archive_sha256",
            "server_notification_sha256",
            "source_receipt_sha256",
            "generated_manifest_sha256",
            "commands_receipt_sha256",
            "tool_versions_sha256",
        ):
            provenance[key] = "3" * 64
        generated = render_overlay(schema_bytes, provenance)
        with tempfile.TemporaryDirectory(prefix="synthetic-process-models-") as directory:
            path = Path(directory) / "process_observation.py"
            path.write_text(generated)
            before_format = path.read_bytes()
            for arguments in (["check", "--diff"], ["format", "--check"]):
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "ruff",
                        *arguments,
                        "--config",
                        str(sdk_pyproject_path()),
                        str(path),
                    ],
                    cwd=sdk_root(),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(path.read_bytes(), before_format)
            spec = importlib.util.spec_from_file_location("synthetic_process_models", path)
            self.assertIsNotNone(spec)
            self.assertIsNotNone(spec.loader)
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            self.addCleanup(sys.modules.pop, spec.name, None)
            spec.loader.exec_module(module)
            cases = [
                ("ProcessExitedNotification", {"processHandle": "fixture", "exitCode": 0}),
                (
                    "ProcessIndeterminateNotification",
                    {"processHandle": "fixture", "reason": "exitObservationLost"},
                ),
                (
                    "ProcessOutputDeltaNotification",
                    {"processHandle": "fixture", "stream": "stdout", "deltaBase64": "YQ=="},
                ),
            ]
            for name, payload in cases:
                model = getattr(module, name).model_validate(payload)
                self.assertEqual(model.model_dump(mode="json", by_alias=True), payload)
            with self.assertRaises(ValidationError):
                module.ProcessIndeterminateNotification.model_validate(
                    {"processHandle": "fixture", "reason": "inventedExit"}
                )


if __name__ == "__main__":
    unittest.main()
