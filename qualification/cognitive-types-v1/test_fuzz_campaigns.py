#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import ModuleType

HERE = Path(__file__).resolve().parent


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CorpusTests(unittest.TestCase):
    def test_target_corpora_are_deterministic_and_nonempty(self) -> None:
        module = load("prepare_fuzz_corpus")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
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
            module.ROOT = root
            first = module.build(root / "corpus")
            second = module.build(root / "corpus")
            self.assertEqual(first, second)
            self.assertEqual(tuple(first["targets"]), module.TARGETS)
            for target in module.TARGETS:
                row = first["targets"][target]
                self.assertGreater(row["seedCount"], 0)
                self.assertEqual(len(row["corpusSha256"]), 64)

    def test_unknown_contract_only_feeds_grammar(self) -> None:
        module = load("prepare_fuzz_corpus")
        self.assertEqual(module._targets_for("UnknownV9"), {"canonical_json_grammar"})


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


if __name__ == "__main__":
    unittest.main()
