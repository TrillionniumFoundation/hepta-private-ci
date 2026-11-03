"""Guard the architecture browser suite's actual pinned native D-Bus prerequisite.

These controls check the exact hosted workflow wiring. The original native browser
suite and its real linked D-Bus identity execute separately on the Actions runner.
"""

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hepta-architecture-convergence.yml"
BUILDER = ROOT / "qualification/keyring-sync-provider/build_pinned_client.py"


class ArchitecturePinnedDBusPrerequisiteTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")
        cls.builder = BUILDER.read_text(encoding="utf-8")
        cls.step = cls.workflow.split(
            "      - name: Qualify pinned native D-Bus client "
            "for original browser semantics\n",
            1,
        )[1].split("\n      - ", 1)[0]

    def test_original_effects_browser_still_executes(self):
        self.assertIn(
            "cargo test --locked --manifest-path codex-rs/Cargo.toml "
            "-p codex-hepta-agentd browser_servo",
            self.workflow,
        )
        self.assertIn("python3 scripts/hepta_ci_exec.py", self.workflow)
        self.assertNotIn("continue-on-error: true", self.step)

    def test_actual_native_prerequisite_is_qualified_before_browser(self):
        self.assertLess(
            self.workflow.index("      - name: Prepare native prerequisites\n"),
            self.workflow.index("      - name: Qualify pinned native D-Bus client"),
        )
        self.assertLess(
            self.workflow.index("      - name: Qualify pinned native D-Bus client"),
            self.workflow.index(
                "      - name: Converged authority and browser semantics\n"
            ),
        )
        self.assertIn(
            "steps.scope.outputs.native == 'true' || "
            "steps.scope.outputs.effects == 'true'",
            self.workflow,
        )
        self.assertIn("steps.scope.outputs.effects == 'true'", self.step)

    def test_failure_is_terminal_and_receipt_is_retained(self):
        self.assertIn("set -euo pipefail", self.step)
        self.assertIn("build_pinned_client.py --output \"$client\"", self.step)
        self.assertIn("jq -er '.status'", self.step)
        self.assertIn('test -x "$client/native-identity"', self.step)
        self.assertIn("trap 'if [[ -f", self.step)
        self.assertNotIn("|| true", self.step)
        self.assertNotIn("continue-on-error", self.step)

    def test_exact_client_identity_is_bound_to_original_cargo(self):
        self.assertIn("PKG_CONFIG_PATH=%s", self.step)
        self.assertIn('>> "$GITHUB_ENV"', self.step)
        self.assertIn('pkg-config --modversion dbus-1', self.step)
        self.assertIn("1.16.2", self.step)
        self.assertIn(
            "0ba2a1a4b16afe7bceb2c07e9ce99a8c2c3508e5dec290dbb643384bd6beb7e2",
            self.builder,
        )
        self.assertIn('run([str(identity)])', self.builder)
        self.assertIn('receipt["status"] = "FAIL"', self.builder)


if __name__ == "__main__":
    unittest.main()
