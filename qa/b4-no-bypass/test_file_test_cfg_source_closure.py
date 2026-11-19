"""File cfg semantics cannot turn test helpers into production authority."""

import unittest

import test_initial_artifact_readview_source_closure as component

PROOF = component.PROOF
CALL = "LedgerWriter::from_durable(original);"


def code(source):
    return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))


class FileTestCfgSourceTests(unittest.TestCase):
    def test_real_leading_test_only_file_attributes_mask_the_complete_file(self):
        for attribute in ("#![cfg(test)]", "#![cfg(all(test, unix))]",
                          "#![cfg(\n all(test, target_os = \"linux\")\n)]"):
            source = "//! module doc\n#![deny(unsafe_code)]\n" + attribute + "\nfn fixture() { " + CALL + " }"
            masked = code(source)
            self.assertNotIn("LedgerWriter", masked)
            self.assertEqual(masked.count("\n"), source.count("\n"))
            self.assertEqual(len(masked), len(source))

    def test_conditions_that_can_hold_in_production_preserve_all_calls(self):
        for attribute in ("#![cfg(any(test, unix))]", "#![cfg(not(test))]",
                          "#![cfg(unix)]", "#![cfg_attr(test, allow(dead_code))]"):
            self.assertIn(CALL, code(attribute + "\nfn product() { " + CALL + " }"))

    def test_nested_inner_cfg_cannot_hide_surrounding_product_code(self):
        source = "mod fixture { #![cfg(test)] fn helper() {} }\nfn product() { " + CALL + " }"
        self.assertIn(CALL, code(source))
        # A misplaced inner attribute is not a whole-file exclusion either.
        self.assertIn(CALL, code("fn earlier() {}\n#![cfg(test)]\nfn later() { " + CALL + " }"))

    def test_comments_and_strings_cannot_supply_a_file_cfg(self):
        for prefix in ("// #![cfg(test)]\n", "/* #![cfg(test)] */\n",
                       'const TEXT: &str = "#![cfg(test)]";\n'):
            self.assertIn(CALL, code(prefix + "fn product() { " + CALL + " }"))

    def test_unbalanced_real_file_attribute_fails_closed(self):
        with self.assertRaises(PROOF.VerificationFailure):
            code("#![cfg(test)\nfn product() { " + CALL + " }")


if __name__ == "__main__":
    unittest.main()
