#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_vectors(root: Path) -> None:
    v1 = root / "qualification/cognitive-types-v1"
    v2 = root / "qualification/cognitive-types-v2"
    v1.mkdir(parents=True)
    v2.mkdir(parents=True)
    (v1 / "bound_vector.json").write_text(
        json.dumps(
            {
                "contract": "ModalitySpanRefV1",
                "schema": "hepta.hnmf.modality-span-ref.v1",
                "schemaVersion": 1,
                "payload": {"spanId": "span:1"},
            }
        ),
        encoding="utf-8",
    )
    (v1 / "negative-vectors.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "contract": "RecallPacketV1",
                        "wire": '{"contract":"RecallPacketV1"}',
                    },
                    {
                        "contract": "MemoryEventV1",
                        "wire": '{"contract":"MemoryEventV1"}',
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (v2 / "negative-vectors.json").write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "contract": "SharedExperienceSnapshotV2",
                        "wire": '{"contract":"SharedExperienceSnapshotV2"}',
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


class CorpusTests(unittest.TestCase):
    def test_target_corpora_are_deterministic_nonempty_and_receipt_identical(self) -> None:
        corpus_module = load("prepare_fuzz_corpus")
        runner_module = load("run_fuzz_campaign")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_vectors(root)
            corpus_module.ROOT = root
            first = corpus_module.build(root / "corpus")
            second = corpus_module.build(root / "corpus")
            self.assertEqual(first, second)
            self.assertEqual(tuple(first["targets"]), corpus_module.TARGETS)
            for target in corpus_module.TARGETS:
                row = first["targets"][target]
                digest, count, total = runner_module._directory_digest(
                    root / "corpus" / target
                )
                self.assertGreater(row["seedCount"], 0)
                self.assertEqual(row["seedCount"], count)
                self.assertEqual(row["corpusBytes"], total)
                self.assertEqual(row["corpusSha256"], digest)
                self.assertEqual(len(row["corpusSha256"]), 64)

    def test_unknown_contract_only_feeds_grammar(self) -> None:
        module = load("prepare_fuzz_corpus")
        self.assertEqual(module._targets_for("UnknownV9"), {"canonical_json_grammar"})


class SourceCoverageTests(unittest.TestCase):
    def test_campaign_registry_matches_cargo_bins(self) -> None:
        module = load("run_fuzz_campaign")
        manifest = (
            ROOT / "codex-rs/hepta-cognitive-types/fuzz/Cargo.toml"
        ).read_text(encoding="utf-8")
        for target in module.TARGETS:
            self.assertIn(f'name = "{target}"', manifest)
            self.assertIn(f'path = "fuzz_targets/{target}.rs"', manifest)

    def test_consumer_handoff_exercises_all_registered_consumers(self) -> None:
        source = (
            ROOT
            / "codex-rs/hepta-cognitive-types/fuzz/fuzz_targets/consumer_handoff.rs"
        ).read_text(encoding="utf-8")
        for variant in (
            "CognitiveRead",
            "CognitiveStore",
            "MemoryRetrieval",
            "CompactEngine",
            "IntelligenceControl",
        ):
            self.assertIn(f"CanonicalConsumerV1::{variant}", source)
        self.assertIn("validate_consumer_semantic_identity_v1", source)
        self.assertIn("bind_prepared_memory_event_consumer_v1", source)
        self.assertIn("bind_prepared_recall_packet_consumer_v1", source)
        self.assertIn("bind_prepared_forget_receipt_consumer_v1", source)

    def test_workflow_requires_complete_five_target_aggregate(self) -> None:
        source = (
            ROOT / ".github/workflows/cognitive-types-fuzz-campaigns.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("verify_fuzz_campaign_receipts.py", source)
        self.assertIn("actions/download-artifact@", source)
        self.assertIn("name: aggregate", source)
        self.assertIn("needs: [verifier, campaign]", source)


class ReceiptParserTests(unittest.TestCase):
    def test_parses_progress_and_final_execution_count(self) -> None:
        module = load("run_fuzz_campaign")
        executions, coverage, features = module._parse_stats(
            "#123 pulse cov: 45 ft: 67\n"
            "stat::number_of_executed_units: 456\n"
        )
        self.assertEqual(executions, 456)
        self.assertEqual(coverage, 45)
        self.assertEqual(features, 67)

    def test_bounded_log_records_full_digest(self) -> None:
        module = load("run_fuzz_campaign")
        data = b"x" * (module.MAX_LOG_BYTES + 1)
        text, truncated, digest = module._bounded(data)
        self.assertTrue(truncated)
        self.assertEqual(len(text), module.MAX_LOG_BYTES)
        self.assertEqual(len(digest), 64)


class AggregateVerifierTests(unittest.TestCase):
    def test_complete_matrix_verifies_and_missing_target_rejects(self) -> None:
        module = load("verify_fuzz_campaign_receipts")
        source = "a" * 40
        tree = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for target in module.TARGETS:
                artifact = root / f"cognitive-types-fuzz-{target}-{source}"
                artifact.mkdir()
                stdout = b"stdout"
                stderr = b"stderr"
                lock = b"lock"
                (artifact / "stdout.log").write_bytes(stdout)
                (artifact / "stderr.log").write_bytes(stderr)
                (artifact / "resolved-Cargo.lock").write_bytes(lock)
                receipt = {
                    "schema": "hepta.cognitive-types.fuzz-campaign-receipt.v1",
                    "schemaVersion": 1,
                    "campaignClass": "smoke",
                    "target": target,
                    "sourceCommit": source,
                    "sourceTree": tree,
                    "sourceCleanBefore": True,
                    "sourceCleanAfter": True,
                    "expectedSourceCommit": source,
                    "corpusSha256": "c" * 64,
                    "seedCount": 1,
                    "corpusBytes": 1,
                    "configuredSeconds": 60,
                    "configuredRssLimitMb": 2048,
                    "startedAtUnixSeconds": 1,
                    "completedAtUnixSeconds": 2,
                    "elapsedNanoseconds": "1",
                    "executions": 1,
                    "coverageEdges": 1,
                    "featureCount": 1,
                    "peakRssRaw": 1,
                    "peakRssBytesBestEffort": 1024,
                    "exitCode": 0,
                    "timedOut": False,
                    "resolvedCargoLockSha256": hashlib.sha256(lock).hexdigest(),
                    "stdoutSha256": hashlib.sha256(stdout).hexdigest(),
                    "stderrSha256": hashlib.sha256(stderr).hexdigest(),
                    "stdoutTruncated": False,
                    "stderrTruncated": False,
                    "crashes": [],
                    "toolchain": {
                        "cargo": "cargo",
                        "rustc": "rustc",
                        "cargoFuzz": "cargo-fuzz",
                        "python": "python",
                        "platform": "linux",
                    },
                    "command": [
                        "/cargo",
                        "fuzz",
                        "run",
                        target,
                        "/corpus",
                        "--",
                        "-max_total_time=60",
                        "-rss_limit_mb=2048",
                        "-artifact_prefix=/artifacts/",
                        "-print_final_stats=1",
                        "-reload=0",
                    ],
                    "passed": True,
                    "productionAuthority": False,
                    "activationAuthority": False,
                    "releaseAuthority": False,
                }
                data = (
                    json.dumps(
                        receipt,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                    )
                    + "\n"
                ).encode("utf-8")
                (artifact / "receipt.json").write_bytes(data)
                digest = hashlib.sha256(data).hexdigest()
                (artifact / "receipt.sha256").write_text(
                    f"{digest}  receipt.json\n",
                    encoding="ascii",
                )
            report = module.verify_matrix(root, source, "smoke", 60, 2048)
            self.assertTrue(report["qualificationPassed"])
            self.assertEqual(len(report["targets"]), len(module.TARGETS))
            missing = root / f"cognitive-types-fuzz-{module.TARGETS[-1]}-{source}"
            for item in missing.iterdir():
                item.unlink()
            missing.rmdir()
            with self.assertRaises(module.EvidenceError):
                module.verify_matrix(root, source, "smoke", 60, 2048)


if __name__ == "__main__":
    unittest.main()
