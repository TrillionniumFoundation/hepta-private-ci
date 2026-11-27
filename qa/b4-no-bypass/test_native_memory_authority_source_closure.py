"""Keep the reviewed native-memory authority call sites closed and ordered.

These tests mutate the active host and owner sources. They verify source
admission only; native signature, revocation and recovery behavior is exercised
by the existing Rust owner tests.
"""

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

import test_current_caller_migrations as migration


ROOT = migration.ROOT
PROOF = migration.PROOF
BOOTSTRAP = "codex-rs/hepta-agentd/src/native_memory_host_bootstrap.rs"
NDU = "codex-rs/hepta-ndu/src/owner_current.rs"
BAO = "codex-rs/hepta-bao-adapter/src/final_use_host.rs"
NDU_CLOCK = (
    "let now = trust\n"
    "            .clock\n"
    "            .now_unix_ms()\n"
    "            .map_err(|_| FinalUseError::Unavailable)?;"
)
NDU_APPLY = (
    "let receipt = trust\n"
    "            .verifier\n"
    "            .apply(&self.authority, signed, now)\n"
    "            .map_err(NduOwnerError::ReadTrust)?;"
)
NDU_RECEIPT = "trust.feed = Some((receipt, signed.update.issued_at_unix_ms));"
BAO_CLOCK = (
    "let now_unix_ms = self\n"
    "            .clock\n"
    "            .now_unix_ms()\n"
    "            .map_err(BaoFinalUseHostError::Trust)?;"
)
BAO_APPLY = (
    "let receipt = match self.authority.authentication_profile() {\n"
    "            FinalUseAuthenticationProfile::ClassicalV1 => {\n"
    "                self.revocation_verifier\n"
    "                    .apply(&self.authority, update, now_unix_ms)\n"
    "            }\n"
    "            FinalUseAuthenticationProfile::MlDsa65V2 => self\n"
    "                .revocation_verifier\n"
    "                .apply_or_confirm_current(&self.authority, update, now_unix_ms),\n"
    "        }\n"
    "        .map_err(BaoFinalUseHostError::Control)?;"
)
BAO_RECEIPT = "*lease = Some(receipt.clone());"
BOOTSTRAP_VERIFY = (
    "feed_key\n"
    "        .verify_strict(\n"
    "            &signed_feed.update.signing_bytes().map_err(string)?,\n"
    "            &ed25519_dalek::Signature::from_slice(&signed_feed.signature)"
    ".map_err(string)?,\n"
    "        )\n"
    "        .map_err(string)?;"
)


class NativeMemoryAuthoritySourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def rejects(self, relative, original, replacement, *, occurrences=1, occurrence=0):
        source = (ROOT / relative).read_text()
        self.assertEqual(source.count(original), occurrences, original)
        start = -1
        for _ in range(occurrence + 1):
            start = source.index(original, start + 1)
        rows = [
            row for row in self.manifest["protected_file"] if row["path"] == relative
        ]
        self.assertEqual(len(rows), 1, relative)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            path.write_text(
                source[:start]
                + replacement
                + source[start + len(original) :]
                + "\n/* Original guard retained only as a comment:\n"
                + original
                + "\n*/\n"
            )
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_reviewed_callers_remain_registered_and_unknown_callers_are_rejected(self):
        for boundary_id, caller in (
            ("final_use_open_state", BOOTSTRAP),
            ("final_use_revocation_feed_trust", BOOTSTRAP),
            ("final_use_revocation_feed_apply", NDU),
        ):
            boundary = self.boundaries[boundary_id]
            paths = (boundary.definition_path, *boundary.product_callers)
            sources = {
                path: PROOF._strip_cfg_test_items(
                    PROOF._strip_rust_non_code((ROOT / path).read_text())
                )
                for path in paths
            }
            with self.subTest(boundary=boundary_id):
                PROOF._verify_boundary(ROOT, boundary, sources, ())
                removed = replace(
                    boundary,
                    product_callers=tuple(
                        path for path in boundary.product_callers if path != caller
                    ),
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, removed, sources, ())
                injected = dict(sources)
                injected["codex-rs/unregistered/src/native_authority.rs"] = (
                    sources[caller]
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, boundary, injected, ())

    def test_bootstrap_signature_cannot_be_removed_hidden_or_ignored(self):
        for changed in (
            "",
            "if false {\n" + BOOTSTRAP_VERIFY + "\n}",
            BOOTSTRAP_VERIFY.replace(".map_err(string)?;", ".ok();"),
            BOOTSTRAP_VERIFY.replace("&signed_feed.signature", "&other_signature"),
        ):
            with self.subTest(replacement=changed):
                self.rejects(BOOTSTRAP, BOOTSTRAP_VERIFY, changed)

    def test_bootstrap_keeps_host_selected_profile_distributor_and_local_clock(self):
        for original, changed in (
            ("descriptor.trust_profile !=", "ignored_profile !="),
            (
                "signed_feed.update.distributor_id != n.feed_distributor_id",
                "false",
            ),
            (
                "let now = clock.now_unix_ms().map_err(string)?;",
                "let now = supplied_time;",
            ),
        ):
            with self.subTest(guard=original):
                self.rejects(BOOTSTRAP, original, changed)

    def test_feed_verification_must_use_original_authority_input_and_time(self):
        for relative, call in ((NDU, NDU_APPLY), (BAO, BAO_APPLY)):
            for changed in (
                "",
                "if false {\n" + call + "\n}",
                call.replace("&self.authority", "&other_authority"),
                call.replace(")?;", ").ok();"),
            ):
                with self.subTest(path=relative, replacement=changed):
                    self.rejects(relative, call, changed)
        for method in ("apply", "apply_or_confirm_current"):
            call = f".{method}(&self.authority, update, now_unix_ms)"
            for argument, replacement in (
                ("&self.authority", "&other_authority"),
                ("update", "other_update"),
                ("now_unix_ms", "supplied_time"),
            ):
                with self.subTest(method=method, argument=argument):
                    self.rejects(BAO, call, call.replace(argument, replacement))

    def test_feed_time_cannot_come_from_untrusted_input_or_ignore_clock_failure(self):
        for relative, clock, occurrences, occurrence in (
            (NDU, NDU_CLOCK, 2, 0),
            (BAO, BAO_CLOCK, 2, 1),
        ):
            for changed in (
                "let now = supplied_time;",
                clock.replace(")?;", ").unwrap_or(0);"),
            ):
                with self.subTest(path=relative, replacement=changed):
                    self.rejects(
                        relative,
                        clock,
                        changed,
                        occurrences=occurrences,
                        occurrence=occurrence,
                    )

    def test_receipt_cannot_be_published_before_signature_verification(self):
        for relative, call, receipt in (
            (NDU, NDU_APPLY, NDU_RECEIPT),
            (BAO, BAO_APPLY, BAO_RECEIPT),
        ):
            source = (ROOT / relative).read_text()
            start = source.index(call)
            end = source.index(receipt, start) + len(receipt)
            middle = source[start + len(call) : end - len(receipt)]
            with self.subTest(path=relative):
                self.rejects(
                    relative,
                    source[start:end],
                    receipt + middle + call,
                )

    def test_both_bao_profiles_use_the_bound_authority_update_and_clock(self):
        for call in (
            ".apply(&self.authority, update, now_unix_ms)",
            ".apply_or_confirm_current(&self.authority, update, now_unix_ms)",
        ):
            for changed in (
                call.replace("&self.authority", "&other_authority"),
                call.replace("update,", "other_update,"),
                call.replace("now_unix_ms", "supplied_time"),
            ):
                with self.subTest(call=call, replacement=changed):
                    self.rejects(BAO, call, changed)

    def test_bao_retention_requires_the_checked_result_and_profile(self):
        self.rejects(BAO, "if !retain_longer_same_head", "if true")
        self.rejects(
            BAO,
            ".apply_or_confirm_current(&self.authority, update, now_unix_ms)",
            ".apply(&self.authority, update, now_unix_ms)",
        )

    def test_receipt_must_bind_the_verified_update(self):
        for relative, receipt, changed in (
            (
                NDU,
                NDU_RECEIPT,
                "trust.feed = Some((other_receipt, signed.update.issued_at_unix_ms));",
            ),
            (
                NDU,
                NDU_RECEIPT,
                "trust.feed = Some((receipt, supplied_time));",
            ),
            (
                BAO,
                BAO_RECEIPT,
                "*lease = Some(other_receipt.clone());",
            ),
            (
                BAO,
                "current.authority_epoch() == receipt.authority_epoch()",
                "true",
            ),
            (
                BAO,
                "current.revision() == receipt.revision()",
                "true",
            ),
            (
                BAO,
                "current.valid_until_unix_ms() > receipt.valid_until_unix_ms()",
                "true",
            ),
        ):
            with self.subTest(path=relative, replacement=changed):
                self.rejects(relative, receipt, changed)


if __name__ == "__main__":
    unittest.main()
