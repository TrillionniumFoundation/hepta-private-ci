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

    def test_cell_split_mutation_and_reconciliation_are_closed_world(self) -> None:
        # A public callback alone does not confer independent NDU/Selector,
        # Evidence durability, or owner-atomic Final-use. Freeze every source
        # caller of the legacy/metrics-bound/reconcile APIs; new callers require
        # explicit security review, never an automatically expanded whitelist.
        expected = {
            "run_pinned_cell_split_execution_with_admission_v1": set(),
            "run_pinned_cell_split_execution_with_admission_and_metrics_v1": {
                "codex-rs/hepta-operator-acceptance/src/lib.rs",
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs",
                "codex-rs/hepta-agentd/src/cell_split_execution.rs",
            },
            "run_pinned_cell_split_reconcile_only_v1": {
                "codex-rs/hepta-operator-acceptance/src/lib.rs",
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs",
            },
        }
        observed: dict[str, set[str]] = {symbol: set() for symbol in expected}
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{relative}" or relative.endswith("_tests.rs"):
                continue
            raw = path.read_text(encoding="utf-8")
            relevant = [symbol for symbol in expected if symbol in raw]
            if not relevant:
                continue
            code = self.lexical_code(relative)
            for symbol in relevant:
                if re.search(rf"\b{re.escape(symbol)}\b", code):
                    observed[symbol].add(relative)
        for symbol, callers in expected.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    observed[symbol],
                    callers,
                    "unreviewed Cell Split mutation or pending-recovery caller",
                )

        # Raw test-only callback may exist in the test build, but must be
        # absent from ordinary production Rust and from all crate exports.
        cli_raw = (
            ROOT / "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"
        ).read_text(encoding="utf-8")
        self.assertRegex(
            cli_raw,
            r"\#\[cfg\(test\)\]\s+fn\s+run_pinned_cell_split_execution_with_admission_v1\b",
            "callback-only admission must be test-only and non-public",
        )
        self.assertNotRegex(
            self.lexical_code("codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"),
            r"\bfn\s+run_pinned_cell_split_execution_with_admission_v1\s*\(",
            "legacy arbitrary callback must not compile into the production coordinator",
        )
        self.assertEqual(
            self.public_free_functions(
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"
            ),
            {
                "run_pinned_cell_split_execution_v1",
                "run_pinned_cell_split_execution_with_admission_and_metrics_v1",
                "run_pinned_cell_split_reconcile_only_v1",
            },
            "Operator Cell Split public API widened without security review",
        )
        self.assertEqual(
            self.public_free_functions("codex-rs/hepta-agentd/src/cell_split_execution.rs"),
            {
                "advance_selected_cell_split_v1",
                "advance_scope_bound_selected_cell_split_v1",
                "advance_scope_bound_selected_cell_split_with_metrics_v1",
            },
            "Agentd Cell Split public ingress widened without security review",
        )
        owner = self.lexical_code(
            "codex-rs/hepta-operator-acceptance/src/cell_split_execution_owner.rs"
        )
        self.assertRegex(
            owner,
            r"\bpub\(crate\)\s+fn\s+advance_with_admission\s*\(",
            "raw effect advancement must remain crate-private",
        )
        self.assertNotRegex(
            owner,
            r"\bpub\s+fn\s+advance_with_admission\s*\(",
            "public raw Cell Split dispatch would bypass approved Agentd ingress",
        )

    def test_cell_split_physical_cns_runtime_writers_are_closed_world(self) -> None:
        # Signed route and independent Final-use alone must never become a
        # second physical writer outside the same-owner Control transaction.
        invocation = re.compile(r"(?:\.|::)\s*apply_governed_topology\s*\(")
        expected = {
            "codex-rs/hepta-runtime/src/lib.rs",
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs",
        }
        observed: set[str] = set()
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{relative}" or relative.endswith("_tests.rs"):
                continue
            if "apply_governed_topology" not in path.read_text(encoding="utf-8"):
                continue
            if invocation.search(self.lexical_code(relative)):
                observed.add(relative)
        self.assertEqual(observed, expected, "unreviewed CNS topology writer")

        port = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        self.assertRegex(
            port,
            r"atomic_control_cutover_prepared:\s*Option\s*<\s*std::convert::Infallible\s*>",
            "physical CNS permit must remain uninhabited until durable Control",
        )
        gate = re.search(
            r"self\.atomic_control_cutover_prepared\s*\.as_ref\(\)\s*\.ok_or\(",
            port,
        )
        actual_effect = re.search(r"\bapply_governed_topology\s*\(", port)
        self.assertIsNotNone(gate, "CNS Control-prepared denial missing")
        self.assertIsNotNone(actual_effect, "physical CNS caller not found")
        if gate is not None and actual_effect is not None:
            self.assertLess(
                gate.start(),
                actual_effect.start(),
                "Control transaction denial must precede physical topology mutation",
            )

    def test_control_cns_writer_never_exports_untyped_success_callback(self) -> None:
        # The only generic effect closure is compiled for the Control crate's
        # own regression fixtures. Production must consume actual signed
        # original-owner bytes and never manufacture successful Control C.
        relative = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        raw = (ROOT / relative).read_text(encoding="utf-8")
        production = self.lexical_code(relative)
        self.assertRegex(
            raw,
            r"\#\[cfg\(test\)\]\s+pub\(crate\)\s+fn\s+publish_cutover_with_external_effect\b",
            "untyped CNS callback must be test-only and crate-private",
        )
        self.assertNotRegex(
            production,
            r"\bfn\s+publish_cutover_with_external_effect\s*\(",
            "untyped callback must not compile as a production CNS mutation API",
        )
        legacy = production.find("pub fn publish_cutover(")
        checkpoint = production.find("pub fn compare_and_publish_checkpoint(")
        self.assertGreaterEqual(legacy, 0, "legacy Control API not found")
        self.assertGreater(checkpoint, legacy, "checkpoint CAS method missing")
        self.assertIn(
            "Err(NduPublicationErrorV1::Unsupported)",
            production[legacy:checkpoint],
            "legacy single-phase CNS mutation must remain denied",
        )
        self.assertIn(
            "state.pending_cutover = true",
            raw,
            "durable Control Begin requires a pending fence",
        )
        self.assertLess(
            raw.index("state.pending_cutover = true"),
            raw.index("apply_original_runtime_once()"),
            "Begin fence must precede the test-only original-runtime callback",
        )
        self.assertIn(
            "if state.pending_cutover",
            production,
            "production checkpoint/CNS reads must refuse pending Begin",
        )
        self.assertIn(
            "original_cns_receipt_binding",
            production,
            "original CNS bytes must be bound to the durable Control C record",
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
