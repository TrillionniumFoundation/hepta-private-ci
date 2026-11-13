"""Cache source-copy negatives; no native execution or authority granted."""
import importlib.util
from pathlib import Path
import re
import shutil
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
CACHE = "codex-rs/hepta-agentd/src/root_observation_cache.rs"
SESSION = "codex-rs/hepta-agentd/src/root_authority_session.rs"
SPEC = importlib.util.spec_from_file_location(
    "root_cache_concurrency_caller_verifier", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

class RootObservationCacheConcurrencySourceClosureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.original_manifest_text = (ROOT / "CALLERS.toml").read_text(encoding="utf-8")
        all_rows = tomllib.loads(self.original_manifest_text)["protected_file"]
        rows = [row for row in all_rows if row["path"] in (CACHE, SESSION)]
        self.assertEqual(sum(row["path"] == CACHE for row in rows), 1)
        self.assertEqual(sum(row["path"] == SESSION for row in rows), 2)
        self.manifest = {"protected_file": rows}
        for relative in (CACHE, SESSION):
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        PROOF._verify_protected_files(self.root, self.manifest)
        self.assert_nonblocking_readers((self.root / CACHE).read_text(encoding="utf-8"))

    def function_span(self, source, function):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        self.assertEqual(code[end], "}")
        return start, end + 1, code[start:end + 1]

    def assert_nonblocking_readers(self, source):
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertNotRegex(
            code,
            r"\bpub(?:\s*\([^)]*\))?\s+fn\s+(?:current_with_clock|accept_with_clock)\s*\(",
        )
        for function in (
            "fn current(", "fn current_with_clock(",
            "fn require_writer_not_poisoned(", "fn revocations_match(",
        ):
            _, _, body = self.function_span(source, function)
            self.assertNotRegex(
                body, r"\.\s*(?:lock|try_lock|read|try_read|write|try_write)\s*\(",
                msg=function,
            )

    def reject_current_mutation(self, transform):
        path = self.root / CACHE
        source = path.read_text(encoding="utf-8")
        start, end, _ = self.function_span(source, "fn current_with_clock(")
        body = source[start:end]
        changed = transform(body)
        self.assertNotEqual(changed, body)
        path.write_text(source[:start] + changed + source[end:], encoding="utf-8")
        with self.assertRaises(PROOF.VerificationFailure):
            PROOF._verify_protected_files(self.root, self.manifest)

    def test_current_snapshot_cannot_skip_final_update_generation(self):
        def change(body):
            self.assertEqual(body.count("after != generation"), 1)
            return body.replace("after != generation", "false", 1)
        self.reject_current_mutation(change)

    def test_actual_sample_cannot_precede_its_high_water_baseline(self):
        def change(body):
            pattern = (
                r"(?P<baseline>let baseline\s*=\s*self\.high_water\.load\(Ordering::Acquire\);)"
                r"(?P<gap>\s*)"
                r"(?P<sample>let now\s*=\s*sample\(\)\.inspect_err\(\|_\|\s*\{.*?\}\)\?;)"
            )
            changed, count = re.subn(
                pattern,
                lambda match: match["sample"] + match["gap"] + match["baseline"],
                body, count=1, flags=re.S,
            )
            self.assertEqual(count, 1)
            return changed
        self.reject_current_mutation(change)

    def test_current_cannot_acquire_the_publisher_mutex(self):
        source = (self.root / CACHE).read_text(encoding="utf-8")
        start, end, _ = self.function_span(source, "fn current_with_clock(")
        body = source[start:end]
        self.assertEqual(body.count("let generation ="), 1)
        changed = body.replace(
            "let generation =",
            "let _forbidden_guard = self.writer.try_lock().unwrap();\n        let generation =",
            1,
        )
        with self.assertRaises(AssertionError):
            self.assert_nonblocking_readers(source[:start] + changed + source[end:])

if __name__ == "__main__":
    unittest.main()
