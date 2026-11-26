import tempfile
import unittest
from pathlib import Path

from verify_hepta_callers import Boundary, VerificationFailure, _verify_boundary


class CallerBoundaryModeTests(unittest.TestCase):
    def verify(self, code, *, receiver_type, expected_callers):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "owner.rs").write_text("impl Gate { pub fn enter(&self) {} }")
            (root / "caller.rs").write_text(code)
            boundary = Boundary(
                identifier="gate-entry",
                symbol="Gate::enter",
                definition_path="owner.rs",
                definition_markers=("pub fn enter",),
                product_callers=expected_callers,
                caller_markers=(),
                call_pattern=r"\.\s*enter\s*\(",
                caller_type_marker="LexicalOwnerMarker",
                receiver_type=receiver_type,
            )
            return _verify_boundary(root, boundary, {"caller.rs": code}, ())

    def test_typed_receiver_cannot_be_hidden_by_absent_lexical_marker(self):
        receipt = self.verify(
            "fn f(renamed: &Gate) { renamed.enter(); }",
            receiver_type="Gate",
            expected_callers=("caller.rs",),
        )
        self.assertEqual(receipt["productCallers"], ["caller.rs"])

    def test_opaque_typed_receiver_is_rejected_without_lexical_marker(self):
        with self.assertRaises(VerificationFailure):
            self.verify(
                "fn f(known: &Gate) { let opaque = factory(known); opaque.enter(); }",
                receiver_type="Gate",
                expected_callers=(),
            )

    def test_generic_qualified_and_method_calls_keep_the_typed_boundary(self):
        for code in (
            "fn f(renamed: &Gate) { Gate::enter::<Option<()>>(renamed); }",
            "fn f(renamed: &Gate) { <Gate>::enter::<Option<()>>(renamed); }",
            "fn f(renamed: &Gate) { renamed.enter::<Option<()>>(); }",
        ):
            with self.subTest(code=code):
                receipt = self.verify(
                    code, receiver_type="Gate", expected_callers=("caller.rs",)
                )
                self.assertEqual(receipt["productCallers"], ["caller.rs"])

    def test_opaque_generic_receiver_is_still_rejected(self):
        with self.assertRaises(VerificationFailure):
            self.verify(
                "fn f(known: &Gate) { let opaque = factory(known); opaque.enter::<()>(); }",
                receiver_type="Gate",
                expected_callers=(),
            )

    def test_lexical_mode_keeps_its_owner_marker_filter(self):
        for code, expected in (
            ("fn f(other: &Other) { other.enter(); }", ()),
            (
                "fn f(owner: &LexicalOwnerMarker) { owner.enter(); }",
                ("caller.rs",),
            ),
        ):
            with self.subTest(code=code):
                receipt = self.verify(
                    code, receiver_type=None, expected_callers=expected
                )
                self.assertEqual(receipt["productCallers"], list(expected))


if __name__ == "__main__":
    unittest.main()
