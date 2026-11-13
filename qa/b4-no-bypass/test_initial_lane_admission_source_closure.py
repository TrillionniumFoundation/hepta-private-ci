"""Mutate actual Initial admission code; this proves no runtime authority."""

import importlib.util
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
AGENT = "codex-rs/hepta-agentd/src/"
LANE = AGENT + "root_generation_initial_lane.rs"
STREAM = AGENT + "root_generation_publication_stream.rs"
CALLS = (
    (AGENT + "root_generation_initial_client.rs", "fn exchange("),
    (AGENT + "root_generation_initial_learning_trust.rs", "fn read_original_learning_trust("),
    (AGENT + "root_generation_initial_run_start.rs", "fn retain_live_run_start("),
    (AGENT + "root_generation_initial_source_capture.rs", "fn capture_source_after_quiescence("),
)
SPEC = importlib.util.spec_from_file_location(
    "initial_lane_admission_source_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)


class InitialLaneAdmissionSourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        paths = {LANE, STREAM, *(path for path, _ in CALLS)}
        manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text(encoding="utf-8"))
        self.manifest = {"protected_file": [
            row for row in manifest["protected_file"] if row["path"] in paths
        ]}
        self.assertEqual({row["path"] for row in self.manifest["protected_file"]}, paths)
        self.original = {}
        for relative in paths:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
            self.original[relative] = target.read_text(encoding="utf-8")
        self.verify()

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def span(self, source, marker):
        code = self.code(source)
        self.assertEqual(code.count(marker), 1, marker)
        start = code.index(marker)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end, marker)
        self.assertEqual(code[end], "}", marker)
        return start, end + 1, code[start:end + 1]

    def verify(self):
        PROOF._verify_protected_files(self.root, self.manifest)
        lane_source = (self.root / LANE).read_text(encoding="utf-8")
        code = self.code(lane_source)
        _, _, fields = self.span(lane_source, "struct Held<")
        data = re.search(r"\bdata\s*:\s*MutexGuard\s*<", fields)
        permit = re.search(r"\bpermit\s*:\s*Permit\s*<", fields)
        self.assertIsNotNone(data)
        self.assertIsNotNone(permit)
        self.assertLess(data.start(), permit.start(), "unwind must release data before the token")
        _, _, constructor = self.span(lane_source, "fn new(")
        self.assertRegex(constructor, r"crossbeam_channel::bounded\s*\(\s*1\s*\)")
        self.assertNotRegex(code, r"\bpub(?:\s*\([^)]*\))?\s+struct\s+Permit\b")
        for marker in (
            "fn acquire<'a, T>(", "fn return_token(", "fn drop(",
            "fn require_admission_open(", "fn acquire_original_lane(",
        ):
            _, _, body = self.span(lane_source, marker)
            self.assertNotRegex(
                body,
                r"\.\s*(?:lock|recv|send|recv_timeout)\s*\(|"
                r"\b(?:loop|while)\b|(?:thread::sleep|yield_now|into_inner)\s*\(",
                marker,
            )
        for relative, marker in CALLS:
            source = (self.root / relative).read_text(encoding="utf-8")
            _, _, body = self.span(source, marker)
            self.assertNotRegex(body, r"\bself\s*\.\s*lane\s*\.\s*(?:lock|try_lock)\s*\(")
            self.assertNotRegex(body, r"\bheld\s*\.\s*end\s*=")
        capture = (self.root / CALLS[-1][0]).read_text(encoding="utf-8")
        _, _, body = self.span(capture, CALLS[-1][1])
        self.assertNotRegex(body, r"\*\s*held(?:\s*\.\s*data)?\s*=\s*Some\s*\(")

    def reject(self, relative, marker, transform):
        source = self.original[relative]
        start, end, _ = self.span(source, marker)
        original_body = source[start:end]
        changed = transform(original_body)
        self.assertNotEqual(changed, original_body)
        path = self.root / relative
        try:
            path.write_text(source[:start] + changed + source[end:], encoding="utf-8")
            with self.assertRaises((PROOF.VerificationFailure, AssertionError)):
                self.verify()
        finally:
            path.write_text(source, encoding="utf-8")

    def replace(self, body, old, new, occurrence=0):
        offsets = [match.start() for match in re.finditer(re.escape(old), body)]
        self.assertGreater(len(offsets), occurrence, old)
        offset = offsets[occurrence]
        return body[:offset] + new + body[offset + len(old):]

    def remove(self, relative, marker, old, occurrence=0):
        self.reject(relative, marker, lambda body: self.replace(
            body, old, "/* removed original check */", occurrence
        ))

    def test_queue_and_original_io_share_the_same_deadline(self):
        for relative, marker in CALLS:
            with self.subTest(path=relative, edge="queue"):
                self.reject(relative, marker, lambda body: self.replace(
                    body, "self.acquire_original_lane(end)?",
                    "self.acquire_original_lane(self.session_end)?",
                ))
            with self.subTest(path=relative, edge="io"):
                self.reject(relative, marker, lambda body: self.replace(
                    body, "held.end", "(Instant::now() + self.frame_timeout).min(self.session_end)",
                ))
        self.reject(CALLS[1][0], CALLS[1][1], lambda body: self.replace(
            body, "&serde_json::to_vec(&request)?", "&[]",
        ))
        self.remove(LANE, "fn original_frame_end(", ".min(self.session_end)")
        self.reject(STREAM, "fn exchange_until(", lambda body: self.replace(
            body, "requested_end.min(now + self.timeout).min(self.end)",
            "(now + self.timeout).min(self.end)",
        ))
        self.reject(LANE, "fn acquire<'a, T>(", lambda body: self.replace(
            body, "recv_deadline(end)", "recv()",
        ))
        # A ready token can be returned even when recv_deadline was already late.
        self.remove(LANE, "fn acquire<'a, T>(", "require_admission_open(fenced, end)?", 1)
        self.remove(STREAM, "fn exchange_until(", "now >= end")

    def test_waiters_recheck_original_session_fence_and_poison(self):
        self.remove(LANE, "fn acquire_original_lane(",
                    "self.connection.require_original_publication_session()")
        self.remove(LANE, "fn acquire_original_lane(", "held.require_open()?")
        self.remove(LANE, "fn require_admission_open(", "fenced.load(Ordering::Acquire)")
        self.remove(LANE, "fn require_admission_open(", "Instant::now() >= end")
        self.remove(LANE, "fn refuse(", "fenced.store(true, Ordering::Release)")
        self.remove(LANE, "fn acquire<'a, T>(", "std::sync::TryLockError::Poisoned(_)")
        for relative, marker in CALLS[:-1]:
            with self.subTest(path=relative):
                source = self.original[relative]
                start, end, _ = self.span(source, marker)
                occurrences = source[start:end].count("held.require_open()?")
                self.assertGreater(occurrences, 0)
                self.remove(relative, marker, "held.require_open()?", occurrences - 1)
        self.remove(CALLS[1][0], CALLS[1][1],
                    "self.require_learning_trust_session(session, identity)?", 1)
        self.remove(CALLS[-1][0], CALLS[-1][1], "held.require_deadline()?")
        self.reject(LANE, "fn acquire<'a, T>(", lambda body: self.replace(
            body, "data.try_lock()", "data.lock()",
        ))

    def test_data_mutex_is_released_before_nonblocking_token_return(self):
        def release_token_first(body):
            changed, count = re.subn(
                r"drop\(data\);\s*permit\.return_token\(\)",
                "let returned = permit.return_token();\n        drop(data);\n        returned",
                body, count=1,
            )
            self.assertEqual(count, 1)
            return changed
        self.reject(LANE, "fn release(", release_token_first)

        def reverse_fields(body):
            pattern = (
                r"(?P<data>pub\(super\)\s+data:\s*MutexGuard<'a,\s*T>,)"
                r"(?P<gap>\s*)"
                r"(?P<permit>permit:\s*Permit<'a>,)"
            )
            changed, count = re.subn(
                pattern, lambda match: match["permit"] + match["gap"] + match["data"],
                body, count=1,
            )
            self.assertEqual(count, 1)
            return changed
        self.reject(LANE, "struct Held<", reverse_fields)
        self.reject(LANE, "fn return_token(", lambda body: self.replace(
            body, "try_send(())", "send(())",
        ))
        self.remove(LANE, "fn return_token(", "refuse(")
        self.remove(LANE, "fn drop(", "self.return_token()")


if __name__ == "__main__":
    unittest.main()
