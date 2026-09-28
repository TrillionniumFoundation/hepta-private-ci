import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MODULE_PATH = ROOT / "scripts" / "runtime_codex_target_host_evidence.py"
SPEC = importlib.util.spec_from_file_location("runtime_codex_target_host_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class TargetHostEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = "a" * 40
        self.tree = "b" * 40
        self.iterations = module.MIN_CANARY_OPERATIONS
        self._write_valid_fixture()

    def _write_valid_fixture(self) -> None:
        for index in range(1, self.iterations + 1):
            correlation = hashlib.sha256(f"correlation:{index}".encode()).hexdigest()
            write_json(
                self.root / "runs" / f"{index}.json",
                {
                    "source_sha": self.source,
                    "terminal_observed": True,
                    "codex_terminal_correlation_digest": correlation,
                    "boundary_status": "Succeeded",
                },
            )
            (self.root / "runs" / f"{index}.log").write_text("ok\n", encoding="utf-8")
            (self.root / "runs" / f"{index}.time").write_text(
                f"Elapsed (wall clock) time (h:mm:ss or m:ss): 0:{index:02d}.0\n"
                f"Maximum resident set size (kbytes): {4096 + index}\n",
                encoding="utf-8",
            )
        write_json(
            self.root / "provider-audit.json",
            {
                "schema": module.PROVIDER_AUDIT_SCHEMA,
                "schemaVersion": 1,
                "sourceSha": self.source,
                "physicalRequestCount": self.iterations,
                "duplicateRequestCount": 0,
                "replayedRequestCount": 0,
                "requestIds": [f"request:{index}" for index in range(1, self.iterations + 1)],
                "auditSha256": "d" * 64,
            },
        )
        (self.root / "binary.sha256").write_text(
            f"{'1' * 64}  /qualified/hepta-infer-worker\n", encoding="utf-8"
        )
        source_root = self.root / "source-qualification"
        source_root.mkdir(parents=True, exist_ok=True)
        for lane in ("source-head", "base-merge"):
            write_json(
                source_root / f"{lane}-receipt.json",
                {
                    "schema": "hepta.runtime-codex-source-qualification.v2",
                    "module": "runtime.codex",
                    "status": "passed",
                    "candidate": {"source": self.source, "lane": lane},
                    "claims": {
                        "sourceQualification": True,
                        "targetHostIdentityQualified": False,
                        "realProviderQualified": False,
                        "allCrashBoundariesQualified": False,
                        "independentAcceptance": False,
                        "activation": False,
                        "promotion": False,
                        "release": False,
                    },
                },
            )
            (source_root / f"{lane}-attestation.jsonl").write_text(
                "verified-attestation-bundle\n", encoding="utf-8"
            )
        for name, schema in module.EVIDENCE_SCHEMAS.items():
            write_json(
                self.root / name,
                {
                    "schema": schema,
                    "schemaVersion": 1,
                    "sourceSha": self.source,
                    "verified": True,
                    "subjectSha256": hashlib.sha256(name.encode()).hexdigest(),
                    "issuedAt": "2026-09-29T00:00:00Z",
                    "issuerId": f"independent:{name}",
                },
            )
        for scenario in module.FAULT_SCENARIOS:
            physical = 0 if scenario in module.ZERO_SEND_SCENARIOS else 1
            fresh = physical
            capacity = scenario not in module.ZERO_SEND_SCENARIOS
            outcome = {
                "provider-ack-loss": "indeterminate",
                "event-lag": "quarantined",
                "worker-kill-after-fence": "indeterminate",
                "worker-restart": "reconciled_terminal",
                "agentd-restart": "indeterminate",
                "revocation-advance-before-entry": "rejected_before_send",
                "duplicate-owner": "single_winner",
                "stale-revision": "rejected_before_send",
            }[scenario]
            value = {
                "schema": module.FAULT_SCHEMA,
                "schemaVersion": module.FAULT_SCHEMA_VERSION,
                "scenario": scenario,
                "sourceSha": self.source,
                "verified": True,
                "operationId": f"operation:{scenario}",
                "physicalRequestCount": physical,
                "freshFenceAckCount": fresh,
                "duplicateRequestCount": 0,
                "replayedRequestCount": 0,
                "abortAfterFenceAccepted": False,
                "ownerRevisionMonotonic": True,
                "unresolvedCapacityRetained": capacity,
                "durableOutcome": outcome,
                "journalSha256": "e" * 64,
                "providerAuditSha256": "f" * 64,
                "harnessSha256": "9" * 64,
                module.SCENARIO_FLAGS[scenario]: True,
            }
            write_json(self.root / "faults" / f"{scenario}.json", value)

    def args(self):
        return type(
            "Args",
            (),
            {
                "evidence_root": self.root,
                "source_sha": self.source,
                "source_tree": self.tree,
                "agent_id": "agent-1",
                "generation": 1,
                "model": "model-1",
                "iterations": self.iterations,
                "output": self.root / "manifest.json",
            },
        )()

    def change_fault(self, scenario: str, **fields: object) -> None:
        path = self.root / "faults" / f"{scenario}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value.update(fields)
        write_json(path, value)

    def test_source_receipt_plan_is_closed_world_for_crash_and_quarantine(self) -> None:
        from scripts import runtime_codex_receipt_v2 as receipt

        self.assertEqual(
            set(receipt.PLAN),
            {
                "runtime-binaries",
                "adapter",
                "durable-control",
                "agent-protocol",
                "agent-run-lifecycle",
                "worker-host",
                "target-host-evidence",
                "crash-matrix",
                "quarantine-protocol",
                "product-e2e",
                "model-only",
                "strict-lint",
                "formatting",
            },
        )
        self.assertEqual(receipt.PLAN["target-host-evidence"][0], 12)
        self.assertEqual(receipt.PLAN["crash-matrix"][0], 12)
        self.assertEqual(receipt.PLAN["quarantine-protocol"][0], 5)

    def test_parse_elapsed_supports_all_gnu_time_shapes(self) -> None:
        self.assertEqual(module.parse_elapsed("7.25"), 7.25)
        self.assertEqual(module.parse_elapsed("2:03.5"), 123.5)
        self.assertEqual(module.parse_elapsed("1:02:03.5"), 3723.5)
        for value in ("1:60", "1:60:00", "nan", "-1"):
            with self.subTest(value=value), self.assertRaises(module.EvidenceError):
                module.parse_elapsed(value)

    def test_manifest_requires_all_eight_faults_and_external_review_records(self) -> None:
        args = self.args()
        module.write_manifest(args)
        module.verify_manifest(args.output)
        manifest = json.loads(args.output.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["faultEvidence"]), set(module.FAULT_SCENARIOS))
        self.assertEqual(set(manifest["independentEvidence"]), set(module.EVIDENCE_SCHEMAS))
        self.assertEqual(
            set(manifest["repositorySourceQualification"]),
            {"source-head", "base-merge"},
        )
        self.assertEqual(manifest["iterations"], module.MIN_CANARY_OPERATIONS)
        self.assertEqual(manifest["latencySeconds"]["p50"], 15.5)
        self.assertTrue(manifest["claimBoundary"]["faultMatrixExecuted"])
        self.assertFalse(manifest["claimBoundary"]["independentAcceptance"])
        self.assertFalse(manifest["claimBoundary"]["release"])

    def test_iteration_floor_and_ceiling_fail_closed(self) -> None:
        args = self.args()
        for count in (module.MIN_CANARY_OPERATIONS - 1, module.MAX_CANARY_OPERATIONS + 1):
            with self.subTest(count=count):
                args.iterations = count
                with self.assertRaises(module.EvidenceError):
                    module.build_manifest(args)

    def test_replay_duplicate_and_post_fence_abort_are_rejected(self) -> None:
        for fields in (
            {"replayedRequestCount": 1},
            {"duplicateRequestCount": 1},
            {"abortAfterFenceAccepted": True},
            {"ownerRevisionMonotonic": False},
        ):
            with self.subTest(fields=fields):
                self._write_valid_fixture()
                self.change_fault("provider-ack-loss", **fields)
                with self.assertRaises(module.EvidenceError):
                    module.build_manifest(self.args())

    def test_pre_entry_scenarios_must_have_zero_send_and_release_capacity(self) -> None:
        self.change_fault(
            "revocation-advance-before-entry",
            physicalRequestCount=1,
            freshFenceAckCount=1,
        )
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())
        self._write_valid_fixture()
        self.change_fault("stale-revision", unresolvedCapacityRetained=True)
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())

    def test_duplicate_owner_requires_one_fresh_winner_and_one_send(self) -> None:
        self.change_fault("duplicate-owner", freshFenceAckCount=0)
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())

    def test_unique_terminal_correlations_are_required(self) -> None:
        first = json.loads((self.root / "runs" / "1.json").read_text(encoding="utf-8"))
        second = json.loads((self.root / "runs" / "2.json").read_text(encoding="utf-8"))
        second["codex_terminal_correlation_digest"] = first[
            "codex_terminal_correlation_digest"
        ]
        write_json(self.root / "runs" / "2.json", second)
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())

    def test_missing_review_record_and_source_drift_are_rejected(self) -> None:
        (self.root / "independent-acceptance.json").unlink()
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())
        self._write_valid_fixture()
        path = self.root / "host-identity.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["sourceSha"] = "c" * 40
        write_json(path, value)
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())

    def test_source_qualification_receipts_and_bundles_are_exact(self) -> None:
        receipt = self.root / "source-qualification" / "source-head-receipt.json"
        value = json.loads(receipt.read_text(encoding="utf-8"))
        value["candidate"]["source"] = "c" * 40
        write_json(receipt, value)
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())
        self._write_valid_fixture()
        (self.root / "source-qualification" / "base-merge-attestation.jsonl").unlink()
        with self.assertRaises(module.EvidenceError):
            module.build_manifest(self.args())

    def test_canonical_manifest_and_sidecar_are_both_required(self) -> None:
        args = self.args()
        module.write_manifest(args)
        manifest = json.loads(args.output.read_text(encoding="utf-8"))
        args.output.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        with self.assertRaises(module.EvidenceError):
            module.verify_manifest(args.output)
        args.output.write_bytes(module.canonical_bytes(manifest))
        args.output.with_suffix(".json.sha256").write_text(
            f"{'0' * 64}  manifest.json\n", encoding="utf-8"
        )
        with self.assertRaises(module.EvidenceError):
            module.verify_manifest(args.output)

    def test_duplicate_json_keys_are_rejected(self) -> None:
        path = self.root / "faults" / "provider-ack-loss.json"
        path.write_text('{"schema":"one","schema":"two"}', encoding="utf-8")
        with self.assertRaises(module.EvidenceError):
            module.load_json(path)


if __name__ == "__main__":
    unittest.main()
