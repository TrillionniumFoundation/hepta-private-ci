"""Original first-Publish history stays data under the whole new Root context.

These mutations are source closure checks. Actual cold processes, signer
authentication and whole-chain outcomes still require their native tests.
"""

from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
P = A + "authority_host_publication_"
ARM, READ = P + "completed_refusal.rs", P + "completed.rs"
OPEN, NEXT = P + "completed_open.rs", P + "completed_next_use.rs"
FILES, SUCCESSOR = P + "completed_files.rs", P + "completed_successor.rs"
DEPLOY = A + "authority_host_completed_publication_deployment.rs"
INPUTS = P + "deployment_inputs.rs"
PROVIDER = A + "authority_host_completed_observation.rs"
GEN = "codex-rs/hepta-neuron/src/cell_generation_feature_observer.rs"
PARSER = "codex-rs/hepta-neuron/src/cell_generation_observer.rs"
CALLERS = {
    "refusal": (READ,), "arm": (DEPLOY,), "deployment": (PROVIDER,),
    "open": (DEPLOY,), "observe": (PROVIDER,), "finish": (DEPLOY,),
    "inputs": (DEPLOY,),
    "original_profile": (READ, OPEN, NEXT, SUCCESSOR, INPUTS),
    "original_time": (READ, OPEN, INPUTS),
}
CALLERS = {"root_completed_publication_" + name: paths for name, paths in CALLERS.items()}
CALLERS.update({
    "root_completed_control_existing": (OPEN, ARM, SUCCESSOR,
        A + "authority_host_completed_checkpoint.rs", A + "authority_host_completed_record.rs"),
    "root_completed_successor_existing": (OPEN,),
    "root_completed_successor_cut": (A + "authority_host_completed_provider.rs",),
    "root_generation_original_feature_boundary": (READ,),
})


def private_fields(code, name):
    match = re.search(r"\bstruct " + name + r"(?:<[^{}]*>)?\s*\{", code)
    if match is None:
        raise PROOF.VerificationFailure("original private capability absent")
    end = PROOF._rust_item_end(code, match.start())
    if re.search(r"\bpub\b", code[match.end():end]):
        raise PROOF.VerificationFailure("original proof/reader fields must not be raw inputs")


def structure(path, source):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if path == ARM:
        private_fields(code, "OriginalPublicationHistoryProofV1")
        body, _ = route.function(source, "fn with_completed_history<T>(")
        inner = route.original.span(body, "let value = held.complete_armed(&armed, end, || {")
        for marker in ("let proof = OriginalPublicationHistoryProofV1 {", "let result = action(&proof)?;"):
            if not inner[0] < body.index(marker) < inner[1]:
                raise PROOF.VerificationFailure("proof creation and action must stay inside original Arm")
    if path == READ:
        private_fields(code, "OriginalCompletedPublicationReadV1")
        body, _ = route.function(source, "fn observe(")
        if re.search(r"(?:original|profile)\.writer\s*!=\s*context\.original_writer_proof", body):
            raise PROOF.VerificationFailure("new recipient proof must not replace the original publisher")
    if path == DEPLOY:
        body, _ = route.function(source, "fn with_original_completed_publication<T>(")
        inner = route.original.span(body, "|proof| {")
        for marker in ("OriginalPostAPublicationFiles::retain_original_publication(",
                       "OriginalInputs::completed_inputs(", "OriginalCompletedPublicationReadV1::open_existing(",
                       "let result = action(&mut read);", "OriginalCompletedPublicationReadV1::finish(&mut read)"):
            if not inner[0] < body.index(marker) < inner[1]:
                raise PROOF.VerificationFailure("all primary data and whole recipient action must stay armed")
        if "let result = action(&mut read)?;" in body:
            raise PROOF.VerificationFailure("an action error must not skip physical postchecks")
    if path == FILES:
        private_fields(code, "OriginalControlFile")
        private_fields(code, "OriginalControlRecord")
        start, end = route.original.span(code, "impl OriginalControlFile {")
        impl = code[start:end]
        opened, _ = route.function(impl, "fn open(")
        checked, _ = route.function(impl, "fn require_unchanged(")
        PROOF._verify_required_order({"required_order": [[
            "OpenOptions::new()", ".read(true)", "libc::O_NOFOLLOW | libc::O_CLOEXEC",
            ".open(&path)?", "Self::stamp(&file.metadata()?)?", "file.read_exact_at(",
            "held.require_unchanged()?;", "Ok(held)",
        ]]}, opened, path)
        PROOF._verify_required_order({"required_order": [[
            "for _ in 0..2", "Self::stamp(&std::fs::symlink_metadata(&self.path)?)? != self.stamp",
            "Self::stamp(&self.file.metadata()?)? != self.stamp", "self.file.read_exact_at(",
            "bytes != self.bytes", "Self::stamp(&self.file.metadata()?)? != self.stamp",
            "Self::stamp(&std::fs::symlink_metadata(&self.path)?)? != self.stamp",
        ]]}, checked, path)
        start, end = route.original.span(code, "impl OriginalControlRecord {")
        opened, _ = route.function(code[start:end], "fn open(")
        PROOF._verify_required_order({"required_order": [[
            "super::original_root()?;", "Digest32::of_bytes(owner.as_bytes())",
            "primary: OriginalControlFile::open(root.join(&name))?",
            "lock: OriginalControlFile::open(root.join(format!", "held.require_unchanged()?;",
        ]]}, opened, path)


class CompletedPublicationSourceClosure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[key].definition_path for key in CALLERS}
        paths.update(path for callers in CALLERS.values() for path in callers)
        cls.sources = {p: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / p).read_text())) for p in paths}

    def reject(self, path, marker, replacement="", function=None):
        source = (ROOT / path).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        if function:
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
            start = code.index("fn " + function + "(")
            end = PROOF._rust_item_end(code, start) + 1
        else:
            start, end = 0, len(source)
        self.assertIn(marker, source[start:end])
        changed = source[:start] + source[start:end].replace(marker, replacement, 1) + source[end:]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            def check(value):
                target.write_text(value)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                structure(path, value)
            check(source)
            with self.assertRaises(PROOF.VerificationFailure):
                check(changed)

    def test_actual_read_only_entry_sets_are_closed(self):
        ignored = tuple(self.manifest["ignored_path_fragments"])
        for identifier, expected in CALLERS.items():
            with self.subTest(identifier=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ignored)
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, replace(row, product_callers=expected[1:]), self.sources, ignored)
                injected = dict(self.sources)
                injected[A + "unregistered_completed_read.rs"] = "fn bypass() { " + row.symbol + "(); }"
                with self.assertRaises(PROOF.VerificationFailure):
                    PROOF._verify_boundary(ROOT, row, injected, ignored)

    def test_first_fact_scope_and_whole_recipient_context_are_armed(self):
        for marker in ("retained.binding.initial != initial.head_digest.to_string()",
                       "retained.binding.scope != scope.binding().to_string()",
                       "let armed = held.arm_ready(before)?;", "accepted.require_original(original)?;",
                       "!= initial.request.envelope.expiry_unix_seconds", "let result = action(&proof)?;",
                       "if held.load_matching()? != armed", "expected.phase = Phase::Ready;"):
            with self.subTest(marker=marker): self.reject(ARM, marker)
        self.reject(ARM, "not_send: PhantomData<Rc<()>>", "not_send: PhantomData<()>")
        self.reject(ARM, "original: &'a ReservedPublicationProfile,", "pub(crate) original: &'a ReservedPublicationProfile,")

    def test_unused_failed_or_repeated_read_cannot_clear_the_original_arm(self):
        for marker in ("!matches!(self.phase, ReadPhase::AwaitingContext)",
                       "self.require_terminal_selection(context)?;", "self.require_original_next_use(context, data)?;",
                       "context.terminal().request != context.initial().request", "context.terminal().owners != context.initial().owners",
                       "self.phase = ReadPhase::Observed(data.clone());"):
            with self.subTest(marker=marker): self.reject(READ, marker, function="observe")
        self.reject(READ, "std::mem::replace(&mut self.phase, ReadPhase::Failed)", function="finish")
        self.reject(READ, "RegisteredSuccessorData::finish_observed(held, &data.cut)?;", function="finish")

    def test_action_error_still_requires_physical_after_reads(self):
        self.reject(DEPLOY, "let result = action(&mut read);", "let result = action(&mut read)?;")
        for marker in ("let finished = OriginalCompletedPublicationReadV1::finish(&mut read);",
                       "files.require_original_files()?;", "material.require_unchanged()?;", "finished?;"):
            with self.subTest(marker=marker): self.reject(DEPLOY, marker)

    def test_original_files_cannot_be_repaired_or_replaced(self):
        for marker in ("metadata.uid() != 0", "metadata.mode() & 0o7777 != 0o600", "metadata.nlink() != 1",
                       "metadata.len() > 16 * 1024", "libc::O_NOFOLLOW | libc::O_CLOEXEC", "for _ in 0..2",
                       "bytes != self.bytes", "lock: OriginalControlFile::open(root.join(format!(\"{name}.lock\")))?,"):
            with self.subTest(marker=marker): self.reject(FILES, marker)
        self.reject(FILES, ".read(true)", ".read(true).create(true)")

    def test_complete_physical_publication_and_current_revocations_are_rechecked(self):
        for marker in ("!= *self.proof.original_current()", "!previous.is_drained()",
                       "!= profile.intent.previous_checkpoint", "!= profile.intent.genesis_checkpoint",
                       ".is_some_and(|before| before != &target)", "self.proof.require_original_observations(",
                       "self.service.issuer.revocations()? != actual"):
            with self.subTest(marker=marker): self.reject(READ, marker, function="require_physical")

    def test_fresh_acceptance_does_not_require_retired_c_or_reissue_execution(self):
        self.reject(OPEN, "OriginalCompletedPublicationModeV1::AcceptedPublication => None", function="open_existing")
        self.reject(READ, "OriginalCompletedPublicationModeV1::AcceptedPublication => None", function="observe")
        self.reject(OPEN, "let at = proof.verified_at_unix_ms();", "let at = 0;")
        self.reject(SUCCESSOR, "record.profile != *proof.original_reserved()", function="open_completed_history")

    def test_full_evaluated_terminal_and_original_a_c_relationship_are_required(self):
        for marker in ("terminal.training_no_update_v2().is_some()", "context.original_task_publication();",
                       "data.cut.writer_epoch != original.intent.target.writer_epoch()",
                       "a.input().scope.run_id != terminal.request.source_run_id", "a.input().scope.run_id == c.input().scope.run_id",
                       "c.bundle_digest() != selected_bundle", "cell.checkpoint_after != c.checkpoint_digest()",
                       "c.require_decision(&cell)", "task_owner_publication: publication_digest",
                       "a.publication_digest().as_array()", "a.checkpoint_digest().as_array()",
                       "terminal.receipts.last().map(|receipt| &receipt.observation) != Some(&expected)"):
            with self.subTest(marker=marker): self.reject(NEXT, marker)

    def test_generation_revision_zero_is_not_a_feature_genesis_proof(self):
        self.reject(PARSER, "if !matches!(&event, GenerationEvent::Drain)", "if false")
        self.reject(PARSER, "feature_boundary_only = false;", "feature_boundary_only = true;")
        self.reject(GEN, "!before.feature_boundary_only", "false")
        self.reject(GEN, "if self.observe()? != before", "if false")


if __name__ == "__main__":
    unittest.main()
