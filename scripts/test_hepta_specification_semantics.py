"""Exercise full CNS/HNMF checks with edited prose and unchanged real sources."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import unittest
from pathlib import Path
from unittest.mock import patch


def load_verifier(name):
    path = Path(__file__).with_name(f"hepta-{name}.py")
    spec = importlib.util.spec_from_file_location(f"specification_{name}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CNS = load_verifier("cns")
HNMF = load_verifier("hnmf")
READ_TEXT = Path.read_text


class SpecificationSemanticsTests(unittest.TestCase):
    def verify_with_prose(self, verifier, replacements):
        root = verifier.ROOT

        def read_text(path, *args, **kwargs):
            for relative, content in replacements.items():
                if path == root / relative:
                    return content
            return READ_TEXT(path, *args, **kwargs)

        with patch.object(Path, "read_text", read_text):
            with contextlib.redirect_stdout(io.StringIO()):
                with contextlib.redirect_stderr(io.StringIO()) as diagnostics:
                    verifier.verify()
        return diagnostics.getvalue()

    def test_cns_concise_reworded_guide_keeps_real_reference_validation(self):
        diagnostics = self.verify_with_prose(
            CNS,
            {
                CNS.TECHNICAL_PATH: "# CNS guide\n\nSee the registered owner contracts.\n",
            },
        )
        self.assertIn("ADVISORY_HEPTA_CNS", diagnostics)

    def test_hnmf_concise_reordered_guides_keep_contract_and_source_checks(self):
        diagnostics = self.verify_with_prose(
            HNMF,
            {
                "docs/hnmf/TECHNICAL.md": "# Memory guide\n\nRead registered contracts first.\n",
                "docs/hnmf/MIGRATION.md": "# Migration\n\nPreserve the owner handoff and recovery gates.\n",
            },
        )
        self.assertIn("ADVISORY_HEPTA_HNMF", diagnostics)

    def test_empty_technical_and_migration_guides_still_reject(self):
        for verifier, path in [
            (CNS, CNS.TECHNICAL_PATH),
            (HNMF, "docs/hnmf/TECHNICAL.md"),
            (HNMF, "docs/hnmf/MIGRATION.md"),
        ]:
            with self.subTest(path=path), self.assertRaisesRegex(SystemExit, "empty"):
                self.verify_with_prose(verifier, {path: " \n"})

    def test_missing_canonical_decoder_does_not_pass_as_concise_code(self):
        with self.assertRaisesRegex(SystemExit, "canonical cognitive contract token"):
            self.verify_with_prose(
                HNMF,
                {
                    "codex-rs/hepta-cognitive-types/src/hnmf.rs": "// omitted",
                    "codex-rs/hepta-cognitive-types/src/hnmf_learning.rs": "// omitted",
                    "codex-rs/hepta-cognitive-types/src/wire.rs": "// omitted",
                },
            )

    def test_empty_reference_implementation_still_rejects(self):
        with self.assertRaisesRegex(SystemExit, "empty algorithm reference runtime"):
            self.verify_with_prose(
                HNMF,
                {
                    "qualification/hnmf-reference/src/lib.rs": " \n",
                },
            )

    def test_authority_key_order_is_editorial_but_identity_is_not(self):
        for verifier in [CNS, HNMF]:
            flags = dict.fromkeys(reversed(verifier.AUTHORITY_KEYS), False)
            with self.subTest(verifier=verifier.__name__):
                verifier.false_authority(flags, "reordered authority")
                flags["unknown"] = flags.pop("runtimeAuthority")
                with self.assertRaises(SystemExit):
                    verifier.false_authority(flags, "substituted authority")

    def test_falsey_non_booleans_are_not_deny_all_authority(self):
        for verifier in [CNS, HNMF]:
            for value in [0, "", None, [], {}]:
                flags = dict.fromkeys(verifier.AUTHORITY_KEYS, False)
                flags["runtimeAuthority"] = value
                with self.subTest(verifier=verifier.__name__, value=value):
                    with self.assertRaises(SystemExit):
                        verifier.false_authority(flags, "malformed authority")

    def test_prose_edit_never_grants_authority(self):
        for verifier in [CNS, HNMF]:
            flags = dict.fromkeys(verifier.AUTHORITY_KEYS, False)
            flags["runtimeAuthority"] = True
            with (
                self.subTest(verifier=verifier.__name__),
                self.assertRaises(SystemExit),
            ):
                verifier.false_authority(flags, "edited specification")


if __name__ == "__main__":
    unittest.main()
