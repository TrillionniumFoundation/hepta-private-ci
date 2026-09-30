from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/channel_matrix_pair_acceptance.py"
spec = importlib.util.spec_from_file_location("channel_matrix_pair_acceptance", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class PairAcceptanceTests(unittest.TestCase):
    def write_json(self, path: Path, row: dict) -> None:
        path.write_text(json.dumps(row, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def digest(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def lane(self, root: Path, lane: str, source_sha: str, base_sha: str, tested_sha: str, tree: str) -> None:
        root.mkdir()
        source = {
            "schema": "hepta.channel-matrix-source-snapshot.v1",
            "lane": lane,
            "sourceSha": source_sha,
            "baseSha": base_sha,
            "testedSha": tested_sha,
            "testedTree": tree,
            "files": [{"path": "docs/modules/channel.matrix/QUALIFICATION_SCENARIOS.json", "sha256": "a" * 64}],
        }
        self.write_json(root / "source.json", source)
        self.write_json(root / "source-after.json", source)
        self.write_json(
            root / "candidate.json",
            {
                "schema": "hepta.channel-matrix-candidate-receipt.v1",
                "status": "PASS_CHANNEL_MATRIX_CANDIDATE_BINDING",
                "candidate": {"commit": tested_sha, "tree": tree},
                "authorityGranted": False,
            },
        )
        states = {
            "source_navigation": "passed",
            "compilation": "passed",
            "native_tests": "passed",
            "strict_lint": "passed",
            "formatting": "passed",
            "target_qualification": "not_proved",
            "independent_acceptance": "not_proved",
        }
        self.write_json(
            root / "status.json",
            {
                "schema": "hepta.channel-matrix-evidence-status.v2",
                "candidate": {"commit": tested_sha, "tree": tree, "lane": lane},
                "states": states,
                "activation": False,
                "release": False,
                "authority_granted": False,
            },
        )
        scenarios = []
        for identity in module.SCENARIOS:
            scenarios.append(
                {
                    "id": identity,
                    "candidate": {"commit": tested_sha, "tree": tree},
                    "native_required": True,
                    "native_fixture_result": "passed",
                    "tests": [],
                    "external_gates": ["target"] if identity == "MATRIX-Q12" else [],
                    "external_qualification": "not_proved" if identity == "MATRIX-Q12" else "not_applicable",
                }
            )
        self.write_json(
            root / "scenario-ledger.json",
            {
                "schema": "hepta.channel-matrix-scenario-ledger.v2",
                "candidate": {"commit": tested_sha, "tree": tree},
                "lane": lane,
                "registry_sha256": "b" * 64,
                "native_completion": "passed",
                "native_blockers": [],
                "external_gates_remaining": ["target"],
                "scenarios": scenarios,
                "independent_acceptance": False,
                "activation": False,
                "release": False,
                "authority_granted": False,
            },
        )
        required = [
            "candidate.json",
            "source.json",
            "source-after.json",
            "status.json",
            "scenario-ledger.json",
            "focused-tests.junit.xml",
        ]
        (root / "focused-tests.junit.xml").write_text("<testsuites/>", encoding="utf-8")
        for label in ("compile", "focused-tests", "clippy", "format"):
            (root / f"{label}.log").write_text("ok\n", encoding="utf-8")
            self.write_json(root / f"{label}.command.json", {"schema": "fixture"})
            required.extend((f"{label}.log", f"{label}.command.json"))
        files = []
        for name in required:
            path = root / name
            files.append({"path": name, "bytes": path.stat().st_size, "sha256": self.digest(path)})
        self.write_json(
            root / "manifest.json",
            {
                "schema": "hepta.channel-matrix-artifact-manifest.v2",
                "runnerReportedStatus": "success",
                "files": files,
                "claims": {
                    "focusedCommandsPassed": True,
                    "homeserverQualified": False,
                    "independentAcceptance": False,
                    "activation": False,
                    "release": False,
                    "authorityGranted": False,
                },
            },
        )

    def pair(self, temp: Path) -> tuple[Path, Path]:
        source_sha = "1" * 40
        base_sha = "2" * 40
        source = temp / "source"
        merge = temp / "merge"
        self.lane(source, "source-head", source_sha, base_sha, source_sha, "3" * 40)
        self.lane(merge, "base-merge", source_sha, base_sha, "4" * 40, "5" * 40)
        return source, merge

    def test_valid_pair_retains_external_denials(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, merge = self.pair(Path(raw))
            row = module.paired(source, merge)
            self.assertTrue(row["allRepositoryControlledScenariosPassed"])
            self.assertEqual(row["targetQualification"], "not_proved")
            self.assertFalse(row["activation"])
            self.assertFalse(row["release"])

    def test_missing_scenario_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, merge = self.pair(Path(raw))
            ledger = json.loads((merge / "scenario-ledger.json").read_text())
            ledger["scenarios"].pop()
            self.write_json(merge / "scenario-ledger.json", ledger)
            manifest = json.loads((merge / "manifest.json").read_text())
            for row in manifest["files"]:
                if row["path"] == "scenario-ledger.json":
                    row["bytes"] = (merge / "scenario-ledger.json").stat().st_size
                    row["sha256"] = self.digest(merge / "scenario-ledger.json")
            self.write_json(merge / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "scenario inventory"):
                module.paired(source, merge)

    def test_mixed_source_identity_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, merge = self.pair(Path(raw))
            source_row = json.loads((merge / "source.json").read_text())
            source_row["sourceSha"] = "9" * 40
            self.write_json(merge / "source.json", source_row)
            self.write_json(merge / "source-after.json", source_row)
            for name in ("source.json", "source-after.json"):
                manifest = json.loads((merge / "manifest.json").read_text())
                for row in manifest["files"]:
                    if row["path"] == name:
                        row["bytes"] = (merge / name).stat().st_size
                        row["sha256"] = self.digest(merge / name)
                self.write_json(merge / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "one source/base"):
                module.paired(source, merge)

    def test_local_status_cannot_claim_target_qualification(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            source, merge = self.pair(Path(raw))
            status = json.loads((source / "status.json").read_text())
            status["states"]["target_qualification"] = "passed"
            self.write_json(source / "status.json", status)
            manifest = json.loads((source / "manifest.json").read_text())
            for row in manifest["files"]:
                if row["path"] == "status.json":
                    row["bytes"] = (source / "status.json").stat().st_size
                    row["sha256"] = self.digest(source / "status.json")
            self.write_json(source / "manifest.json", manifest)
            with self.assertRaisesRegex(ValueError, "external qualification"):
                module.paired(source, merge)


if __name__ == "__main__":
    unittest.main()
