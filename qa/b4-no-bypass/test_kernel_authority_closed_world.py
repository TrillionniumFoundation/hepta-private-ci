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

    def locked_original_cns_receipt_body(self, code: str) -> str:
        """Follow the compatibility API to its sole locked Control owner."""

        def method_body(name: str) -> str:
            entry = re.search(rf"\bpub\s+fn\s+{name}\s*\(", code)
            self.assertIsNotNone(entry, f"missing original Control {name}")
            assert entry is not None
            opening = code.find("{", entry.end())
            closing = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
            self.assertIsNotNone(closing, f"unbalanced original Control {name}")
            assert closing is not None
            return code[opening + 1 : closing]

        wrapper = method_body("verify_original_cns_receipt_binding")
        self.assertRegex(
            wrapper,
            r"^\s*self\s*\.\s*verify_original_cns_receipt_frontier_v1\s*\(\s*"
            r"externally_verified_original_receipt_bytes\s*\)\s*"
            r"\.\s*map\s*\(\s*\|_\|\s*\(\s*\)\s*\)\s*$",
            "legacy CNS receipt API must be a one-hop typed Control owner join",
        )
        body = method_body("verify_original_cns_receipt_frontier_v1")
        self.assertRegex(
            body,
            r"\bself\s*\.\s*state\s*\.\s*lock\s*\(\s*\)",
            "typed original Control receipt join must hold the live mutex",
        )
        self.assertIn("state.pending_cutover", body)
        self.assertIn("state.verify_original_full_history()", body)
        self.assertIn("state.last_cns_original_receipt_binding", body)
        self.assertIn("if expected != observed", body)
        self.assertNotIn("drop(state)", body)
        self.assertLess(
            body.index("state.verify_original_full_history()"),
            body.index("original_cns_receipt_binding("),
            "the original WAL history must replay before signed receipt equality",
        )
        return body

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
        # The void-return API is only a compatibility wrapper. Verify its
        # sole call and inspect the callee's original Control mutex instead.
        join_body = self.locked_original_cns_receipt_body(lexical)
        self.assertGreaterEqual(
            join_body.count(
                "state.verify_original_paths(state.bytes, state.sequence, state.head)"
            ),
            2,
            "Control pins original WAL path and fsynced tail before and after the join",
        )

        physical = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        self.assertRegex(
            physical,
            r"atomic_control_cutover_owner:\s*None",
            "native physical CNS port must not invent a Control owner",
        )
        # A populated optional Control handle would not prove B/effect/C.
        # Require the non-test-only denial as the first executable statement;
        # then retain the existing optional-owner guard for test mechanisms.
        # No signed preflight, Final-use, original mutation or child dispatch
        # is permitted before this explicit production closure.
        method = re.search(r"\bfn\s+publish_once\s*\(", physical)
        self.assertIsNotNone(method, "original runtime CNS mutator missing")
        assert method is not None
        opening = physical.find("{", method.end())
        closing = CALLER_PROOF._matching_delimiter(physical, opening, "{", "}")
        self.assertIsNotNone(closing, "malformed physical cutover owner")
        assert closing is not None
        body = physical[opening + 1 : closing]
        self.assertRegex(
            body,
            r"^\s*if\s+!\s*cfg!\s*\(\s*test\s*\)\s*\{\s*"
            r"return\s+Err\s*\(",
            "non-test CNS port must deny before consulting any optional owner",
        )
        self.assertRegex(
            body,
            r"self\s*\.\s*atomic_control_cutover_owner\s*\.\s*"
            r"as_ref\(\)\s*\.\s*ok_or\(",
            "test CNS cutover must still require an original Control owner",
        )
        self.assertLess(
            body.index("if !cfg!(test)"),
            body.index("atomic_control_cutover_owner"),
            "a possibly populated owner is not the original B/effect/C protocol",
        )
        self.assertLess(
            body.index("atomic_control_cutover_owner"),
            body.index("self.verify_pin(plan, intent)?"),
            "a signed pin is not an original durable Control Begin/Commit",
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

    def test_signed_independent_control_highwater_cannot_mint_physical_cutover(self) -> None:
        # External Control high-water must be signed under a distinct key and
        # fresh challenge, against an ACTUAL original Control WAL Actor read.
        path = "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        code = self.lexical_code(path)
        method = re.search(
            r"\bpub\s+fn\s+verify_independent_control_highwater_v1\s*<", code
        )
        self.assertIsNotNone(method, "independent Control Observer gate missing")
        assert method is not None
        begin = code.find("{", method.end())
        end = CALLER_PROOF._matching_delimiter(code, begin, "{", "}")
        self.assertIsNotNone(end, "unbalanced external Observer validator")
        assert end is not None
        body = code[begin + 1 : end]
        self.assertIn("secure_cns_nonce()", body)
        self.assertEqual(
            body.count(".read_original_local_frontier_v1()"),
            2,
            "original Control must be read before AND after signed Observer RPC",
        )
        self.assertIn(".read_signed_highwater(", body)
        self.assertIn("pinned_observer_key == &self.runtime_key", body)
        self.assertIn("verify_strict(", body)
        self.assertIn("if original_before != original_after", body)
        root = self.lexical_code("codex-rs/hepta-runtime/src/lib.rs")
        self.assertIn("CellSplitIndependentControlObserverV1", root)
        self.assertIn("CellSplitSignedControlHighwaterV1", root)
        self.assertIn("cell_split_control_highwater_signing_bytes_v1", root)
        self.assertIn("CELL_SPLIT_SIGNED_CONTROL_HIGHWATER_SCHEMA_V1", root)
        self.assertIn("self.plan.ndu_snapshot_digest", body)
        self.assertIn("claimed.wal_inode != original_before.wal_inode", body)
        self.assertIn("claimed.marker_inode != original_before.marker_inode", body)
        # No original sender keys, runtime cutover, Final-use claim or grant.
        self.assertNotIn("apply_governed_topology(", body)
        self.assertNotIn("publish_once(", body)
        self.assertNotIn("authority.claim(", body)

    def test_signed_cns_control_and_external_highwater_are_joined_read_only(self) -> None:
        # It is insufficient for an operator to call two separately successful
        # read-only verifiers at unrelated Control WAL revisions. Require a
        # single explicitly named double-collect entrypoint and deny any
        # original CNS-missing case BEFORE external Observer RPC.
        code = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        method = re.search(
            r"\bpub\s+fn\s+"
            r"verify_original_cns_control_independent_highwater_join_v1\s*<",
            code,
        )
        self.assertIsNotNone(method, "joined original signed owner verifier missing")
        assert method is not None
        opening = code.find("{", method.end())
        closing = CALLER_PROOF._matching_delimiter(code, opening, "{", "}")
        self.assertIsNotNone(closing, "unbalanced joined original owner verifier")
        assert closing is not None
        body = code[opening + 1 : closing]
        self.assertEqual(body.count(".read_original_local_frontier_v1()"), 2)
        signed = "self.verify_original_cns_control_commit_v1(control)?"
        remote = "self.verify_independent_control_highwater_v1("
        self.assertEqual(body.count(signed), 2)
        self.assertEqual(body.count(remote), 1)
        self.assertLess(body.index(signed), body.index(remote))
        self.assertLess(body.index(remote), body.rindex(signed))
        self.assertIn("if before != after", body)
        self.assertNotIn("publish_once(", body)
        self.assertNotIn("apply_governed_topology(", body)
        self.assertNotIn("authority.claim(", body)

    def test_control_highwater_unix_rpc_has_no_echoback_or_mutation_surface(self) -> None:
        path = "codex-rs/hepta-runtime/src/cell_split_control_highwater_unix.rs"
        code = self.lexical_code(path)
        root = self.lexical_code("codex-rs/hepta-runtime/src/lib.rs")
        self.assertIn("mod cell_split_control_highwater_unix;", root)
        self.assertIn("CellSplitControlHighwaterUnixPortV1", root)
        self.assertIn("CELL_SPLIT_CONTROL_HIGHWATER_RPC_SCHEMA_V1", root)
        self.assertIn("CellSplitIndependentControlObserverV1 for", code)
        self.assertIn("fn read_signed_highwater(", code)
        self.assertIn("fs::symlink_metadata(", code)
        self.assertIn(".file_type()", code)
        self.assertIn(".is_socket()", code)
        self.assertIn("remaining(started, budget)?", code)
        self.assertIn("MAX_FRAME_BYTES", code)
        self.assertIn("MAX_TRACKED_SCOPES", code)
        self.assertIn("seen: BTreeMap<String, ObservedControlHighwater>", code)
        self.assertIn("let key = scope_id.to_owned()", code)
        self.assertIn("split_id: proof.split_id.clone()", code)
        self.assertIn("verify_strict(", code)
        self.assertIn("proof.challenge_nonce != nonce", code)
        self.assertIn("proof.sequence < previous.sequence", code)
        self.assertIn("proof.sequence == previous.sequence && observed != *previous", code)
        self.assertIn("proof.wal_bytes <= previous.wal_bytes", code)
        self.assertIn("proof.route_fence < previous.route_fence", code)
        self.assertIn("proof.wal_inode != previous.wal_inode", code)
        self.assertRegex(
            code,
            r"previous\.original_cns_receipt_binding\.is_some\(\)\s*"
            r"&&\s*proof\.original_cns_receipt_binding\.is_none\(\)",
            "later signed Control WAL may not erase an original CNS commit binding",
        )
        # The closed-world lexer intentionally strips Rust string literals.
        # Verify the literal RPC method against source bytes, not stripped code.
        raw = (ROOT / path).read_text(encoding="utf-8")
        self.assertIn('const READ_METHOD: &str = "read_control_highwater";', raw)
        # An RPC read may send identity and freshness only, never the original
        # local WAL frontier for an untrusted service to echo-sign.
        self.assertNotRegex(code, r"pub\s+fn\s+sign_|SigningKey")
        self.assertNotIn("apply_governed_topology(", code)
        self.assertNotIn("publish_cutover(", code)
        self.assertNotIn("publish_once(", code)
        test_path = (
            "codex-rs/hepta-runtime/src/cell_split_control_highwater_unix_tests.rs"
        )
        tests = (ROOT / test_path).read_text(encoding="utf-8")
        for named in (
            "signed_unix_observer_requests_only_scope_split_and_fresh_challenge",
            "mismatched_signer_or_signed_replayed_nonce_never_returns_evidence",
            "even_a_validly_signed_remote_rollback_is_denied_by_client_ratchet",
            "signed_same_sequence_cannot_rewrite_checkpoint_or_frozen_plan",
            "signed_newer_sequence_cannot_shrink_original_wal_or_lower_fences",
            "valid_signed_control_wal_append_is_accepted_without_evicting_history",
            "signed_later_control_wal_cannot_forget_an_original_cns_receipt_binding",
            "changed_original_cns_binding_requires_begin_commit_and_new_route_fence",
            "signed_new_split_id_cannot_reset_original_scope_wal_ratchet",
            "new_split_may_follow_actual_same_inode_wal_append_without_erasing_scope_ratchet",
            "malformed_denial_and_oversized_frame_are_rejected_before_positive_proof",
            "missing_or_symlinked_socket_and_unbounded_timeout_fail_closed",
            "truncated_frame_times_out_within_bounded_read_budget",
        ):
            self.assertIn(f"fn {named}(", tests)

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
            "let mut tail_storage = [0_u8; MAX_ROW]",
            "let tail = &mut tail_storage[..tail_bytes]",
            "read_exact_at(tail,",
            "last.sequence != expected_sequence",
            "last.head != expected_head",
            "last.head != event_hash(&last)",
        ):
            self.assertIn(assertion, code, f"Control WAL tail fence missing: {assertion}")
        self.assertNotIn(
            "vec![0_u8; tail_bytes]",
            code,
            "Control tick/readback cannot allocate a WAL tail Vec",
        )
        native = (
            ROOT / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn fixed_stack_original_control_wal_tail_protects_short_and_multirow_histories()",
            native,
            "real short/long fsynced WAL corruption tests must survive",
        )
        self.assertNotIn("state.verify_original_paths()", code)

        body = self.locked_original_cns_receipt_body(code)
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

    def test_original_control_wal_requires_canonical_parent_before_open(self) -> None:
        # Original Control WAL and its owner-lock marker share a single
        # canonical persistent identity. The native symlink-ancestor fixture
        # exercises actual Unix behavior; this early B4 audit makes removal
        # of the production bootstrap guard review-visible before expensive
        # Rust owner suites run.
        relative = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        production = self.lexical_code(relative)
        bootstrap = production.find("pub fn open_production(")
        self.assertGreaterEqual(bootstrap, 0, "original Control bootstrap missing")
        open_lock = production.find("let mut lock_flags =", bootstrap)
        self.assertGreater(
            open_lock, bootstrap, "original persistent lock opener missing"
        )
        prefix = production[bootstrap:open_lock]
        self.assertRegex(
            prefix,
            r"if\s+parent\s*\.canonicalize\(\)\s*\.map_err\(\|_\|\s*"
            r"NduPublicationErrorV1::UnsafePath\)\?\s*!=\s*parent\s*"
            r"\{\s*return\s+Err\(NduPublicationErrorV1::UnsafePath\);\s*\}",
            "noncanonical ancestor must fail before opening original WAL or lock",
        )
        test_source = (
            ROOT / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn symlink_in_ancestor_cannot_alias_or_bootstrap_original_control_owner()",
            test_source,
            "original Unix symlink-ancestor regression must remain present",
        )

    def test_original_control_wal_custody_requires_effective_unix_uid(self) -> None:
        # Private 0700/0600 modes and matching file/path owners alone do not
        # prevent a privileged process adopting another principal's frontier.
        code = self.lexical_code("codex-rs/hepta-control-plane/src/ndu_publication.rs")
        self.assertIn(
            "rustix::process::geteuid().as_raw()",
            code,
            "original Control must compare the actual process EUID",
        )
        self.assertEqual(
            code.count(
                "!control_original_owner_uid_matches_euid(opened.uid(), named.uid())"
            ),
            2,
            "WAL/marker and pinned parent both need the effective-principal fence",
        )
        manifest = (
            ROOT / "codex-rs/hepta-control-plane/Cargo.toml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'rustix = { workspace = true, features = ["fs", "process"] }',
            manifest,
            "Unix UID read must be safe and enabled in the locked workspace",
        )
        native = (
            ROOT / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn original_control_wal_requires_effective_uid_for_private_owner_and_reopen()",
            native,
            "must exercise real fsynced original WAL recovery and foreign UID cases",
        )

    def test_original_control_marker_read_is_pinned_and_postchecked(self) -> None:
        # A path-based marker read after inode preflight can accept data
        # from a different file. This Audit protects the original locked FD
        # positional read and final name-to-FD revalidation. A real Unix
        # deterministic rebind fixture must also remain in the same source.
        relative = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        code = self.lexical_code(relative)
        start = code.find("fn verify_original_paths_with_identity_hook(")
        end = code.find("fn verify_original_full_history(", start)
        self.assertGreaterEqual(start, 0, "original Control marker verifier missing")
        self.assertGreater(end, start, "original full-history verifier missing")
        body = code[start:end]
        self.assertNotIn(
            "fs::read(&self.lock_path)",
            body,
            "owner-lock content must never be reopened by mutable pathname",
        )
        self.assertRegex(
            body,
            r"self\.owner_lock\s*\.read_exact_at\(",
            "marker content must come from the already locked original FD",
        )
        self.assertIn(
            "MAX_CONTROL_OWNER_MARKER_BYTES",
            body,
            "marker read must use a fixed bounded stack buffer",
        )
        self.assertIn(
            "encode_control_owner_marker_v1(device, inode)",
            body,
            "live marker identity must use the allocation-free bounded encoder",
        )
        encoder_start = code.find("fn encode_control_owner_marker_v1(")
        encoder_end = code.find("fn control_parent_dir_identity(", encoder_start)
        self.assertGreaterEqual(encoder_start, 0, "original marker encoder missing")
        self.assertGreater(encoder_end, encoder_start, "marker encoder not bounded")
        encoder = code[encoder_start:encoder_end]
        for required in (
            "let mut marker = [0_u8; MAX_CONTROL_OWNER_MARKER_BYTES]",
            "let mut decimal = [0_u8; 20]",
            ".checked_add(digits.len() + 1)",
            "if end > marker.len()",
        ):
            self.assertIn(required, encoder)
        for forbidden in ("format!(", "String::", "Vec::", "vec![", ".to_owned()"):
            self.assertNotIn(forbidden, encoder, "no heap allocation per marker")
        self.assertNotIn(
            "format!(", body, "live owner must not allocate a marker String",
        )
        self.assertIn(
            "recorded[..expected_len] != expected[..expected_len]",
            body,
            "original locked FD marker must match exact decimal bytes",
        )
        recheck = body.rfind(
            "control_owner_file_identity(&self.owner_lock, &self.lock_path)?;"
        )
        self.assertGreater(
            recheck,
            body.find(".read_exact_at("),
            "live marker pathname must be rechecked after the positional read",
        )
        native = (
            ROOT / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn live_control_owner_rejects_same_bytes_rebound_marker_after_identity_check()",
            native,
            "same-byte different-inode owner marker fault regression is mandatory",
        )
        self.assertIn(
            "fn fixed_stack_control_owner_marker_matches_original_decimal_grammar()",
            native,
            "original decimal marker must match u64 carry and maximum boundaries",
        )

    def test_original_control_wal_uses_pinned_dirfd_for_both_children(self) -> None:
        # Local owner writes must never resolve the journal or owner-lock by
        # a second mutable absolute pathname after checking a private parent.
        # The actual rename/rebind proof remains the native Unix test below.
        relative = "codex-rs/hepta-control-plane/src/ndu_publication.rs"
        code = self.lexical_code(relative)
        bootstrap = code.find("fn open_production_with_directory_hook(")
        self.assertGreaterEqual(bootstrap, 0, "pinned directory owner missing")
        inspect_start = code.find("pub fn inspect_original_pending_begin_v1(", bootstrap)
        self.assertGreater(
            inspect_start,
            bootstrap,
            "read-only original Begin recovery must follow the canonical writer",
        )
        live = code[bootstrap:inspect_start]
        self.assertIn(
            "control_parent_dir_identity(&parent_dir, parent)",
            live,
            "the pinned parent path must be rechecked after child opens",
        )
        self.assertRegex(
            live,
            r"unixfs::openat\(\s*&parent_dir,\s*"
            r"lock_path\s*\.file_name\(\)",
            "owner-lock must be opened relative to the original dirfd",
        )
        self.assertRegex(
            live,
            r"unixfs::openat\(\s*&parent_dir,\s*"
            r"path\.file_name\(\)",
            "original WAL must be opened relative to the same dirfd",
        )
        self.assertEqual(
            live.count("unixfs::openat("),
            2,
            "adding an unreviewed Control file opener is an authority change",
        )
        self.assertGreaterEqual(
            live.count("OFlags::NOFOLLOW"),
            3,
            "original directory and both children require no-follow flags",
        )
        self.assertNotIn("lock_options.open(", live)
        self.assertNotIn("journal_options.open(", live)
        # This is a SECOND, explicitly reviewed, non-mutating opener.
        # Preserve the original two writable openat calls and forbid any
        # additional hidden opener anywhere in the original Control module.
        observer = code[inspect_start : code.find("pub fn current(", inspect_start)]
        self.assertEqual(
            observer.count("unixfs::openat("),
            2,
            "only the original marker and WAL may be opened by the read-only observer",
        )
        self.assertEqual(
            code.count("unixfs::openat("),
            4,
            "extra Control file openers require independent review",
        )
        self.assertRegex(
            observer,
            r"let flags\s*=\s*OFlags::RDONLY\s*\|\s*OFlags::NOFOLLOW\s*"
            r"\|\s*OFlags::CLOEXEC",
            "both Observer files must be opened read-only and no-follow",
        )
        for forbidden in (
            "OFlags::RDWR",
            "OFlags::APPEND",
            "OFlags::CREATE",
            "OFlags::EXCL",
            ".write_all(",
            ".sync_all(",
            "publish_cutover_with_external_effect(",
        ):
            self.assertNotIn(
                forbidden,
                observer,
                f"read-only pending Begin observation may not gain effect authority: {forbidden}",
            )
        self.assertRegex(
            observer,
            r"marker\s*\.try_lock_shared\(\)",
            "observer must refuse an active original marker writer",
        )
        self.assertRegex(
            observer,
            r"file\.try_lock_shared\(\)",
            "observer must refuse an active original WAL writer",
        )
        for required in (
            "control_parent_dir_identity(&directory, parent)?",
            "control_owner_file_identity(&file, path)?",
            "control_owner_file_identity(&marker, &marker_path)?",
            "validate_replay(&event, current, checkpoint, pending)",
            "let pending = pending.ok_or(NduPublicationErrorV1::Stale)?",
            "current != Some(predecessor)",
            "before.mtime() != after.mtime()",
            "before.ctime() != after.ctime()",
        ):
            self.assertIn(
                required,
                observer,
                "independent forensic read must replay and repin the ORIGINAL bytes",
            )
        native = (
            ROOT / "codex-rs/hepta-control-plane/src/ndu_publication_tests.rs"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "fn pinned_dirfd_keeps_original_wal_bootstrap_out_of_rebound_directory()",
            native,
            "deterministic Unix postcheck directory-rebind fixture missing",
        )

    def test_orphan_control_cns_join_does_not_gain_mutation_authority(self) -> None:
        source = self.lexical_code(
            "codex-rs/hepta-runtime/src/cell_split_cns_runtime_port.rs"
        )
        start = source.find("pub fn inspect_orphan_control_and_signed_cns_v1(")
        end = source.find("fn live_runtime(", start)
        self.assertGreater(start, 0, "read-only orphan join must exist")
        self.assertGreater(end, start, "read-only join must be method-scoped")
        observation = source[start:end]
        self.assertIn(
            "pub posture: NonAuthorizingPosture,",
            source,
            "successful forensic diagnostics must carry a sealed no-authority type",
        )
        self.assertIn(
            "posture: NonAuthorizingPosture::DENY_ALL,",
            observation,
            "the only successful forensic result must deny all effect authority",
        )
        for forbidden in (
            "apply_governed_topology(",
            "publish_cutover_with_external_effect(",
            "publish_once(",
            "take_admitted_successor(",
            "persist_actual_runtime_receipt(",
        ):
            self.assertNotIn(
                forbidden,
                observation,
                "orphan evidence must never invoke a mutation or Final-use owner",
            )
        # Lexical code strips comments and string literals deliberately.
        # Count genuine original-owner calls, not diagnostic message text.
        for required, minimum in (
            ("inspect_original_pending_begin_v1(", 3),
            ("verify_original_commit(", 2),
            ("signed_route(", 2),
        ):
            self.assertGreaterEqual(
                observation.count(required),
                minimum,
                "the original WAL, signed CNS record and live route need replay",
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
