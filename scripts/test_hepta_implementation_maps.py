#!/usr/bin/env python3

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/hepta-implementation-maps.py"


class ExactHeadImplementationEvidenceTests(unittest.TestCase):
    def test_compact_dossier_parser_keeps_shared_source_entrypoints(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        try:
            import runpy

            namespace = runpy.run_path(str(SCRIPT))
        finally:
            sys.path.pop(0)

        entries = namespace["parse_entrypoints"]("compact.engine")
        symbols = {entry["nativeSymbol"] for entry in entries}
        self.assertEqual(symbols, {"build_qualified_candidate", "prove_compaction"})
        self.assertEqual(
            {entry["sourcePath"] for entry in entries},
            {"codex-rs/hepta-compact-engine/src/qualified.rs"},
        )

    def test_evidence_binds_current_head_and_discovers_compact_tests(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "implementation-evidence.json"
            subprocess.run(
                [sys.executable, str(SCRIPT), "evidence", "--output", str(output)],
                cwd=ROOT,
                check=True,
                text=True,
                capture_output=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
            head = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip()
            tree = subprocess.check_output(
                ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
            ).strip()
            self.assertEqual(payload["sourceBase"], {"commit": head, "tree": tree})
            compact = next(
                row for row in payload["modules"] if row["module"] == "compact.engine"
            )
            tests = {
                test
                for operation in compact["operations"]
                for test in operation.get("tests", [])
            }
            self.assertTrue(
                any(
                    test.endswith(
                        "qualified_tests.rs::canonical_path_rejects_live_tombstone_live_resurrection"
                    )
                    for test in tests
                ),
                tests,
            )
            self.assertTrue(
                any(
                    "proof_requires_host_trusted_ed25519_evaluator" in test
                    for test in tests
                ),
                tests,
            )
            self.assertTrue(
                any("large_input_remains_deterministic_and_bounded" in test for test in tests),
                tests,
            )
            integration_tests = set(compact.get("integrationTests", []))
            self.assertTrue(
                any(
                    test.endswith(
                        "production_writer_host_tests.rs::"
                        "agentd_compaction_full_path_publishes_resolves_and_re_admits"
                    )
                    for test in integration_tests
                ),
                integration_tests,
            )
            self.assertTrue(
                any(
                    test.endswith(
                        "qualified_compact_store_tests.rs::"
                        "canonical_checkpoint_payload_and_proof_survive_reopen"
                    )
                    for test in integration_tests
                ),
                integration_tests,
            )
            self.assertTrue(integration_tests.issubset(set(payload["testInventory"])))


if __name__ == "__main__":
    unittest.main()
