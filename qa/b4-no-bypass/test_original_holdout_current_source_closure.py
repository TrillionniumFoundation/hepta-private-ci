"""Keep final-holdout CURRENT on the original file, with no new authority port."""

import importlib.util
from pathlib import Path
import re
import sys
import tempfile
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
REPLAY = DIRECTORY + "fenced_holdout_file_replay.rs"
OWNER = DIRECTORY + "fenced_holdout.rs"
LOCK = DIRECTORY + "holdout_file_lock.rs"
UNIX_LOCK = DIRECTORY + "holdout_file_lock_unix.rs"
FUNCTIONS = {
    OWNER: {
        "fn consume(", "fn read_consumption(", "fn read_consumption_for_execution(",
        "fn is_poisoned(", "fn anchor(", "fn apply_cas<S: FinalHoldoutCasStoreV1>(",
        "fn digest_state(", "fn fence(", "fn from(", "fn head_digest(",
        "fn initialize(", "fn into_store(", "fn issue(", "fn new(",
        "fn qualification_unpoisoned_file_bytes(", "fn recover(", "fn resume(",
        "fn state_digest(",
    },
    STORE: {
        "fn create(", "fn recover(", "fn require_current(", "fn require_physical_current(",
        "fn acquire(", "fn load(", "fn compare_and_swap(", "fn anchor(",
        "fn decode_fence(",
        "fn encode_fence(", "fn fmt(", "fn io_error(",
        "fn qualification_unpoisoned_file_bytes(", "fn record_anchor(",
        "fn replay_event(", "fn transition_payload(", "fn validate_minimum(",
    },
    # Physical CURRENT delegates the shared replay grammar to REPLAY below.
    CURRENT: {"fn read_physical("},
    LOCK: {"fn acquire(", "fn check_process(", "fn deref(", "fn deref_mut(", "fn drop("},
    UNIX_LOCK: {"fn reserve(", "fn check_origin(", "fn acquire(", "fn check(", "fn release_registered("},
}
REPLAY_FUNCTIONS = {"fn read_stable_image(", "fn read_image(", "fn replay_image("}
# Each file has one consolidated record containing every guard from both owners.
PROTECTED_ROW_COUNTS = {path: 1 for path in (*FUNCTIONS, REPLAY)}


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
    assert body.index("current.bytes == expected_image", physical) < checked


class OriginalHoldoutCurrentSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = PROOF._load_manifest(ROOT / "CALLERS.toml")

    def rows(self, path):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), PROTECTED_ROW_COUNTS[path])
        return rows

    def row(self, path):
        expected = REPLAY_FUNCTIONS if path == REPLAY else FUNCTIONS[path]
        scoped = [
            row for row in self.rows(path)
            if {rule["function"] for rule in row["required_function_order"]} == expected
            and (
                path != CURRENT
                or "hepta.intelligence-eval.locked-holdout-current.v1" in row["required"]
            )
        ]
        self.assertEqual(len(scoped), 1)
        return scoped[0]

    def verify_changed(self, path, changed):
        self.row(path)
        rows = self.rows(path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text((ROOT / path).read_text())
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_each_original_physical_read_write_and_fence_guard_is_effective(self):
        for path, functions in {**FUNCTIONS, REPLAY: REPLAY_FUNCTIONS}.items():
            source = (ROOT / path).read_text()
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            self.assertEqual(len(code), len(source))
            rules = self.row(path)["required_function_order"]
            self.assertEqual({rule["function"] for rule in rules}, functions)
            for rule in rules:
                cursor = code.index(rule["function"])
                end = PROOF._rust_item_end(code, cursor)
                self.assertIsNotNone(end)
                for marker in rule["sequence"]:
                    with self.subTest(path=path, function=rule["function"], marker=marker):
                        # Guards use masked code; equal offsets select the full original bytes.
                        offset = code.index(marker, cursor, end + 1)
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
        for path in (OWNER, STORE, CURRENT):
            original = (ROOT / path).read_text()
            for call in ("SigningKey::from_bytes(bytes);", "LearningEvidenceVerifierV1::new(trust);"):
                with self.subTest(path=path, call=call):
                    self.verify_changed(path, original + "\nfn bypass() { " + call + " }\n")

    def test_recovery_retains_original_minimum_and_byte_record_bounds(self):
        store = (ROOT / STORE).read_text()
        current = (ROOT / CURRENT).read_text()
        replay = (ROOT / REPLAY).read_text()
        for marker in (
            "const MAX_BYTES: u64 = 32 * 1024 * 1024",
            "const MAX_FRAME: usize = 4096",
            "const MAX_RECORDS: usize = 1_000_000",
            "AcquiredFile::acquire(file)",
        ):
            self.assertIn(marker, store)
            self.verify_changed(STORE, store.replace(marker, "", 1))
        lock = (ROOT / LOCK).read_text()
        unix_lock = (ROOT / UNIX_LOCK).read_text()
        for path, source, markers in (
            (LOCK, lock, ("file.try_lock()?", "let _ = self.file.unlock()", "unix::release(&self.file, lease)")),
            (UNIX_LOCK, unix_lock, ("acquired.file.try_lock()", "registry.release(lease, || file.unlock())")),
        ):
            for marker in markers:
                self.assertIn(marker, source)
                self.verify_changed(path, source.replace(marker, "", 1))
        recovery = function_body(store, "fn recover(")
        self.assertIn("current::read_physical(&mut file, binding, minimum)?", recovery)
        self.assertNotRegex(recovery, r"(?:initialize|create|compare_and_swap|write_all)\s*\(")
        self.verify_changed(STORE, store.replace(
            "current::read_physical(&mut file, binding, minimum)?",
            "current::read_physical(&mut file, binding, None)?", 1,
        ))
        self.assertIn("physical::replay_image(&bytes, binding, minimum)?", current)
        self.verify_changed(CURRENT, current.replace(
            "physical::replay_image(&bytes, binding, minimum)?",
            "physical::replay_image(&bytes, binding, None)?", 1,
        ))
        self.assertIn("validate_minimum(state.as_ref(), minimum, minimum_witnessed)?", replay)
        self.verify_changed(REPLAY, replay.replace(
            "validate_minimum(state.as_ref(), minimum, minimum_witnessed)?",
            "validate_minimum(state.as_ref(), None, true)?", 1,
        ))

    def test_no_new_public_port_and_known_non_effect_errors_are_retained(self):
        source = (ROOT / STORE).read_text()
        production = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        self.assertEqual(set(re.findall(r"pub fn (\w+)\(", production)), {
            "create", "recover", "anchor",
        })
        observation = (ROOT / (DIRECTORY + "fenced_holdout_file_observation.rs")).read_text()
        self.assertIn('#[cfg(feature = "qualification-owned-file-read")]', source)
        self.assertIn("pub fn qualification_file_bytes(", observation)
        self.assertIn("pub(crate) fn qualification_unpoisoned_file_bytes(", source)
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
