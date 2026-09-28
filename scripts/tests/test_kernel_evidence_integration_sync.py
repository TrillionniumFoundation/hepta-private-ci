"""Real-Git regressions for the integration inventory and included-source map."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import kernel_evidence_integration_sync as sync


class IntegrationBindingTests(unittest.TestCase):
    REQUIRED = (
        "codex-rs/hepta-agentd/src/client.rs",
        "codex-rs/hepta-agentd/src/config.rs",
        "codex-rs/hepta-agentd/src/runtime.rs",
        "codex-rs/hepta-agentd/src/evidence_host.rs",
        "codex-rs/hepta-agentd/src/evidence_production.rs",
        "codex-rs/hepta-agentd/src/evidence_production_checks.rs",
        "codex-rs/hepta-agent-protocol/src/evidence.rs",
    )
    PARENT = "codex-rs/hepta-agentd/src/evidence_production.rs"
    CHECKS = "codex-rs/hepta-agentd/src/evidence_production_checks.rs"
    MARKER = "kernel.evidence recovery_required"

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run_git("init", "-q")
        self.run_git("config", "user.name", "Inventory fixture")
        self.run_git("config", "user.email", "fixture@example.invalid")
        for path in self.REQUIRED:
            self.write(path, "// fixture\n")
        self.write(self.PARENT, 'include!("evidence_production_checks.rs");\n')
        self.write(self.CHECKS, f'fn error() {{ println!("{self.MARKER}"); }}\n')
        self.mapping = (
            self.root / "docs/modules/kernel.evidence/IMPLEMENTATION_MAP.json"
        )
        self.mapping.parent.mkdir(parents=True)
        self.mapping.write_text(
            json.dumps(
                {
                    "sourceBase": {},
                    "productionImplementation": False,
                    "claimBoundary": {
                        key: False
                        for key in (
                            "productionImplementation",
                            "productExecutionProved",
                            "independentAcceptance",
                            "activation",
                            "release",
                        )
                    },
                    "productionWriterBindings": [
                        {"sourcePath": self.PARENT, "mustContain": self.MARKER}
                    ],
                    "operations": [],
                }
            )
        )
        self.anchor = self.commit()
        self.addCleanup(patch.stopall)
        patch.object(sync, "ROOT", self.root).start()
        patch.object(sync, "MAP", self.mapping).start()

    def run_git(self, *args: str) -> str:
        return subprocess.check_output(
            ["git", *args], cwd=self.root, text=True, stderr=subprocess.PIPE
        ).strip()

    def write(self, path: str, content: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit(self) -> str:
        self.run_git("add", "--all")
        self.run_git("commit", "-q", "-m", "fixture")
        return self.run_git("rev-parse", "HEAD")

    def test_inventory_binds_mode_routing_protocol_and_setup(self) -> None:
        additional = (
            "codex-rs/hepta-agent-protocol/src/lib.rs",
            "codex-rs/state/Cargo.toml",
            ".github/actions/setup-ci/action.yml",
        )
        for path in additional:
            self.write(path, "fixture\n")
        self.write("codex-rs/unrelated/src/evidence_unrelated.rs", "unrelated\n")
        anchor = self.commit()
        expected = sorted((*self.REQUIRED, *additional))
        self.assertEqual(sync.source_inventory(anchor), expected)

    def test_deleted_product_paths_cannot_disappear_from_inventory(self) -> None:
        for path in self.REQUIRED:
            with self.subTest(path=path):
                original = (self.root / path).read_text()
                (self.root / path).unlink()
                missing_anchor = self.commit()
                # Restoring only the worktree must not repair the recorded tree.
                self.write(path, original)
                with self.assertRaisesRegex(ValueError, "lacks product admission"):
                    sync.source_inventory(missing_anchor)
                self.commit()

    def test_map_binds_included_error_source_without_advancing_gates(self) -> None:
        sync.bind_map(self.anchor)
        actual = json.loads(self.mapping.read_text())
        self.assertEqual(
            actual["productionWriterBindings"],
            [{"sourcePath": self.CHECKS, "mustContain": self.MARKER}],
        )
        self.assertEqual(
            actual["sourceBase"],
            {
                "commit": self.anchor,
                "tree": self.run_git("rev-parse", f"{self.anchor}^{{tree}}"),
            },
        )
        self.assertFalse(actual["productionImplementation"])
        self.assertFalse(any(actual["claimBoundary"].values()))
        before = self.mapping.read_bytes()
        sync.bind_map(self.anchor)
        self.assertEqual(before, self.mapping.read_bytes())

    def test_uncompiled_checks_cannot_satisfy_the_map(self) -> None:
        self.write(self.PARENT, "// no compiled checks\n")
        anchor = self.commit()
        with self.assertRaisesRegex(ValueError, "no longer includes"):
            sync.bind_map(anchor)

    def test_worktree_marker_cannot_substitute_for_anchor(self) -> None:
        self.write(self.CHECKS, "// marker is absent\n")
        anchor = self.commit()
        self.write(self.CHECKS, f"// {self.MARKER}\n")
        with self.assertRaisesRegex(ValueError, "lost their fail-closed"):
            sync.bind_map(anchor)

    def test_duplicate_or_foreign_writer_binding_is_rejected(self) -> None:
        baseline = json.loads(self.mapping.read_text())
        for bindings in (
            baseline["productionWriterBindings"] * 2,
            [
                {
                    "sourcePath": "codex-rs/unrelated/src/lib.rs",
                    "mustContain": self.MARKER,
                }
            ],
        ):
            with self.subTest(bindings=bindings):
                altered = dict(baseline, productionWriterBindings=bindings)
                self.mapping.write_text(json.dumps(altered))
                with self.assertRaisesRegex(ValueError, "ambiguous production"):
                    sync.bind_map(self.anchor)


if __name__ == "__main__":
    unittest.main()
