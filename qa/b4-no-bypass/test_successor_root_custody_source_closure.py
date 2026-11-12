"""Guard the actual C registration and retired physical read.

Source mutations are not native cold recovery or proof of a Dataset/Outcome.
The Root's existing publication refusal owns the entire observation interval.
"""
from dataclasses import replace
from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_task_read_source_closure as route

ROOT, PROOF, A = route.ROOT, route.PROOF, route.A
FILES = A + "authority_host_successor_deployment_files.rs"
READ = A + "authority_host_successor_files_read.rs"
STORE = A + "authority_host_publication_successor.rs"
ENROLL = A + "authority_host_publication_registration.rs"
TRANSPORT = A + "authority_host_generation_publication_transport.rs"
PLAN = A + "authority_host_post_a_publication.rs"
CELL = A + "authority_host_historical_cell_files.rs"
MATERIAL = A + "authority_host_post_a_publication_material.rs"
CALLERS = {
    "fixed_custody": (PLAN,), "fixed_data": (PLAN,),
    "baseline": (STORE,), "physical": (STORE,), "inputs": (),
    "register": (ENROLL,), "exact": (ENROLL,), "baseline_post": (ENROLL,),
    "capture_read": (TRANSPORT,), "finish": (TRANSPORT,), "reply_data": (TRANSPORT,),
    "physical_retirement": (), "cell_physical": (READ,), "readonly_description": (READ,),
}
CALLERS = {"root_successor_" + key: value for key, value in CALLERS.items()}


def require_structure(path, source):
    if path == FILES:
        body, _ = route.function(source, "fn open_original(")
        reserve = route.original.span(body, "Mode::Reserve => {")
        calls = list(re.finditer(r"RetainedMaterial::open_original\s*\(", body))
        if len(calls) != 1 or not reserve[0] < calls[0].start() < reserve[1]:
            raise PROOF.VerificationFailure("cold files must open only inside the later refusal")
        if "Mode::Recover => None" not in body:
            raise PROOF.VerificationFailure("Recover cannot preload or initialize execution files")
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        start = code.index("struct RootOriginalSuccessorFilesV1 {")
        end = PROOF._rust_item_end(code, start)
        if re.search(r"\bpub\b", code[start + len("struct RootOriginalSuccessorFilesV1 {"):end]):
            raise PROOF.VerificationFailure("Root custody fields cannot be raw construction inputs")
    if path == STORE:
        body, _ = route.function(source, "fn enroll(")
        reserve = route.original.span(body, "RootGenerationPublicationModeV1::Reserve => {")
        recover = route.original.span(body, "RootGenerationPublicationModeV1::Recover => {")
        for marker in ("RootOriginalSuccessorFilesV1::require_registered_baseline(",
                       "HostAuthorityFrontierStore::initialize("):
            if not reserve[0] < body.index(marker) < reserve[1]:
                raise PROOF.VerificationFailure("first baseline/init must stay in explicit Reserve")
        if any(x in body[recover[0]:recover[1]] for x in ("initialize(", "require_registered_baseline(")):
            raise PROOF.VerificationFailure("Recover cannot create missing original custody")
    if path == ENROLL:
        body, _ = route.function(source, "fn enroll_generation_publication(")
        arm = route.original.span(body, "|refusal| {")
        context = route.original.span(body, "|initial, proof| {")
        if not arm[0] < context[0] < context[1] < arm[1]:
            raise PROOF.VerificationFailure("actual Root writer context must stay in the durable arm")
        for match in re.finditer(r"with_learning_profile\s*\(", body):
            if not arm[0] < match.start() < arm[1]:
                raise PROOF.VerificationFailure("actual Root proof cannot precede durable arm")
        call = body.index("RegisteredSuccessorData::enroll(")
        if not context[0] < call < context[1]:
            raise PROOF.VerificationFailure("C registration needs the actual original Root context")
        enclosed = body[arm[0]:arm[1]]
        for marker, expected_depth in (
            ("RegisteredSuccessorData::require_baseline(&retained)?", 3),
            ("RegisteredSuccessorData::require_exact(&retained)?", 3),
            ("enrolled.successor = Some(retained)", 2),
            ("require_end(end)?", 1),
        ):
            matches = list(re.finditer(route.token_pattern(marker), enclosed))
            if len(matches) != 1:
                raise PROOF.VerificationFailure("one exact successor postcheck required")
            prefix = enclosed[:matches[0].start()]
            if prefix.count("{") - prefix.count("}") != expected_depth:
                raise PROOF.VerificationFailure("successor postcheck hidden behind another branch")
        after = body[context[1]:arm[1]]
        if not re.match(r"\s*,\s*\)\?;", after):
            raise PROOF.VerificationFailure("Root context postcheck failure must propagate")
        for marker in ("RegisteredSuccessorData::require_baseline(&retained)?",
                       "RegisteredSuccessorData::require_exact(&retained)?", "require_end(end)?"):
            if marker not in after:
                raise PROOF.VerificationFailure("exact post-context checks must precede Ready")
    if path == TRANSPORT:
        body, _ = route.function(source, "fn serve_generation_publication_with_end(")
        arm = route.original.span(body, "PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {")
        context = route.original.span(body, "|initial, proof| {")
        if not arm[0] < context[0] < context[1] < arm[1]:
            raise PROOF.VerificationFailure("whole Root current context must remain armed")
        call = body.index("RegisteredSuccessorData::observe_retired(")
        if not context[0] < call < context[1]:
            raise PROOF.VerificationFailure("C physical read needs actual Root current authority")
        tail = body[context[1]:arm[1]]
        if not re.match(r"\s*,\s*\)\?;", tail):
            raise PROOF.VerificationFailure("full writer postchecks must return Ok")
        for marker in ("RegisteredSuccessorData::finish_observed(",
                       "RegisteredSuccessorData::read_data(", "refusal::require_end(end)?", "Ok(raw)"):
            if marker not in tail:
                raise PROOF.VerificationFailure("C physical re-read and deadline must precede Ready")
    if path == READ:
        body, _ = route.function(source, "fn require_registered_baseline(")
        if re.search(r"try_lock|FileAnchorWitnessStore::open|sync_data|\.write\(", body):
            raise PROOF.VerificationFailure("live baseline must not acquire or repair a witness owner")
        body, _ = route.function(source, "fn with_inputs<T>(")
        locks = re.findall(r"files\[(\d+)\]\s*\.observe_ready", body)
        if locks != ["0", "1", "2"]:
            raise PROOF.VerificationFailure("only fixed config files share-lock during the live baseline")


class SuccessorRootCustodySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}
        paths = {cls.boundaries[key].definition_path for key in CALLERS}
        paths.update(path for values in CALLERS.values() for path in values)
        cls.sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(
            (ROOT / path).read_text())) for path in paths}

    def mutate(self, path, change):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        source = (ROOT / path).read_text()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            def verify(text):
                target.write_text(text)
                PROOF._verify_protected_files(root, {"protected_file": rows})
                require_structure(path, text)
            verify(source)
            changed = change(source)
            self.assertNotEqual(source, changed)
            with self.assertRaises(PROOF.VerificationFailure):
                verify(changed)

    reject = route.HistoricalTaskReadSourceTests.reject
    check = route.HistoricalTaskReadSourceTests.check

    def test_actual_closed_callers_reject_omission_and_new_entry(self):
        for identifier, callers in CALLERS.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, callers)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, self.sources, ())
                if callers:
                    with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                        PROOF._verify_boundary(ROOT, replace(row, product_callers=()), self.sources, ())
                rogue = dict(self.sources)
                rogue[A + "unregistered_successor_custody.rs"] = (
                    f"fn bypass(real: &{row.receiver_type}) {{ real.{row.symbol.rsplit('::', 1)[-1]}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, rogue, ())

    def test_recover_cannot_open_execution_files_outside_the_refusal(self):
        self.check(FILES, "open_original", ("original_root()?", "data.require_bounds()?", "Mode::Recover => None", "held.require_original()?"))
        self.mutate(FILES, lambda s: s.replace("Mode::Recover => None", "Mode::Recover => { RetainedMaterial::open_original(data.source_journal.clone(), uid, gid)?; None }", 1))
        self.mutate(FILES, lambda s: s.replace("    files: Option<[RetainedMaterial; 8]>", "    pub(crate) files: Option<[RetainedMaterial; 8]>", 1))

    def test_fixed_context_and_all_physical_identities_remain_bounded(self):
        self.check(FILES, "require_bounds", ("Digest32::from_array(self.cell_witness_scope).is_zero()", "Digest32::from_array(self.cell_witness_objective).is_zero()", "!(3..=4096).contains(&self.cell_witness_records)", "!(3..=16).contains(&self.maximum_cell_records)", "!(1..=64).contains(&self.inference_capacity)", "self.worker_generation == 0", "Generation::new(self.cell_witness_generation)", "require_absolute(&file.path)?", "file.device == 0 || file.inode == 0 || file.mode != 0o100600", "file.path == previous.path", "(file.device, file.inode) == (previous.device, previous.inode)"))

    def test_all_eight_fixed_descriptions_keep_their_original_roles(self):
        self.check(FILES, "files", tuple("&self." + name for name in (
            "source_configuration", "target_configuration", "signed_ingress", "source_journal",
            "source_witness", "cell_journal", "cell_witness", "inference_control")))

    def test_live_baseline_observes_headers_without_taking_writer_locks(self):
        self.check(READ, "require_registered_baseline", ("for _ in 0..2", "source.journal.metadata()?.len() != 0", "observe_original_file_anchor_v1(", "source.witness_scope,", "source.witness_generation,", "source.witness_records,", ".is_some()", "OriginalCellFiles::require_original_cell_baseline(&cell)?"))
        self.mutate(READ, lambda s: s.replace("for _ in 0..2 {", "source.witness.try_lock_shared()?; for _ in 0..2 {", 1))

    def test_original_configuration_target_and_readonly_descriptions_surround_action(self):
        # Generic marker remains exact; use the global protected-file guard.
        for marker in ("identity,", "original.source_journal != self.data.source_journal.path", "original.source_witness != self.data.source_witness.path", "!= *target", ".retain_original(identity, target, self.uid, self.gid)?", ".into_registered(identity, target, self.uid, self.gid)?", "source.require_unchanged()?", "target_data.require_unchanged()?", "ingress.require_unchanged()?", "file.require_original()?"):
            def change(source, marker=marker):
                key = "fn with_inputs<T>("
                body, _ = route.function(source, key)
                match = re.search(route.token_pattern(marker), body)
                self.assertIsNotNone(match, marker)
                code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
                start = code.index(key)
                lo, hi = start + match.start(), start + match.end()
                return source[:lo] + "/* " + source[lo:hi] + " */" + source[hi:]
            self.mutate(READ, change)
        self.check(MATERIAL, "original_readonly_description", ("self.require_original()?", ".read(true)", "libc::O_CLOEXEC | libc::O_NONBLOCK", "original.as_raw_fd()", "self.require_descriptor(&file)?"))

    def test_cold_physical_source_and_cell_must_match_the_exact_original_cut(self):
        self.check(READ, "observe_original_successor", ("inputs.witness.metadata()?.len() == 0", "FileAnchorWitnessStore::open(", "HistoricalCircuitTaskSourceV1::open(", "&inputs.fence,", "&inputs.registry,", "vec![inputs.source.clone()]", "OriginalCellFiles::read_original_successor_cell(", "RootHistoricalTaskPublicationDataV1::from_original_observation(&before, &decision)", "before.publication() != after.publication()", "before.journal_anchor() != after.journal_anchor()", "before.binding_digest() != after.binding_digest()", "writer_epoch: target.writer_epoch()"))
        for occurrence in (0, 1):
            self.reject(CELL, "read_original_successor_cell", "self.read_original_cell_data(definition, source, publication, target)?", occurrence)
        self.reject(CELL, "read_original_successor_cell", "if before != after")

    def test_only_first_reserve_can_create_the_original_publisher_record(self):
        self.check(STORE, "enroll", ("head.current != original.intent.previous", "head.prepared.is_some()", "original != &slot.profile", "registration.publisher_epoch == 0", "registration.checkpoint_owner_agent_id != identity.agent_id", "RootOriginalSuccessorFilesV1::require_registered_baseline(", "profile: slot.reserved.clone()", "serde_json::to_string(&registration.registered_identity)", "pid: registration.peer_pid", "boot_id: registration.boot_id.clone()", "process_start_ticks: registration.process_start_ticks", "HostAuthorityFrontierStore::<SuccessorRecord>::open(", "record.profile != slot.reserved", "record.files != files.deployment_digest()?.to_string()", "record.publisher.uid != config.peer_uid", "record.peer_gid != config.peer_gid"))

    def test_retirement_is_kernel_observed_before_and_after_original_physical_io(self):
        for occurrence in (0, 1):
            self.reject(STORE, "read_physical", "RetiredCheckpointPublisher::observe(record.publisher.clone())", occurrence)
        self.check(STORE, "read_physical", ("original_identity(record)?", "RootOriginalSuccessorFilesV1::observe_original_successor(", "&profile.intent.target", "cut.configuration != record.configuration"))
        self.check(STORE, "original_identity", ("serde_json::from_str(&record.registered_identity)", "serde_json::to_string(&registered)", "!= record.registered_identity", "registered.identity()"))

    def test_explicit_capture_cannot_be_inferred_from_missing_or_finalized_data(self):
        self.check(STORE, "observe_retired", ("self.require_exact()?", "capture != matches!(original.phase, SuccessorPhase::Registered)", "let cut = self.read_physical(&original)?", "if capture", ".compare_and_set(&self.owner, &original, &next)", "self.store.load(&self.owner)", "!= next", "*original = next", "retained.as_ref() == &cut"))
        self.check(STORE, "read_data", ("self.require_exact()?", "retained.as_ref() == &cut", "serde_json::to_vec(&*record)"))

    def test_registration_postchecks_must_finish_before_durable_ready(self):
        self.check(ENROLL, "enroll_generation_publication", ("PublicationRefusal::enroll(", "self.with_learning_profile(", "version != PublicationVersion::DurableV2", "enrolled.profile.writer != proof", "RegisteredSuccessorData::enroll(", "RegisteredSuccessorData::require_baseline(&retained)?", "RegisteredSuccessorData::require_exact(&retained)?", "verify_pinned_process(registration, config.peer_uid, config.peer_gid, owner, end)?"))
        self.mutate(ENROLL, lambda s: s.replace("RegisteredSuccessorData::require_baseline(&retained)?;", "if false { RegisteredSuccessorData::require_baseline(&retained)?; }", 1))

    def test_cold_commands_require_actual_current_and_complete_context_postchecks(self):
        self.check(TRANSPORT, "serve_generation_publication_with_end", ("PublicationRefusal::inspect(&slot.refusal, &slot.reserved, end, || {", "version != PublicationVersion::DurableV2 || before.current != intent.target", "RegisteredSuccessorData::observe_retired(successor, matches!(&request.command, Command::CaptureRetiredTask {}))?", "raw.len() > 16 * 1024", "RegisteredSuccessorData::finish_observed(successor, &observed.cut)?", "RegisteredSuccessorData::read_data(successor, observed.cut.clone())? != observed", "refusal::require_end(end)?"))
        self.check(STORE, "finish_observed", ("self.observe_retired(", "false", "!= *expected", "self.require_exact()"))


if __name__ == "__main__":
    unittest.main()
