from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import textwrap
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class CallerProofTests(unittest.TestCase):
    def make_fixture(self, *, method_pattern: bool = False) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "codex-rs/owner/src").mkdir(parents=True)
        (root / "codex-rs/caller/src").mkdir(parents=True)
        (root / "codex-rs/owner/src/lib.rs").write_text(
            "pub struct Gate; impl Gate { pub fn enter(&self) {} }\n", encoding="utf-8"
        )
        caller = "fn use_gate(gate: &Gate) { gate.enter(); }\n" if method_pattern else "fn use_gate() { Gate::enter(); }\n"
        (root / "codex-rs/caller/src/lib.rs").write_text(caller, encoding="utf-8")
        pattern = 'call_pattern = "gate\\\\s*\\\\.\\\\s*enter\\\\s*\\\\("\n' if method_pattern else ""
        caller_marker = "gate.enter" if method_pattern else "Gate::enter"
        (root / "CALLERS.toml").write_text(
            textwrap.dedent(
                f"""
                schema_version = 2
                plan_id = "HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN"
                source_roots = ["codex-rs"]
                ignored_path_fragments = ["/tests/", "/examples/", "_tests.rs"]
                [privileged_inventory]
                required_boundary_ids = ["gate"]
                [[boundary]]
                id = "gate"
                symbol = "Gate::enter"
                {pattern}definition_path = "codex-rs/owner/src/lib.rs"
                definition_markers = ["pub struct Gate", "pub fn enter"]
                product_callers = ["codex-rs/caller/src/lib.rs"]
                caller_markers = ["{caller_marker}"]
                [[protected_file]]
                path = "codex-rs/caller/src/lib.rs"
                required = ["{caller_marker}"]
                forbidden = ["Gate::bypass"]
                [authority]
                runtime_authority = false
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        return root

    def test_exact_caller_set_passes(self) -> None:
        root = self.make_fixture()
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["status"], "PASS_HEPTA_CALLER_CLOSED_SET")

    def test_method_call_pattern_passes(self) -> None:
        root = self.make_fixture(method_pattern=True)
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_typed_receiver_rejects_arbitrary_unregistered_parameter(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = manifest.read_text()
        text = "\n".join(line for line in text.splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass(completely_different: &Gate) { completely_different.enter(); }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_receiver_rejects_arbitrary_field_alias_in_split_impl(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(line for line in manifest.read_text().splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("struct Owner { anything: Gate }\n")
        (extra / "child.rs").write_text("impl Owner { fn bypass(&self) { self.anything.enter(); } }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_related_method_cannot_bypass_closed_set(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(line for line in manifest.read_text().splitlines() if not line.startswith("call_pattern ="))
        manifest.write_text(text.replace('symbol = "Gate::enter"', 'symbol = "Gate::enter"\nreceiver_type = "Gate"\nreceiver_methods = ["enter", "enter_next"]') + "\n")
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass(unexpected: &Gate) { unexpected.enter_next(); }\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_cfg_test_callsite_does_not_manufacture_product_caller(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "#[cfg(all(test, unix))]\nmod tests { fn only_test() { Gate::enter(); } }\n",
            encoding="utf-8",
        )
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_cfg_test_fields_preserve_the_production_suffix(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "struct Store { live: u8, #[cfg(test)] test_only: Pair<u8, u8>, }\n"
            "impl Store { fn open() -> Self { Self { live: 1, #[cfg(test)] test_only: Pair::new(1, 2), } } }\n"
            "fn bypass() { Gate::enter(); }\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, root / "CALLERS.toml")
        stripped = MODULE._strip_cfg_test_items((extra / "lib.rs").read_text())
        self.assertEqual(stripped.count("{"), stripped.count("}"))
        self.assertIn("fn bypass", stripped)
        self.assertNotIn("test_only", stripped)

    def test_last_cfg_test_field_does_not_remove_enclosing_brace(self) -> None:
        source = "struct Store { live: u8, #[cfg(test)] test_only: u8 } fn f() { Gate::enter(); }"
        stripped = MODULE._strip_cfg_test_items(source)
        self.assertEqual(stripped.count("{"), stripped.count("}"))
        self.assertIn("Gate::enter", stripped)

    def test_cfg_production_alternatives_remain_visible(self) -> None:
        for condition in ("not(test)", "any(test, unix)", "all(not(test), unix)"):
            with self.subTest(condition=condition):
                source = f"#[cfg({condition})] fn bypass() {{ Gate::enter(); }}"
                self.assertIn("Gate::enter", MODULE._strip_cfg_test_items(source))
        self.assertNotIn("Gate::enter", MODULE._strip_cfg_test_items(
            "#[cfg(all(test, unix))] fn only_test() { Gate::enter(); }"
        ))

    def test_inventory_omission_fails(self) -> None:
        root = self.make_fixture()
        manifest = root / "CALLERS.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                'required_boundary_ids = ["gate"]',
                'required_boundary_ids = ["gate", "missing_privileged_boundary"]',
            ),
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, manifest)

    def test_unexpected_product_caller_fails(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("fn bypass() { Gate::enter(); }\n", encoding="utf-8")
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, root / "CALLERS.toml")

    def test_comment_and_string_do_not_manufacture_callers(self) -> None:
        root = self.make_fixture()
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            '// Gate::enter()\nconst TEXT: &str = "Gate::enter()";\n', encoding="utf-8"
        )
        receipt = MODULE.verify(root, root / "CALLERS.toml")
        self.assertEqual(receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"])

    def test_positive_authority_fails(self) -> None:
        root = self.make_fixture()
        manifest = root / "CALLERS.toml"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace(
                "runtime_authority = false", "runtime_authority = true"
            ),
            encoding="utf-8",
        )
        with self.assertRaises(MODULE.VerificationFailure):
            MODULE.verify(root, manifest)

    def test_optional_source_pin_is_exact_and_requires_an_explicit_update(self) -> None:
        root = self.make_fixture()
        data = tomllib.loads((root / "CALLERS.toml").read_text())
        row = data["protected_file"][0]
        source = root / row["path"]
        MODULE._verify_protected_files(root, data)  # Original rows need no pin.
        row["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        MODULE._verify_protected_files(root, data)
        source.write_bytes(source.read_bytes() + b"\n")
        with self.assertRaisesRegex(MODULE.VerificationFailure, "protected source SHA256 mismatch"):
            MODULE._verify_protected_files(root, data)
        # Even a formatting change needs a matching source-identity update.
        row["source_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
        MODULE._verify_protected_files(root, data)
        row["source_sha256"] = "0" * 64
        with self.assertRaisesRegex(MODULE.VerificationFailure, "protected source SHA256 mismatch"):
            MODULE._verify_protected_files(root, data)

    def test_present_source_pin_rejects_empty_malformed_and_wrong_type_values(self) -> None:
        root = self.make_fixture()
        data = tomllib.loads((root / "CALLERS.toml").read_text())
        for invalid in (None, "", False, 0, [], {}, "a" * 63, "a" * 65, "A" * 64, "g" * 64):
            with self.subTest(pin=invalid):
                data["protected_file"][0]["source_sha256"] = invalid
                with self.assertRaisesRegex(MODULE.VerificationFailure, "source_sha256 must be 64 lowercase hex"):
                    MODULE._verify_protected_files(root, data)

    def test_real_final_use_pins_reject_known_verifier_and_message_drift(self) -> None:
        paths = [
            "codex-rs/hepta-contracts/src/final_use.rs",
            "codex-rs/hepta-contracts/src/final_use_ml_dsa65_v2.rs",
        ]
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        data = {"protected_file": [
            row for row in manifest["protected_file"] if row["path"] in paths
        ]}
        self.assertEqual([row["path"] for row in data["protected_file"]], paths)
        for row in data["protected_file"]:
            self.assertIn("source_sha256", row)
        originals = {path: (ROOT / path).read_bytes() for path in paths}
        source = originals[paths[1]].decode("utf-8")
        code = MODULE._strip_rust_non_code(source)

        def item(marker: str) -> tuple[str, str]:
            start = source.index(marker)
            brace = code.index("{", start)
            end = MODULE._matching_delimiter(code, brace, "{", "}")
            self.assertIsNotNone(end)
            return source[start:end + 1], source[start:brace]

        verify, header = item("pub(super) fn verify(")
        broken = source.replace(verify, header + "{ true }")
        decoy = (
            "const DECOY: () = { enum OtherIssuer { "
            "Ed25519V1(VerifyingKey), MlDsa65V2(Box<MlDsaVerifyingKey<MlDsa65>>) "
            "} impl OtherIssuer { " + verify + " } };"
        )
        implementation, _ = item("impl IssuerVerifier {")
        imports = source[source.index("use ml_dsa::EncodedVerifyingKey;"):source.index("pub const")]
        constants = source[source.index("pub const"):source.index("\n\n/// One host-pinned")]
        binding, binding_header = item("fn bind_key_id(")
        context = 'pub const FINAL_USE_ML_DSA65_V2_CONTEXT: &[u8] = b"hepta.kernel.final-use.ml-dsa-65.v2";'
        mutations = {
            "nested_impl": broken.replace("impl IssuerVerifier {", "impl IssuerVerifier { " + decoy),
            "macro": broken.replace("impl IssuerVerifier {", "impl self::IssuerVerifier {")
                + "\nmacro_rules! ignore { ($($t:tt)*) => {}; }\nignore!(" + implementation + ");\n",
            "nested_import": source.replace("use ml_dsa::MlDsa65;", "use ml_dsa::MlDsa87 as MlDsa65;")
                + "\nmod decoy { " + imports + " }\n",
            "nested_context": source.replace('b"hepta.kernel.final-use.ml-dsa-65.v2"', 'b"hepta.kernel.final-use.ml-dsa-65.v3"')
                + "\nmod decoy { " + constants + " }\n",
            "nested_key_binding": source.replace(binding, binding_header + "{ Ok(input.to_vec()) }")
                + "\nmod decoy { " + binding + " }\n",
            "conditional_context": source.replace(context, '#[cfg(target_os = "windows")]\n' + context)
                + '\n#[cfg(not(target_os = "windows"))]\n' + context.replace("65.v2", "65.v3"),
            "serde_grant": originals[paths[0]].decode("utf-8").replace(
                "    pub binding: FinalUseBinding,", "    #[serde(skip_serializing)]\n    pub binding: FinalUseBinding,"
            ),
        }
        for name, changed in mutations.items():
            with self.subTest(mutation=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for relative, raw in originals.items():
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                self.assertEqual(MODULE._verify_protected_files(root, data), paths)
                target = root / paths[0 if name == "serde_grant" else 1]
                self.assertNotEqual(target.read_text(), changed)
                target.write_text(changed)
                with self.assertRaisesRegex(MODULE.VerificationFailure, "protected source SHA256 mismatch"):
                    MODULE._verify_protected_files(root, data)


    def test_real_final_use_retained_owner_delegate_noops_fail_source_pins(self) -> None:
        paths = [
            "codex-rs/hepta-contracts/src/final_use.rs",
            "codex-rs/hepta-contracts/src/final_use_ml_dsa65_v2.rs",
            "codex-rs/hepta-contracts/src/final_use_live_owner.rs",
            "codex-rs/hepta-contracts/src/final_use_store.rs",
            "codex-rs/utils/windows-private-state/src/private_owner_lock.rs",
        ]
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        data = {
            "protected_file": [
                row for row in manifest["protected_file"] if row["path"] in paths
            ]
        }
        originals = {path: (ROOT / path).read_bytes() for path in paths}
        cases = [
            (paths[2], "pub(super) fn ensure_live_state<'state>", "Ok(state)"),
            (paths[3], "pub(super) fn revalidate_owner(", "Ok(())"),
            (paths[4], "pub fn revalidate_shared(", "Ok(())"),
        ]
        for relative, marker, body in cases:
            with self.subTest(delegate=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                for path, raw in originals.items():
                    target = root / path
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                # Exercise the original validator on the actual reviewed sources
                # before replacing one real delegate body with a permissive no-op.
                MODULE._verify_protected_files(root, data)
                source = originals[relative].decode("utf-8")
                code = MODULE._strip_rust_non_code(source)
                self.assertEqual(code.count(marker), 1)
                start = code.index(marker)
                brace = code.index("{", start)
                end = MODULE._matching_delimiter(code, brace, "{", "}")
                self.assertIsNotNone(end)
                assert end is not None
                changed = source[:brace] + "{ " + body + " }" + source[end + 1 :]
                self.assertNotEqual(source, changed)
                (root / relative).write_text(changed, encoding="utf-8")
                with self.assertRaisesRegex(
                    MODULE.VerificationFailure, "protected source SHA256 mismatch"
                ):
                    MODULE._verify_protected_files(root, data)


if __name__ == "__main__":
    unittest.main()
