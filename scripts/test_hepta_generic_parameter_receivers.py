"""Truncated parameter types cannot hide a possible authority receiver."""

from dataclasses import replace
import json
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

from hepta_typed_callers import (
    UnresolvedTypedReceiver,
    authority_fields,
    has_authority_call,
)
from verify_hepta_callers import VerificationFailure, _boundary_rows, _verify_boundary

ROOT = Path(__file__).resolve().parents[1]
TARGET = "FinalUseApprovalVerifier"
ALIAS = "pub use codex_hepta_contracts::FinalUseApprovalVerifier as Gate;"
WRAPPER = """pub struct Wrapper<A, B> { pub first: A, pub inner: B }
impl<A, B> std::ops::Deref for Wrapper<A, B> {
    type Target = B;
    fn deref(&self) -> &B { &self.inner }
}
"""


class GenericParameterReceiverTests(unittest.TestCase):
    def source(self, parameter, call):
        return (
            "use crate::aliases::Gate; use crate::wrapper::Wrapper; "
            f"fn f(gate: &{parameter}) {{ gate.{call}(grant, approval); }}"
        )

    def index(self, code):
        return {"aliases.rs": ALIAS, "wrapper.rs": WRAPPER, "rogue.rs": code}

    def match(self, code):
        return has_authority_call(
            code, TARGET, "verify", authority_fields(self.index(code), TARGET)
        )

    def verify_boundary(self, code):
        rows = _boundary_rows(tomllib.loads((ROOT / "CALLERS.toml").read_text()))
        row = next(row for row in rows if row.identifier == "final_use_approval_verify")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner.rs").write_text("pub fn verify(")
            return _verify_boundary(
                root,
                replace(
                    row,
                    definition_path="owner.rs",
                    definition_markers=("pub fn verify(",),
                    product_callers=(),
                    caller_markers=(),
                ),
                self.index(code),
                (),
            )

    def test_split_file_alias_second_argument_rejects_plain_raw_and_generic_calls(self):
        for call in ("verify", "r#verify", "verify::<()>", "r#verify::<Option<()>>"):
            code = self.source("Wrapper<(), Gate>", call)
            with self.subTest(call=call), self.assertRaises(VerificationFailure):
                self.verify_boundary(code)

    def test_nested_late_authority_arguments_cannot_be_declared_unrelated(self):
        for parameter in (
            "Wrapper<Option<()>, Gate>",
            "Wrapper<Wrapper<(), ()>, Gate>",
            "Wrapper<fn() -> (), Gate>",
            "Wrapper<fn() -> Option<()>, Wrapper<(), Gate>>",
            "Wrapper<((), ()), Gate>",
            "Wrapper<[(); 2], Gate>",
            "Wrapper<(), Wrapper<(), Gate>>",
        ):
            for call in ("verify", "r#verify", "verify::<[u8; 1]>"):
                code = self.source(parameter, call)
                with (
                    self.subTest(parameter=parameter, call=call),
                    self.assertRaises(VerificationFailure),
                ):
                    self.verify_boundary(code)

    def test_target_already_visible_in_partial_parameter_stays_detected(self):
        for parameter in ("Wrapper<Gate, ()>", "Wrapper<Option<Gate>, ()>"):
            code = self.source(parameter, "verify")
            with self.subTest(parameter=parameter):
                self.assertTrue(self.match(code))

    def test_complete_explicit_unrelated_types_remain_unrelated(self):
        for parameter in (
            "Other",
            "&Other",
            "&mut Other",
            "&'a Other",
            "crate::Other",
            "::crate_name::Other",
            "Unrelated<Other>",
            "Unrelated<Option<Other>>",
            "Unrelated<fn() -> Other>",
            "Unrelated<fn() -> Option<Other>>",
        ):
            code = (
                "use crate::aliases::Gate; "
                f"fn f(known: &Gate, other: {parameter}) {{ other.verify(); }}"
            )
            with self.subTest(parameter=parameter):
                self.assertFalse(self.match(code))

    def test_incomplete_type_is_unknown_even_without_target_in_partial_fragment(self):
        for parameter in ("Wrapper<(), Other>", "Wrapper<fn() -> (), Other>"):
            code = (
                "use crate::aliases::Gate; "
                f"fn f(known: &Gate, other: &{parameter}) {{ other.verify(); }}"
            )
            with (
                self.subTest(parameter=parameter),
                self.assertRaises(UnresolvedTypedReceiver),
            ):
                self.match(code)

    def test_typed_proof_does_not_rely_on_b4_raw_owner_marker_for_alias_call(self):
        code = self.source("Wrapper<(), Gate>", "verify")
        rows = json.loads(
            (ROOT / "qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json").read_text()
        )["boundaries"]
        row = next(row for row in rows if row["id"] == "final_use_approval_verify")
        observed = [
            path
            for path, source in self.index(code).items()
            if row["typeMarker"] in source
            and any(re.search(pattern, source) for pattern in row["callPatterns"])
        ]
        self.assertEqual(observed, [])
        with self.assertRaises(VerificationFailure):
            self.verify_boundary(code)


if __name__ == "__main__":
    unittest.main()
