"""Exercise the actual synthetic-merge action with its caller's history depth."""

import os
from pathlib import Path
import re
import subprocess
import tempfile
import textwrap
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == "posix", "Ubuntu workflow shell integration")
class ProductUiMergeCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.origin = self.root / "origin"
        self.git(self.root, "init", "-q", "-b", "main", str(self.origin))
        (self.origin / "base.txt").write_text("base\n")
        self.git(self.origin, "add", "base.txt")
        self.git(self.origin, "commit", "-qm", "base")
        self.base = self.git(self.origin, "rev-parse", "HEAD").strip()
        self.git(self.origin, "switch", "-qc", "source")
        (self.origin / "ui.txt").write_text("source\n")
        self.git(self.origin, "add", "ui.txt")
        self.git(self.origin, "commit", "-qm", "source")
        self.source = self.git(self.origin, "rev-parse", "HEAD").strip()
        action = (ROOT / ".github/actions/hepta-synthetic-merge/action.yml").read_text()
        self.script = textwrap.dedent(action.split("run: |\n", 1)[1])

    @staticmethod
    def git(cwd, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "user.name=fixture",
                "-c",
                "user.email=fixture@invalid",
                *args,
            ],
            cwd=cwd,
            text=True,
            stderr=subprocess.PIPE,
        )

    def merge_with_depth(self, depth, name):
        checkout = self.root / name
        depth_args = ["--depth", str(depth)] if depth else []
        self.git(
            self.root,
            "clone",
            "--quiet",
            *depth_args,
            "--branch",
            "source",
            self.origin.as_uri(),
            str(checkout),
        )
        env = dict(
            os.environ,
            BASE_SHA=self.base,
            SOURCE_SHA=self.source,
            PR_NUMBER="1",
            AUTHOR_NAME="fixture",
            AUTHOR_EMAIL="fixture@invalid",
            MESSAGE="fixture merge",
            GITHUB_OUTPUT=str(self.root / f"{name}-outputs"),
        )
        return checkout, subprocess.run(
            ["bash", "-c", self.script],
            cwd=checkout,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_shallow_checkout_cannot_supply_the_immutable_base(self):
        _, result = self.merge_with_depth(1, "shallow")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(self.base, result.stderr)

    def test_product_caller_history_constructs_exact_two_parent_source_tree(self):
        workflow = (ROOT / ".github/workflows/ui-product-foundation.yml").read_text()
        checkout = workflow.split("- uses: actions/checkout@", 1)[1].split(
            "      - ", 1
        )[0]
        depth = re.search(r"fetch-depth:\s*(\d+)", checkout)
        directory, result = self.merge_with_depth(
            int(depth.group(1)) if depth else 1, "caller"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        merged = self.git(directory, "rev-parse", "HEAD").strip()
        self.assertEqual(
            self.git(directory, "rev-list", "--parents", "-n", "1", "HEAD").strip(),
            f"{merged} {self.base} {self.source}",
        )
        self.assertEqual(
            self.git(directory, "rev-parse", "HEAD^{tree}"),
            self.git(self.origin, "rev-parse", "source^{tree}"),
        )


class ProductGatewayWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = (
            ROOT / ".github/workflows/ui-product-foundation.yml"
        ).read_text()

    def test_actual_entry_runs_between_default_and_fixture_renderers(self):
        steps = [
            "- id: default_browser",
            "- id: product_gateway_build",
            "- id: product_gateway_transport_tests",
            "- id: product_gateway_browser",
            "- id: fixture_build",
        ]
        positions = [self.workflow.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("--config=playwright.product.config.mjs", self.workflow)
        self.assertIn("product-status-results.json", self.workflow)
        self.assertIn("ui_product_preview.hepta-build.json", self.workflow)

    def test_backend_pin_is_command_scoped_and_event_pair_unchanged(self):
        self.assertIn("RUSTUP_TOOLCHAIN: 1.95.0", self.workflow)
        self.assertIn(
            "RUSTUP_TOOLCHAIN=1.96.0 python3 apps/hepta-control-ui/tools/build-product-preview.py",
            self.workflow,
        )
        self.assertNotIn('RUSTUP_TOOLCHAIN=1.96.0" >>', self.workflow)
        self.assertIn(
            "base-sha: ${{ github.event.pull_request.base.sha }}", self.workflow
        )
        self.assertIn(
            "source-sha: ${{ github.event.pull_request.head.sha }}", self.workflow
        )
        self.assertIn("contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)

    def test_gateway_dependency_closure_and_embedded_inputs_have_triggers(self):
        from hepta_ci_dependencies import graph, matches

        revision = subprocess.check_output(
            ["git", "--no-replace-objects", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dependency_graph = graph(ROOT, revision)
        self.assertFalse(dependency_graph.conservative)
        gateway = "codex-hepta-native-gateway"
        closure = {gateway}
        while True:
            expanded = closure | {
                dependency
                for dependency, consumer, dev_only in dependency_graph.edges
                if consumer in closure and (not dev_only or consumer == gateway)
            }
            if expanded == closure:
                break
            closure = expanded
        self.assertFalse(closure & dependency_graph.opaque_input_consumers)
        patterns = re.findall(r"^      - ([^\n]+)$", self.workflow, re.MULTILINE)
        for directory, owner in dependency_graph.owners.items():
            if owner in closure:
                self.assertIn(directory + "/**", patterns, owner)
        for path, owner in dependency_graph.external_inputs:
            if owner in closure:
                self.assertTrue(
                    any(matches(path, pattern) for pattern in patterns), path
                )

    def test_transport_command_executes_the_authored_module_with_bound_identity(self):
        block = self.workflow.split("- id: product_gateway_transport_tests", 1)[
            1
        ].split("- id: product_gateway_browser", 1)[0]
        for expected in (
            "RUSTUP_TOOLCHAIN: 1.96.0",
            "SOURCE_SHA: ${{ github.event.pull_request.head.sha }}",
            "BASE_SHA: ${{ github.event.pull_request.base.sha }}",
            'TESTED_SHA="$(git rev-parse HEAD)" python3 scripts/hepta_ci_exec.py',
            "HEPTA_CI_LANE: ${{ matrix.lane }}",
            "scripts/hepta_ci_exec.py",
            "--minimum-tests 9",
            "just test --locked -p codex-hepta-native-gateway --lib",
            "test(http_transport::tests::)",
        ):
            self.assertIn(expected, block)
        transport = (
            ROOT / "codex-rs/hepta-native-gateway/src/http_transport.rs"
        ).read_text()
        self.assertEqual(
            len(re.findall(r"#\[tokio::test(?:\([^\n]*\))?\]", transport)), 9
        )
        self.assertIn(
            "mid_transfer_writer_error_reports_exact_accepted_bytes", transport
        )
        self.assertIn("gateway-transport-${{ matrix.lane }}.json*", self.workflow)

    def test_official_tools_do_not_dirty_the_source_checkout(self):
        self.assertNotIn(".tmp/ui-official-tools-robrix", self.workflow)
        self.assertIn("${{ runner.temp }}/ui-official-tools-robrix", self.workflow)
        self.assertIn("ui-official-tools-v3-runner-temp-", self.workflow)

    def test_gateway_changes_trigger_source_and_merge_evidence(self):
        for path in (
            "codex-rs/hepta-native-gateway/**",
            "codex-rs/Cargo.toml",
            "codex-rs/Cargo.lock",
            "codex-rs/rust-toolchain.toml",
        ):
            self.assertIn("      - " + path, self.workflow)
        self.assertIn("lane: [source-head, base-merge]", self.workflow)


if __name__ == "__main__":
    unittest.main()
