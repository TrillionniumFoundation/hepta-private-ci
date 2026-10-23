#!/usr/bin/env python3
"""Regression tests for lexical inventory guards, not Rust privacy proofs."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("authbus_inventory", Path(__file__).with_name("check-authbus-closed-world.py"))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class InventoryContract(unittest.TestCase):
    def test_return_types_and_impls_are_not_literals(self):
        for text in ["fn issuer() -> IssuerRegistration { todo!() }",
                     "fn issuer() -> crate::IssuerRegistration { todo!() }",
                     "impl IssuerRegistration { fn f() {} }",
                     "pub struct IssuerRegistration { view: View }"]:
            self.assertFalse(module.has_struct_literal(text, "IssuerRegistration"), text)

    def test_field_order_and_shorthand_cannot_hide_a_literal(self):
        for text in ["IssuerRegistration { issuer_id: x, revoked: false }",
                     "IssuerRegistration { revoked: false, issuer_id: x }",
                     "crate::IssuerRegistration { view, registry_digest, registry_revision }"]:
            self.assertTrue(module.has_struct_literal(text, "IssuerRegistration"), text)

    def test_comments_strings_and_lifetimes(self):
        for text in ['// IssuerRegistration { x }',
                     '/* nested /* IssuerRegistration { x } */ comment */',
                     'r###"IssuerRegistration { x }"###',
                     '"IssuerRegistration { x }"',
                     "fn read<'a>(x: &'a IssuerRegistration) {}"]:
            self.assertFalse(module.has_struct_literal(text, "IssuerRegistration"), text)

    def test_real_literal_after_comment_is_detected(self):
        self.assertTrue(module.has_struct_literal("/* ignored */ IssuerRegistration { view }", "IssuerRegistration"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
