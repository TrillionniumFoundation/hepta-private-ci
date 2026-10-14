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

    def test_public_cell_split_callback_only_advance_is_non_authorizing(self) -> None:
        # This legacy function is still exported to existing Rust callers,
        # including Agentd, but an arbitrary always-OK callback must not
        # create any production prepared intent, CAS, or CNS RPC.
        source_path = "codex-rs/hepta-operator-acceptance/src/cell_split_execution_cli.rs"
        raw = (ROOT / source_path).read_text(encoding="utf-8")
        self.assertIn('if action == "advance" && !cfg!(test)', raw)
        code = self.lexical_code(source_path)
        entrypoint = re.search(
            r"\bpub\s+fn\s+run_pinned_cell_split_execution_with_admission_v1\s*<",
            code,
        )
        self.assertIsNotNone(entrypoint, "legacy callback seam was renamed without review")
        assert entrypoint is not None
        opening = code.find("{", entrypoint.end())
        ending = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
        self.assertIsNotNone(ending, "legacy callback function is not a complete Rust item")
        assert ending is not None
        body = code[opening + 1 : ending]
        self.assertRegex(
            body,
            r"^\s*if\s+action\s*==\s*&&\s*!\s*cfg!\s*\(\s*test\s*\)\s*\{\s*"
            r"return\s+Err\s*\(",
            "non-test callback-only advancement must deny as its first action",
        )
        self.assertLess(
            body.index("if action"),
            body.index("read_private_config"),
            "public callback cannot access owner/config before production rejection",
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

    def test_generic_runtime_all_topology_mutations_require_control_owner(self) -> None:
        # A typed Split rejection alone is insufficient: a mislabeled
        # Replace/Merge/Rewire or Retire can still physically change a graph.
        # Until original signed Control Begin/Commit is integrated, EVERY
        # production mutation entrypoint must deny before lock/Final-use.
        path = "codex-rs/hepta-runtime/src/organs.rs"
        code = self.lexical_code(path)
        public = self.lexical_code("codex-rs/hepta-runtime/src/lib.rs")
        for method_name in ("apply_governed_topology", "recover_governed_topology"):
            with self.subTest(method=method_name):
                self.assertRegex(
                    public,
                    rf"\bself\.organs\s*\.\s*{method_name}\s*\(",
                    "public runtime must delegate to the single guarded owner",
                )
                method = re.search(
                    rf"\bpub\(crate\)\s+fn\s+{method_name}\s*\(", code
                )
                self.assertIsNotNone(method, "missing guarded runtime mutation")
                assert method is not None
                opening = code.find("{", method.end())
                closing = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
                self.assertIsNotNone(closing, "unbalanced runtime mutation body")
                assert closing is not None
                body = code[opening + 1 : closing]
                self.assertRegex(
                    body,
                    r"^\s*if\s+!\s*cfg!\s*\(\s*test\s*\)\s*\{\s*"
                    r"return\s+Err\s*\(\s*"
                    r"RuntimeTopologyExecutionError::Binding\s*\)\s*;\s*\}",
                    "production runtime must deny before lock, claim or write",
                )
                self.assertIn("authority.claim(", body)

    def test_control_original_inode_actor_replays_history_before_cns_receipt_join(self) -> None:
        # A valid final Control WAL row cannot authenticate an altered older
        # prefix. Freeze the serving original descriptor/Actor reader, and
        # require this complete replay in the non-test CNS receipt join.
        path = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        code = self.lexical_code(path)

        def method_body(name: str) -> str:
            entry = re.search(rf"\bfn\s+{name}\s*\(", code)
            self.assertIsNotNone(entry, f"{name}: missing original owner method")
            assert entry is not None
            begin = code.find("{", entry.end())
            end = CALLER_PROOF._matching_delimiter(code, begin, "{", "}")
            self.assertIsNotNone(end, f"{name}: invalid original owner body")
            assert end is not None
            return code[begin + 1 : end]

        full = method_body("verify_original_full_history")
        self.assertIn("self.file", full)
        self.assertIn(".read_exact_at(", full)
        self.assertIn("validate_replay(", full)
        self.assertNotIn(".seek(", full)
        self.assertIn("self.bytes", full)
        local = method_body("read_original_local_frontier_v1")
        self.assertIn("state.verify_original_full_history()", local)
        self.assertIn("state.pending_cutover", local)
        wrapper = method_body("verify_original_cns_receipt_binding")
        self.assertIn("self.verify_original_cns_receipt_frontier_v1(", wrapper)
        join = method_body("verify_original_cns_receipt_frontier_v1")
        self.assertIn("state.verify_original_full_history()", join)
        self.assertLess(
            join.index("state.verify_original_full_history()"),
            join.index("original_cns_receipt_binding("),
            "CNS receipt digest must not precede full original Control replay",
        )
        runtime = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        self.assertIn("let control_before = control", runtime)
        self.assertIn("let control_after = control", runtime)
        self.assertGreaterEqual(
            runtime.count(".verify_original_cns_receipt_frontier_v1("), 2
        )
        self.assertIn("if control_before != control_after", runtime)

    def test_generic_cns_generation_writer_callers_are_closed_world(self) -> None:
        # The generic CNS host is shared beyond Cell Split and cannot be
        # arbitrarily disabled. Freeze the concrete non-test callsites for
        # generation replacement and recovery; any new route writer must
        # undergo an explicit Control/Final-use owner review.
        allowed: dict[str, set[str]] = {
            "replace_read_only_generation": {
                "codex-rs/hepta-control-plane/src/cell_split_route.rs",
            },
            "replace_read_only_generation_with_migration": {
                "codex-rs/hepta-control-plane/src/cell_split_route.rs",
                "codex-rs/hepta-runtime/src/organs.rs",
            },
            "recover_read_only_generation": set(),
            "recover_read_only_generation_with_migration": {
                "codex-rs/hepta-runtime/src/organs.rs",
            },
            "replace_admitted_read_only_generation": {
                "codex-rs/hepta-control-plane/src/organ_hierarchy.rs",
            },
            "replace_admitted_read_only_generation_with_migration": {
                "codex-rs/hepta-control-plane/src/organ_hierarchy.rs",
            },
            "recover_admitted_read_only_generation": {
                "codex-rs/hepta-control-plane/src/organ_hierarchy.rs",
            },
            "recover_admitted_read_only_generation_with_migration": {
                "codex-rs/hepta-control-plane/src/organ_hierarchy.rs",
            },
        }
        names = tuple(allowed)
        invocation = re.compile(
            r"(?:\.|::)\s*(" + "|".join(re.escape(name) for name in names)
            + r")\s*\("
        )
        observed: dict[str, set[str]] = {name: set() for name in names}
        for path in self.rust_sources():
            relative = path.relative_to(ROOT).as_posix()
            if (
                "/tests/" in f"/{relative}"
                or "/examples/" in f"/{relative}"
                or relative.endswith("_tests.rs")
            ):
                continue
            raw = path.read_text(encoding="utf-8")
            if not any(name in raw for name in names):
                continue
            code = self.lexical_code(relative)
            for found in invocation.finditer(code):
                observed[found.group(1)].add(relative)
        self.assertEqual(
            observed,
            allowed,
            "generic CNS generation writer callsites drifted; audit Control handoff",
        )

    def test_generic_runtime_denies_typed_split_before_final_use(self) -> None:
        # This is a second physical cutover route distinct from the direct
        # CellSplitRouteController. An admitted topology Update carrying a
        # typed Split must not claim Final-use and must not publish a route
        # until the original CNS/Control Begin/Commit has a real owner.
        path = "codex-rs/hepta-runtime/src/topology_execution.rs"
        code = self.lexical_code(path)
        self.assertIn("ControlCutoverUnbound", code)
        ingress = re.search(
            r"\bfn\s+validate_runtime_topology_transition_for_destination_v1\s*\(",
            code,
        )
        self.assertIsNotNone(ingress, "common apply/recover validator missing")
        assert ingress is not None
        opening = code.find("{", ingress.end())
        closing = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
        self.assertIsNotNone(closing, "common topology validator must be complete")
        assert closing is not None
        body = code[opening + 1 : closing]
        deny = body.find("reject_ungoverned_split_operation_v1(change.operation)?")
        self.assertGreaterEqual(deny, 0, "typed Split rejection is not called")
        self.assertIn(
            "for change in &candidate.changes",
            body,
            "all changes including compound Updates must be inspected",
        )
        self.assertLess(
            deny,
            body.index("if candidate.kind"),
            "typed Split must deny before accepting a generic Update",
        )
        self.assertLess(
            deny,
            body.index("let binding = FinalUseBinding"),
            "typed Split must deny before creating a Final-use binding",
        )
        self.assertRegex(
            code,
            r"if\s+operation\s*==\s*TopologyOperationV2::Split\s*\{\s*"
            r"return\s+Err\s*\(\s*RuntimeTopologyExecutionError::ControlCutoverUnbound\s*\)",
            "typed Split must never return generic approval",
        )
        for method in (
            "validate_runtime_topology_transition_v1",
            "validate_runtime_topology_recovery_v1",
        ):
            entry = re.search(rf"\bfn\s+{method}\s*\(", code)
            self.assertIsNotNone(entry, f"{method} is no longer a reviewed API")
            assert entry is not None
            start = code.find("{", entry.end())
            end = CALLER_PROOF._matching_delimiter(code, start, "{", "}")
            self.assertIsNotNone(end, f"{method} is not a complete Rust method")
            assert end is not None
            self.assertIn(
                "validate_runtime_topology_transition_for_destination_v1(",
                code[start + 1 : end],
                f"{method} bypasses the shared Split-denying validator",
            )

    def test_live_runtime_rejects_split_before_claim_or_route_mutation(self) -> None:
        # Final-use on a generic Update cannot compensate for a typed Split
        # lacking the original durable Control/CNS transaction. Confirm the
        # real live Runtime order, not only the stand-alone validation helper.
        code = self.lexical_code("codex-rs/hepta-runtime/src/organs.rs")
        for action, validation, mutation in (
            (
                "apply_governed_topology",
                "validate_runtime_topology_transition_v1",
                "replace_read_only_generation_with_migration",
            ),
            (
                "recover_governed_topology",
                "validate_runtime_topology_recovery_v1",
                "recover_read_only_generation_with_migration",
            ),
        ):
            with self.subTest(action=action):
                entry = re.search(rf"\bfn\s+{action}\s*\(", code)
                self.assertIsNotNone(entry, f"{action} Runtime API missing")
                assert entry is not None
                start = code.find("{", entry.end())
                end = CALLER_PROOF._matching_delimiter(code, start, "{", "}")
                self.assertIsNotNone(end, f"{action} has no complete body")
                assert end is not None
                body = code[start + 1 : end]
                positions = [
                    body.index(validation + "("),
                    body.index("authority.claim("),
                    body.index("authority.with_verified_use("),
                    body.index(mutation + "("),
                    body.index("host.route = successor.route"),
                ]
                self.assertEqual(
                    positions,
                    sorted(positions),
                    f"{action} must validate before Final-use, effect and route publication",
                )

    def test_control_signed_cns_join_pins_same_inode_wal_tail_under_one_lock(self) -> None:
        # Verify two independent requirements on the SAME implementation:
        # (1) a live Control WAL may not silently shrink or rewrite its final
        # fsynced row while retaining its inode; and (2) the signed original
        # CNS receipt is checked against one locked Control frontier, not an
        # unlocked two-step readback that can straddle another Commit.
        path = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        code = self.lexical_code(path)
        self.assertRegex(
            code,
            r"\bfn\s+verify_original_paths\s*\(\s*&self\s*,\s*"
            r"expected_bytes\s*:\s*u64\s*,\s*"
            r"expected_sequence\s*:\s*u64\s*,\s*"
            r"expected_head\s*:\s*Digest32",
            "Control must pin WAL length, monotonic sequence and fsynced head",
        )
        for assertion in (
            "read_exact_at(&mut tail",
            "last.sequence != expected_sequence",
            "last.head != expected_head",
            "last.head != event_hash(&last)",
        ):
            self.assertIn(assertion, code, f"Control WAL tail fence missing: {assertion}")
        self.assertNotIn("state.verify_original_paths()", code)

        entry = re.search(
            r"\bpub\s+fn\s+verify_original_cns_receipt_binding\s*\(",
            code,
        )
        self.assertIsNotNone(entry, "read-only original CNS receipt join absent")
        assert entry is not None
        start = code.find("{", entry.end())
        end = CALLER_PROOF._matching_delimiter(code, start, "{", "}")
        self.assertIsNotNone(end, "original CNS receipt join is incomplete")
        assert end is not None
        body = code[start + 1 : end]
        self.assertRegex(body, r"self\s*\.\s*state\s*\.\s*lock\s*\(\s*\)")
        self.assertGreaterEqual(
            body.count("state.verify_original_paths(state.bytes, state.sequence, state.head)"),
            2,
            "single locked receipt comparison must revalidate WAL tail before and after",
        )
        self.assertNotIn(
            "self.last_cns_original_receipt_binding()",
            body,
            "released Control lock can admit a different signed receipt frontier",
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
