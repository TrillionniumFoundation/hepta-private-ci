"""An exact existing delegate never exempts the rest of its file or callers."""

from copy import deepcopy
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
        self.policy = json.loads((ROOT / POLICY).read_text())
        self.entry = self.policy["methodDelegates"][0]
        self.path = self.entry["sourcePath"]
        self.original = (ROOT / self.path).read_text()
        self.boundaries = _boundary_rows(
            tomllib.loads((ROOT / "CALLERS.toml").read_text())
        )
        self.callee = next(
            row
            for row in self.boundaries
            if row.identifier == self.entry["calleeBoundary"]
        )
        for name in (POLICY, self.path, self.callee.definition_path):
            dest = self.root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())

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
