"""Keep the original Published CURRENT I/O inside one borrowed read call.

This is a source and caller mutation gate. It does not establish native timing,
the Observer's unchanged 500 ms contract, or ordinary learning qualification.
"""
from collections import Counter
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_published_current_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC and SPEC.loader
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
A = "codex-rs/hepta-agentd/src/"
CURRENT = A + "circuit_feature_current_read.rs"
TASK = A + "circuit_feature_current.rs"
LEARNING = A + "circuit_feature_current_learning.rs"
OWNER = A + "circuit_feature_current_owner.rs"
SERVICE = A + "circuit_learning_read_service.rs"
EXPECTED = {
    "circuit_feature_original_selection_observation": (
        A + "circuit_selection_receipt_owner.rs",
        A + "circuit_model_selection_receipt_sources.rs",
        SERVICE,
        A + "circuit_learning_completion_readiness_service.rs",
        A + "circuit_retained_version_c_task.rs",
        A + "circuit_evaluated_selection_receipt.rs",
    ),
    "circuit_feature_original_next_use_observation": (
        A + "circuit_next_use_receipt_owner.rs",
        A + "circuit_evaluated_next_use_receipt.rs",
    ),
    "circuit_feature_read_current_individual": (LEARNING, OWNER, SERVICE),
    "circuit_feature_read_current_begin": (SERVICE,),
    "circuit_feature_read_current_purpose": (SERVICE,),
    "circuit_feature_read_current_require": (LEARNING, OWNER, SERVICE),
    "circuit_feature_read_current_finish": (SERVICE,),
    "circuit_feature_read_current_selection": (SERVICE,),
    "circuit_feature_read_current_next_use": (),
    "circuit_feature_original_next_use_read_set": (SERVICE,),
    "circuit_feature_read_current_committed": (LEARNING,),
}


class OriginalPublishedCurrentTransactionClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def code(self, source):
        return PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))

    def verifies(self, path, source):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def mutate(self, path, function, marker, replacement="", occurrence=0):
        source = (ROOT / path).read_text()
        code = self.code(source)
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        offsets = [m.start() for m in re.finditer(re.escape(marker), code[start:end + 1])]
        self.assertGreater(len(offsets), occurrence, (function, marker))
        offset = start + offsets[occurrence]
        self.verifies(path, source)
        with self.assertRaises(PROOF.VerificationFailure):
            self.verifies(path, source[:offset] + replacement + source[offset + len(marker):])

    def test_exact_original_read_callers_and_unregistered_callers(self):
        paths = {p for identifier in EXPECTED for p in (
            self.boundaries[identifier].definition_path,
            *self.boundaries[identifier].product_callers,
        )}
        index = {p: self.code((ROOT / p).read_text()) for p in paths}
        for identifier, callers in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, index, ())
                extra = dict(index)
                extra[A + "unregistered_published_current.rs"] = (
                    "fn bypass(owner: &" + row.receiver_type + ") { " + row.symbol + "(owner); }"
                )
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())

    def test_exact_first_and_last_slots_cannot_skip_original_current(self):
        for marker, occurrence in (
            ("cell.task.require_current()?", 0),
            ("cell.task.require_current()?", 1),
            ("cell.task.require_current()?", 2),
            ("if slots == 0", 0),
            ("if slots == purpose.slots()", 0),
            ("self.state = State::Complete", 0),
        ):
            with self.subTest(marker=marker, occurrence=occurrence):
                self.mutate(CURRENT, "fn require(", marker, occurrence=occurrence)
        for old, new in (("Self::Selection => 6", "Self::Selection => 5"),
                         ("Self::NextUse => 9", "Self::NextUse => 8"),
                         ("Self::NextUse => 9", "Self::NextUse => 10")):
            with self.subTest(slot=old, change=new):
                self.mutate(CURRENT, "fn slots(", old, new)

    def test_same_live_original_allocations_and_borrow_cannot_be_replaced(self):
        for marker in ("!Arc::ptr_eq(&self.original.original, &cell.original)",
                       "!Arc::ptr_eq(&self.original.task.0, &cell.task.0)"):
            self.mutate(CURRENT, "fn require(", marker, "false")
        source = (ROOT / CURRENT).read_text()
        code = self.code(source)
        start = code.index("pub(super) struct OriginalPublishedReadCurrent")
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        declaration = source[start:end + 1]
        for marker in ("original: &'a PublishedCircuitCellOwnerV1<W>",
                       "state: State", "_single_thread: PhantomData<Rc<()>>"):
            for visibility in ("pub ", "pub(crate) ", "pub(super) "):
                with self.subTest(field=marker, visibility=visibility):
                    self.assertEqual(declaration.count(marker), 1)
                    changed = declaration.replace(marker, visibility + marker, 1)
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verifies(CURRENT, source[:start] + changed + source[end + 1:])
        for before, after in (("PhantomData<Rc<()>>", "PhantomData<()>"),
                              ("original: &'a PublishedCircuitCellOwnerV1<W>",
                               "original: &'static PublishedCircuitCellOwnerV1<W>")):
            with self.subTest(change=before):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(CURRENT, source.replace(before, after, 1))

    def test_partial_wrong_purpose_and_extra_slots_poison_the_call(self):
        for function, marker in (
            ("fn select_purpose(", "mem::replace(&mut self.state, State::Refused)"),
            ("fn select_purpose(", "State::BeforePurpose { slots: 1 }"),
            ("fn select_purpose(", "self.state = State::Reading { purpose, slots: 1 }"),
            ("fn require(", "mem::replace(&mut self.state, State::Refused)"),
            ("fn require(", "if slots >= 1"),
            ("fn require(", "if !(1..purpose.slots()).contains(&slots)"),
            ("fn require(", "State::Complete | State::Refused"),
            ("fn finish(", "if !matches!(self.state, State::Complete)"),
        ):
            with self.subTest(function=function, marker=marker):
                self.mutate(CURRENT, function, marker)

    def test_actual_mode_fixes_one_call_and_final_source_precedes_completion(self):
        for marker in (
            "OriginalPublishedReadCurrent::for_original_read(&self.cell)",
            "self.require_original_selection(&selection)?",
            "let mode = self.context.mode()?;",
            "wire::Mode::Selection => OriginalPublishedReadPurpose::Selection",
            "wire::Mode::NextUse => OriginalPublishedReadPurpose::NextUse",
            "PublishedCircuitCellOwnerV1::read_learning_next_use_set(",
            "OriginalPublishedReadCurrent::finish(current)?",
        ):
            with self.subTest(marker=marker):
                self.mutate(SERVICE, "fn read_original(", marker)
        # Each original input and CURRENT endpoint remains at its real position.
        for marker in (
            "self.require_original_task_input()?",
            "OriginalPublishedReadCurrent::require(&mut current, &self.cell)?",
            "cell.read_learning_selection_with_current(&coordinator, &mut current)?",
        ):
            for occurrence in (0, 1):
                self.mutate(SERVICE, "fn read_original(", marker, occurrence=occurrence)
        for marker in ("source.require_original_input(&self.identity, input)?",
                       "input.scope.run_id == request.source_run_id"):
            self.mutate(SERVICE, "fn require_original_task_input(", marker)
        self.mutate(SERVICE, "fn require_task_input_current_with_current(",
                    "self.require_original_task_input()?")
        for occurrence in (0, 1):
            self.mutate(SERVICE, "fn require_task_input_current_with_current(",
                        "OriginalPublishedReadCurrent::require(current, &self.cell)?",
                        occurrence=occurrence)


    def test_all_version_source_cell_and_checkpoint_reads_remain_real(self):
        for path, function, marker in (
            (LEARNING, "fn read_learning_selection_with_current(",
             "LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())"),
            (LEARNING, "fn read_learning_selection_with_current(",
             "self.task.0.original.lock().map_err(invalid)?.selection("),
            (LEARNING, "fn read_learning_next_use_set(",
             "self.read_learning_selection_with_current(&prefix, current)?"),
            (LEARNING, "fn read_learning_next_use_set(",
             "PublishedCircuitCellOwnerV1::committed_with_current(self, &before, current)?"),
            (LEARNING, "fn read_learning_next_use_set(",
             "if actual_selection != selection.observation"),
            (LEARNING, "fn read_learning_next_use_set(",
             "receipt.bundle_digest != candidate_bundle"),
            (OWNER, "fn committed_with_current(", "self.original.lock().map_err(invalid)?"),
            (OWNER, "fn committed_with_current(", ".pending_inference(&input.scope)"),
            (OWNER, "fn committed_with_current(", ".lookup(&input.scope, &input.operation_id, digest)"),
            (OWNER, "fn committed_with_current(", "source.require_decision(&decision)"),
            (OWNER, "fn committed_with_current(", "owner.snapshot(&input.scope)"),
            (OWNER, "fn committed_with_current(", "decision.checkpoint_after != source.checkpoint_digest()"),
        ):
            with self.subTest(function=function, marker=marker):
                self.mutate(path, function, marker)
        for occurrence in (0, 1):
            self.mutate(LEARNING, "fn read_learning_next_use_set(",
                        ".read_run_publication(identity, &self.task.source().scope.run_id)",
                        occurrence=occurrence)
        # Consume the native pair's owned results within this call. The service
        # keeps its separate real Source-input endpoints; it never imports a
        # cached publication from a caller or reconnects a replacement owner.
        for marker in ("selection: selection_observation", "observation: result",
                       "source_publication: before.publication_digest()"):
            self.mutate(LEARNING, "fn read_learning_next_use_set(", marker)
        for marker in ("self.selection", "self.observation", "self.source_publication"):
            self.mutate(LEARNING, "fn into_parts(", marker)
        for marker in (
            ".read_learning_next_use_set(coordinator, source, identity, current)?",
            ".into_parts()",
            "Ok(observation)",
        ):
            self.mutate(LEARNING, "fn read_learning_next_use_with_current<", marker)

    def test_public_individual_reads_and_writer_guards_keep_physical_current(self):
        for path, function, marker in (
            (LEARNING, "fn read_learning_selection(", "OriginalPublishedReadCurrent::individual(self)"),
            (LEARNING, "fn read_learning_next_use<", "OriginalPublishedReadCurrent::individual(self)"),
            (OWNER, "fn committed(", "OriginalPublishedReadCurrent::individual(self)"),
            (SERVICE, "fn require_task_input_current(",
             "OriginalPublishedReadCurrent::individual(&self.cell)"),
        ):
            with self.subTest(function=function):
                self.mutate(path, function, marker)
        self.mutate(OWNER, "fn scope(", ".require_current()")
        self.mutate(OWNER, "fn admit_inference(", ".require_active()", occurrence=0)
        self.mutate(OWNER, "fn admit_inference(", ".require_active()", occurrence=1)

    def test_checks_hidden_in_unused_closures_are_rejected(self):
        for path, function, marker in (
            (CURRENT, "fn select_purpose(",
             "let prior = mem::replace(&mut self.state, State::Refused);"),
            (CURRENT, "fn require(",
             "let prior = mem::replace(&mut self.state, State::Refused);"),
            (CURRENT, "fn finish(", "if !matches!(self.state, State::Complete)"),
            (SERVICE, "fn read_original(", "OriginalPublishedReadCurrent::finish(current)?;"),
            (SERVICE, "fn require_original_task_input(",
             "source.require_original_input(&self.identity, input)?;"),
        ):
            with self.subTest(function=function, marker=marker):
                source = (ROOT / path).read_text()
                code = self.code(source)
                start = code.index(function)
                end = PROOF._rust_item_end(code, start)
                offset = code.index(marker, start, end + 1)
                if marker.startswith("if "):
                    last = PROOF._rust_item_end(code, offset) + 1
                else:
                    last = offset + len(marker)
                moved = source[offset:last]
                replacement = "let _not_invoked = || { " + moved + " };"
                self.verifies(path, source)
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(path, source[:offset] + replacement + source[last:])

    def test_no_export_clone_signing_io_or_async_escape_is_added(self):
        source = (ROOT / CURRENT).read_text()
        for attack in (
            "impl Clone for OriginalPublishedReadCurrent {}",
            "unsafe impl Send for OriginalPublishedReadCurrent {}",
            "pub(crate) fn arbitrary() {}",
            "fn export() { Box::leak(value); }",
            "struct Forgery { signer: SigningKey }",
            "fn reconnect() { UnixStream::connect(path); }",
            "#[derive(Deserialize)] struct Imported {}",
        ):
            with self.subTest(attack=attack):
                with self.assertRaises(PROOF.VerificationFailure):
                    self.verifies(CURRENT, source + "\n" + attack + "\n")
        code = self.code(source)
        self.assertEqual(Counter(re.findall(r"\bfn\s+(\w+)\s*\(", code)),
                         Counter(("slots", "individual", "for_original_read",
                                  "select_purpose", "require", "finish")))
        self.assertNotIn("async ", code)
        self.assertNotIn("await", code)

    def test_actual_withdrawal_and_wrong_original_mechanisms_remain_mounted(self):
        task = (ROOT / TASK).read_text()
        self.assertIn('#[path = "circuit_feature_current_read.rs"]\nmod current_read;', task)
        support = (ROOT / (A + "circuit_learning_read_support_tests.rs")).read_text()
        owners = (ROOT / (A + "circuit_learning_read_owner_tests.rs")).read_text()
        self.assertIn('#[path = "circuit_feature_current_read_support_tests.rs"]', support)
        self.assertIn("pub(crate) mod current_slots;", support)
        self.assertIn('#[path = "circuit_feature_current_read_tests.rs"]', owners)
        self.assertIn("mod current_slots;", owners)
        tests = (ROOT / (A + "circuit_feature_current_read_tests.rs")).read_text()
        for marker in (
            "published_current_last_original_slot_rejects_actual_withdrawal",
            "published_current_call_rejects_other_original_incomplete_and_reuse",
            "slot_fixture::pending_final_reads(&f.original.session.cell)?",
            "f.original.version.withdraw()?",
            "std::mem::discriminant(&final_error)",
            "std::mem::discriminant(&public_error)",
            "final_error.to_string(), public_error.to_string()",
            "owner_bytes(&f.original.session)?",
        ):
            self.assertIn(marker, tests)
        helper = (ROOT / (A + "circuit_feature_current_read_support_tests.rs")).read_text()
        for marker in ("self.current.require(self.cell)?", "self.current.finish()",
                       "wrong\n        .require(other)", "wrong.finish().is_err()",
                       "unfinished.current.finish().is_err()", "let same = cell.clone()",
                       "complete.current.require(cell).is_err()", "complete.current.finish().is_err()",
                       "missing_purpose.require(cell).is_err()", "missing_purpose.finish().is_err()"):
            self.assertIn(marker, helper)


if __name__ == "__main__":
    unittest.main()
