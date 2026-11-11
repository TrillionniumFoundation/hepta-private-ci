"""Keep final-holdout CURRENT on the original file, with no new authority port."""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_holdout_current_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
DIRECTORY = "codex-rs/hepta-intelligence-eval/src/"
STORE = DIRECTORY + "fenced_holdout_file.rs"
CURRENT = DIRECTORY + "fenced_holdout_current.rs"
FUNCTIONS = {
    STORE: {"fn create(", "fn recover(", "fn require_current(", "fn load(", "fn compare_and_swap("},
    CURRENT: {"fn read_physical(", "fn replay("},
}


def function_body(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    assert code.count(marker) == 1
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    assert end is not None
    return code[start:end + 1]


def require_post_read_cache_commit(source):
    body = function_body(source, "fn compare_and_swap(")
    physical = body.index("let observed =")
    checked = body.index("current.state.as_ref() == Some(next)", physical)
    for assignment in ("self.state =", "self.length =", "self.history_digest ="):
        assert body.count(assignment) == 1, assignment
        assert body.index(assignment) > checked, assignment
    assert body.index("self.require_current()?") < body.index(".write_all(&frame)")
    assert body.index(".sync_all()") < physical
    assert body.index("current.bytes == expected_bytes", physical) < checked


class OriginalHoldoutCurrentSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    def row(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        return rows[0]

    def verify_changed(self, path, changed):
        row = self.row(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text((ROOT / path).read_text())
            PROOF._verify_protected_files(root, {"protected_file": [row]})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": [row]})

    def test_each_original_physical_read_write_and_fence_guard_is_effective(self):
        for path, functions in FUNCTIONS.items():
            source = (ROOT / path).read_text()
            rules = self.row(path)["required_function_order"]
            self.assertEqual({rule["function"] for rule in rules}, functions)
            for rule in rules:
                cursor = source.index(rule["function"])
                end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), cursor)
                self.assertIsNotNone(end)
                for marker in rule["sequence"]:
                    with self.subTest(path=path, function=rule["function"], marker=marker):
                        # Match the same ordered occurrence as the function guard.
                        offset = source.index(marker, cursor, end + 1)
                        self.verify_changed(path, source[:offset] + source[offset + len(marker):])
                        cursor = offset + len(marker)

    def test_cache_is_advanced_only_after_the_actual_post_write_read(self):
        source = (ROOT / STORE).read_text()
        require_post_read_cache_commit(source)
        marker = "let observed = current::read_physical"
        # Injecting an early cache assignment must not be accepted merely
        # because the correct final assignment still exists later.
        start = source.index("fn compare_and_swap(")
        offset = source.index("let write =", start)
        for assignment in (
            "self.state = Some(next.clone());",
            "self.length = next_length;",
            "self.history_digest = Digest32::ZERO;",
        ):
            changed = source[:offset] + assignment + source[offset:]
            with self.subTest(assignment=assignment):
                with self.assertRaises(AssertionError):
                    require_post_read_cache_commit(changed)
        self.assertIn("current::read_physical", source[source.index(marker, start):])

    def test_same_handle_read_has_no_reopen_unlock_or_effect_fallback(self):
        source = (ROOT / CURRENT).read_text()
        for call in (
            "File::open(path);", "std::fs::read(path);", "file.try_clone();",
            "file.unlock();", "file.write_all(bytes);", "file.sync_all();",
            "store.compare_and_swap(binding, old, next);",
        ):
            with self.subTest(call=call):
                self.verify_changed(CURRENT, source + "\nfn bypass() { " + call + " }\n")
        for path in FUNCTIONS:
            original = (ROOT / path).read_text()
            for call in ("SigningKey::from_bytes(bytes);", "LearningEvidenceVerifierV1::new(trust);"):
                with self.subTest(path=path, call=call):
                    self.verify_changed(path, original + "\nfn bypass() { " + call + " }\n")

    def test_recovery_retains_original_minimum_and_byte_record_bounds(self):
        store = (ROOT / STORE).read_text()
        current = (ROOT / CURRENT).read_text()
        for marker in (
            "const MAX_BYTES: u64 = 32 * 1024 * 1024",
            "const MAX_FRAME: usize = 4096",
            "const MAX_RECORDS: usize = 1_000_000",
            "file.try_lock()",
            "let _ = self.0.unlock()",
        ):
            self.assertIn(marker, store)
            self.verify_changed(STORE, store.replace(marker, "", 1))
        recovery = function_body(store, "fn recover(")
        self.assertIn("current::read_physical(&mut file, binding, minimum)?", recovery)
        self.assertNotRegex(recovery, r"(?:initialize|create|compare_and_swap|write_all)\s*\(")
        self.verify_changed(STORE, store.replace(
            "current::read_physical(&mut file, binding, minimum)?",
            "current::read_physical(&mut file, binding, None)?", 1,
        ))
        self.verify_changed(CURRENT, current.replace(
            "validate_minimum(state.as_ref(), minimum, minimum_witnessed)?",
            "validate_minimum(state.as_ref(), None, true)?", 1,
        ))

    def test_no_new_public_port_and_known_non_effect_errors_are_retained(self):
        source = (ROOT / STORE).read_text()
        production = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(set(re.findall(r"pub fn (\w+)\(", production)), {
            "create", "recover", "qualification_file_bytes", "anchor",
        })
        for injected in ("pub history_digest:", "pub state:", "pub file:"):
            with self.subTest(injected=injected):
                self.verify_changed(STORE, source + "\nstruct Export { " + injected + " Raw }\n")
        load = function_body(source, "fn load(")
        self.assertLess(load.index("if binding != self.binding"), load.index("self.require_current()?"))
        self.assertIn("Ok(current.state)", load)
        self.assertNotIn("self.state.clone()", load)
        self.assertIn("FinalHoldoutCasStoreError::Conflict", load)
        cas = function_body(source, "fn compare_and_swap(")
        self.assertIn("FinalHoldoutCasStoreError::Rejected", cas)
        self.assertNotIn("NoUpdate", production)

    def test_native_group_uses_actual_eval_package_and_registered_file_owner_cases(self):
        scripts = ROOT / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            spec = importlib.util.spec_from_file_location(
                "holdout_current_native_coverage", scripts / "hepta_c_observer_coverage.py"
            )
            self.assertIsNotNone(spec)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            sys.path.pop(0)
        groups = [group for group in module.OWNER_GROUPS if group[0] == "original_holdout_current"]
        self.assertEqual(len(groups), 1)
        _, package, names = groups[0]
        self.assertEqual(package, "codex-hepta-intelligence-eval")
        self.assertEqual(len(names), 6)
        files = {
            "fenced_holdout_file::tests::physical_current::": DIRECTORY + "fenced_holdout_current_tests.rs",
            "product_runner::tests::execution_tests::holdout_current::": DIRECTORY + "product_execution_holdout_current_tests.rs",
        }
        observed = set()
        for prefix, path in files.items():
            body = (ROOT / path).read_text()
            observed.update(prefix + name for name in re.findall(r"\nfn (holdout_current_\w+)\(", body))
            self.assertIn("LockedFileFinalHoldoutCasStoreV1", body)
            self.assertIn("FencedFinalHoldoutOwnerV1", body)
        self.assertEqual(set(names), observed)
        self.assertIn('mod physical_current;', (ROOT / DIRECTORY / "fenced_holdout_file_tests.rs").read_text())
        self.assertIn('mod holdout_current;', (ROOT / DIRECTORY / "product_execution_tests.rs").read_text())
        actual = (ROOT / DIRECTORY / "product_execution_holdout_current_tests.rs").read_text()
        for marker in ("LockedFileProductEvaluationExecutionStoreV1::create(",
                       "evaluate_or_readback_temporal_comparison(", "Err(Error::Pending)",
                       "self.original.compare_and_swap(binding, expected, next)?"):
            self.assertIn(marker, actual)


if __name__ == "__main__":
    unittest.main()
