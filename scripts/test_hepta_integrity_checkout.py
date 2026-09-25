"""Credential hygiene is per checkout, never a decorative workflow token."""

import importlib.util
from pathlib import Path
import sys
import unittest

SPEC = importlib.util.spec_from_file_location(
    "hepta_integrity_checkout_subject",
    Path(__file__).with_name("hepta-repository-integrity.py"),
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

PERMISSIONS = "permissions:\n  contents: read\njobs:\n  check:\n    steps:\n"
CHECKOUT = "      - uses: actions/checkout@pinned\n"
SAFE = CHECKOUT + "        with:\n          persist-credentials: false\n"
PATH = ".github/workflows/fixture.yml"


class CheckoutCredentialTests(unittest.TestCase):
    def rules(self, text):
        return {item.rule for item in MODULE.scan_path(PATH, text)}

    def test_no_checkout_requires_no_irrelevant_credential_setting(self):
        self.assertEqual(
            self.rules(PERMISSIONS + "      - run: rustc --version\n"), set()
        )

    def test_default_checkout_credentials_are_rejected(self):
        self.assertIn(
            "missing-checkout-credential-opt-out", self.rules(PERMISSIONS + CHECKOUT)
        )

    def test_explicit_false_is_required_on_every_checkout(self):
        for steps in (SAFE + CHECKOUT, CHECKOUT + SAFE):
            with self.subTest(steps=steps):
                self.assertIn(
                    "missing-checkout-credential-opt-out",
                    self.rules(PERMISSIONS + steps),
                )
        self.assertEqual(self.rules(PERMISSIONS + SAFE + SAFE), set())

    def test_comment_and_other_step_settings_do_not_authorize_checkout(self):
        for suffix in (
            "        # persist-credentials: false\n",
            "      - run: echo ok\n        with:\n          persist-credentials: false\n",
            "        env:\n          persist-credentials: false\n",
        ):
            with self.subTest(suffix=suffix):
                self.assertIn(
                    "missing-checkout-credential-opt-out",
                    self.rules(PERMISSIONS + CHECKOUT + suffix),
                )

    def test_named_quoted_checkout_accepts_its_own_false_setting(self):
        text = "      - name: Read source\n        uses: 'actions/checkout@pinned'\n        with:\n          persist-credentials: false # scoped\n"
        self.assertEqual(self.rules(PERMISSIONS + text), set())

    def test_checkout_settings_may_precede_uses(self):
        text = "      - with:\n          persist-credentials: false\n        uses: actions/checkout@pinned\n"
        self.assertEqual(self.rules(PERMISSIONS + text), set())

    def test_comment_on_with_does_not_change_its_scope(self):
        self.assertEqual(
            self.rules(PERMISSIONS + SAFE.replace("with:", "with: # inputs")), set()
        )

    def test_scalar_text_is_not_a_checkout_step(self):
        text = "      - run: |\n          cat <<'EOF'\n          uses: actions/checkout@pinned\n          EOF\n"
        self.assertEqual(self.rules(PERMISSIONS + text), set())

    def test_nested_or_scalar_false_does_not_disable_credentials(self):
        for body in (
            "          note: |\n            persist-credentials: false\n",
            "          nested:\n            persist-credentials: false\n",
        ):
            with self.subTest(body=body):
                self.assertIn(
                    "missing-checkout-credential-opt-out",
                    self.rules(PERMISSIONS + CHECKOUT + "        with:\n" + body),
                )

    def test_duplicate_input_or_with_mapping_is_rejected(self):
        for suffix in (
            "          persist-credentials: false\n",
            "        with:\n          persist-credentials: false\n",
        ):
            with self.subTest(suffix=suffix):
                self.assertIn(
                    "missing-checkout-credential-opt-out",
                    self.rules(PERMISSIONS + SAFE + suffix),
                )

    def test_true_and_write_permissions_remain_rejected(self):
        self.assertIn(
            "persisted-checkout-credentials",
            self.rules(
                (PERMISSIONS + SAFE).replace("credentials: false", "credentials: true")
            ),
        )
        self.assertIn(
            "contents-write",
            self.rules(
                (PERMISSIONS + SAFE).replace("contents: read", "contents: write")
            ),
        )
        self.assertIn(
            "missing-safe-workflow-token",
            self.rules("jobs:\n  job:\n    steps:\n" + SAFE),
        )

    def test_composite_checkout_also_requires_opt_out(self):
        text = (
            "runs:\n  using: composite\n  steps:\n    - uses: actions/checkout@pinned\n"
        )
        rules = {
            item.rule
            for item in MODULE.scan_path(".github/actions/fixture/action.yml", text)
        }
        self.assertIn("missing-checkout-credential-opt-out", rules)


if __name__ == "__main__":
    unittest.main()
