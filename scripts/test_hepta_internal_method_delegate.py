"""An exact existing delegate never exempts the rest of its file or callers."""

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
import tomllib
import unittest

from verify_hepta_callers import (
    VerificationFailure,
    _boundary_rows,
    _mask_method_delegate_spans,
    _strip_cfg_test_items,
    _strip_rust_non_code,
    _verified_method_delegate_spans,
    _verify_boundary,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY = "qa/b4-no-bypass/KERNEL_AUTHORITY_EXTENSION_API.json"


class InternalMethodDelegateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        # Exercise the shared verifier with a synthetic exact delegate. This
        # older product candidate has no extension-policy exemption installed.
        self.path = "wrapper.rs"
        method = """pub fn verify(verifier: &FinalUseRevocationFeedVerifier, signed: Input, now_unix_ms: u64) {
        let trust_key_id = verifier.verify(signed, now_unix_ms)?.to_owned();
        let signing_bytes = signed.bytes();
    }"""
        self.original = "impl VerifiedFinalUseRevocationHead {\n    " + method + "\n}\n"
        existing = _boundary_rows(tomllib.loads((ROOT / "CALLERS.toml").read_text()))
        self.callee = replace(
            next(
                row
                for row in existing
                if row.identifier == "final_use_revocation_feed_apply"
            ),
            identifier="synthetic_callee",
            symbol="FinalUseRevocationFeedVerifier::verify",
            definition_path="callee.rs",
            definition_markers=("pub fn verify(",),
            receiver_methods=("verify",),
            product_callers=(),
            caller_markers=(),
        )
        wrapper = replace(
            self.callee,
            identifier="synthetic_wrapper",
            symbol="VerifiedFinalUseRevocationHead::verify",
            definition_path=self.path,
            receiver_type="VerifiedFinalUseRevocationHead",
        )
        self.boundaries = (self.callee, wrapper)
        self.entry = {
            "sourcePath": self.path,
            "enclosingType": "VerifiedFinalUseRevocationHead",
            "enclosingMethod": "verify",
            "wrapperBoundary": "synthetic_wrapper",
            "calleeBoundary": "synthetic_callee",
            "expectedCalls": 1,
            "definitionSha256": hashlib.sha256(method.encode()).hexdigest(),
        }
        self.policy = {
            "sourcePath": self.path,
            "types": [
                {
                    "typeName": "VerifiedFinalUseRevocationHead",
                    "privilegedMethods": {"verify": "synthetic_wrapper"},
                }
            ],
            "methodDelegates": [self.entry],
        }
        (self.root / POLICY).parent.mkdir(parents=True, exist_ok=True)
        (self.root / POLICY).write_text(json.dumps(self.policy))
        (self.root / self.path).write_text(self.original)
        (self.root / "callee.rs").write_text(
            "impl FinalUseRevocationFeedVerifier { pub fn verify(&self) {} }"
        )

    def check(self, source=None, extra=None, policy=None):
        (self.root / self.path).write_text(
            source if source is not None else self.original
        )
        (self.root / POLICY).write_text(
            json.dumps(policy if policy is not None else self.policy)
        )
        index = {
            self.path: _strip_cfg_test_items(
                _strip_rust_non_code((self.root / self.path).read_text())
            )
        }
        index.update(extra or {})
        delegates = _verified_method_delegate_spans(self.root, self.boundaries, index)
        for path, spans in delegates.get(self.callee.identifier, {}).items():
            index[path] = _mask_method_delegate_spans(index[path], spans)
        return _verify_boundary(self.root, self.callee, index, ())

    def test_existing_exact_wrapper_is_the_only_exempted_call(self):
        self.assertEqual(self.check()["productCallers"], [])

    def test_same_file_other_function_is_not_exempt(self):
        call = "\nfn rogue(verifier: &FinalUseRevocationFeedVerifier) { verifier.r#verify(signed, now); }\n"
        with self.assertRaises(VerificationFailure):
            self.check(self.original + call)

    def test_same_file_other_type_is_not_exempt(self):
        call = "\nstruct Rogue; impl Rogue { fn verify(verifier: &FinalUseRevocationFeedVerifier) { verifier.r#verify(signed, now); } }\n"
        with self.assertRaises(VerificationFailure):
            self.check(self.original + call)

    def test_external_file_is_not_exempt(self):
        with self.assertRaises(VerificationFailure):
            self.check(
                extra={
                    "rogue.rs": "fn rogue(verifier: &FinalUseRevocationFeedVerifier) { verifier.verify(signed, now); }"
                }
            )

    def test_duplicate_call_inside_wrapper_is_rejected(self):
        source = self.original.replace(
            "let trust_key_id = verifier.verify",
            "verifier.verify(signed, now_unix_ms)?;\n        let trust_key_id = verifier.verify",
        )
        with self.assertRaises(VerificationFailure):
            self.check(source)

    def test_changed_body_deleted_call_or_digest_is_rejected(self):
        for source in (
            self.original.replace(
                "let signing_bytes =", "let unrelated = 1;\n        let signing_bytes ="
            ),
            self.original.replace(
                "verifier.verify(signed, now_unix_ms)?.to_owned()", "String::new()"
            ),
        ):
            with self.subTest(source=source), self.assertRaises(VerificationFailure):
                self.check(source)
        policy = deepcopy(self.policy)
        policy["methodDelegates"][0]["definitionSha256"] = "0" * 64
        with self.assertRaises(VerificationFailure):
            self.check(policy=policy)

    def test_wrong_count_owner_path_or_wrapper_is_rejected(self):
        for key, value in (
            ("expectedCalls", 2),
            ("expectedCalls", True),
            ("enclosingType", "Rogue"),
            ("enclosingMethod", "distributor_id"),
            ("sourcePath", "other.rs"),
            ("wrapperBoundary", "final_use_open_state"),
        ):
            policy = deepcopy(self.policy)
            policy["methodDelegates"][0][key] = value
            with (
                self.subTest(key=key, value=value),
                self.assertRaises(VerificationFailure),
            ):
                self.check(policy=policy)

    def test_changed_count_fails_even_if_raw_digest_is_rebound(self):
        code = _strip_rust_non_code(self.original)
        spans = _verified_method_delegate_spans(
            self.root, self.boundaries, {self.path: code}
        )[self.callee.identifier][self.path]
        start, end = spans[0]
        body = self.original[start:end].replace(
            "let trust_key_id = verifier.verify",
            "verifier.verify(signed, now_unix_ms)?;\n        let trust_key_id = verifier.verify",
        )
        source = self.original[:start] + body + self.original[end:]
        policy = deepcopy(self.policy)
        policy["methodDelegates"][0]["definitionSha256"] = hashlib.sha256(
            body.encode()
        ).hexdigest()
        with self.assertRaises(VerificationFailure):
            self.check(source, policy=policy)


if __name__ == "__main__":
    unittest.main()
