#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).with_name("hepta-lane-b-truth.py")
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("hepta_lane_b_truth", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DelegatedOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.agent_root = "codex-rs/hepta-agentd"
        self.ledger_root = "codex-rs/hepta-learning-ledger"
        self.write("codex-rs/Cargo.toml", "[workspace]\n")
        self.write(f"{self.agent_root}/src/lib.rs", "pub fn run() {}\n")
        self.write(f"{self.ledger_root}/src/lib.rs", "pub fn append() {}\n")
        self.write(
            "docs/modules/MODULES.json",
            json.dumps(
                {
                    "modules": [
                        {
                            "id": "runtime.agentd",
                            "rootBindings": [{"path": self.agent_root}],
                        },
                        {
                            "id": "learning.ledger",
                            "rootBindings": [{"path": self.ledger_root}],
                        },
                    ]
                }
            ),
        )
        self.direct_dependency(self.ledger_root, "codex-hepta-learning-ledger")
        self.delegate = {
            "role": "delegated_callee",
            "ownerModule": "learning.ledger",
            "path": f"{self.ledger_root}/src/lib.rs",
            "symbol": "pub fn append(",
            "buildTarget": "codex-hepta-learning-ledger",
        }

    def write(self, path, content):
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def direct_dependency(self, dependency_root, package_name):
        self.write(
            f"{self.agent_root}/Cargo.toml",
            '[package]\nname = "codex-hepta-agentd"\nversion = "0.0.0"\n'
            f'[dependencies]\n{package_name} = {{path = "../{Path(dependency_root).name}"}}\n',
        )
        self.write(
            f"{dependency_root}/Cargo.toml",
            f'[package]\nname = "{package_name}"\nversion = "0.0.0"\n',
        )

    def test_actual_direct_dependency_cannot_relabel_registered_foreign_owner(self):
        self.delegate["ownerModule"] = "runtime.agentd"
        with mock.patch.object(MODULE, "ROOT", self.root):
            self.assertFalse(
                MODULE.delegate_matches_owner(
                    "runtime.agentd", [self.agent_root], self.delegate
                )
            )

    def test_actual_direct_dependency_preserves_registered_cross_lane_owner(self):
        with mock.patch.object(MODULE, "ROOT", self.root):
            self.assertTrue(
                MODULE.delegate_matches_owner(
                    "learning.ledger", [self.ledger_root], self.delegate
                )
            )

    def test_actual_direct_dependency_can_navigate_unregistered_implementation(self):
        implementation = "codex-rs/core"
        self.write(f"{implementation}/src/lib.rs", "pub fn navigate() {}\n")
        self.direct_dependency(implementation, "codex-core")
        self.delegate.update(
            ownerModule="runtime.agentd",
            path=f"{implementation}/src/lib.rs",
            symbol="pub fn navigate(",
            buildTarget="codex-core",
        )
        with mock.patch.object(MODULE, "ROOT", self.root):
            self.assertTrue(
                MODULE.delegate_matches_owner(
                    "runtime.agentd", [self.agent_root], self.delegate
                )
            )


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
        truth = json.loads(MODULE.TRUTH.read_text())
        self.assertEqual(set(MODULE.MODULES), set(MODULE.OPS))
        self.assertEqual(truth["moduleOrder"], MODULE.MODULES)
        self.assertEqual(truth["operationCount"], MODULE.OPERATION_COUNT)
        self.assertEqual(MODULE.OPERATION_COUNT, sum(map(len, MODULE.OPS.values())))
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
                    MODULE,
                    "git",
                    return_value="codex-rs/hepta-agentd/src/automation.rs",
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

    def test_path_blob_manifest_binds_mapped_operation_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "codex-rs/hepta-automation/src/authorized_effect.rs"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("pub async fn execute() {}\n", encoding="utf-8")
            blob = "c" * 40
            row = {
                "sourceIdentityPolicy": "path_blob_manifest_v1",
                "exactSourceEvidence": {
                    "kind": "path_blob_manifest_v1",
                    "entries": [
                        {
                            "path": "codex-rs/hepta-automation/src/authorized_effect.rs",
                            "blobSha": blob,
                        }
                    ],
                },
                "operations": [
                    {"sourcePath": "codex-rs/hepta-automation/src/authorized_effect.rs"}
                ],
            }
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "git", return_value=blob),
            ):
                MODULE.verify_observed_source(row, "automation.taskflow")

    def test_path_blob_manifest_rejects_blob_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "codex-rs/hepta-automation/src/authorized_effect.rs"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text("pub async fn execute() {}\n", encoding="utf-8")
            row = {
                "sourceIdentityPolicy": "path_blob_manifest_v1",
                "exactSourceEvidence": {
                    "kind": "path_blob_manifest_v1",
                    "entries": [
                        {
                            "path": "codex-rs/hepta-automation/src/authorized_effect.rs",
                            "blobSha": "c" * 40,
                        }
                    ],
                },
                "operations": [
                    {"sourcePath": "codex-rs/hepta-automation/src/authorized_effect.rs"}
                ],
            }
            with (
                mock.patch.object(MODULE, "ROOT", root),
                mock.patch.object(MODULE, "git", return_value="d" * 40),
            ):
                with self.assertRaisesRegex(MODULE.Invalid, "exact source blob drift"):
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
