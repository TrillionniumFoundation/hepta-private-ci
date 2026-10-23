from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_EXTENSION_API.json"
CANONICAL = ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
SPEC = importlib.util.spec_from_file_location(
    "verify_hepta_callers", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
CALLER_PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CALLER_PROOF
SPEC.loader.exec_module(CALLER_PROOF)

PUBLIC_FUNCTION = re.compile(
    r"\bpub\s+(?:(?:async|const)\s+)?fn\s+([A-Za-z_][A-Za-z0-9_]*)"
)


class KernelAuthorityExtensionApiTests(unittest.TestCase):
    def policy(self) -> dict[str, object]:
        value = json.loads(POLICY.read_text(encoding="utf-8"))
        self.assertEqual(value.get("schema"), "hepta.kernel-authority-extension-api.v1")
        return value

    def lexical_code(self, source_path: str) -> str:
        raw = (ROOT / source_path).read_text(encoding="utf-8")
        return CALLER_PROOF._strip_cfg_test_items(
            CALLER_PROOF._strip_rust_non_code(raw)
        )

    def public_free_functions(self, source_path: str) -> set[str]:
        code = self.lexical_code(source_path)
        functions: set[str] = set()
        for function in PUBLIC_FUNCTION.finditer(code):
            prefix = code[: function.start()]
            depth = prefix.count("{") - prefix.count("}")
            if depth == 0:
                functions.add(function.group(1))
        return functions

    def public_methods(self, source_path: str, type_name: str) -> set[str]:
        code = self.lexical_code(source_path)
        methods: set[str] = set()
        for implementation in re.finditer(r"(?m)^\s*impl\b", code):
            prefix = code[: implementation.start()]
            if prefix.count("{") - prefix.count("}") != 0:
                continue
            brace = code.find("{", implementation.end())
            self.assertNotEqual(brace, -1, "top-level impl without an opening brace")
            header = code[implementation.start() : brace]
            if re.search(rf"\b{re.escape(type_name)}\b", header) is None:
                continue
            end = CALLER_PROOF._matching_delimiter(code, brace, "{", "}")
            self.assertIsNotNone(end, f"unbalanced impl block for {type_name}")
            assert end is not None
            block = code[brace + 1 : end]
            for method in PUBLIC_FUNCTION.finditer(block):
                method_prefix = block[: method.start()]
                depth = method_prefix.count("{") - method_prefix.count("}")
                if depth == 0:
                    methods.add(method.group(1))
        return methods

    def test_extension_api_is_exhaustively_classified(self) -> None:
        policy = self.policy()
        source_path = str(policy["sourcePath"])
        free_functions = policy.get("freeFunctions")
        self.assertIsInstance(free_functions, dict)
        assert isinstance(free_functions, dict)
        privileged_free = free_functions.get("privileged")
        non_privileged_free = free_functions.get("nonPrivileged")
        self.assertIsInstance(privileged_free, dict)
        self.assertIsInstance(non_privileged_free, list)
        assert isinstance(privileged_free, dict)
        assert isinstance(non_privileged_free, list)
        classified_free = {str(name) for name in privileged_free} | {
            str(name) for name in non_privileged_free
        }
        self.assertEqual(
            self.public_free_functions(source_path),
            classified_free,
            "authority_trust.rs public free-function classification drifted",
        )

        rows = policy.get("types")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        seen: set[str] = set()
        classified_method_count = 0
        for row in rows:
            self.assertIsInstance(row, dict)
            assert isinstance(row, dict)
            type_name = str(row["typeName"])
            self.assertNotIn(type_name, seen, f"duplicate extension type: {type_name}")
            seen.add(type_name)
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
            classified = privileged_methods | non_privileged_methods
            self.assertEqual(
                self.public_methods(source_path, type_name),
                classified,
                f"{type_name}: extension method classification drifted",
            )
            classified_method_count += len(classified)

        observed_definition_count = len(PUBLIC_FUNCTION.findall(self.lexical_code(source_path)))
        self.assertEqual(
            observed_definition_count,
            len(classified_free) + classified_method_count,
            "authority_trust.rs contains a public function outside the closed extension inventory",
        )

    def test_privileged_extension_entries_reference_canonical_boundaries(self) -> None:
        policy = self.policy()
        canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        boundary_ids = {str(row["id"]) for row in canonical["boundaries"]}
        free_functions = policy["freeFunctions"]
        assert isinstance(free_functions, dict)
        privileged_free = free_functions["privileged"]
        assert isinstance(privileged_free, dict)
        for function, boundary_id in privileged_free.items():
            self.assertIn(
                str(boundary_id),
                boundary_ids,
                f"{function}: missing canonical boundary",
            )
        rows = policy["types"]
        assert isinstance(rows, list)
        for row in rows:
            assert isinstance(row, dict)
            privileged = row["privilegedMethods"]
            assert isinstance(privileged, dict)
            for method, boundary_id in privileged.items():
                self.assertIn(
                    str(boundary_id),
                    boundary_ids,
                    f"{row['typeName']}::{method}: missing canonical boundary",
                )

    def test_production_final_use_constructor_callers_are_closed(self) -> None:
        policy = self.policy()
        source_path = str(policy["sourcePath"])
        canonical = json.loads(CANONICAL.read_text(encoding="utf-8"))
        boundary_ids = {str(row["id"]) for row in canonical["boundaries"]}
        ignored = ("/tests/", "/examples/", "_tests.rs")
        rust_sources = sorted((ROOT / "codex-rs").rglob("*.rs"))
        raw_cache: dict[Path, str] = {}
        code_cache: dict[Path, str] = {}
        rows = policy.get("freeFunctionCallers")
        self.assertIsInstance(rows, list)
        assert isinstance(rows, list)
        for row in rows:
            self.assertIsInstance(row, dict)
            assert isinstance(row, dict)
            function = str(row["function"])
            self.assertIn(str(row["boundaryId"]), boundary_ids)
            patterns = [re.compile(str(value)) for value in row["callPatterns"]]
            expected = {str(value) for value in row["allowedCallers"]}
            observed: set[str] = set()
            for path in rust_sources:
                relative = path.relative_to(ROOT).as_posix()
                if relative == source_path or any(
                    fragment in f"/{relative}" for fragment in ignored
                ):
                    continue
                if path not in raw_cache:
                    raw_cache[path] = path.read_text(encoding="utf-8")
                raw = raw_cache[path]
                if function not in raw:
                    continue
                if path not in code_cache:
                    code_cache[path] = CALLER_PROOF._strip_cfg_test_items(
                        CALLER_PROOF._strip_rust_non_code(raw)
                    )
                if any(pattern.search(code_cache[path]) for pattern in patterns):
                    observed.add(relative)
            self.assertEqual(
                observed,
                expected,
                f"{function}: production constructor caller set drifted",
            )


if __name__ == "__main__":
    unittest.main()
