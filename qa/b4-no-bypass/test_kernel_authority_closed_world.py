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
        return rows

    def rust_sources(self) -> list[Path]:
        return sorted((ROOT / "codex-rs").rglob("*.rs"))

    def lexical_code(self, source_path: str) -> str:
        raw = (ROOT / source_path).read_text(encoding="utf-8")
        return CALLER_PROOF._strip_cfg_test_items(
            CALLER_PROOF._strip_rust_non_code(raw)
        )

    def public_methods(self, source_path: str, type_name: str) -> set[str]:
        code = self.lexical_code(source_path)
        matches = list(re.finditer(rf"\bimpl\s+{re.escape(type_name)}\s*\{{", code))
        self.assertTrue(matches, f"missing impl block for {type_name}")
        methods: set[str] = set()
        for match in matches:
            brace = code.find("{", match.start())
            end = CALLER_PROOF._matching_delimiter(code, brace, "{", "}")
            self.assertIsNotNone(end, f"unbalanced impl block for {type_name}")
            assert end is not None
            block = code[brace + 1 : end]
            for method in re.finditer(
                r"\bpub\s+(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", block
            ):
                prefix = block[: method.start()]
                depth = prefix.count("{") - prefix.count("}")
                if depth == 0:
                    methods.add(method.group(1))
        return methods

    def public_free_functions(self, source_path: str) -> set[str]:
        code = self.lexical_code(source_path)
        functions: set[str] = set()
        for function in re.finditer(
            r"\bpub\s+(?:async\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)", code
        ):
            prefix = code[: function.start()]
            depth = prefix.count("{") - prefix.count("}")
            if depth == 0:
                functions.add(function.group(1))
        return functions

    def test_every_public_authority_free_function_is_explicitly_classified(self) -> None:
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
                source_path, seen_paths, f"duplicate free-function policy: {source_path}"
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
            self.assertNotIn(type_name, seen_types, f"duplicate type policy: {type_name}")
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
            extension_paths = row.get("extensionSourcePaths", [])
            self.assertIsInstance(extension_paths, list)
            assert isinstance(extension_paths, list)
            source_paths = [str(row["sourcePath"]), *extension_paths]
            self.assertTrue(all(isinstance(path, str) and path for path in source_paths))
            self.assertEqual(
                len(source_paths), len(set(source_paths)),
                f"{type_name}: duplicate authority method source path",
            )
            observed: set[str] = set()
            # Only the independently reviewed explicit paths extend this type;
            # neither the caller manifest nor observed methods grant a policy.
            for source_path in source_paths:
                observed.update(self.public_methods(source_path, type_name))
            self.assertEqual(
                observed,
                privileged_methods | non_privileged_methods,
                f"{type_name}: public method classification drifted",
            )

    def test_split_authority_impls_cannot_add_unclassified_public_methods(self) -> None:
        data = {
            "types": [{
                "typeName": "ExampleAuthority",
                "sourcePath": "classic.rs",
                "extensionSourcePaths": ["pq.rs"],
                "privilegedMethods": {"open": "example_open", "open_pq": "example_open_pq"},
                "nonPrivilegedMethods": [],
            }],
            "boundaries": [{"id": "example_open"}, {"id": "example_open_pq"}],
        }
        sources = {
            "classic.rs": "impl ExampleAuthority { pub fn open() {} }",
            "pq.rs": "impl ExampleAuthority { pub fn open_pq() {} }",
        }
        with patch.object(self, "data", return_value=data), patch.object(
            self, "lexical_code", side_effect=sources.__getitem__
        ):
            self.test_every_public_authority_method_is_explicitly_classified()
            with self.subTest(mutation="omitted_extension_file"):
                data["types"][0]["extensionSourcePaths"] = []
                with self.assertRaisesRegex(AssertionError, "public method classification drifted"):
                    self.test_every_public_authority_method_is_explicitly_classified()
                data["types"][0]["extensionSourcePaths"] = ["pq.rs"]
            with self.subTest(mutation="unclassified_method_in_second_impl"):
                sources["pq.rs"] += "\nimpl ExampleAuthority { pub fn unreviewed_authority() {} }"
                with self.assertRaisesRegex(AssertionError, "public method classification drifted"):
                    self.test_every_public_authority_method_is_explicitly_classified()

    def test_canonical_kernel_authority_inventory_is_declared_in_callers_manifest(self) -> None:
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
        rows = self.inventory()
        type_markers = {str(row["typeMarker"]) for row in rows}
        # Read each physical source once. Repeating this scan for every
        # boundary adds I/O while proving exactly the same closed set.
        sources = []
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if any(fragment in f"/{relative}" for fragment in ignored):
                continue
            raw = path.read_text(encoding="utf-8")
            if any(marker in raw for marker in type_markers):
                code = CALLER_PROOF._strip_cfg_test_items(
                    CALLER_PROOF._strip_rust_non_code(raw)
                )
                sources.append((relative, raw, code))
        for row in rows:
            boundary_id = str(row["id"])
            type_marker = str(row["typeMarker"])
            definition = str(row["definitionPath"])
            patterns = [re.compile(str(value)) for value in row["callPatterns"]]
            expected = {str(value) for value in row["allowedCallers"]}
            observed: set[str] = set()
            for relative, raw, code in sources:
                if relative == definition or type_marker not in raw:
                    continue
                if any(pattern.search(code) for pattern in patterns):
                    observed.add(relative)
            with self.subTest(boundary=boundary_id):
                self.assertEqual(
                    observed,
                    expected,
                    f"{boundary_id}: independent kernel.authority caller set drifted",
                )


if __name__ == "__main__":
    unittest.main()
