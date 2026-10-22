"""Guard the exact-head NDU Rust CI trigger against silent input omissions.

These are source-level workflow contract checks, not native Rust evidence.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/hepta-ndu-portfolio-exact.yml"
RUST_TOOLCHAIN = ROOT / "codex-rs/rust-toolchain.toml"

DIRECT_NATIVE_INPUTS = {
    "codex-rs/hepta-ndu/**",
    "codex-rs/hepta-types/**",
    "codex-rs/hepta-contracts/**",
    "codex-rs/Cargo.toml",
    "codex-rs/Cargo.lock",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/.cargo/**",
    ".cargo/**",
    "codex-rs/rustfmt.toml",
    "rustfmt.toml",
    "qa/meta-network-scale/check_cell_codex_boundary.py",
    "qa/meta-network-scale/test_cell_codex_boundary.py",
    "qa/meta-network-scale/scale_matrix.py",
    "qa/meta-network-scale/test_scale_matrix.py",
    "docs/learning/CELL_EXECUTION_BENCHMARK_MATRIX.json",
    ".github/workflows/hepta-cell-codex-boundary.yml",
    ".github/workflows/hepta-p5-scale-evidence-exact.yml",
    "scripts/test_hepta_ndu_portfolio_ci.py",
    ".github/workflows/hepta-ndu-portfolio-exact.yml",
}


class NduPortfolioNativeWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_pull_request_scope_covers_native_dependency_inputs(self) -> None:
        self.assertIn("  pull_request:\n", self.workflow)
        self.assertIn("  workflow_dispatch:", self.workflow)
        trigger = self.workflow.split("  pull_request:\n", 1)[1].split(
            "  workflow_dispatch:", 1
        )[0]
        paths = set(re.findall(r'^\s{6}- "([^"]+)"\s*$', trigger, flags=re.MULTILINE))
        self.assertTrue(
            DIRECT_NATIVE_INPUTS.issubset(paths),
            f"missing native trigger paths: {sorted(DIRECT_NATIVE_INPUTS - paths)}",
        )
        self.assertFalse(any(path.startswith("!") for path in paths))

    def test_native_checks_are_exact_source_bound_and_fail_on_zero_tests(self) -> None:
        for required in (
            "github.event.pull_request.head.sha || github.sha",
            'test "$(git rev-parse HEAD)" = "$SOURCE_SHA"',
            "cargo fmt --manifest-path codex-rs/Cargo.toml",
            "cargo test --locked --manifest-path codex-rs/Cargo.toml",
            "cargo clippy --locked --manifest-path codex-rs/Cargo.toml",
            "grep -Eq 'test result: ok[.] [1-9][0-9]* passed; 0 failed;'",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.workflow)

    def test_native_compiler_version_matches_repository_pin(self) -> None:
        pin = RUST_TOOLCHAIN.read_text(encoding="utf-8")
        match = re.search(r'^channel\s*=\s*"([^"]+)"', pin, flags=re.MULTILINE)
        self.assertIsNotNone(match, "Rust toolchain channel must be pinned")
        self.assertIn(f'toolchain: "{match.group(1)}"', self.workflow)


if __name__ == "__main__":
    unittest.main()
