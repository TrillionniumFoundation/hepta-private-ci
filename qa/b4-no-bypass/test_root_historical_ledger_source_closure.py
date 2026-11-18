"""Root four-file custody/cold refusal source checks, not native admission proof."""

from pathlib import Path
import re
import tempfile
import tomllib
import unittest

import test_historical_ledger_readonly_source_closure as component

ROOT = component.ROOT
AGENT = component.AGENT


class RootHistoricalLedgerSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())

    reject_removal = component.HistoricalLedgerReadonlySourceTests.reject_removal
    check_markers = component.HistoricalLedgerReadonlySourceTests.check_markers


    def _deadline_function(self, source, function):
        code = component.PROOF._strip_cfg_test_items(component.PROOF._strip_rust_non_code(source))
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = component.PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return start, end + 1, code[start:end + 1]

    def _verify_original_deadline_flow(self, root):
        # These are the actual four functions which carry the bound session end.
        # Existing authority, physical, phase and ordering checks still run first.
        functions = (
            ("authority_host_initial_enrollment_runtime.rs", "fn enroll_original("),
            ("authority_host_historical_ledger_session.rs", "fn register_original_source_ledger("),
            ("authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger("),
            ("authority_host_historical_ledger_pin.rs", "fn with_original_ledger_capture<T>("),
        )
        for filename, function in functions:
            path = AGENT + filename
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            self.assertTrue(rows)
            component.PROOF._verify_protected_files(root, {"protected_file": rows})
            _, _, body = self._deadline_function((root / path).read_text(), function)
            compact = re.sub(r"\s+", "", body)
            if re.search(r"\b(?:let\s+(?:mut\s+)?|mut\s+|&\s*mut\s+)(?:end|capture_end)\b", body):
                raise component.PROOF.VerificationFailure("original deadline cannot be rebound or borrowed mutably")
            if re.search(r"\blet\s*\([^;=]*\b(?:end|capture_end)\b[^;=]*\)\s*=", body):
                raise component.PROOF.VerificationFailure("original deadline cannot be destructured into a new binding")
            if re.search(r"(?<![\w.])(?:end|capture_end|self\.end|context\.end|original\.capture_end)(?:=[^=>]|[+*/-]=)", compact):
                raise component.PROOF.VerificationFailure("original deadline cannot be reassigned")
            if filename == "authority_host_historical_ledger_pin.rs" and re.search(r"\breturn\s+Ok\(", body):
                raise component.PROOF.VerificationFailure("capture cannot return success before its original postchecks")
            if filename in ("authority_host_historical_ledger_registration.rs", "authority_host_historical_ledger_pin.rs"):
                expected = "end" if filename.endswith("_registration.rs") else "original.capture_end"
                values = re.findall(r"Instant::now\(\)>=(.*?)(?=\|\||\{|;)", compact)
                if values != [expected, expected]:
                    raise component.PROOF.VerificationFailure("both expiry checks must use their unchanged original deadline")

    def _reject_deadline_transform(self, filename, function, transform):
        paths = (
            "authority_host_initial_enrollment_runtime.rs",
            "authority_host_historical_ledger_session.rs",
            "authority_host_historical_ledger_registration.rs",
            "authority_host_historical_ledger_pin.rs",
        )
        source = (ROOT / (AGENT + filename)).read_text()
        start, end, _ = self._deadline_function(source, function)
        changed = transform(source[start:end])
        self.assertNotEqual(changed, source[start:end])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in paths:
                target = root / (AGENT + name)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text((ROOT / (AGENT + name)).read_text())
            self._verify_original_deadline_flow(root)
            (root / (AGENT + filename)).write_text(source[:start] + changed + source[end:])
            with self.assertRaises(component.PROOF.VerificationFailure):
                self._verify_original_deadline_flow(root)

    def _replace_deadline_marker(self, body, old, new, occurrence=0):
        offset = 0
        for _ in range(occurrence + 1):
            offset = body.index(old, offset) + len(old)
        offset -= len(old)
        return body[:offset] + new + body[offset + len(old):]

    def _move_deadline_block(self, body, marker, before):
        code = component.PROOF._strip_rust_non_code(body)
        self.assertEqual(code.count(marker), 1)
        start = code.index(marker)
        end = component.PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        block = body[start:end + 1]
        remainder = body[:start] + body[end + 1:]
        self.assertEqual(remainder.count(before), 1)
        offset = remainder.index(before)
        return remainder[:offset] + block + "\n" + remainder[offset:]

    def test_actual_capture_and_complete_task_read_callers_are_fixed(self):
        rows = {row["id"]: row for row in self.manifest["boundary"]}
        expected = {
            "root_original_ledger_metadata": ["authority_host_historical_source_deployment.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_custody": ["authority_host_historical_ledger_session.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_install": ["authority_host_historical_source_deployment.rs"],
            "root_original_ledger_runtime_registration": ["authority_host_initial_enrollment_runtime.rs"],
            "root_original_ledger_baseline": ["authority_host_historical_ledger_session.rs"],
            "root_original_ledger_runtime_take": ["authority_host_historical_source_session.rs"],
            "root_original_source_data_context": ["authority_host_historical_source_pin.rs"],
            "root_original_ledger_capture_context": ["authority_host_historical_source_data.rs"],
            "root_original_ledger_capture": ["authority_host_historical_source_pin.rs"],
            "root_original_ledger_physical_open": ["authority_host_historical_ledger_pin.rs", "authority_host_historical_ledger_history.rs"],
            "root_original_ledger_historical_context": ["authority_host_historical_task.rs"],
            "root_original_ledger_historical_observation": ["authority_host_historical_task.rs"],
            "root_original_ledger_historical_cut": ["authority_host_historical_task.rs"],
            "root_original_ledger_read_data": ["authority_host_historical_task.rs"],
        }
        for identifier, callers in expected.items():
            with self.subTest(boundary=identifier):
                self.assertEqual(rows[identifier]["product_callers"], [AGENT + name for name in callers])

    def test_root_metadata_retains_only_existing_distinct_public_inputs(self):
        self.check_markers(AGENT + "authority_host_initial_ledger_files.rs", "fn open_original(", (
            "original_root()?", "MetadataFile::open_metadata(path)?", "data.schema != 1",
            "paths[..index].contains(path)", "*path == &data.ledger.generator_key",
            "RootInitialLearningTrustFilesV1::open_original_learning_trust(", "held.require_original_files()?"))
        for index in range(4):
            self.reject_removal(AGENT + "authority_host_initial_ledger_files.rs", "fn open_original(",
                                f"OriginalFile::open_original(paths[{index}])?")

    def test_custody_checks_four_inodes_private_original_owner_and_metadata(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn retain_original_ledger(", (
            "original_root()?", "uid == 0 || gid == 0", "FilePin::readonly(descriptor, uid, gid)?",
            "(previous.device, previous.inode) == (pin.device, pin.inode)", "held.require_original_files()?"))
        self.check_markers(AGENT + "authority_host_initial_ledger_files.rs", "fn require_original_files(", (
            "self.metadata.require_metadata_unchanged()?", "self.trust.require_original_files()?",
            "file.require_original_file()?", "self.metadata.require_metadata_unchanged()"))

    def test_empty_baseline_is_physically_locked_twice_before_any_initialization(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn require_empty_baseline(", (
            "self.open_original_descriptors()?", "file.try_lock_shared()", "for _ in 0..2",
            "file.metadata()?.len() != 0"))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + "authority_host_historical_ledger_registration.rs",
                                "fn register_original_initial_ledger(", "files.require_empty_baseline()?", occurrence)

    def test_four_locks_and_independent_signature_reader_survive_the_context(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn open_original_terminal(", (
            "ReadOnlyLedgerViewV1::observe_closed(", "ReadOnlyLedgerViewV1::open_at_retained_cut(",
            "signatures.try_lock_shared()", "signature_witness\n            .try_lock_shared()",
            "FilePin::readonly(&self.files[2], self.uid, self.gid)?",
            "signature_files: [signatures, signature_witness]"))

    def test_signature_cut_requires_actual_witness_and_two_completed_envelopes(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn open_original_terminal(", (
            "observe_original_file_anchor_v1(",
            "anchor.sequence != 5 || expected_signatures.is_some_and(|expected| expected != anchor)",
            "context.signature_binding()", "sequence: anchor.sequence - 1", "history_digest: anchor.checkpoint_digest"))
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn observe_original_terminal(", (
            "context.execution_keys()", "ProductEvaluationExecutionStateV1::Completed(bytes)",
            "self.signatures.readback(key)", ".verify_original_terminal(", "&envelopes[0]", "&envelopes[1]"))

    def test_all_physical_images_and_frontiers_are_rechecked(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn signature_images(", (
            "anchor != Some(self.anchor)", "image(&self.signature_files[0], 32 * 1024 * 1024)? != before[0]",
            "image(&self.signature_files[1], 1024 * 1024)? != before[1]"))
        self.check_markers(AGENT + "authority_host_historical_ledger_files.rs", "fn require_unchanged(", (
            "self.ledger.observe().map_err(io::Error::other)?.cut != expected.cut",
            "self.anchor != expected.signature_anchor", "self.signature_images()? != expected.signature_images"))

    def test_baseline_arm_contains_the_entire_original_root_context(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger(", (
            "RootDataRefusalV1::create_fresh(", "RootDataKind::HistoricalLedger",
            "self.with_initial_publication_context(", "slot.mode != RootGenerationInitialModeV1::Reserve",
            "files.deployment.initial != slot.profile.deployment", "slot.profile.writer != proof",
            "Some(&trust.pin) != slot.profile.learning_trust.as_ref()", "registered_identity: serde_json::to_string(",
            "registered_at: now / 1_000", "HostAuthorityFrontierStore::initialize("))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + "authority_host_historical_ledger_registration.rs",
                                "fn register_original_initial_ledger(", "Instant::now() >= end", occurrence)

    def test_capture_ready_requires_post_context_physical_record_and_deadline(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn with_original_ledger_capture<T>(", (
            "RootDataRefusalV1::inspect(&original.refusal, ||", "original.baseline.phase != LedgerPhase::Enrolled",
            "let result = action(Some(&mut pending))?", "let (captured, observation, mut held)",
            "held.require_unchanged(&observation)?", "!= captured"))
        for occurrence in (0, 1):
            self.reject_removal(AGENT + "authority_host_historical_ledger_pin.rs", "fn with_original_ledger_capture<T>(",
                                "Instant::now() >= original.capture_end", occurrence)

    def test_capture_requires_same_original_source_publisher_and_real_signed_facts(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn observe_and_retain_original_ledger(", (
            "retained.expected.pin.initial_profile != baseline.initial_profile",
            "retained.expected.pin.publisher != baseline.publisher",
            "retained.expected.pin.publisher_epoch != baseline.publisher_epoch",
            "retained.expected.pin.target != baseline.target", "source.original_identity() != identity",
            "(ledger.device, ledger.inode) == (source.device, source.inode)",
            "generator != original.config.generator || observer != original.config.observer",
            "OriginalLedgerReadGuard::observe_original_terminal(", ".compare_and_set(&original.owner, baseline, &next)",
            "held.require_unchanged(&observed)?"))

    def test_complete_cut_binds_real_cell_and_every_original_file(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_pin.rs", "fn from_original(", (
            "source_pin: source_pin.to_string()", "publication.publication_digest()",
            "crate::circuit_cell_output::encode_receipt(cell)", "&cell.representation.drive_q24",
            "&cell.representation.prediction_q24", "observed.cut.ledger_digest", "observed.cut.witness_digest",
            "observed.signature_images[0].1", "observed.signature_images[1].1",
            "observed.facts.decision.chain_digest", "observed.facts.outcome.chain_digest"))

    def test_cold_arm_precedes_primary_and_all_four_file_opening(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(", (
            "RootDataRefusalV1::open_existing(", 'refusal\n            .inspect(||',
            "HostAuthorityFrontierStore::open(root, owner.clone())", "record.registered_at == 0",
            "!matches!(record.phase, LedgerPhase::Captured { .. })", "registration.identity()?",
            'RootHistoricalLedgerDeploymentV1::open_original(deployment_path)\n                    .inspect_err(|_| {\n                    let _ =\n                        std::io::stderr().write_all(b"root_stage=historical_ledger.deployment\\n");\n                })?',
            "OriginalLedgerFiles::retain_original_ledger(", "files.file_pins() != &record.files",
            "files.deployment.metadata_digest().to_string() != record.metadata",
            'let result = action(&mut pending).inspect_err(|_| {\n                    let _ = std::io::stderr()\n                        .write_all(b"root_stage=historical_ledger.recipient_action\\n");\n                })?', 'held.require_unchanged(&observed).inspect_err(|_| {\n                    let _ = std::io::stderr()\n                        .write_all(b"root_stage=historical_ledger.held_postcheck\\n");\n                })?', 'trust\n                    .revalidate('))
        self.reject_removal(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(",
                            "Instant::now() >= end", 1)

    def test_caught_error_or_second_read_never_completes_the_cold_attempt(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn observe_original_terminal(", (
            "std::mem::replace(&mut self.state, HistoryState::Verifying)", "HistoryState::Unobserved",
            "Instant::now() >= self.end", "self.state = HistoryState::Complete"))
        self.reject_removal(AGENT + "authority_host_historical_ledger_history.rs", "fn with_retained_original_ledger<T>(",
                            "let HistoryState::Complete")

    def test_cold_identity_target_source_and_original_roles_are_exact(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn observe_original_terminal(", (
            "original.pin.writer != record.writer", "original.pin.target != record.target",
            "original.pin.publisher != record.publisher", "original.pin.publisher_epoch != record.publisher_epoch",
            "source.original_identity() != &self.identity", "original.pin.source_configuration != source.binding_digest().to_string()",
            "original.pin.source_sequence != source.journal_anchor().sequence",
            "require_target(&record.target, definition, source.original_source())?", "trust.pin != record.trust",
            ".configuration(generator, observer, record.registered_at)", "OriginalLedgerReadModeV1::Retained",
            "CapturedLedgerCut::from_original(", "!= **cut", 'held.require_unchanged(&observed).inspect_err(|_| {\n            let _ = std::io::stderr().write_all(b"root_stage=historical_ledger.held_postcheck\\n");\n        })?'))

    def test_runtime_custody_requires_pre_a_cell_and_consumes_once(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_session.rs", "fn install_initial_source_ledger(", (
            "initial.phase.load(Ordering::Acquire) != PREPARED", "source.phase.load(Ordering::Acquire) != PREPARED",
            "inputs.initial != initial.deployment", "cell_retention::OriginalCellCustody::Held(_)",
            "self.service.with_initial_publication_context(", "!matches!(&*held, OriginalLedgerCustody::Absent)"))
        self.check_markers(AGENT + "authority_host_historical_ledger_session.rs", "fn take_original_source_ledger(", (
            "std::mem::replace(&mut *held, OriginalLedgerCustody::Absent)",
            "OriginalLedgerCustody::Registered(original) => Ok(Some(original))", "OriginalLedgerCustody::Held(_)", "self.close()"))

    def test_actual_registration_precedes_ack_and_nested_context_keeps_cell(self):
        self.reject_removal(AGENT + "authority_host_initial_enrollment_runtime.rs", "fn enroll_original(",
                            "source\n                    .register_original_source_ledger(context, self.end)")
        self.check_markers(AGENT + "authority_host_historical_source_data.rs", "fn with_original_capture<T>(", (
            "original.ledger.is_some() && original.cell.is_none()",
            "RegisteredOriginalCellCaptureV1::with_original_cell_capture(",
            "RegisteredOriginalLedgerCaptureV1::with_original_ledger_capture(", "|ledger| action(cell, ledger)"))


    def test_wire_data_is_bounded_exact_and_only_structurally_validated(self):
        self.check_markers(AGENT + "root_historical_ledger_data.rs", "fn validate_data(", (
            "self.purpose != LEDGER_READ_DATA_PURPOSE", "self.registered_identity.len() > 4096",
            "self.cut.ledger_sequence != 2", "self.cut.signature_sequence != 5",
            "self.cut.witness_length != 72 + 88 * 2", "self.source.sequence == 0",
            "self.source.publication != self.cut.source_publication",
            "serde_json::from_str(&self.registered_identity)", "!= self.registered_identity",
            "self.trust.require_target(&self.target)?", "pin.mode & 0o7777 != 0o600",
            "(other.device, other.inode) == (pin.device, pin.inode)",
            'serde_json::to_vec(self).map_err(io::Error::other)?.len() > Self::JSON_BOUND'))

    def test_wire_conversion_preserves_entire_retained_cut(self):
        self.check_markers(AGENT + "root_historical_ledger_data.rs", "fn ledger_cut(", (
            "self.validate_data()?", "self.cut_fields()"))
        self.check_markers(AGENT + "root_historical_ledger_data.rs", "fn cut_fields(", (
            "self.cut.ledger_binding.parse()",
            "sequence: self.cut.ledger_sequence", "self.cut.ledger_chain.parse()",
            "segment: None", "sealed: false", "self.cut.ledger_image.parse()",
            "self.cut.witness_image.parse()"))
        self.check_markers(AGENT + "root_historical_ledger_data.rs", "fn data_cut_digest(", (
            "self.validate_data()?", "&self.target.digest()", "&serde_json::to_vec(self)"))

    def test_root_wire_data_comes_from_the_actual_observed_source_and_capture(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn ledger_read_data(", (
            "let record = &self.record", "let source = &self.source", "let LedgerPhase::Captured { cut }",
            "registered_identity: record.registered_identity.clone()", "publisher: record.publisher.clone()",
            "metadata: record.metadata.clone()", "registered_at: record.registered_at",
            "trust: record.trust.clone()", "files: source\n                    .source_files",
            "configuration: source.source_configuration.clone()", "sequence: source.source_sequence",
            "checkpoint: source.source_checkpoint.clone()", "cut: (**cut).clone()", "data.validate_data()?"))

    def test_root_canonical_image_is_derived_from_the_same_physical_terminal_observation(self):
        self.check_markers(AGENT + "authority_host_historical_ledger_history.rs", "fn observe_original_terminal(", (
            "encode_readonly_ledger_data_v1(", "observed.cut.binding",
            "observed.facts.decision.clone()", "observed.facts.outcome.clone()",
            "ledger_image.len() as u64 != observed.cut.ledger_length",
            "Digest32::of_bytes(&ledger_image) != observed.cut.ledger_digest"))
        self.reject_removal(AGENT + "authority_host_historical_ledger_history.rs", "fn ledger_read_data(",
                            "ledger_image_bytes: STANDARD.encode(&self.ledger_image)")

    def test_recipient_data_replays_the_exact_image_without_a_second_physical_read(self):
        self.reject_removal(AGENT + "root_historical_ledger_data.rs", "fn validate_data(", "self.decode_image()?")
        self.check_markers(AGENT + "root_historical_ledger_data.rs", "fn decode_image(", (
            "self.ledger_image_bytes.len() > 12 * 1024", ".decode(&self.ledger_image_bytes)",
            "STANDARD.encode(&bytes) != self.ledger_image_bytes",
            "let maximum_records = 2", "decode_readonly_ledger_data_v1(&bytes, self.cut_fields()?, maximum_records)",
            "!= Some(self.cut.decision_chain.clone())", "!= Some(self.cut.outcome_chain.clone())"))


    def test_capture_deadline_keeps_the_original_session_through_every_holder(self):
        cases = (
            ("authority_host_initial_enrollment_runtime.rs", "fn enroll_original(",
             "register_original_source_ledger(context, self.end)", "register_original_source_ledger(context, end)"),
            ("authority_host_initial_enrollment_runtime.rs", "fn enroll_original(",
             "register_original_source_ledger(context, self.end)",
             "register_original_source_ledger(context, Instant::now() + Duration::from_secs(300))"),
            ("authority_host_historical_ledger_session.rs", "fn register_original_source_ledger(",
             "context.end,\n            capture_end,", "capture_end,\n            context.end,"),
            ("authority_host_historical_ledger_session.rs", "fn register_original_source_ledger(",
             "context.end,\n            capture_end,", "context.end,\n            context.end,"),
            ("authority_host_historical_ledger_session.rs", "fn register_original_source_ledger(",
             "context.end,\n            capture_end,", "context.end,"),
            ("authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger(",
             "refusal,\n            capture_end,", "refusal,\n            capture_end: end,"),
            ("authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger(",
             "refusal,\n            capture_end,",
             "refusal,\n            capture_end: std::time::Instant::now() + std::time::Duration::from_secs(300),"),
            ("authority_host_historical_ledger_session.rs", "fn register_original_source_ledger(",
             "self.root.require_current()?;", "self.root.require_current()?;\nlet capture_end = Instant::now() + std::time::Duration::from_secs(300);"),
            ("authority_host_historical_ledger_registration.rs", "fn register_original_initial_ledger(",
             "original_root()?;", "original_root()?;\nlet capture_end = capture_end.checked_add(std::time::Duration::from_secs(1)).unwrap();"),
        )
        for filename, function, old, new in cases:
            with self.subTest(file=filename, old=old, replacement=new):
                self._reject_deadline_transform(filename, function,
                    lambda body, old=old, new=new: self._replace_deadline_marker(body, old, new))

    def test_registration_frame_checks_and_session_bound_remain_inside_the_arm(self):
        filename = "authority_host_historical_ledger_registration.rs"
        function = "fn register_original_initial_ledger("
        for occurrence in (0, 1):
            with self.subTest(frame_check=occurrence):
                self._reject_deadline_transform(filename, function,
                    lambda body, occurrence=occurrence: self._replace_deadline_marker(
                        body, "Instant::now() >= end", "Instant::now() >= capture_end", occurrence))
        for replacement in ("if end < capture_end {", "if false && end > capture_end {", "if false {"):
            with self.subTest(bound=replacement):
                self._reject_deadline_transform(filename, function,
                    lambda body, replacement=replacement: self._replace_deadline_marker(
                        body, "if end > capture_end {", replacement))
        self._reject_deadline_transform(filename, function,
            lambda body: self._move_deadline_block(body, "if end > capture_end {",
                                                  "let (refusal, ()) = RootDataRefusalV1::create_fresh("))

    def test_capture_expiry_cannot_be_renewed_or_moved_ahead_of_physical_postchecks(self):
        filename = "authority_host_historical_ledger_pin.rs"
        function = "fn with_original_ledger_capture<T>("
        for occurrence in (0, 1):
            for replacement in (
                "Instant::now() >= original.capture_end + std::time::Duration::from_secs(300)",
                "Instant::now() >= std::time::Instant::now() + std::time::Duration::from_secs(300)",
            ):
                with self.subTest(check=occurrence, replacement=replacement):
                    self._reject_deadline_transform(filename, function,
                        lambda body, occurrence=occurrence, replacement=replacement: self._replace_deadline_marker(
                            body, "Instant::now() >= original.capture_end", replacement, occurrence))
        for before in ("let result = action(Some(&mut pending))?;",
                       "held.require_unchanged(&observation)?;"):
            with self.subTest(postcheck_moved_before=before):
                self._reject_deadline_transform(filename, function,
                    lambda body, before=before: self._replace_deadline_marker(
                        self._replace_deadline_marker(body,
                            "|| std::time::Instant::now() >= original.capture_end", ""),
                        before,
                        'if std::time::Instant::now() >= original.capture_end { return Err(io::Error::other("expired")); }\n' + before))
        self._reject_deadline_transform(filename, function,
            lambda body: self._replace_deadline_marker(
                body, "held.require_unchanged(&observation)?;",
                "return Ok(result);\nheld.require_unchanged(&observation)?;"))


if __name__ == "__main__":
    unittest.main()
