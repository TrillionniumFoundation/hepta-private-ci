from __future__ import annotations

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
        caller = (
            "fn use_gate(gate: &Gate) { gate.enter(); }\n"
            if method_pattern
            else "fn use_gate() { Gate::enter(); }\n"
        )
        (root / "codex-rs/caller/src/lib.rs").write_text(caller, encoding="utf-8")
        pattern = (
            'call_pattern = "gate\\\\s*\\\\.\\\\s*enter\\\\s*\\\\("\n'
            if method_pattern
            else ""
        )
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
        self.assertEqual(
            receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"]
        )

    def test_typed_receiver_rejects_arbitrary_unregistered_parameter(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = manifest.read_text()
        text = "\n".join(
            line for line in text.splitlines() if not line.startswith("call_pattern =")
        )
        manifest.write_text(
            text.replace(
                'symbol = "Gate::enter"',
                'symbol = "Gate::enter"\nreceiver_type = "Gate"',
            )
            + "\n"
        )
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "fn bypass(completely_different: &Gate) { completely_different.enter(); }\n"
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_receiver_rejects_arbitrary_field_alias_in_split_impl(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(
            line
            for line in manifest.read_text().splitlines()
            if not line.startswith("call_pattern =")
        )
        manifest.write_text(
            text.replace(
                'symbol = "Gate::enter"',
                'symbol = "Gate::enter"\nreceiver_type = "Gate"',
            )
            + "\n"
        )
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text("struct Owner { anything: Gate }\n")
        (extra / "child.rs").write_text(
            "impl Owner { fn bypass(&self) { self.anything.enter(); } }\n"
        )
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"):
            MODULE.verify(root, manifest)

    def test_typed_related_method_cannot_bypass_closed_set(self) -> None:
        root = self.make_fixture(method_pattern=True)
        manifest = root / "CALLERS.toml"
        text = "\n".join(
            line
            for line in manifest.read_text().splitlines()
            if not line.startswith("call_pattern =")
        )
        manifest.write_text(
            text.replace(
                'symbol = "Gate::enter"',
                'symbol = "Gate::enter"\nreceiver_type = "Gate"\nreceiver_methods = ["enter", "enter_next"]',
            )
            + "\n"
        )
        extra = root / "codex-rs/extra/src"
        extra.mkdir(parents=True)
        (extra / "lib.rs").write_text(
            "fn bypass(unexpected: &Gate) { unexpected.enter_next(); }\n"
        )
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
        self.assertEqual(
            receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"]
        )

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
        self.assertNotIn(
            "Gate::enter",
            MODULE._strip_cfg_test_items(
                "#[cfg(all(test, unix))] fn only_test() { Gate::enter(); }"
            ),
        )

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
        (extra / "lib.rs").write_text(
            "fn bypass() { Gate::enter(); }\n", encoding="utf-8"
        )
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
        self.assertEqual(
            receipt["boundaries"][0]["productCallers"], ["codex-rs/caller/src/lib.rs"]
        )

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


class RequiredCodeOrderTests(unittest.TestCase):
    def check(self, source: str, order=None) -> list[str]:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "rotation.rs").write_text(source)
            row = {
                "path": "rotation.rs",
                "required": [],
                "forbidden": [],
                "required_order": order
                if order is not None
                else [
                    [
                        "predecessor.validate_successor(successor)?",
                        ".put_lease(",
                    ]
                ],
            }
            return MODULE._verify_protected_files(root, {"protected_file": [row]})

    def test_original_pre_cas_shape_order_passes(self):
        self.assertEqual(
            self.check(
                "fn rotate() { predecessor.validate_successor(successor)?; leases.put_lease(next); }"
            ),
            ["rotation.rs"],
        )

    def test_late_validation_keeps_both_markers_but_is_rejected(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.check(
                "fn rotate() { leases.put_lease(next); predecessor.validate_successor(successor)?; }"
            )

    def test_comment_or_string_cannot_supply_pre_cas_validation(self):
        for fake in (
            "// predecessor.validate_successor(successor)?\n",
            'let fake = "predecessor.validate_successor(successor)?"; ',
        ):
            with self.subTest(fake=fake), self.assertRaises(MODULE.VerificationFailure):
                self.check(
                    fake
                    + "fn rotate() { leases.put_lease(next); predecessor.validate_successor(successor)?; }"
                )

    def test_malformed_or_missing_code_order_is_rejected(self):
        for order in (
            "invalid",
            ["invalid"],
            [["only-one"]],
            [[1, 2]],
            [["", "second"]],
        ):
            with (
                self.subTest(order=order),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check("fn rotate() {}", order)
        with self.assertRaises(MODULE.VerificationFailure):
            self.check("fn rotate() { predecessor.validate_successor(successor)?; }")


class FunctionOrderTests(unittest.TestCase):
    def verify(self, source, *, top_level=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.rs").write_text(source)
            return MODULE._verify_protected_files(
                root,
                {
                    "protected_file": [
                        {
                            "path": "source.rs",
                            "required": [],
                            "forbidden": [],
                            "required_function_order": [
                                {
                                    "function": "fn bind(",
                                    "sequence": ["listen()?", "ready()?", "finish()"],
                                    "top_level": list(top_level),
                                }
                            ],
                        }
                    ]
                },
            )

    def test_original_order_inside_one_function(self):
        self.verify("fn bind(ready: impl FnOnce()) { listen()?; ready()?; finish() }")

    def test_functions_cannot_supply_each_others_markers(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify(
                "fn bind() { listen()?; } fn unrelated() { ready()?; finish() }"
            )

    def test_early_ready_is_rejected(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify("fn bind() { ready()?; listen()?; finish() }")

    def test_comments_and_strings_cannot_supply_the_missing_order(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify(
                'fn bind() { ready()?; listen()?; /* ready()? */ "ready()?"; finish() }'
            )

    def test_test_only_function_cannot_supply_production_body(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unique code function"):
            self.verify("#[cfg(test)] fn bind() { listen()?; ready()?; finish() }")

    def test_duplicate_function_is_not_an_unambiguous_guard(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "unique code function"):
            self.verify("fn bind() { listen()?; } fn bind() { ready()?; finish() }")

    def test_function_declaration_cannot_borrow_a_later_body(self):
        with self.assertRaisesRegex(
            MODULE.VerificationFailure, "function body required"
        ):
            self.verify(
                "trait A { fn bind(); } fn other() { listen()?; ready()?; finish() }"
            )

    def test_unused_nested_function_cannot_supply_the_outer_order(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify("fn bind() { fn unused() { listen()?; ready()?; finish() } }")

    def test_nested_raw_identifier_function_cannot_supply_the_outer_order(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify("fn bind() { fn r#unused() { listen()?; ready()?; finish() } }")

    def test_nested_unicode_function_cannot_supply_the_outer_order(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.verify("fn bind() { fn 未调用() { listen()?; ready()?; finish() } }")

    def test_registered_closure_keeps_its_actual_call_markers(self):
        self.verify("fn bind() { register(|| { listen()?; ready()?; finish() }); }")

    def test_callback_and_return_are_in_the_outer_function_body(self):
        self.verify(
            "fn bind() { listen()?; ready()?; finish() }", top_level=("ready()?;",)
        )

    def test_uncalled_closure_cannot_hide_the_outer_ready_callback(self):
        with self.assertRaisesRegex(
            MODULE.VerificationFailure, "top-level function code"
        ):
            self.verify(
                "fn bind() { listen()?; let unused = || { ready()?; }; finish() }",
                top_level=("ready()?;",),
            )

    def test_conditional_branch_cannot_hide_the_outer_ready_callback(self):
        with self.assertRaisesRegex(
            MODULE.VerificationFailure, "top-level function code"
        ):
            self.verify(
                "fn bind() { listen()?; if condition { ready()?; } finish() }",
                top_level=("ready()?;",),
            )


class OriginalNotesSourceGuardTests(unittest.TestCase):
    """Exercise registered guards against mutations of the actual product source."""

    def check_source(self, filename, mutate=None):
        return self.check_path_source(
            f"codex-rs/hepta-agentd/src/{filename}.rs", mutate
        )

    def check_path_source(self, path, mutate=None):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        rows = [row for row in manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        if mutate is not None:
            source = mutate(source)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            return MODULE._verify_protected_files(root, {"protected_file": rows})

    def replace_once(self, old, new, *, within=None):
        def mutate(source):
            before, body = (
                source.split(within, 1) if within is not None else ("", source)
            )
            self.assertIn(old, body)
            changed = body.replace(old, new, 1)
            return before + (within or "") + changed

        return mutate

    def test_current_original_notes_sources_pass(self):
        for filename in (
            "notes_thread_seed",
            "notes_thread_execution",
            "notes_thread_status",
            "notes_thread_runtime",
            "notes_thread_proof",
            "notes_thread_recorded",
            "notes_recovery_selection",
            "app_runtime",
            "runtime",
        ):
            with self.subTest(filename=filename):
                self.check_source(filename)

    def test_notes_status_discovery_keeps_original_proof_and_read_bounds(self):
        for old, new in (
            ("const TURNS: usize = 16", "const TURNS: usize = 64"),
            ("const TOTAL_ITEMS: usize = 1024", "const TOTAL_ITEMS: usize = 65536"),
            ("end: tokio::time::Instant", "end: std::time::Instant"),
            ("entry.turn_id != turn.id", "false"),
            (
                "VerifiedNotesThreadOperation::from_original_item",
                "unverified_history_reference",
            ),
        ):
            with (
                self.subTest(old=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_status", self.replace_once(old, new))

    def test_status_discovery_preserves_every_budget_and_the_single_deadline(self):
        for old, new in (
            ("const PAGE_ITEMS: usize = 64", "const PAGE_ITEMS: usize = 4096"),
            ("const TURN_PAGES: usize = 4", "const TURN_PAGES: usize = 100"),
            ("const RPCS: usize = 64", "const RPCS: usize = 1024"),
            ("let mut rpc_count = 1", "let mut rpc_count = 0"),
            ("rpc_count += 1", "rpc_count += 0"),
            ("rpc_count >= RPCS || item_count >= TOTAL_ITEMS", "false"),
            ("item_count += page.data.len()", "item_count += 0"),
            ("item_count > TOTAL_ITEMS", "false"),
            (
                "let page = tokio::time::timeout_at(\n                end,",
                "let page = tokio::time::timeout_at(\n                tokio::time::Instant::now() + Duration::from_secs(5),",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_status", self.replace_once(old, new))

    def test_status_cannot_select_the_wrong_turn_order_or_unbound_items(self):
        for old, new in (
            ("SortDirection::Desc", "SortDirection::Asc"),
            ("SortDirection::Asc", "SortDirection::Desc"),
            ("turn_id: Some(turn.id.clone())", "turn_id: None"),
            ("!seen_turns.insert(turn.id.clone())", "false"),
            ("turn.items_view != TurnItemsView::NotLoaded", "false"),
            ("!turn.items.is_empty()", "false"),
            ("namespace.is_none()", "true"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_status", self.replace_once(old, new))

    def test_status_cannot_skip_incomplete_newer_turns_or_repeat_cursors(self):
        for old, new in (
            ("if cursor.is_some() {", "if false {"),
            ("next.is_empty()", "false"),
            ("next.len() > 2048", "false"),
            ("!seen_cursors.insert(next.clone())", "false"),
            ("if turns.next_cursor.is_some()", "if false"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_status", self.replace_once(old, new))

    def test_status_callback_keeps_seed_and_human_checks_in_actual_code(self):
        for old, within in (
            (
                "crate::verify_original_notes_thread_seed(&client, seed).await?;",
                "async fn connect(",
            ),
            (
                "let human = connection.verify_human_turn(&state, &self.adapter, call.turn_id()).await?;",
                "async fn run_bound(",
            ),
            (
                "let call = connection.verify(&params).await?;",
                "async fn run_bound(",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source(
                    "notes_thread_runtime",
                    self.replace_once(old, "/*" + old + "*/", within=within),
                )

    def test_status_selector_is_strict_and_cannot_bypass_argument_validation(self):
        with self.assertRaises(MODULE.VerificationFailure):
            self.check_source(
                "notes_thread_status",
                self.replace_once(
                    "#[serde(deny_unknown_fields)]\npub(super) struct StatusSelector",
                    "pub(super) struct StatusSelector",
                ),
            )
        with self.assertRaises(MODULE.VerificationFailure):
            self.check_source(
                "notes_thread_proof",
                self.replace_once("navigation.validate()", "Ok(())"),
            )

    def test_unknown_status_never_fabricates_an_original_operation_identity(self):
        for old, new in (
            ('"original_reference":null', '"original_reference":params.call_id'),
            ('"operation_id":null', '"operation_id":params.call_id'),
            (
                '"app_server_session_id":self.route.app_server_session_id,',
                '"app_server_session_id":"unknown",',
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source(
                    "notes_thread_runtime",
                    self.replace_once(old, new, within="async fn run_bound("),
                )

    def test_core_and_recorded_navigation_cannot_restart_the_shared_deadline(self):
        for old, new in (
            (
                "let end = tokio::time::Instant::now() + Duration::from_secs(5)",
                "let end = tokio::time::Instant::now() + Duration::from_secs(10)",
            ),
            (
                "status::discover_latest_original_replace(&self.route, &mut connection, end)",
                "status::discover_latest_original_replace(&self.route, &mut connection, tokio::time::Instant::now() + Duration::from_secs(5))",
            ),
            (
                "self.adapter.latest_recorded_thread_operation(&self.route, end)",
                "self.adapter.latest_recorded_thread_operation(&self.route, tokio::time::Instant::now() + Duration::from_secs(5))",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source(
                    "notes_thread_runtime",
                    self.replace_once(old, new, within="async fn run_bound("),
                )
        for old, new in (
            ("if !lookup_budget_available(end)", "if false"),
            (
                "match tokio::time::timeout_at(end, async",
                "match tokio::time::timeout(Duration::from_secs(5), async",
            ),
            (
                "latest_matching_request(scope, requests, end)?",
                "unbounded_latest(scope, requests)?",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source(
                    "notes_thread_recorded",
                    self.replace_once(
                        old, new, within="async fn latest_recorded_thread_operation("
                    ),
                )

    def test_retained_receipt_cannot_turn_incomplete_core_navigation_into_success(self):
        for old, new in (
            (
                "&& !matches!(reason, status::StatusUnknownReason::OriginalReplaceNotObserved)",
                "&& false",
            ),
            (
                "return Ok(status::preserve_incomplete_navigation(unknown, observed))",
                "return Ok(observed)",
            ),
            ('&& value["status"] != "unknown"', "&& true"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_runtime", self.replace_once(old, new))
        for old, new in (
            (
                'unknown["operation_id"] = serde_json::Value::Null',
                'unknown["operation_id"] = observed["operation_id"].clone()',
            ),
            (
                'unknown["original_reference"] = serde_json::Value::Null',
                'unknown["original_reference"] = observed["original_reference"].clone()',
            ),
            (
                'unknown["last_known_retained_observation"] = observed',
                "unknown = observed",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_status", self.replace_once(old, new))

    def test_recorded_reference_must_match_signed_source_and_actual_operation(self):
        for old, new in (
            ("reference.app_server_session_id != route.app_server_session_id", "false"),
            (
                "ingress.body.model_tuple_digest != scope.bindings.model_tuple_digest.to_string()",
                "false",
            ),
            ("source.request_id != call_intent_id", "false"),
            ("exact_operation != operation.operation", "false"),
            (
                "source.principal_scope_digest != scope.bindings.principal_scope_digest",
                "false",
            ),
            ("== reference.callback_sha256", "== String::new()"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_recorded", self.replace_once(old, new))

    def test_original_sender_cut_remains_private_bounded_and_read_only(self):
        for filename in (
            "objective_sender_read",
            "objective_sender_store",
            "objective_sender_model",
            "objective_sender_integrity",
        ):
            self.check_path_source(f"codex-rs/hepta-memory/src/{filename}.rs")
        for filename, old, new in (
            (
                "objective_sender_read",
                "transaction.rollback().await",
                "transaction.commit().await",
            ),
            (
                "objective_sender_read",
                "self.writer.verify_authority().await?;",
                "/* self.writer.verify_authority().await?; */",
            ),
            (
                "objective_sender_store",
                "if requests.len() > MAX_REQUESTS as usize",
                "if false",
            ),
            ("objective_sender_store", "if foreign != 0", "if false"),
            (
                "objective_sender_model",
                'skip_serializing_if = "Option::is_none"',
                'skip_serializing_if = "always_false"',
            ),
            (
                "objective_sender_model",
                "MAX_REQUESTS: i64 = 1_024",
                "MAX_REQUESTS: i64 = 65_536",
            ),
            (
                "objective_sender_integrity",
                "verify_fence(tx, row, &binding).await?;",
                "/* verify_fence(tx, row, &binding).await?; */",
            ),
        ):
            with (
                self.subTest(file=filename, marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_path_source(
                    f"codex-rs/hepta-memory/src/{filename}.rs",
                    self.replace_once(old, new),
                )

    def test_recovery_selector_cannot_accept_ambiguous_or_unverified_selection(self):
        for old, new in (
            ("(Some(operation_id), None)", "(Some(operation_id), _)"),
            ("codex_hepta_types::StableId::new(&operation_id)", "Ok(())"),
            ("#[serde(deny_unknown_fields)]\n        struct Latest", "struct Latest"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source(
                    "notes_recovery_selection", self.replace_once(old, new)
                )
        with self.assertRaises(MODULE.VerificationFailure):
            self.check_source(
                "notes_thread_recorded",
                self.replace_once("original.target == *previous_target", "true"),
            )
        with self.assertRaises(MODULE.VerificationFailure):
            self.check_source(
                "notes_thread_tool",
                self.replace_once(
                    ".verify_persisted()?;", "/* .verify_persisted()?; */"
                ),
            )

    def test_original_callback_reference_is_validated_before_preparation(self):
        for old, new in (
            ("original_reference.thread_id != human.route().thread_id", "false"),
            (
                "!recorded::callback_matches(&original_reference, text, expected_revision)?",
                "false",
            ),
            (
                ".map(|binding| binding.original_reference.clone())",
                ".map(|_| untrusted_reference())",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_literal_adapter", self.replace_once(old, new))

    def test_new_read_only_apis_reject_an_unregistered_product_caller(self):
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        calls = {
            "notes_original_retained_reference_projection": "verified.recorded_reference(&route);",
            "memory_original_sender_read_only_cut": "sender.retained_owner_requests().await;",
            "notes_recorded_original_observation_proof": "adapter.latest_recorded_thread_operation(&route, end).await;",
            "notes_previous_recovery_typed_resolution": "config.with_original_notes_previous_recovery_request(request).await;",
        }
        for boundary in MODULE._boundary_rows(manifest):
            if boundary.identifier not in calls:
                continue
            index = {
                caller: MODULE._strip_cfg_test_items(
                    MODULE._strip_rust_non_code((ROOT / caller).read_text())
                )
                for caller in boundary.product_callers
            }
            index["codex-rs/unregistered/src/lib.rs"] = calls[boundary.identifier]
            with (
                self.subTest(boundary=boundary.identifier),
                self.assertRaisesRegex(MODULE.VerificationFailure, "unexpected"),
            ):
                MODULE._verify_boundary(
                    ROOT, boundary, index, tuple(manifest["ignored_path_fragments"])
                )

    def test_resume_requires_persisted_checks_in_the_original_function(self):
        for old, new in (
            ("receipt.verify_persisted()?;", ""),
            (
                "receipt.verify_persisted()?;",
                "/* receipt.verify_persisted()?; */",
            ),
            (
                "receipt.verify_persisted()?;",
                "fn unused() { receipt.verify_persisted()?; }",
            ),
        ):
            with (
                self.subTest(replacement=new),
                self.assertRaisesRegex(
                    MODULE.VerificationFailure, "required code order"
                ),
            ):
                self.check_source(
                    "notes_thread_seed",
                    self.replace_once(
                        old,
                        new,
                        within="pub async fn verify_original_notes_thread_seed(",
                    ),
                )

    def test_resume_requires_both_effective_configuration_observations(self):
        for stage in ("before", "after"):

            def mutate(source):
                start = source.index("pub async fn verify_original_notes_thread_seed(")
                marker = f'request_id("config-{stage}-resume")?'
                request = source.index(marker, start)
                begin = source.rfind(
                    "    notes_thread_execution::verify_effective(", start, request
                )
                end = source.index("    .await?;", request) + len("    .await?;")
                block = source[begin:end]
                # Keep every raw marker in a comment: only code order may reject it.
                return source[:begin] + "/*" + block + "*/" + source[end:]

            with (
                self.subTest(stage=stage),
                self.assertRaisesRegex(
                    MODULE.VerificationFailure, "required code order"
                ),
            ):
                self.check_source("notes_thread_seed", mutate)

    def test_original_resume_cannot_add_configuration_overrides(self):
        with self.assertRaisesRegex(MODULE.VerificationFailure, "required code order"):
            self.check_source(
                "notes_thread_seed",
                self.replace_once(
                    "exclude_turns: true,\n                ..Default::default()",
                    'exclude_turns: true,\n                model: Some("other".into()),\n                ..Default::default()',
                    within="async fn resume(",
                ),
            )

    def test_execution_files_and_layered_origin_cannot_be_substituted(self):
        for old, new in (
            ("Digest32::of_bytes(&config)", 'Digest32::of_bytes(b"constant")'),
            ("Digest32::of_bytes(&environments)", 'Digest32::of_bytes(b"constant")'),
            ("include_local = false", "include_local = true"),
            ("hepta_memory = false", "hepta_memory = true"),
            ("hepta_cognitive_write = false", "hepta_cognitive_write = true"),
            ("fields.iter().all(", "fields.iter().any("),
            (
                "ConfigLayerSource::User { file, .. }",
                "ConfigLayerSource::Project { file, .. }",
            ),
            ("while let Some((key, value)) = pending.pop()", "while false"),
            ("Some(&serde_json::to_value(expected_provider)?)", "None"),
            ("before.modified()? != after.modified()?", "false"),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("notes_thread_execution", self.replace_once(old, new))

    def test_original_notes_producer_cannot_restore_general_cognitive_tools(self):
        for old, new in (
            ("Self::OriginalNotes => false", "Self::OriginalNotes => true"),
            (
                "production_cognitive_mutation.filter(|_| cognitive_tools_enabled)",
                "production_cognitive_mutation",
            ),
            (
                "required_feature_states.insert(Feature::HeptaMemory, false)",
                "required_feature_states.insert(Feature::HeptaMemory, true)",
            ),
            (
                "let cognitive_write_enabled = model_tools.cognitive_tools_enabled()",
                "let cognitive_write_enabled = true",
            ),
        ):
            with (
                self.subTest(marker=old),
                self.assertRaises(MODULE.VerificationFailure),
            ):
                self.check_source("app_runtime", self.replace_once(old, new))

    def test_actual_notes_producer_must_select_the_private_original_profile(self):
        with self.assertRaises(MODULE.VerificationFailure):
            self.check_source(
                "runtime",
                self.replace_once(
                    "crate::app_runtime::AppServerModelToolProfile::OriginalNotes",
                    "crate::app_runtime::AppServerModelToolProfile::Standard",
                ),
            )


if __name__ == "__main__":
    unittest.main()
