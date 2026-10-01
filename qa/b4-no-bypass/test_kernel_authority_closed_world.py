from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
INVENTORY = ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
MANIFEST = ROOT / "CALLERS.toml"
PUBLIC_FUNCTION = re.compile(
    r"\bpub\s+(?:(?:const|async|unsafe|extern)\s+)*fn\s+(?:r#)?([A-Za-z_][A-Za-z0-9_]*)"
)
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
CALLER_PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CALLER_PROOF
SPEC.loader.exec_module(CALLER_PROOF)


class KernelAuthorityClosedWorldTests(unittest.TestCase):
    def data(self) -> dict[str, object]:
        data = json.loads(INVENTORY.read_text(encoding="utf-8"))
        self.assertEqual(
            data.get("schema"), "hepta.kernel-authority-privileged-boundaries.v3"
        )
        return data

    def inventory(self) -> list[dict[str, object]]:
        rows = self.data().get("boundaries")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        ids = [row.get("id") for row in rows]
        self.assertEqual(
            len(ids), len(set(ids)), "duplicate canonical privileged boundary id"
        )
        for row in rows:
            patterns = row.get("callPatterns")
            self.assertIsInstance(patterns, list)
            self.assertTrue(patterns, f"{row['id']}: empty privileged call patterns")
            for pattern in patterns:
                self.assertIsInstance(pattern, str)
                self.assertTrue(pattern, f"{row['id']}: empty privileged call pattern")
                try:
                    re.compile(pattern)
                except re.error as error:
                    self.fail(f"{row['id']}: invalid privileged call pattern: {error}")
        return rows

    def test_malformed_privileged_pattern_is_rejected_before_source_scan(self) -> None:
        data = self.data()
        data["boundaries"][0]["callPatterns"].append("unterminated(")
        with patch.object(self, "data", return_value=data):
            with self.assertRaisesRegex(
                self.failureException, "invalid privileged call pattern"
            ):
                self.inventory()
        manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        manifest["boundary"][0]["call_pattern"] = "unterminated("
        with self.assertRaisesRegex(
            CALLER_PROOF.VerificationFailure, "invalid call_pattern"
        ):
            CALLER_PROOF._boundary_rows(manifest)

    def test_unknown_public_authority_method_is_rejected(self) -> None:
        source_path = "codex-rs/hepta-contracts/src/final_use.rs"
        original = self.lexical_code
        raw = (ROOT / source_path).read_text(encoding="utf-8")
        for placement in ("first", "second", "raw-second"):
            for qualifier in ("", "const ", "unsafe ", 'unsafe extern "C" '):
                with self.subTest(placement=placement, qualifier=qualifier):
                    name = (
                        "r#unclassified_owner_entry"
                        if placement == "raw-second"
                        else "unclassified_owner_entry"
                    )
                    method = f"pub {qualifier}fn {name}(&self) {{}}"
                    changed = (
                        raw.replace(
                            "impl FinalUseAuthority {",
                            f"impl FinalUseAuthority {{ {method}",
                            1,
                        )
                        if placement == "first"
                        else raw + f"\nimpl FinalUseAuthority {{ {method} }}\n"
                    )
                    code = CALLER_PROOF._strip_cfg_test_items(
                        CALLER_PROOF._strip_rust_non_code(changed)
                    )
                    with patch.object(
                        self,
                        "lexical_code",
                        side_effect=lambda path: (
                            code if path == source_path else original(path)
                        ),
                    ):
                        with self.assertRaisesRegex(
                            self.failureException,
                            "FinalUseAuthority: public method classification drifted",
                        ):
                            self.test_every_public_authority_method_is_explicitly_classified()

    def test_unknown_qualified_public_free_function_is_rejected(self) -> None:
        source_path = "codex-rs/hepta-contracts/src/final_use.rs"
        original = self.lexical_code
        for qualifier in ("const ", "unsafe ", 'unsafe extern "C" '):
            with self.subTest(qualifier=qualifier):
                code = original(source_path) + CALLER_PROOF._strip_rust_non_code(
                    f"\npub {qualifier}fn unclassified_owner_entry() {{}}\n"
                )
                with patch.object(
                    self,
                    "lexical_code",
                    side_effect=lambda path: (
                        code if path == source_path else original(path)
                    ),
                ):
                    with self.assertRaisesRegex(
                        self.failureException,
                        "public free-function classification drifted",
                    ):
                        self.test_every_public_authority_free_function_is_explicitly_classified()

    def test_unknown_method_on_a_same_source_type_alias_is_rejected(self) -> None:
        source_path = "codex-rs/hepta-contracts/src/final_use.rs"
        original = self.lexical_code
        code = (
            original(source_path)
            + """
          type AuthorityAuditAlias = FinalUseAuthority;
          type ChainedAlias = AuthorityAuditAlias;
          impl ChainedAlias { pub fn unclassified_owner_entry(&self) {} }
        """
        )
        with patch.object(
            self,
            "lexical_code",
            side_effect=lambda path: code if path == source_path else original(path),
        ):
            with self.assertRaisesRegex(
                self.failureException,
                "FinalUseAuthority: public method classification drifted",
            ):
                self.test_every_public_authority_method_is_explicitly_classified()

    def test_private_and_trait_methods_do_not_enter_public_inherent_inventory(
        self,
    ) -> None:
        code = """impl Gate { fn private() {} pub(crate) fn internal() {} }
          impl Foreign for Gate { fn trait_entry() {} }
          impl Other { pub fn unrelated() {} }
          impl Gate { pub const fn r#visible() {} }"""
        with patch.object(self, "lexical_code", return_value=code):
            self.assertEqual(self.public_methods("fixture.rs", "Gate"), {"visible"})
            self.assertEqual(self.public_free_functions("fixture.rs"), set())

    def test_guarded_methods_reject_aliased_extra_paths_in_both_closed_sets(
        self,
    ) -> None:
        manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        for boundary_id, method in (
            ("final_use_async_dispatch_fence", "with_verified_use_async"),
            ("final_use_guarded_effect", "with_verified_effect"),
            ("final_use_entry_raw", "enter_verified_use"),
            ("bao_authbus_final_use_consumer", "consume_kv_v2_with_authbus"),
        ):
            row = next(row for row in self.inventory() if row["id"] == boundary_id)
            boundary = next(
                boundary
                for boundary in CALLER_PROOF._boundary_rows(manifest)
                if boundary.identifier == boundary_id
            )
            for call in (
                f"gate.{method}(token, binding, consumer)",
                f"AuthorityAlias::{method}(gate, token, binding, consumer)",
                f"gate.{method}::<u64, _>(token, binding, consumer)",
                f"let admit = AuthorityAlias::{method}; admit(gate, token, binding, consumer)",
                f"gate.r#{method}(token, binding, consumer)",
            ):
                with self.subTest(boundary=boundary_id, call=call):
                    extra = "codex-rs/unregistered/src/lib.rs"
                    code = f"fn bypass(gate: &AuthorityAlias) {{ {call}; }}"
                    self.assertNotIn("FinalUseAuthority", code)
                    paths = [ROOT / path for path in row["allowedCallers"]] + [
                        ROOT / extra
                    ]
                    read_text = Path.read_text
                    with (
                        patch.object(self, "inventory", return_value=[row]),
                        patch.object(self, "rust_sources", return_value=paths),
                        patch.object(
                            Path,
                            "read_text",
                            lambda path, *args, **kwargs: (
                                code
                                if path == ROOT / extra
                                else read_text(path, *args, **kwargs)
                            ),
                        ),
                    ):
                        with self.assertRaisesRegex(
                            self.failureException,
                            "independent kernel.authority caller set drifted",
                        ):
                            self.test_type_anchored_callers_match_independent_closed_set()
                    sources = {
                        path: self.lexical_code(path) for path in row["allowedCallers"]
                    }
                    sources[extra] = code
                    with self.assertRaisesRegex(
                        CALLER_PROOF.VerificationFailure, "unexpected=.*unregistered"
                    ):
                        CALLER_PROOF._verify_boundary(
                            ROOT,
                            boundary,
                            sources,
                            tuple(manifest["ignored_path_fragments"]),
                        )

    def rust_sources(self) -> list[Path]:
        return sorted((ROOT / "codex-rs").rglob("*.rs"))

    def lexical_code(self, source_path: str) -> str:
        raw = (ROOT / source_path).read_text(encoding="utf-8")
        return CALLER_PROOF._strip_cfg_test_items(
            CALLER_PROOF._strip_rust_non_code(raw)
        )

    def public_methods(self, source_path: str, type_name: str) -> set[str]:
        code = self.lexical_code(source_path)
        # Resolve direct aliases in this source only; this is a lexical proof,
        # not Rust name resolution or macro/type checking across modules.
        names = {type_name}
        aliases = re.findall(
            r"\btype\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*((?:[A-Za-z_][A-Za-z0-9_]*\s*::\s*)*[A-Za-z_][A-Za-z0-9_]*)\s*;",
            code,
        )
        while True:
            updated = names | {
                alias
                for alias, target in aliases
                if target.split("::")[-1].strip() in names
            }
            if updated == names:
                break
            names = updated
        type_pattern = "|".join(re.escape(name) for name in sorted(names))
        methods: set[str] = set()
        found_impl = False
        for match in re.finditer(r"\bimpl\b([^{};]*)\{", code):
            header = match.group(1).strip()
            if header.startswith("<"):
                end = CALLER_PROOF._matching_delimiter(header, 0, "<", ">")
                if end is None:
                    continue
                header = header[end + 1 :].lstrip()
            target = re.match(
                rf"(?:[A-Za-z_][A-Za-z0-9_]*\s*::\s*)*(?:{type_pattern})\b",
                header,
            )
            if target is None:
                continue
            tail = header[target.end() :].lstrip()
            if tail.startswith("<"):
                end = CALLER_PROOF._matching_delimiter(tail, 0, "<", ">")
                self.assertIsNotNone(end, f"unbalanced impl type for {type_name}")
                assert end is not None
                tail = tail[end + 1 :].lstrip()
            if tail and not re.match(r"where\b", tail):
                continue  # Trait implementations are not inherent methods.
            found_impl = True
            brace = match.end() - 1
            end = CALLER_PROOF._matching_delimiter(code, brace, "{", "}")
            self.assertIsNotNone(end, f"unbalanced impl block for {type_name}")
            assert end is not None
            block = code[brace + 1 : end]
            for method in PUBLIC_FUNCTION.finditer(block):
                prefix = block[: method.start()]
                if prefix.count("{") == prefix.count("}"):
                    methods.add(method.group(1))
        self.assertTrue(found_impl, f"missing impl block for {type_name}")
        return methods

    def public_free_functions(self, source_path: str) -> set[str]:
        code = self.lexical_code(source_path)
        functions: set[str] = set()
        for function in PUBLIC_FUNCTION.finditer(code):
            prefix = code[: function.start()]
            depth = prefix.count("{") - prefix.count("}")
            if depth == 0:
                functions.add(function.group(1))
        return functions

    def test_every_public_authority_free_function_is_explicitly_classified(
        self,
    ) -> None:
        data = self.data()
        rows = data.get("freeFunctions")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        boundary_ids = {str(row["id"]) for row in self.inventory()}
        seen_paths: set[str] = set()
        for row in rows:
            self.assertIsInstance(row, dict)
            assert isinstance(row, dict)
            source_path = str(row["sourcePath"])
            self.assertNotIn(
                source_path,
                seen_paths,
                f"duplicate free-function policy: {source_path}",
            )
            seen_paths.add(source_path)
            privileged = row.get("privilegedFunctions")
            non_privileged = row.get("nonPrivilegedFunctions")
            self.assertIsInstance(privileged, dict)
            self.assertIsInstance(non_privileged, list)
            assert isinstance(privileged, dict)
            assert isinstance(non_privileged, list)
            privileged_functions = {str(name) for name in privileged}
            non_privileged_functions = {str(name) for name in non_privileged}
            self.assertFalse(
                privileged_functions & non_privileged_functions,
                f"{source_path}: function cannot be both privileged and non-privileged",
            )
            for function, boundary_id in privileged.items():
                self.assertIn(
                    str(boundary_id),
                    boundary_ids,
                    f"{source_path}::{function}: missing canonical privileged boundary",
                )
            observed = self.public_free_functions(source_path)
            self.assertEqual(
                observed,
                privileged_functions | non_privileged_functions,
                f"{source_path}: public free-function classification drifted",
            )

    def test_every_public_authority_method_is_explicitly_classified(self) -> None:
        data = self.data()
        rows = data.get("types")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        boundary_ids = {str(row["id"]) for row in self.inventory()}
        seen_types: set[str] = set()
        for row in rows:
            self.assertIsInstance(row, dict)
            assert isinstance(row, dict)
            type_name = str(row["typeName"])
            self.assertNotIn(
                type_name, seen_types, f"duplicate type policy: {type_name}"
            )
            seen_types.add(type_name)
            privileged = row.get("privilegedMethods")
            non_privileged = row.get("nonPrivilegedMethods")
            self.assertIsInstance(privileged, dict)
            self.assertIsInstance(non_privileged, list)
            assert isinstance(privileged, dict)
            assert isinstance(non_privileged, list)
            privileged_methods = {str(name) for name in privileged}
            non_privileged_methods = {str(name) for name in non_privileged}
            self.assertFalse(
                privileged_methods & non_privileged_methods,
                f"{type_name}: method cannot be both privileged and non-privileged",
            )
            for method, boundary_id in privileged.items():
                self.assertIn(
                    str(boundary_id),
                    boundary_ids,
                    f"{type_name}::{method}: missing canonical privileged boundary",
                )
            observed = self.public_methods(str(row["sourcePath"]), type_name)
            self.assertEqual(
                observed,
                privileged_methods | non_privileged_methods,
                f"{type_name}: public method classification drifted",
            )

    def test_canonical_kernel_authority_inventory_is_declared_in_callers_manifest(
        self,
    ) -> None:
        data = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
        declared_rows = data.get("boundary")
        self.assertIsInstance(declared_rows, list)
        assert isinstance(declared_rows, list)
        declared = {row.get("id") for row in declared_rows}
        manifest_inventory = data.get("privileged_inventory")
        self.assertIsInstance(manifest_inventory, dict)
        assert isinstance(manifest_inventory, dict)
        required = set(manifest_inventory.get("required_boundary_ids", []))
        canonical = {row["id"] for row in self.inventory()}
        self.assertTrue(
            canonical.issubset(declared),
            f"kernel.authority privileged boundaries missing from CALLERS.toml: {sorted(canonical - declared)}",
        )
        self.assertTrue(
            canonical.issubset(required),
            f"kernel.authority privileged boundaries missing from privileged_inventory: {sorted(canonical - required)}",
        )

    def test_type_anchored_callers_match_independent_closed_set(self) -> None:
        ignored = ("/tests/", "/examples/", "_tests.rs")
        sources = self.rust_sources()
        for row in self.inventory():
            boundary_id = str(row["id"])
            type_marker = str(row["typeMarker"])
            definition = str(row["definitionPath"])
            patterns = [re.compile(str(value)) for value in row["callPatterns"]]
            expected = {str(value) for value in row["allowedCallers"]}
            observed: set[str] = set()
            for path in sources:
                relative = path.relative_to(ROOT).as_posix()
                if relative == definition or any(
                    fragment in f"/{relative}" for fragment in ignored
                ):
                    continue
                raw = path.read_text(encoding="utf-8")
                if type_marker not in raw:
                    continue
                code = CALLER_PROOF._strip_cfg_test_items(
                    CALLER_PROOF._strip_rust_non_code(raw)
                )
                if any(pattern.search(code) for pattern in patterns):
                    observed.add(relative)
            self.assertEqual(
                observed,
                expected,
                f"{boundary_id}: independent kernel.authority caller set drifted",
            )


if __name__ == "__main__":
    unittest.main()
