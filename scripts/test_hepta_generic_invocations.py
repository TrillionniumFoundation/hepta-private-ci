"""Adversarial source-proof cases: generic syntax cannot hide an authority use."""

import json
from dataclasses import replace
import re
import tempfile
import tomllib
import unittest
from pathlib import Path

from hepta_typed_callers import (
    UnresolvedTypedReceiver,
    authority_fields,
    has_authority_call,
)
from verify_hepta_callers import (
    _boundary_rows,
    VerificationFailure,
    _strip_rust_non_code,
    _verify_boundary,
)

ROOT = Path(__file__).resolve().parents[1]


class GenericAuthorityInvocationTests(unittest.TestCase):
    def code(self, receiver, generic):
        return f"fn f(gate: &FinalUseAuthority) {{ {receiver}::<{generic}>(token, binding, || [0]); }}"

    def match(self, raw):
        code = _strip_rust_non_code(raw)
        return has_authority_call(
            code,
            "FinalUseAuthority",
            "with_verified_use",
            authority_fields({"rogue.rs": code}, "FinalUseAuthority"),
        )

    def cases(self):
        for receiver in (
            "gate.with_verified_use",
            "FinalUseAuthority::with_verified_use",
            "<FinalUseAuthority>::with_verified_use",
            "gate.r#with_verified_use",
            "FinalUseAuthority::r#with_verified_use",
            "<FinalUseAuthority>::r#with_verified_use",
            "<crate::FinalUseAuthority>::with_verified_use",
            "<crate::FinalUseAuthority>::r#with_verified_use",
            "<crate::nested::FinalUseAuthority>::with_verified_use",
            "<crate::r#FinalUseAuthority>::r#with_verified_use",
            "<crate::模块::FinalUseAuthority>::with_verified_use",
            "<:: alias::FinalUseAuthority>::with_verified_use",
            "< :: alias :: FinalUseAuthority >::r#with_verified_use",
        ):
            for generic in (
                "[u8; 1]",
                "{ let n = 1; n }",
                "Option<Result<[u8; 1], Vec<[u8; { 1 + 1 }]>>>",
                "fn(u8) -> Option<[u8; 1]>",
                "{ 1 << 2 }",
            ):
                yield self.code(receiver, generic)

    def test_three_receiver_forms_handle_arrays_consts_and_nested_generics(self):
        for code in self.cases():
            with self.subTest(code=code):
                self.assertTrue(self.match(code))

    def test_real_delivery_boundary_rejects_each_undeclared_generic_caller(self):
        for code in self.cases():
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "owner.rs").write_text("pub fn with_verified_use() {}")
                declared = _boundary_rows(
                    tomllib.loads((ROOT / "CALLERS.toml").read_text())
                )
                actual = next(
                    row
                    for row in declared
                    if row.identifier == "final_use_delivery_raw"
                )
                boundary = replace(
                    actual,
                    definition_path="owner.rs",
                    definition_markers=("pub fn with_verified_use",),
                    product_callers=(),
                    caller_markers=(),
                )
                with self.assertRaises(VerificationFailure):
                    _verify_boundary(root, boundary, {"rogue.rs": code}, ())

    def test_independent_b4_delivery_patterns_also_catch_generic_prefixes(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        row = next(row for row in rows if row["id"] == "final_use_delivery_raw")
        for code in self.cases():
            with self.subTest(code=code):
                self.assertTrue(any(re.search(p, code) for p in row["callPatterns"]))

    def test_comments_strings_and_method_definitions_are_not_calls(self):
        for code in (
            'fn f(gate: &FinalUseAuthority) { let text = "gate.with_verified_use::<[u8; 1]>(x)"; }',
            "fn f(gate: &FinalUseAuthority) { /* FinalUseAuthority::with_verified_use::<{1}>(x) */ }",
            "impl FinalUseAuthority { fn with_verified_use<T>(&self) {} }",
            "impl FinalUseAuthority { fn with_verified_use<const N: usize>(&self) {} }",
        ):
            with self.subTest(code=code):
                self.assertFalse(self.match(code))
                rows = json.loads(
                    (
                        ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json"
                    ).read_text()
                )["boundaries"]
                row = next(row for row in rows if row["id"] == "final_use_delivery_raw")
                clean = _strip_rust_non_code(code)
                self.assertFalse(any(re.search(p, clean) for p in row["callPatterns"]))

    def test_unsupported_explicit_target_qualified_types_fail_closed(self):
        for receiver in (
            "<(crate::FinalUseAuthority)>::with_verified_use",
            "<FinalUseAuthority as SomeTrait>::with_verified_use",
            "<FinalUseAuthority as SomeTrait<{ 1 < 2 }>>::with_verified_use",
            "<FinalUseAuthority" + " " * 8300 + ">::with_verified_use",
            "FinalUseAuthority" + " " * 8300 + "::with_verified_use",
        ):
            with (
                self.subTest(receiver=receiver),
                self.assertRaises(UnresolvedTypedReceiver),
            ):
                self.match(self.code(receiver, "[u8; 1]"))

    def test_raw_type_aliases_do_not_poison_method_identifiers(self):
        for declaration in (
            "use crate::FinalUseAuthority as r#Gate;",
            "type r#Gate = crate::FinalUseAuthority;",
        ):
            for receiver in (
                "<r#Gate>::r#with_verified_use",
                "r#Gate::r#with_verified_use",
                "Gate::with_verified_use",
                "gate.r#with_verified_use",
            ):
                code = (
                    declaration
                    + f" fn f(gate: &r#Gate) {{ {receiver}::<[u8; 1]>(x); }}"
                )
                with self.subTest(code=code):
                    self.assertTrue(self.match(code))

    def test_unrelated_explicit_receiver_stays_unrelated(self):
        self.assertFalse(
            self.match(
                "fn f(gate: &FinalUseAuthority, other: &Other) { other.with_verified_use::<[u8; 1]>(x); }"
            )
        )

    def test_unresolved_generic_receiver_fails_closed(self):
        with self.assertRaises(UnresolvedTypedReceiver):
            self.match(
                "fn f(gate: &FinalUseAuthority) { let opaque = factory(gate); opaque.with_verified_use::<[u8; 1]>(x); }"
            )

    def test_broken_generic_cannot_consume_a_later_statement(self):
        for suffix in ("::<T; other.call()>", "::<[u8; 1>", "::<{1}>"):
            with (
                self.subTest(suffix=suffix),
                self.assertRaises(UnresolvedTypedReceiver),
            ):
                self.match(
                    f"fn f(gate: &FinalUseAuthority) {{ gate.with_verified_use{suffix}; later(); }}"
                )


class EffectAuthorityInvocationTests(unittest.TestCase):
    def cases(self):
        for boundary_id, method, generic in (
            ("final_use_guarded_effect", "with_verified_effect", "[u8; 1]"),
            ("final_use_async_dispatch_fence", "with_verified_use_async", "[u8; 1], _"),
        ):
            for prefix in (
                "gate.",
                "FinalUseAuthority::",
                "<crate::FinalUseAuthority>::",
            ):
                for raw in ("", "r#"):
                    suffix = f"::<{generic}>"
                    yield (
                        boundary_id,
                        method,
                        (
                            f"async fn f(gate: &FinalUseAuthority) {{ {prefix}{raw}{method}{suffix}(token, binding, consumer); }}"
                        ),
                    )

    def test_actual_empty_caller_boundaries_reject_each_effect_invocation(self):
        declared = _boundary_rows(tomllib.loads((ROOT / "CALLERS.toml").read_text()))
        for boundary_id, method, code in self.cases():
            with (
                self.subTest(boundary=boundary_id, code=code),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                (root / "owner.rs").write_text(f"pub fn {method}() {{}}")
                actual = next(row for row in declared if row.identifier == boundary_id)
                boundary = replace(
                    actual,
                    definition_path="owner.rs",
                    definition_markers=(f"pub fn {method}",),
                    product_callers=(),
                    caller_markers=(),
                )
                with self.assertRaises(VerificationFailure):
                    _verify_boundary(root, boundary, {"rogue.rs": code}, ())

    def test_independent_b4_patterns_reject_each_effect_invocation(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        for boundary_id, method, code in self.cases():
            row = next(row for row in rows if row["id"] == boundary_id)
            with self.subTest(boundary=boundary_id, code=code):
                self.assertTrue(
                    any(
                        re.search(p, _strip_rust_non_code(code))
                        for p in row["callPatterns"]
                    )
                )

    def test_effect_comments_strings_and_definitions_are_shielded(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        for boundary_id, method, call in self.cases():
            row = next(row for row in rows if row["id"] == boundary_id)
            for code in (
                f'let text = "{call}";',
                f"/* {call} */",
                f"impl FinalUseAuthority {{ fn {method}<T>(&self) {{}} }}",
            ):
                with self.subTest(code=code):
                    self.assertFalse(
                        any(
                            re.search(p, _strip_rust_non_code(code))
                            for p in row["callPatterns"]
                        )
                    )


class RemainingGenericAuthorityInvocationTests(unittest.TestCase):
    METHODS = (
        (
            "final_use_dispatch_raw",
            "FinalUseAuthority",
            "with_dispatch_boundary",
            "[u8; 1]",
        ),
        (
            "authority_lease_delivery",
            "AuthorityLeaseVerifier",
            "with_verified_use",
            "[u8; 1]",
        ),
        (
            "authority_lease_dispatch_raw",
            "AuthorityLeaseVerifier",
            "with_dispatch_boundary",
            "[u8; 1]",
        ),
        (
            "bao_authbus_final_use_consumer",
            "BaoClient",
            "consume_kv_v2_with_authbus",
            "Provider",
        ),
        (
            "bao_final_use_consumer",
            "BaoClient",
            "consume_kv_v2_with_authbus",
            "Provider",
        ),
    )
    FUNCTIONS = (
        ("final_use_delivery", "deliver_final_use"),
        ("final_use_delivery_witness", "deliver_final_use_with_witness"),
        ("final_use_dispatch", "dispatch_final_use"),
        ("final_use_dispatch_witness", "dispatch_final_use_with_witness"),
        ("authority_lease_delivery_witness", "deliver_authority_lease_with_witness"),
        ("authority_lease_dispatch_witness", "dispatch_authority_lease_with_witness"),
    )

    def check_case(self, boundary_id, method, code, expected):
        declared = _boundary_rows(tomllib.loads((ROOT / "CALLERS.toml").read_text()))
        actual = next(row for row in declared if row.identifier == boundary_id)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner.rs").write_text(f"pub fn {method}() {{}}")
            boundary = replace(
                actual,
                definition_path="owner.rs",
                definition_markers=(f"pub fn {method}",),
                product_callers=(),
                caller_markers=(),
            )
            if expected:
                with self.assertRaises(VerificationFailure):
                    _verify_boundary(root, boundary, {"rogue.rs": code}, ())
            else:
                self.assertEqual(
                    _verify_boundary(root, boundary, {"rogue.rs": code}, ())[
                        "productCallers"
                    ],
                    [],
                )

    def cases(self):
        for boundary_id, typ, method, generic in self.METHODS:
            for prefix in ("gate.", f"{typ}::", f"<crate::{typ}>::"):
                for raw in ("", "r#"):
                    yield (
                        boundary_id,
                        method,
                        f"fn f(gate: &{typ}) {{ {prefix}{raw}{method}::<{generic}>(args); }}",
                    )
        for boundary_id, method in self.FUNCTIONS:
            for prefix in ("", "crate::"):
                for raw in ("", "r#"):
                    yield (
                        boundary_id,
                        method,
                        f"fn f() {{ {prefix}{raw}{method}::<[u8; 1]>(args); }}",
                    )

    def test_real_boundaries_reject_generic_calls(self):
        for boundary_id, method, code in self.cases():
            with self.subTest(boundary=boundary_id, code=code):
                self.check_case(boundary_id, method, code, True)

    def test_independent_b4_catches_generic_calls(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        for boundary_id, method, code in self.cases():
            row = next(row for row in rows if row["id"] == boundary_id)
            with self.subTest(boundary=boundary_id, code=code):
                self.assertTrue(
                    any(
                        re.search(p, _strip_rust_non_code(code))
                        for p in row["callPatterns"]
                    )
                )

    def test_typed_unrelated_receiver_remains_unrelated(self):
        for boundary_id, typ, method, generic in self.METHODS:
            code = f"fn f(gate: &{typ}, other: &Other) {{ other.{method}::<{generic}>(args); }}"
            with self.subTest(boundary=boundary_id):
                self.check_case(boundary_id, method, code, False)

    def test_literals_comments_and_definitions_are_not_calls(self):
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        for boundary_id, method, call in self.cases():
            row = next(row for row in rows if row["id"] == boundary_id)
            for raw in (
                f'let text = "{call}";',
                f"/* {call} */",
                f"fn {method}<T>() {{}}",
            ):
                code = _strip_rust_non_code(raw)
                with self.subTest(boundary=boundary_id, code=raw):
                    self.check_case(boundary_id, method, code, False)
                    self.assertFalse(
                        any(re.search(p, code) for p in row["callPatterns"])
                    )


if __name__ == "__main__":
    unittest.main()
