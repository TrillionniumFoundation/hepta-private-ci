"""Actual-regression cases for the fail-closed A32 configured Bazel closure."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

FILE = Path(__file__).with_name("a32_exec_authorized_read_native.py")
SPEC = importlib.util.spec_from_file_location("a32_exec_native_closure_guard", FILE)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def configured(*extras: str) -> bytes:
    return ("\n".join([*MODULE.OWNERS, *extras]) + "\n").encode("utf-8")


class ConfiguredClosureTests(unittest.TestCase):
    def test_real_uuid_v8_module_and_arm_crypto_are_not_js_runtime(self) -> None:
        harmless = (
            "@@rules_rs++crate+crates__uuid-1.28.0//:src/v8.rs",
            "@@rules_rs++crate+crates__aes-0.8.4//:src/armv8.rs",
            "@@rules_rs++crate+crates__aws-lc-sys-0.46.0//:aws-lc/crypto/fipsmodule/aes/asm/aesv8-armx.pl",
            "//codex-rs/exec-server:src/v8.rs",
        )
        self.assertEqual(
            MODULE.validate_closure(configured(*harmless)),
            sorted(set([*MODULE.OWNERS, *harmless])),
        )

    def test_actual_v8_runtime_and_full_codex_packages_are_still_denied(self) -> None:
        forbidden = (
            "@@rules_rs++crate+crates__v8-150.4.0//:src/lib.rs",
            "@@rules_rs++crate+crates__rusty_v8-150.4.0//:src/lib.rs",
            "@v8//:src/lib.rs",
            "//codex-rs/core:core-unit-tests",
            "//codex-rs/cli:codex",
            "//codex-rs/code-mode:tool",
            "//codex-rs/v8-poc:v8-poc",
            "//some-other-package:v8",
            "//some-other-package:rusty_v8",
        )
        for label in forbidden:
            with self.subTest(label=label):
                with self.assertRaisesRegex(RuntimeError, "unreviewed V8/full-CLI closure"):
                    MODULE.validate_closure(configured(label))

    def test_missing_owner_is_not_excused_by_unrelated_source_files(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "configured closure missing an owning test target"):
            MODULE.validate_closure(
                ("\n".join([*MODULE.OWNERS[:-1], "@@rules_rs++crate+crates__uuid-1.28.0//:src/v8.rs"]) + "\n").encode()
            )

    def test_configured_closure_is_canonical_set_not_partial_or_duplicate(self) -> None:
        closure = configured(MODULE.OWNERS[0], "@@rules_rs++crate+crates__uuid-1.28.0//:src/v8.rs")
        result = MODULE.validate_closure(closure)
        self.assertEqual(len(result), len(MODULE.OWNERS) + 1)
        self.assertEqual(result, sorted(result))


if __name__ == "__main__":
    unittest.main()
