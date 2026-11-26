"""Mutation checks for every inventoried privileged row's lexical call forms."""

from dataclasses import replace
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

from verify_hepta_callers import (
    VerificationFailure,
    _boundary_rows,
    _strip_rust_non_code,
    _verify_boundary,
    normalize_symbol_aliases,
    symbol_aliases,
)

ROOT = Path(__file__).resolve().parents[1]


class PrivilegedInvocationFormsTests(unittest.TestCase):
    def rows(self):
        policy = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )
        ids = {row["id"] for row in policy["boundaries"]}
        return [
            row
            for row in _boundary_rows(
                tomllib.loads((ROOT / "CALLERS.toml").read_text())
            )
            if row.identifier in ids
        ]

    def check_call(self, row, code, expected, extra=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            owner = "fn owner_marker() {}"
            if row.receiver_associated_only:
                owner += (
                    f" impl {row.receiver_type} {{ "
                    + " ".join(
                        f"pub fn {method}() {{}}" for method in row.receiver_methods
                    )
                    + " }"
                )
            (root / "owner.rs").write_text(owner)
            boundary = replace(
                row,
                definition_path="owner.rs",
                definition_markers=("fn owner_marker",),
                product_callers=(),
                caller_markers=(),
            )
            if expected:
                with self.assertRaises(VerificationFailure):
                    _verify_boundary(
                        root, boundary, {"rogue.rs": code, **(extra or {})}, ()
                    )
            else:
                self.assertEqual(
                    _verify_boundary(
                        root, boundary, {"rogue.rs": code, **(extra or {})}, ()
                    )["productCallers"],
                    [],
                )

    def typed_cases(self):
        for row in self.rows():
            if not row.receiver_type:
                continue
            specs = [(row.receiver_type, method) for method in row.receiver_methods]
            specs += [tuple(item.split("::")) for item in row.receiver_alternatives]
            for target, method in specs:
                prefixes = [
                    f"{target}::",
                    f"<crate::{target}>::",
                    f"<:: alias::{target}>::",
                ]
                if not row.receiver_associated_only:
                    prefixes.append("gate.")
                for prefix in prefixes:
                    code = f"fn f(gate: &{target}) {{ {prefix}r#{method}(args); }}"
                    yield row, target, method, code

    def test_all_typed_rows_reject_raw_method_calls(self):
        for row, target, method, code in self.typed_cases():
            with self.subTest(boundary=row.identifier, code=code):
                self.check_call(row, code, True)

    def test_explicit_unrelated_types_do_not_become_authority_receivers(self):
        for row, target, method, _ in self.typed_cases():
            for call in (
                f"Other::r#{method}(args)",
                f"<crate::Other>::r#{method}(args)",
                f"other.r#{method}(args)",
            ):
                code = f"fn f(gate: &{target}, other: &Other) {{ {call}; }}"
                with self.subTest(boundary=row.identifier, code=code):
                    self.check_call(row, code, False)

    def test_comments_strings_and_method_definitions_do_not_create_callers(self):
        for row, target, method, call in self.typed_cases():
            for raw in (
                f'let text = "{call}";',
                f"/* {call} */",
                f"impl {target} {{ fn r#{method}(&self) {{}} }}",
            ):
                with self.subTest(boundary=row.identifier, code=raw):
                    self.check_call(row, _strip_rust_non_code(raw), False)

    def test_b4_qualified_raw_forms_preserve_each_independent_boundary(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        patterns = {row["id"]: row["callPatterns"] for row in rows}
        for row, target, method, code in self.typed_cases():
            if "gate.r#" in code:
                # B4 preserves its pre-existing named-receiver constraints.
                # The primary proof above covers arbitrary typed local names.
                continue
            with self.subTest(boundary=row.identifier, code=code):
                self.assertTrue(
                    any(
                        re.search(pattern, code) for pattern in patterns[row.identifier]
                    )
                )

    def test_explicit_sibling_verifier_fields_keep_distinct_types(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        header = "struct Host { feed: FinalUseRevocationFeedVerifier, approval: FinalUseApprovalVerifier } "
        for field, expected in (("feed", True), ("approval", False)):
            code = (
                header
                + f"impl Host {{ fn f(&self) {{ self.{field}.r#verify(args); }} }}"
            )
            with self.subTest(field=field):
                self.check_call(row, code, expected)

    def test_both_types_of_async_entry_are_checked_without_marker_bypass(self):
        row = next(
            row for row in self.rows() if row.identifier == "final_use_async_entry"
        )
        for target, method in (
            ("VerifiedUseToken", "enter"),
            ("FinalUseAuthority", "enter_verified_use"),
        ):
            self.check_call(
                row, f"fn f(gate: &{target}) {{ gate.r#{method}(args); }}", True
            )
            self.check_call(
                row,
                f"fn f(gate: &{target}, other: &Other) {{ other.r#{method}(args); }}",
                False,
            )

    def test_receiver_configuration_rejects_malformed_alternatives(self):
        data = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        row = next(
            row for row in data["boundary"] if row["id"] == "final_use_async_entry"
        )
        for value in (
            ["VerifiedUseToken::enter::extra"],
            [""],
            [3],
            "VerifiedUseToken::enter",
        ):
            with self.subTest(value=value), self.assertRaises(VerificationFailure):
                _boundary_rows({"boundary": [{**row, "receiver_alternatives": value}]})

    def test_balanced_unrelated_generic_constructor_keeps_nominal_type(self):
        row = next(
            row for row in self.rows() if row.identifier == "bao_final_use_host_new"
        )
        for receiver in (
            "BTreeMap::<Role, BTreeSet<(String, String)>>",
            "BTreeSet::<String>",
        ):
            self.check_call(
                row, f"fn f(host: &BaoFinalUseHost) {{ {receiver}::r#new(); }}", False
            )
        self.check_call(row, "fn f() { <crate::BaoFinalUseHost>::r#new(args); }", True)

    def test_generic_sibling_field_is_not_misclassified_as_unrelated(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for fields in (
            "feed: FinalUseRevocationFeedVerifier, nested: Wrapper<Other, FinalUseRevocationFeedVerifier>",
            "nested: Wrapper<Other, FinalUseRevocationFeedVerifier>",
        ):
            code = f"struct Host {{ {fields} }} impl Host {{ fn f(&self) {{ self.nested.verify(); }} }}"
            with self.subTest(fields=fields):
                self.check_call(row, code, True)

    def test_constructor_wrappers_cannot_hide_authority_receivers(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for expression in (
            "Arc::new(FinalUseRevocationFeedVerifier::new())",
            "Arc::new(inner)",
            "std::sync::Arc::new(inner)",
            "Box::new(inner)",
            "Factory::make(inner)",
        ):
            code = f"fn f(inner: FinalUseRevocationFeedVerifier) {{ let gate = {expression}; gate.verify(); }}"
            with self.subTest(expression=expression):
                self.check_call(row, code, True)

    def test_generic_identity_alias_cannot_hide_authority_type(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        code = "type Identity<T> = T; fn f(gate: &FinalUseRevocationFeedVerifier) { Identity::<FinalUseRevocationFeedVerifier>::verify(gate); }"
        self.check_call(row, code, True)

    def test_explicit_free_function_aliases_remain_privileged(self):
        policy = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )
        patterns = {row["id"]: row["callPatterns"] for row in policy["boundaries"]}
        for row in self.rows():
            if row.receiver_type:
                continue
            for alias in (
                "renamed",
                "r#renamed",
                "改名",
                "cafe\u0301",
                "a\u0308\u0301",
            ):
                declaration = f"pub use crate::{row.symbol} as {alias};"
                for split in (False, True):
                    code = (
                        "" if split else declaration
                    ) + f" fn f() {{ {alias}(args); }}"
                    extra = {"exports.rs": declaration} if split else {}
                    with self.subTest(
                        boundary=row.identifier, alias=alias, split=split
                    ):
                        self.check_call(row, code, True, extra=extra)
                        aliases = symbol_aliases(
                            {"rogue.rs": code, **extra}, row.symbol
                        )
                        canonical = normalize_symbol_aliases(code, row.symbol, aliases)
                        self.assertTrue(
                            any(
                                re.search(pattern, canonical)
                                for pattern in patterns[row.identifier]
                            )
                        )

    def test_inner_shadow_does_not_erase_outer_authority_binding(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for shadow in ("let gate = other;", "let gate: Other = make_other();"):
            code = f"fn f(gate: &FinalUseRevocationFeedVerifier, other: &Other) {{ {{ {shadow} let _ = gate; }} gate.verify(); }}"
            self.check_call(row, code, True)

    def test_associated_only_signature_drift_is_rejected(self):
        row = next(
            row for row in self.rows() if row.identifier == "bao_final_use_host_new"
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            boundary = replace(
                row,
                definition_path="owner.rs",
                definition_markers=("pub fn new",),
                product_callers=(),
                caller_markers=(),
            )
            for signature in ("pub fn new(&self)", "pub fn new(self: Box<Self>)"):
                (root / "owner.rs").write_text(
                    "impl BaoFinalUseHost { " + signature + " {} }"
                )
                with (
                    self.subTest(signature=signature),
                    self.assertRaises(VerificationFailure),
                ):
                    _verify_boundary(root, boundary, {"rogue.rs": "fn f() {}"}, ())

    def test_typed_alias_with_combining_marks_is_not_truncated(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for alias in ("cafe\u0301", "a\u0308\u0301"):
            code = f"use crate::FinalUseRevocationFeedVerifier as {alias}; fn f(gate: &{alias}) {{ {alias}::verify(gate); }}"
            self.check_call(row, code, True)

    def test_target_bearing_type_alias_paths_cannot_disappear(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for rhs in (
            "crate::नमस्ते::FinalUseRevocationFeedVerifier",
            "Identity<FinalUseRevocationFeedVerifier>",
        ):
            code = f"type Gate = {rhs}; fn f(gate: &Gate) {{ Gate::verify(gate); }}"
            self.check_call(row, code, True)

    def test_alias_equal_to_method_does_not_rename_the_method_slot(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for call in (
            "gate.verify(args)",
            "gate.r#verify(args)",
            "verify::verify(gate, args)",
            "<verify>::verify(gate, args)",
        ):
            code = f"use crate::FinalUseRevocationFeedVerifier as verify; fn f(gate: &verify) {{ {call}; }}"
            with self.subTest(call=call):
                self.check_call(row, code, True)

    def test_grouped_calls_and_function_values_fail_closed(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        for body in (
            "(FinalUseRevocationFeedVerifier::verify)(gate)",
            "let invoke = FinalUseRevocationFeedVerifier::verify; invoke(gate)",
            "use crate::FinalUseRevocationFeedVerifier as verify; let invoke = verify::verify; invoke(gate)",
        ):
            self.check_call(
                row, f"fn f(gate: &FinalUseRevocationFeedVerifier) {{ {body}; }}", True
            )
        for row in self.rows():
            if row.receiver_type:
                continue
            for body in (
                f"({row.symbol})(args)",
                f"let invoke = {row.symbol}; invoke(args)",
            ):
                with self.subTest(boundary=row.identifier, body=body):
                    self.check_call(row, f"fn f() {{ {body}; }}", True)

    def test_qualified_alias_in_a_parameter_still_names_the_target(self):
        row = next(
            row
            for row in self.rows()
            if row.identifier == "final_use_revocation_feed_verify"
        )
        code = "use crate::FinalUseRevocationFeedVerifier as verify; fn f(gate: &crate::verify) { gate.verify(args); }"
        self.check_call(row, code, True)

    def test_non_callable_type_symbol_is_not_a_free_function_reference(self):
        rows = _boundary_rows(tomllib.loads((ROOT / "CALLERS.toml").read_text()))
        row = next(
            row
            for row in rows
            if row.identifier == "learning_artifact_verified_current_view"
        )
        self.check_call(
            row, "fn f(view: &VerifiedCurrentRegistryViewV1) { let _ = view; }", False
        )

    def test_free_function_kind_matches_the_independent_inventory(self):
        policy = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )
        expected = {
            boundary
            for source in policy["freeFunctions"]
            for boundary in source["privilegedFunctions"].values()
        }
        for row in self.rows():
            with self.subTest(boundary=row.identifier):
                self.assertEqual(row.free_function, row.identifier in expected)

    def test_associated_only_does_not_confuse_an_unrelated_returned_instance(self):
        row = next(
            row for row in self.rows() if row.identifier == "final_use_open_state"
        )
        self.check_call(
            row,
            "fn f(gate: &FinalUseAuthority) { ProductionFinalUseTrustContext::bind(args)?.open_state_dir(args); }",
            False,
        )


if __name__ == "__main__":
    unittest.main()
