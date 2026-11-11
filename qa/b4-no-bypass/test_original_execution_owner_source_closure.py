"""Preserve raw execution custody, exact recovery and effect-free Selector readback."""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_execution_owner_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
OWNER = AGENT + "neuron_cell_evaluation_execution_store.rs"
RECOVERY = AGENT + "neuron_cell_evaluation_execution_recovery.rs"
READBACK = AGENT + "neuron_cell_evaluation_execution_readback.rs"
SOURCES = AGENT + "circuit_model_selection_receipt_sources.rs"
WITNESS = "codex-rs/hepta-neuron/src/witness.rs"
FUNCTIONS = {
    OWNER: {
        "fn create(", "fn readback_only(", "fn require_current(", "fn unchanged(",
        "fn failed_operation(", "fn witness_effect(", "fn claim(", "fn complete(",
        "fn readback(", "fn witnessed(",
    },
    RECOVERY: {"fn recover("},
    READBACK: {"fn claim(", "fn complete(", "fn readback("},
}
EFFECT = re.compile(r"(?:\.|::)\s*(?:claim|complete|compare_and_swap|create)\s*\(")


def function_body(source, marker):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    start = code.index(marker)
    end = PROOF._rust_item_end(code, start)
    assert end is not None
    return code[start:end + 1]


def reject_effects(source, marker):
    if EFFECT.search(function_body(source, marker)):
        raise PROOF.VerificationFailure("readback or recovery contains an execution effect")


def reject_witness_current_effects(source):
    body = function_body(source, "fn current(")
    effects = re.compile(
        r"(?:\.|::)\s*(?:write|write_all|write_fmt|set_len|sync_all|sync_data|"
        r"open|create|compare_and_swap|unlock|try_clone|get_mut|into_inner)\s*\("
    )
    clears_poison = re.compile(r"\bself\s*\.\s*poisoned\s*\.\s*store\s*\(\s*false\b")
    if effects.search(body) or clears_poison.search(body) or "Ok(self.current)" in body:
        raise PROOF.VerificationFailure("physical witness readback cannot write, clear its fence or use a cached result")


class OriginalExecutionOwnerSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def rows(self, path):
        return [row for row in self.manifest["protected_file"] if row["path"] == path]

    def verify_changed(self, path, change):
        source = (ROOT / path).read_text()
        rows = self.rows(path)
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(change(source))
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def test_every_physical_mutation_recovery_and_fence_guard_is_effective(self):
        for path, functions in FUNCTIONS.items():
            rules = self.rows(path)[0]["required_function_order"]
            self.assertEqual({row["function"] for row in rules}, functions)
            for rule in rules:
                for marker in rule["sequence"]:
                    with self.subTest(path=path, function=rule["function"], marker=marker):
                        def remove(source, function=rule["function"], token=marker):
                            start = source.index(function)
                            end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), start)
                            self.assertIsNotNone(end)
                            offset = source.index(token, start, end + 1)
                            return source[:offset] + source[offset + len(token):]
                        self.verify_changed(path, remove)

    def test_original_constructors_are_closed_and_selector_gets_only_readback(self):
        expected = {
            "learning_original_execution_store_create": (AGENT + "neuron_cell_evaluation_qualification_owner.rs",),
            "learning_original_execution_store_recover": (AGENT + "neuron_cell_evaluation_qualification_owner.rs",),
            "learning_original_execution_store_readback_only": (SOURCES, AGENT + "neuron_cell_evaluation_qualification_sources.rs"),
            "learning_original_owner_physical_current": ("codex-rs/hepta-agentd/src/learning_owner_journal.rs", "codex-rs/hepta-agentd/src/cell_composed_q24_training_owner.rs", "codex-rs/hepta-agentd/src/cell_q24_model_proposal.rs", "codex-rs/hepta-agentd/src/neuron_cell_evaluation_execution_store.rs", "codex-rs/hepta-agentd/src/circuit_task_source_journal.rs",),
        }
        paths = {path for identifier in expected for path in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                self.assertEqual(row.product_callers, callers)
                PROOF._verify_boundary(ROOT, row, sources, ())
                if callers:
                    with self.assertRaises(PROOF.VerificationFailure):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                changed = dict(sources)
                changed[AGENT + "unregistered_execution_owner.rs"] = (
                    f"fn unexpected(owner: &{row.receiver_type}) {{ owner.{method}(); }}"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, changed, ())
        self.assertEqual(self.boundaries["root_learning_original_stage_assembly"].product_callers, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_recovery_and_all_readback_functions_have_no_effect_calls(self):
        for path, marker in (
            (RECOVERY, "fn recover("), (OWNER, "fn readback("),
            (READBACK, "fn claim("), (READBACK, "fn complete("), (READBACK, "fn readback("),
        ):
            source = (ROOT / path).read_text()
            reject_effects(source, marker)
            start = source.index(marker)
            body_start = source.index("{", start) + 1
            for call in ("owner.claim(key);", "owner.complete(key, bytes);",
                         "witness.compare_and_swap(old, new);", "Owner::create(file, witness);"):
                with self.subTest(path=path, marker=marker, call=call):
                    changed = source[:body_start] + call + source[body_start:]
                    with self.assertRaises(PROOF.VerificationFailure):
                        reject_effects(changed, marker)

    def test_selector_cannot_reopen_raw_parts_or_initialize_witnesses(self):
        for old, new in (
            ("pub executions: &'a mut OriginalCellEvaluationExecutionStoreV1<W>",
             "pub executions: &'a mut LockedFileProductEvaluationExecutionStoreV1"),
            ("OriginalCellEvaluationExecutionStoreV1::readback_only(",
             "OriginalCellEvaluationExecutionStoreV1::create("),
            ("config.execution_evidence.key()", "different_key"),
        ):
            with self.subTest(old=old):
                self.verify_changed(SOURCES, lambda source, old=old, new=new: source.replace(old, new))
        for path in (RECOVERY, READBACK, SOURCES):
            with self.subTest(path=path):
                self.verify_changed(path, lambda source: source + "\nfn repair() { witness.compare_and_swap(old, new); }\n")

    def test_no_owner_can_extract_raw_custody_or_provision_signing_authority(self):
        for path in FUNCTIONS:
            for code in (
                "pub journal: Raw", "pub witness: Witness",
                "SigningKey::from_bytes(bytes);", "LearningEvidenceVerifierV1::new(trust);",
                "File::open(path);", "owner.try_clone();", "owner.into_inner();",
                "owner.get_mut();",
            ):
                with self.subTest(path=path, code=code):
                    self.verify_changed(path, lambda source, code=code: source + "\nfn bypass() { " + code + " }\n")
        owner = (ROOT / OWNER).read_text()
        self.assertIn("StoreError::Missing | StoreError::Conflict | StoreError::Rejected => error", owner)
        self.verify_changed(OWNER, lambda source: source.replace(
            "StoreError::Missing | StoreError::Conflict | StoreError::Rejected => error",
            "StoreError::Missing | StoreError::Conflict | StoreError::Rejected => StoreError::Indeterminate",
        ))

    def test_positive_fixture_uses_production_owner_and_retains_custody_limits(self):
        source = (ROOT / AGENT / "circuit_model_selection_evaluation_support_tests.rs").read_text()
        self.assertIn("OriginalCellEvaluationExecutionStoreV1::create(", source)
        self.assertIn("OriginalCellEvaluationExecutionOwnerV1::create(", source)
        self.assertIn("OriginalCellEvaluationReceiptOwnerV1::create(", source)
        self.assertIn("retention_receipt_digests: Vec::new()", source)
        self.assertIn("cohorts, product declarations and role custody remain test fixtures", source)
        self.assertNotIn("WitnessedExecutions", source)
        self.assertFalse((ROOT / AGENT / "circuit_model_selection_execution_support_tests.rs").exists())


    def reject_witness_guard_removals(self, functions):
        source = (ROOT / WITNESS).read_text()
        rows = self.rows(WITNESS)
        self.assertEqual(len(rows), 1)
        rules = rows[0]["required_function_order"]
        self.assertEqual({rule["function"] for rule in rules}, {
            "fn acquire(", "fn open(", "fn current(", "fn compare_and_swap(",
        })
        for rule in rules:
            if rule["function"] not in functions:
                continue
            cursor = source.index(rule["function"])
            end = PROOF._rust_item_end(PROOF._strip_rust_non_code(source), cursor)
            self.assertIsNotNone(end)
            for marker in rule["sequence"]:
                with self.subTest(function=rule["function"], marker=marker):
                    offset = source.index(marker, cursor, end + 1)
                    self.verify_changed(
                        WITNESS,
                        lambda text, offset=offset, count=len(marker):
                            text[:offset] + text[offset + count:],
                    )
                    cursor = offset + len(marker)

    def test_file_witness_current_checks_full_history_cursor_and_sticky_poison(self):
        self.reject_witness_guard_removals({"fn current("})

    def test_file_witness_open_and_cas_preserve_bounds_lock_and_physical_effect_order(self):
        self.reject_witness_guard_removals({"fn acquire(", "fn open(", "fn compare_and_swap("})
        for marker in self.rows(WITNESS)[0]["required"]:
            with self.subTest(marker=marker):
                self.verify_changed(WITNESS, lambda text, marker=marker: text.replace(marker, "", 1))

    def test_file_witness_readback_cannot_reopen_write_clear_poison_or_return_cache(self):
        source = (ROOT / WITNESS).read_text()
        reject_witness_current_effects(source)
        start = source.index("fn current(")
        body_start = source.index("{", start) + 1
        for code in (
            "file.write_all(bytes);", "file.set_len(0);", "file.sync_data();",
            "file.sync_all();", "File::open(path);", "File::create(path);",
            "file.unlock();", "file.try_clone();", "file.get_mut();",
            "file.into_inner();", "self.compare_and_swap(old, next);",
            "self.poisoned.store(false, Ordering::Release);", "return Ok(self.current);",
        ):
            with self.subTest(code=code):
                changed = source[:body_start] + code + source[body_start:]
                with self.assertRaises(PROOF.VerificationFailure):
                    reject_witness_current_effects(changed)
        for code in (
            "SigningKey::from_bytes(bytes);", "LearningEvidenceVerifierV1::new(trust);",
            "File::open(path);", "std::fs::read(path);", "file.try_clone();",
            "pub file: Raw", "pub current: Anchor", "pub history_digest: Digest",
        ):
            with self.subTest(code=code):
                self.verify_changed(
                    WITNESS,
                    lambda text, code=code: text + "\nfn bypass() { " + code + " }\n",
                )


if __name__ == "__main__":
    unittest.main()
