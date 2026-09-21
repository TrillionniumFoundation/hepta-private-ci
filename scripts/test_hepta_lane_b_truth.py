#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-lane-b-truth.py")
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_truth", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LaneBTruthTests(unittest.TestCase):
    def test_duplicate_json_keys_fail(self) -> None:
        with self.assertRaises(MODULE.Invalid):
            json.loads('{"a":1,"a":2}', object_pairs_hook=MODULE.pairs)

    def test_path_envelope_is_prefix_bounded(self) -> None:
        self.assertTrue(
            MODULE.allowed("qualification/lane-b/a", ["qualification/lane-b/"])
        )
        self.assertFalse(
            MODULE.allowed("qualification/lane-c/a", ["qualification/lane-b/"])
        )

    def test_closed_module_and_operation_sets(self) -> None:
        self.assertEqual(11, len(MODULE.MODULES))
        self.assertEqual(39, sum(map(len, MODULE.OPS.values())))
        self.assertEqual(len(MODULE.MODULES), len(set(MODULE.MODULES)))

    def test_owner_anchor_cannot_escape_resolved_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "foreign" / "source.rs"
            source.parent.mkdir()
            source.write_text("pub fn run() {}\n", encoding="utf-8")
            anchor = {
                "role": "owner_entrypoint",
                "path": "foreign/source.rs",
                "symbol": "pub fn run(",
                "buildTarget": "fixture",
            }
            with mock.patch.object(MODULE, "ROOT", root):
                with self.assertRaisesRegex(MODULE.Invalid, "owner-root escape"):
                    MODULE.verify_anchor("fixture", ["owned"], anchor, True)

    def test_observed_source_rejects_product_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("codex-rs/hepta-automation", "codex-rs/hepta-agentd"):
                (root / relative).mkdir(parents=True, exist_ok=True)
            row = {
                "resolvedRoots": ["codex-rs/hepta-automation"],
                "observedSourcePaths": [
                    "codex-rs/hepta-automation",
                    "codex-rs/hepta-agentd",
                ],
                "observedAtHead": {"commit": "a" * 40, "tree": "b" * 40},
            }
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(
                    MODULE, "verify_source_base", return_value=("a" * 40, "b" * 40)
                ),
                mock.patch.object(
                    MODULE, "git", return_value="codex-rs/hepta-agentd/src/automation.rs"
                ),
            ):
                with self.assertRaisesRegex(MODULE.Invalid, "observed source drift"):
                    MODULE.verify_observed_source(row, "automation.taskflow")

    def test_observed_source_accepts_document_only_followup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("codex-rs/hepta-automation", "codex-rs/hepta-agentd"):
                (root / relative).mkdir(parents=True, exist_ok=True)
            row = {
                "resolvedRoots": ["codex-rs/hepta-automation"],
                "observedSourcePaths": [
                    "codex-rs/hepta-automation",
                    "codex-rs/hepta-agentd",
                ],
                "observedAtHead": {"commit": "a" * 40, "tree": "b" * 40},
            }
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(
                    MODULE, "verify_source_base", return_value=("a" * 40, "b" * 40)
                ),
                mock.patch.object(MODULE, "git", return_value=""),
            ):
                MODULE.verify_observed_source(row, "automation.taskflow")

    def test_pull_request_current_base_override_precedes_event_snapshot(self) -> None:
        event = {
            "pull_request": {
                "base": {"sha": "a" * 40},
                "head": {"sha": "c" * 40},
            }
        }
        pull_request = event["pull_request"]
        with mock.patch.dict(
            MODULE.os.environ,
            {"HEPTA_CANDIDATE_BASE_SHA": "b" * 40},
            clear=False,
        ):
            event_base = pull_request["base"]["sha"]
            actual_base = (
                MODULE.os.environ.get("HEPTA_CANDIDATE_BASE_SHA") or event_base
            )
        self.assertEqual("b" * 40, actual_base)
        self.assertNotEqual(event_base, actual_base)

    def test_traceability_preserves_external_claim_boundary(self) -> None:
        truth = {
            "sourceBase": {"commit": "a" * 40, "tree": "b" * 40},
            "laneId": "LANE-B-RUNTIME",
        }
        module_map = {
            "module": "fixture",
            "externalEvidenceGates": ["external target"],
            "operations": [
                {
                    "designOperation": "run",
                    "tests": [{"path": "test.rs", "command": "cargo test"}],
                }
            ],
        }
        projection = MODULE.trace_projection(truth, [module_map])
        self.assertFalse(
            projection["claimBoundary"]["productExecutionProvedByRegistry"]
        )
        self.assertFalse(projection["claimBoundary"]["externalEffectsProvedByRegistry"])
        self.assertEqual(1, projection["operationCount"])


if __name__ == "__main__":
    unittest.main()
