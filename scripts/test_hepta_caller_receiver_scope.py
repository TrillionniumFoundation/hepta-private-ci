"""Receiver-scoped disambiguation must never hide a registered host caller."""

import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_hepta_callers as proof


class NonBoundarySelfCallTests(unittest.TestCase):
    def boundary(self, receiver_type="BaoClient", method="consume_kv_v2"):
        row = {
            "id": "bao_registered_final_use_host",
            "symbol": "BaoFinalUseHost::consume_kv_v2",
            "definition_path": "host.rs",
            "definition_markers": [],
            "product_callers": [],
            "caller_markers": [],
            "call_pattern": r"(?:\.\s*consume_kv_v2|BaoFinalUseHost\s*::\s*consume_kv_v2)\s*\(",
            "non_boundary_self_calls": [
                {"path": "client.rs", "receiver_type": receiver_type, "method": method}
            ],
        }
        return proof._boundary_rows({"boundary": [row]})[0]

    def source(self, body=""):
        raw = (
            "pub struct BaoClient {}\n"
            "impl BaoClient {\n"
            "fn dispatch(&self) {\n"
            'let ignored = "impl BaoFinalUseHost { self.consume_kv_v2(); }";\n'
            "if ready { self\n .consume_kv_v2(); }\n"
            + body
            + "\n}\n}\n"
        )
        return proof._strip_cfg_test_items(proof._strip_rust_non_code(raw))

    def verify(self, code, extra=None):
        sources = {"client.rs": code, **(extra or {})}
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value=""
        ):
            return proof._verify_boundary(
                Path("/unused"), self.boundary(), sources, ()
            )

    def test_other_type_self_call_is_not_a_host_caller(self):
        receipt = self.verify(self.source())
        self.assertEqual(receipt["productCallers"], [])
        self.assertEqual(
            receipt["nonBoundarySelfCalls"],
            [{"path": "client.rs", "receiverType": "BaoClient", "method": "consume_kv_v2"}],
        )

    def test_host_receiver_in_same_impl_is_still_rejected(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "unexpected=.*client.rs"):
            self.verify(self.source("host.consume_kv_v2();"))

    def test_host_ufcs_in_same_impl_is_still_rejected(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "unexpected=.*client.rs"):
            self.verify(self.source("BaoFinalUseHost::consume_kv_v2(&host);"))

    def test_host_self_in_another_impl_is_still_rejected(self):
        code = self.source() + (
            "struct BaoFinalUseHost {}\n"
            "impl BaoFinalUseHost { fn dispatch(&self) { self.consume_kv_v2(); } }\n"
        )
        with self.assertRaisesRegex(proof.VerificationFailure, "unexpected=.*client.rs"):
            self.verify(code)

    def test_other_file_self_calls_are_still_rejected(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "unexpected=.*other.rs"):
            self.verify(self.source(), {"other.rs": "self.consume_kv_v2();"})

    def test_scoped_type_cannot_be_the_boundary_type(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "different receiver type"):
            self.boundary(receiver_type="BaoFinalUseHost")

    def test_scoped_method_must_match_the_boundary(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "same method"):
            self.boundary(method="another_method")

    def test_unbalanced_receiver_impl_fails_closed(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "unbalanced"):
            self.verify("struct BaoClient {} impl BaoClient { self.consume_kv_v2();")

    def test_nested_receiver_impl_fails_closed(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "ambiguous"):
            self.verify(
                self.source(
                    "impl BaoFinalUseHost { fn dispatch(&self) { self.consume_kv_v2(); } }"
                )
            )

    def test_comment_or_literal_cannot_establish_receiver_scope(self):
        raw = '// struct BaoClient {}\nlet x = "impl BaoClient { self.consume_kv_v2(); }";'
        with self.assertRaisesRegex(proof.VerificationFailure, "struct is missing"):
            self.verify(proof._strip_rust_non_code(raw))

    def test_cfg_test_only_receiver_scope_fails_closed(self):
        code = proof._strip_cfg_test_items(
            "#[cfg(test)] struct BaoClient {}\n#[cfg(test)] impl BaoClient { fn run(&self) { self.consume_kv_v2(); } }"
        )
        with self.assertRaisesRegex(proof.VerificationFailure, "struct is missing"):
            self.verify(code)


class ProtectedTokenTests(unittest.TestCase):
    def verify(self, source, pattern=r"\bcodex_hepta_memory\s*::\s*CognitiveStore\b"):
        data = {
            "protected_file": [
                {"path": "runtime.rs", "required": [], "forbidden": [], "forbidden_patterns": [pattern]}
            ]
        }
        with patch.object(Path, "is_file", return_value=True), patch.object(
            Path, "read_text", return_value=source
        ):
            return proof._verify_protected_files(Path("/unused"), data)

    def test_error_type_is_allowed(self):
        self.assertEqual(
            self.verify("type Error = codex_hepta_memory::CognitiveStoreError;"),
            ["runtime.rs"],
        )

    def test_legacy_type_is_denied(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "forbidden code pattern"):
            self.verify("use codex_hepta_memory::CognitiveStore;")

    def test_whitespace_does_not_hide_legacy_type(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "forbidden code pattern"):
            self.verify("type Old = codex_hepta_memory \n :: \n CognitiveStore;")

    def test_comments_do_not_manufacture_a_legacy_type(self):
        self.assertEqual(
            self.verify("// codex_hepta_memory::CognitiveStore\nfn run() {}"),
            ["runtime.rs"],
        )

    def test_negative_selection_test_name_is_allowed(self):
        self.assertEqual(
            self.verify("fn rejects_self_selection() {}", r"\bself_select\b"),
            ["runtime.rs"],
        )

    def test_actual_self_select_call_is_denied(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "forbidden code pattern"):
            self.verify("self_select();", r"\bself_select\b")

    def test_invalid_forbidden_pattern_fails_closed(self):
        with self.assertRaisesRegex(proof.VerificationFailure, "invalid forbidden pattern"):
            self.verify("fn run() {}", "[")


if __name__ == "__main__":
    unittest.main()
