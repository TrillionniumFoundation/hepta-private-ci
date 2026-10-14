from __future__ import annotations

import importlib.util
import json
import re
import sys
import tomllib
import unittest
from pathlib import Path


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
        match = re.search(rf"\bimpl\s+{re.escape(type_name)}\s*\{{", code)
        self.assertIsNotNone(match, f"missing impl block for {type_name}")
        assert match is not None
        brace = code.find("{", match.start())
        end = CALLER_PROOF._matching_delimiter(code, brace, "{", "}")
        self.assertIsNotNone(end, f"unbalanced impl block for {type_name}")
        assert end is not None
        block = code[brace + 1 : end]
        methods: set[str] = set()
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
            observed = self.public_methods(str(row["sourcePath"]), type_name)
            self.assertEqual(
                observed,
                privileged_methods | non_privileged_methods,
                f"{type_name}: public method classification drifted",
            )

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

    def test_control_cns_mutation_requires_an_original_owner_adapter(self) -> None:
        # A Control WAL digest alone is not a signed, current CNS receipt.
        # Until the original runtime owner and durable Control transaction
        # are composed, neither the old one-phase publication nor the
        # internal success-shaped test callback may authorize a cutover.
        path = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        source = (ROOT / path).read_text(encoding="utf-8")
        self.assertRegex(
            source,
            r"(?m)^\s*#\[cfg\(test\)\]\s*\n\s*pub\(crate\)\s+fn\s+publish_cutover_with_external_effect\s*<",
            "unsigned CNS callback must remain test-only and crate-private",
        )
        lexical = self.lexical_code(path)
        self.assertRegex(
            lexical,
            r"\bpending\s*\.\s*is_some_and\s*\(\s*\|prepared\|",
            "replayed CNS Commit must have a preceding durable Control Begin",
        )
        self.assertRegex(
            lexical,
            r"!\s*e\s*\.\s*read\s*\.\s*is_zero\s*\(\s*\)",
            "replayed CNS Commit must bind original runtime receipt bytes",
        )
        self.assertNotRegex(
            lexical,
            r"\bpending\s*\.\s*is_none_or\s*\(",
            "pre-B legacy CNS Commit must not replay as successful cutover",
        )
        self.assertNotRegex(
            lexical,
            r"\b(?:pub(?:\(crate\))?\s+)?fn\s+publish_cutover_with_external_effect\s*<",
            "normal production Rust must not expose a generic Control cutover",
        )
        match = re.search(r"\bpub\s+fn\s+publish_cutover\s*\(", lexical)
        self.assertIsNotNone(match, "legacy API must remain explicitly denied")
        assert match is not None
        opening = lexical.find("{", match.end())
        ending = CALLER_PROOF._matching_delimiter(lexical, opening, "{", "}")
        self.assertIsNotNone(ending, "legacy public Control API must have a complete body")
        assert ending is not None
        self.assertEqual(
            lexical[opening + 1 : ending].strip(),
            "Err(NduPublicationErrorV1::Unsupported)",
            "old direct CNS cutover API became effectful",
        )
        joined = re.search(
            r"\bpub\s+fn\s+verify_original_cns_receipt_binding\s*\(", lexical
        )
        self.assertIsNotNone(
            joined, "independent CNS Observer must retain read-only WAL receipt join"
        )
        assert joined is not None
        join_start = lexical.find("{", joined.end())
        join_end = CALLER_PROOF._matching_delimiter(lexical, join_start, "{", "}")
        self.assertIsNotNone(join_end, "Control receipt join body must be complete")
        assert join_end is not None
        join_body = lexical[join_start + 1 : join_end]
        self.assertRegex(
            join_body,
            r"\bself\s*\.\s*state\s*\.\s*lock\s*\(\s*\)",
            "original CNS receipt comparison must hold a live Control lock",
        )
        self.assertNotIn(
            "self.last_cns_original_receipt_binding()",
            join_body,
            "separate readback may release the lock before receipt comparison",
        )
        self.assertRegex(join_body, r"\bstate\s*\.\s*verify_original_paths\s*\(\s*\)")
        self.assertRegex(join_body, r"\bstate\s*\.\s*pending_cutover\b")
        self.assertNotIn(
            "drop(state)", join_body, "no Control lock release before joined equality"
        )

        physical = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        self.assertRegex(
            physical,
            r"atomic_control_cutover_owner:\s*None",
            "native physical CNS port must not invent a Control owner",
        )
        self.assertRegex(
            physical,
            r"self\.atomic_control_cutover_owner\.as_ref\(\)\.ok_or\(",
            "original runtime cutover must stay blocked without Control",
        )

    def test_legacy_cell_split_route_activation_cannot_bypass_control(self) -> None:
        # The older CnsOrganHost reference controller replaces a generation
        # and makes children dispatchable. Signed Final-use on a different
        # runtime path is not evidence of Control's durable Begin/Commit.
        source_path = "codex-rs/hepta-control-plane/src/cell_split_route.rs"
        code = self.lexical_code(source_path)
        self.assertIn("ControlHandoffRequired", code)
        # A newly named public mutation entrypoint could evade checks for
        # the two historic activation method names. The entire public
        # controller surface is reviewed as a closed set.
        self.assertEqual(
            self.public_methods(source_path, "CellSplitRouteControllerV1"),
            {
                "new",
                "generation",
                "phase",
                "with_metrics_sink",
                "production_metrics_ready",
                "flush_production_metrics",
                "cns_latency_observations",
                "parent_route",
                "host",
                "route_fence_receipt",
                "child_route",
                "start_all",
                "dispatch_parent_once",
                "activate_children",
                "activate_children_with_migration",
                "dispatch_child_once",
            },
            "unreviewed CellSplit controller method may bypass Control handoff",
        )
        for method in ("activate_children", "activate_children_with_migration"):
            with self.subTest(entrypoint=method):
                entrypoint = re.search(
                    rf"\bpub\s+fn\s+{method}\b", code
                )
                self.assertIsNotNone(
                    entrypoint, f"{method} public compatibility API disappeared"
                )
                assert entrypoint is not None
                opening = code.find("{", entrypoint.end())
                ending = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
                self.assertIsNotNone(
                    ending, f"{method}: cannot parse the complete activation body"
                )
                assert ending is not None
                body = code[opening + 1 : ending]
                self.assertRegex(
                    body,
                    r"^\s*if\s+!\s*cfg!\s*\(\s*test\s*\)\s*\{\s*"
                    r"return\s+Err\s*\(\s*"
                    r"CellSplitRouteErrorV1::ControlHandoffRequired\s*\)\s*;\s*\}",
                    f"{method}: the first production action must deny physical cutover",
                )
                self.assertTrue(
                    "replace_read_only_generation" in body,
                    f"{method}: keep the positive reference-host tests isolated",
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
