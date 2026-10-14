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

    def test_cell_split_current_ingress_and_reconciliation_api_are_closed_world(self) -> None:
        # Match THIS stack's actual exported methods, not later Metrics/recovery
        # versions on sibling Draft branches. New public entrypoints or callers
        # require independent review before they can dispatch a physical effect.
        expected = {
            "run_pinned_cell_split_execution_v1": {
                "codex-rs/hepta-operator-acceptance/src/lib.rs",
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs",
                # This reviewed CLI caller is transcript-only; guard proof below.
                "codex-rs/hepta-operator-acceptance/src/main.rs",
            },
            "run_pinned_cell_split_execution_with_admission_v1": {
                "codex-rs/hepta-operator-acceptance/src/lib.rs",
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs",
                "codex-rs/hepta-agentd/src/cell_split_execution.rs",
            },
        }
        observed: dict[str, set[str]] = {name: set() for name in expected}
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{relative}" or relative.endswith("_tests.rs"):
                continue
            raw = path.read_text(encoding="utf-8")
            active = [name for name in expected if name in raw]
            if not active:
                continue
            code = self.lexical_code(relative)
            for name in active:
                if re.search(rf"\b{re.escape(name)}\b", code):
                    observed[name].add(relative)
        for name, required in expected.items():
            with self.subTest(api=name):
                self.assertEqual(observed[name], required,
                                 "unreviewed CellSplit executing caller")
        self.assertEqual(
            self.public_free_functions(
                "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"
            ),
            {"run_pinned_cell_split_execution_v1",
             "run_pinned_cell_split_execution_with_admission_v1"},
            "Operator mutation surface changed without security review",
        )
        self.assertEqual(
            self.public_free_functions("codex-rs/hepta-agentd/src/cell_split_execution.rs"),
            {"advance_selected_cell_split_v1",
             "advance_scope_bound_selected_cell_split_v1"},
            "Agentd mutation ingress changed without security review",
        )
        owner = self.lexical_code(
            "codex-rs/hepta-operator-acceptance/src/cell_split_execution_owner.rs"
        )
        self.assertRegex(owner, r"\bpub\(crate\)\s+fn\s+advance_with_admission\s*\(",
                         "raw effect advancement must remain crate-private")
        self.assertNotRegex(owner, r"\bpub\s+fn\s+advance_with_admission\s*\(",
                            "raw CellSplit dispatch must not be exposed")

    def test_operator_cli_transcript_only_and_legacy_advance_denial(self) -> None:
        # Adding a known caller must never relax the actual physical-effect guard.
        cli = self.lexical_code("codex-rs/hepta-operator-acceptance/src/main.rs")
        cli_entry = cli.split("fn run_cell_split_execution_command", 1)
        self.assertEqual(len(cli_entry), 2, "Unix operator CLI entrypoint missing")
        cli_body = cli_entry[1].split("fn run_cell_split_execution_command", 1)[0]
        cli_deny = re.search(
            r'if\s+action\s*!=\s*"transcript"\s*\{\s*return\s+Err\s*\(',
            cli_body,
        )
        cli_call = re.search(r'\brun_pinned_cell_split_execution_v1\s*\(', cli_body)
        self.assertTrue(
            cli_deny is not None and cli_call is not None
            and cli_deny.start() < cli_call.start(),
            "Operator CLI must deny all effectful actions before its legacy call",
        )
        owner = self.lexical_code(
            "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"
        )
        legacy = owner.split("pub fn run_pinned_cell_split_execution_v1", 1)
        self.assertEqual(len(legacy), 2, "legacy API disappeared")
        legacy_body = legacy[1].split(
            "pub fn run_pinned_cell_split_execution_with_admission_v1", 1
        )[0]
        legacy_deny = re.search(
            r'if\s+action\s*==\s*"advance"\s*\{\s*return\s+Err\s*\(',
            legacy_body,
        )
        legacy_delegate = re.search(
            r'\brun_pinned_cell_split_execution_with_admission_v1\s*\(',
            legacy_body,
        )
        self.assertTrue(
            legacy_deny is not None and legacy_delegate is not None
            and legacy_deny.start() < legacy_delegate.start(),
            "legacy API must deny advance before admission-effect delegation",
        )

    def test_cns_effect_owner_and_observer_remain_fail_closed(self) -> None:
        invocation = re.compile(r"(?:\.|::)\s*apply_governed_topology\s*\(")
        expected = {
            "codex-rs/hepta-runtime/src/lib.rs",
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs",
        }
        seen: set[str] = set()
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if "/tests/" in f"/{relative}" or relative.endswith("_tests.rs"):
                continue
            if "apply_governed_topology" not in path.read_text(encoding="utf-8"):
                continue
            if invocation.search(self.lexical_code(relative)):
                seen.add(relative)
        self.assertEqual(seen, expected, "unreviewed physical CNS writer")

        port = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        self.assertRegex(
            port,
            r"atomic_control_cutover_owner:\s*Option\s*<\s*Arc\s*<\s*NduPublicationOwnerV1\s*>\s*>",
            "CNS original Control owner field changed",
        )
        self.assertRegex(port, r"atomic_control_cutover_owner:\s*None",
                         "public constructor may have installed a physical Control permit")
        self.assertEqual(len(re.findall(r"\batomic_control_cutover_owner\b", port)), 3,
                         "unexpected Control permit assignment or new physical ingress")
        gate = re.search(
            r"self\.atomic_control_cutover_owner\s*\.as_ref\(\)\s*\.ok_or\(", port
        )
        effect = re.search(r"\bapply_governed_topology\s*\(", port)
        self.assertIsNotNone(gate, "physical CNS fail-closed preflight absent")
        self.assertIsNotNone(effect, "physical CNS mutation path unavailable for review")
        if gate is not None and effect is not None:
            self.assertLess(gate.start(), effect.start(),
                            "CNS Control denial must precede physical mutation")
        self.assertIn("pub fn verify_original_cns_control_commit_v1", port)
        observer = port.split("pub fn verify_original_cns_control_commit_v1", 1)[1]
        observer = observer.split("fn live_runtime", 1)[0]
        self.assertNotRegex(
            observer, r"apply_governed_topology|take_admitted_successor|persist_actual_runtime_receipt",
            "independent signed CNS/Control Observer must stay read-only",
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

    def test_control_unsigned_cutover_api_remains_test_only(self) -> None:
        path = ROOT / "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        raw = path.read_text(encoding="utf-8")
        self.assertRegex(
            raw,
            r"#\[cfg\(test\)\]\s*pub\(crate\)\s+fn\s+publish_cutover_with_external_effect",
            "unsigned callback would become a production write surface",
        )
        self.assertNotRegex(raw, r"\bpub\s+fn\s+publish_cutover_with_external_effect",
                            "unsigned external effect callback cannot be publicly invoked")
        control = self.lexical_code(
            "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        )
        self.assertRegex(
            control,
            r"(?s)\bpub\s+fn\s+publish_cutover\s*\([^}]*?\)\s*->\s*Result<[^}]*?\{\s*Err\(NduPublicationErrorV1::Unsupported\)\s*\}",
            "deprecated direct CNS publication must always deny",
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
