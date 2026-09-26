import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "runtime_codex_target_host_evidence.py"
SPEC = importlib.util.spec_from_file_location("runtime_codex_target_host_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TargetHostEvidenceTests(unittest.TestCase):
    def test_parse_elapsed_supports_all_gnu_time_shapes(self) -> None:
        self.assertEqual(module.parse_elapsed("7.25"), 7.25)
        self.assertEqual(module.parse_elapsed("2:03.5"), 123.5)
        self.assertEqual(module.parse_elapsed("1:02:03.5"), 3723.5)
        with self.assertRaises(module.EvidenceError):
            module.parse_elapsed("1:60")
        with self.assertRaises(module.EvidenceError):
            module.parse_elapsed("1:60:00")

    def test_manifest_requires_faults_exact_sends_and_canonical_digest(self) -> None:
        source = "a" * 40
        tree = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index in range(1, 4):
                write_json(
                    root / "runs" / f"{index}.json",
                    {
                        "source_sha": source,
                        "terminal_observed": True,
                        "codex_terminal_correlation_digest": "c" * 64,
                        "boundary_status": "Succeeded",
                    },
                )
                (root / "runs" / f"{index}.log").write_text("ok\n", encoding="utf-8")
                (root / "runs" / f"{index}.time").write_text(
                    "Elapsed (wall clock) time (h:mm:ss or m:ss): 1:02.5\n"
                    "Maximum resident set size (kbytes): 4096\n",
                    encoding="utf-8",
                )
            write_json(
                root / "provider-audit.json",
                {
                    "schema": "hepta.runtime-codex-provider-audit.v1",
                    "sourceSha": source,
                    "physicalRequestCount": 3,
                    "duplicateRequestCount": 0,
                    "requestIds": ["one", "two", "three"],
                    "auditSha256": "d" * 64,
                },
            )
            for name, schema in module.EVIDENCE_SCHEMAS.items():
                write_json(
                    root / name,
                    {
                        "schema": schema,
                        "schemaVersion": 1,
                        "sourceSha": source,
                        "verified": True,
                        "subjectSha256": "e" * 64,
                        "issuedAt": "2026-09-26T00:00:00Z",
                    },
                )
            for scenario in module.FAULT_SCENARIOS:
                outcome = next(iter(module.FAULT_OUTCOMES[scenario]))
                write_json(
                    root / "faults" / f"{scenario}.json",
                    {
                        "schema": "hepta.runtime-codex-fault-evidence.v1",
                        "schemaVersion": 1,
                        "scenario": scenario,
                        "sourceSha": source,
                        "verified": True,
                        "physicalRequestCount": 1,
                        "duplicateRequestCount": 0,
                        "replayedRequestCount": 0,
                        "durableOutcome": outcome,
                        "operationId": f"operation:{scenario}",
                        "journalSha256": "f" * 64,
                        "restartObserved": scenario == "agentd-restart",
                    },
                )

            args = type(
                "Args",
                (),
                {
                    "evidence_root": root,
                    "source_sha": source,
                    "source_tree": tree,
                    "agent_id": "agent-1",
                    "generation": 1,
                    "model": "model-1",
                    "iterations": 3,
                    "output": root / "manifest.json",
                },
            )()
            module.write_manifest(args)
            module.verify_manifest(args.output)
            manifest = json.loads(args.output.read_text(encoding="utf-8"))
            self.assertEqual(manifest["latencySeconds"]["p50"], 62.5)
            self.assertTrue(manifest["claimBoundary"]["faultMatrixExecuted"])
            self.assertFalse(manifest["claimBoundary"]["release"])

            broken = root / "faults" / "provider-ack-loss.json"
            value = json.loads(broken.read_text(encoding="utf-8"))
            value["replayedRequestCount"] = 1
            write_json(broken, value)
            with self.assertRaises(module.EvidenceError):
                module.build_manifest(args)


if __name__ == "__main__":
    unittest.main()
