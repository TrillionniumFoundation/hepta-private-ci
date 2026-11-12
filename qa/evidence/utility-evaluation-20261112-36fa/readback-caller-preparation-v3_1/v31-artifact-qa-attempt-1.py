"""Fence audited original Artifact channel callers and their critical dependencies.

HEAD Sign consumes the original owner's capability; it is not a read-only RPC.
Registry and HEAD Readback cannot acquire that capability. These are source
mutation checks through the unchanged verifier, not execution/signature proofs.
The membership test uses the complete repository Rust collection.
"""
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "original_artifact_channel_proof", ROOT / "scripts/verify_hepta_callers.py"
)
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = "codex-rs/hepta-agentd/src/"
ARTIFACT = "codex-rs/hepta-learning-artifacts/src/"
CLIENT = AGENT + "artifact_original_head_client.rs"
SERVICE = AGENT + "artifact_original_head_service.rs"
REGISTRY = AGENT + "artifact_original_registry_source.rs"
OWNER = AGENT + "artifact_original_head_owner.rs"
WIRE = AGENT + "artifact_original_head_wire.rs"
CONFIG = ARTIFACT + "owner_head_source.rs"
DURABLE = ARTIFACT + "owner_host_registry_durable.rs"
EXPECTED = ('codex-rs/hepta-agentd/src/cell_q24_training_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command.rs', 'codex-rs/hepta-agentd/src/cell_q24_material_command_service.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_capability.rs', 'codex-rs/hepta-agentd/src/circuit_learning_read_service.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_connection.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command.rs', 'codex-rs/hepta-agentd/src/circuit_next_use_command_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_candidate_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_candidate.rs', 'codex-rs/hepta-agentd/src/cell_q24_no_update_stage_inputs.rs', 'codex-rs/hepta-agentd/src/circuit_learning_completion_readiness_service.rs', 'codex-rs/hepta-agentd/src/authority_host_learning_resident_transport.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_command.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_host_service.rs', 'codex-rs/hepta-agentd/src/circuit_retained_version_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_connection.rs', 'codex-rs/hepta-agentd/src/cell_q24_model_command_service.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_connection.rs', 'codex-rs/hepta-agentd/src/neuron_cell_evaluation_model_material_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_command_readback_service.rs', 'codex-rs/hepta-agentd/src/cell_q24_training_bootstrap_readback.rs', 'codex-rs/hepta-agentd/src/circuit_evaluated_selection_readback_owner.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback.rs', 'codex-rs/hepta-agentd/src/circuit_selection_command_readback_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs', 'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs')
ADMITTED = (CLIENT, SERVICE, REGISTRY)


class OriginalArtifactChannelClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {
            row.identifier: row for row in PROOF._boundary_rows(cls.manifest)
        }

    def assert_protected_rejects(self, path, changed):
        original = (ROOT / path).read_text()
        self.assertNotEqual(original, changed)
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertEqual(len(rows), 1)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(original)
            PROOF._verify_protected_files(root, {"protected_file": rows})
            target.write_text(changed)
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_protected_files(root, {"protected_file": rows})

    def function(self, path, function):
        original = (ROOT / path).read_text()
        code = PROOF._strip_rust_non_code(original)
        self.assertEqual(code.count(function), 1, (path, function))
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        return original, start, end + 1

    def mutate(self, path, function, marker, replacement=""):
        original, start, end = self.function(path, function)
        body = original[start:end]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        changed = body.replace(marker, replacement, 1)
        self.assert_protected_rejects(path, original[:start] + changed + original[end:])

    def move_after(self, path, function, marker, anchor):
        original, start, end = self.function(path, function)
        body = original[start:end]
        self.assertEqual(body.count(marker), 1, (path, function, marker))
        self.assertEqual(body.count(anchor), 1, (path, function, anchor))
        self.assertLess(body.index(marker), body.index(anchor))
        changed = body.replace(marker, "", 1).replace(anchor, anchor + "\n" + marker, 1)
        self.assert_protected_rejects(path, original[:start] + changed + original[end:])

    def assert_actual_durable_filename_templates(self, source):
        # The original literal_calls verifier intentionally supports simple
        # calls, not format! macros. This narrowly scoped QA checks raw first
        # arguments only at the two real macro spans inside the real function.
        # The original complete-body fence is checked separately below.
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        function = "fn read_original_registry_durable("
        self.assertEqual(code.count(function), 1)
        start = code.index(function)
        end = PROOF._rust_item_end(code, start)
        self.assertIsNotNone(end)
        body = code[start:end + 1]
        macros = list(re.finditer(r"\bformat!\s*\(", body))
        self.assertEqual(len(macros), 2, "two actual durable filename macros")
        observed = []
        for macro in macros:
            opening = start + macro.end() - 1
            closing = PROOF.typed_callers._end(code, opening, "(", ")")
            self.assertLessEqual(closing, end)
            arguments = source[opening + 1:closing]
            literal = re.match(r'\s*("(?:[^"\\]|\\.)*")\s*,', arguments)
            self.assertIsNotNone(literal, "actual format first argument must be a string literal")
            first = opening + 1 + literal.start(1)
            last = opening + 1 + literal.end(1)
            self.assertEqual(code[first:last], PROOF._strip_rust_non_code(source[first:last]))
            observed.append(literal.group(1))
        self.assertEqual(
            observed, ['"{}-{}.bin"', '"{}-{}.witness"'],
            "actual durable filename templates cannot be supplied by unrelated text",
        )

    def test_actual_durable_directory_literals_reject_same_length_and_decoy_replacements(self):
        original = (ROOT / DURABLE).read_text()
        for old, new in (('.join("payloads")', '.join("payloade")'), ('.join("witnesses")', '.join("witnessed")')):
            self.assertEqual(len(old), len(new))
            self.assertEqual(original.count(old), 1)
            changed = original.replace(old, new, 1)
            for suffix in ("", "\n// " + old + "\n", "\nfn unused_path(p: &std::path::Path) { let _ = p" + old + "; }\n"):
                with self.subTest(literal=old, suffix=suffix):
                    self.assert_protected_rejects(DURABLE, changed + suffix)

    def test_actual_durable_filename_templates_reject_same_length_and_decoy_replacements(self):
        original = (ROOT / DURABLE).read_text()
        rows = [row for row in self.manifest["protected_file"] if row["path"] == DURABLE]
        self.assertEqual(len(rows), 1)
        PROOF._verify_protected_files(ROOT, {"protected_file": rows})
        self.assert_actual_durable_filename_templates(original)
        for old, new in (('"{}-{}.bin"', '"{}+{}.bin"'), ('"{}-{}.witness"', '"{}+{}.witness"')):
            self.assertEqual(len(old), len(new))
            self.assertEqual(original.count(old), 1)
            changed = original.replace(old, new, 1)
            for suffix in ("", "\n// " + old + "\n", "\nconst UNUSED_FILENAME_TEMPLATE: &str = " + old + ";\n"):
                with self.subTest(literal=old, suffix=suffix):
                    candidate = changed + suffix
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        target = root / DURABLE
                        target.parent.mkdir(parents=True)
                        target.write_text(candidate)
                        # Preserve the distinction: this is the new QA's check,
                        # not a capability claimed for the unchanged verifier.
                        PROOF._verify_protected_files(root, {"protected_file": rows})
                    with self.assertRaisesRegex(AssertionError, "actual durable filename templates"):
                        self.assert_actual_durable_filename_templates(candidate)

    def test_exact_original_channel_membership_uses_all_rust_and_rejects_another_caller(self):
        roots = PROOF._string_tuple(self.manifest, "source_roots")
        ignored = PROOF._string_tuple(self.manifest, "ignored_path_fragments")
        PROOF._verify_privileged_inventory(self.manifest, tuple(self.boundaries.values()))
        sources = {
            path.relative_to(ROOT).as_posix(): PROOF._strip_cfg_test_items(
                PROOF._strip_rust_non_code(path.read_text(encoding="utf-8"))
            )
            for path in PROOF._source_files(ROOT, roots)
        }
        boundary = self.boundaries["learning_original_owner_command_channel"]
        self.assertEqual(boundary.product_callers, tuple(EXPECTED))
        self.assertIsNone(boundary.receiver_type)
        PROOF._verify_boundary(ROOT, boundary, sources, ignored, fields_by_receiver_type={})
        extra = dict(sources)
        extra[AGENT + "unregistered_artifact_channel_consumer.rs"] = (
            f"fn bypass() {{ {boundary.symbol}(); }}"
        )
        with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
            PROOF._verify_boundary(ROOT, boundary, extra, ignored, fields_by_receiver_type={})
        for admitted in ADMITTED:
            with self.subTest(missing=admitted):
                missing = dict(sources)
                self.assertIn(admitted, missing)
                del missing[admitted]
                with self.assertRaisesRegex(PROOF.VerificationFailure, "missing"):
                    PROOF._verify_boundary(
                        ROOT, boundary, missing, ignored, fields_by_receiver_type={}
                    )
        self.assertEqual(
            self.boundaries["root_learning_original_stage_assembly"].product_callers, ()
        )
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_head_client_cannot_promote_readback_or_retain_a_signing_continuation(self):
        self.mutate(CLIENT, "fn recover_original_stream(", "Origin::Readonly(expected)", "Origin::Fresh")
        self.mutate(
            CLIENT, "fn sign_original_registry(",
            "if !matches!(&self.origin, Origin::Fresh)",
            "if matches!(&self.origin, Origin::Fresh)",
        )
        self.mutate(CLIENT, "fn sign_original_registry(", "        self,", "        &self,")
        self.mutate(CLIENT, "fn sign_original_registry(", "claims.require_unsigned_phase()?;")
        self.mutate(CLIENT, "fn read_original_head(", "wire::Action::Readback", "wire::Action::Sign")
        self.mutate(
            CLIENT, "fn exchange(",
            "Error::CommitUncertain\n            } else", "Error::ReadbackRequired\n            } else",
        )
        self.mutate(
            CLIENT, "fn exchange(", "&& expected != signed", "&& expected == signed",
        )

    def test_head_peer_currentness_and_complete_signature_are_checked_after_io(self):
        for marker in (
            "require_peer(&peer, &config.signer_id)?;",
            "config.authenticate_current(started)?;",
            "original_head_pidfd,",
            "channel.check_peer_lifetime()?;",
            "config.authenticate_current(initial_at)?;",
        ):
            with self.subTest(bind=marker):
                self.mutate(CLIENT, "fn bind(", marker)
        for marker in (
            "source.authenticate_current(&self.config, started)?;",
            "channel.channel.check_peer_lifetime()?;",
            "let current = fresh(started)?;",
            ".verify_original_head(&source, &signed, current)?;",
        ):
            with self.subTest(exchange=marker):
                self.mutate(CLIENT, "fn exchange(", marker)
        self.move_after(
            CLIENT, "fn exchange(", "channel.channel.check_peer_lifetime()?;",
            ".verify_original_head(&source, &signed, current)?;",
        )
        self.mutate(CLIENT, "fn exchange(", "wire::Purpose::Head", "wire::Purpose::Registry")

    def test_head_service_authenticates_and_dispatches_the_original_action_without_upgrade(self):
        for marker in (
            "require_peer(&consumer, &self.source.config.writer_lease.producer_id)?;",
            ".try_acquire_owned()",
            "original_consumer_pidfd,",
            "original.source.config.authenticate_current(started)?;",
            ".authenticate_current(fresh(started)?)?;",
        ):
            with self.subTest(marker=marker):
                self.mutate(SERVICE, "fn serve_commands(", marker)
        self.mutate(
            SERVICE, "fn serve_commands(",
            "wire::Action::Readback => original.read_original(&cancelled)",
            "wire::Action::Readback => original.sign_original(&cancelled)",
        )
        self.move_after(
            SERVICE, "fn serve_commands(",
            "original.source.config.authenticate_current(started)?;",
            "let response = match request.action {\n"
            "                            wire::Action::Sign => original.sign_original(&cancelled),\n"
            "                            wire::Action::Readback => original.read_original(&cancelled),\n"
            "                        };",
        )
        for marker, replacement in (
            ("wire::Purpose::Head, nonce, binding", "wire::Purpose::Registry, nonce, binding"),
            ("wire::Status::Missing, &[]", "wire::Status::Completed, &[]"),
            ("wire::Status::Pending, &[]", "wire::Status::Completed, &[]"),
            ("wire::Status::ReadbackRequired, &[]", "wire::Status::Completed, &[]"),
            ("for nonce in 1..=128", "for nonce in 1..=129"),
        ):
            with self.subTest(marker=marker):
                self.mutate(SERVICE, "fn serve_commands(", marker, replacement)

    def test_registry_read_uses_the_same_writer_then_fresh_authentication(self):
        for marker in (
            "config.authenticate_current(now()?)?;",
            "let binding = config.binding()?;",
            "            writer,",
        ):
            with self.subTest(constructor=marker):
                self.mutate(REGISTRY, "fn from_original_writer(", marker)
        for marker in (
            "require_peer(&consumer, &self.config.signer_id)?;",
            ".try_acquire_owned()",
            "original_consumer_pidfd,",
        ):
            with self.subTest(service=marker):
                self.mutate(REGISTRY, "fn serve_reads(", marker)
        self.mutate(
            REGISTRY, "fn respond(", "wire::Purpose::Registry", "wire::Purpose::Head",
        )
        self.mutate(REGISTRY, "fn respond(", "self.config.authenticate_current(started)?;")
        self.mutate(
            REGISTRY, "fn respond(",
            "LearningArtifactOwnerService::read_original_registry_durable(",
            "LearningArtifactOwnerService::resume_original(",
        )
        self.mutate(REGISTRY, "fn respond(", "claims.authenticate_current(&self.config, fresh(started)?)?;")
        self.move_after(
            REGISTRY, "fn respond(", "drop(writer);",
            "claims.authenticate_current(&self.config, fresh(started)?)?;",
        )

    def test_registry_channel_is_restored_only_after_current_subject_and_time_checks(self):
        self.mutate(
            REGISTRY, "fn from_original_stream(",
            "require_peer(&peer, &config.writer_lease.producer_id)?;",
        )
        self.mutate(REGISTRY, "fn from_original_stream(", "config.authenticate_current(observed)?;")
        for marker in (
            ".take()",
            "self.config.authenticate_current(started)?;",
            "let payload = request.read_response(&bytes)?;",
            "let current = fresh(started)?;",
            "source.authenticate_current(&self.config, current)?;",
        ):
            with self.subTest(marker=marker):
                self.mutate(REGISTRY, "fn read_current_in_lane(", marker)
        for marker, replacement in (
            ("wire::Action::Readback", "wire::Action::Sign"),
            ("source.observed_unix_millis() < channel.source_at", "source.observed_unix_millis() > channel.source_at"),
            ("channel.subject.is_some_and(|old| old != binding)", "channel.subject.is_some_and(|old| old == binding)"),
        ):
            with self.subTest(marker=marker):
                self.mutate(REGISTRY, "fn read_current_in_lane(", marker, replacement)
        self.move_after(
            REGISTRY, "fn read_current_in_lane(",
            "source.authenticate_current(&self.config, current)?;",
            "*self.channel.try_lock().map_err(|_| Error::Busy)? = Some(channel);",
        )
        self.mutate(REGISTRY, "fn drop(", "self.0.store(true, Ordering::Release);", "self.0.store(false, Ordering::Release);")

    def test_native_recovery_cannot_create_a_fresh_signing_owner(self):
        self.mutate(OWNER, "fn recover(", "admitted: AtomicBool::new(true)", "admitted: AtomicBool::new(false)")
        self.mutate(
            OWNER, "fn recover(", "LearningOwnerJournalV1::recover(file, witness, binding)",
            "LearningOwnerJournalV1::create(file, witness, binding)",
        )
        self.mutate(OWNER, "fn create(", "before.require_unsigned_phase()?;")
        self.mutate(
            OWNER, "fn create(",
            ".require_registered_key(&original_key.verifying_key().to_bytes(), started)?;",
        )
        for function in ("fn create(", "fn recover("):
            for marker in (
                "if !queued_before.same_original_observation(&current_source)",
                "if !before.same_original_observation(&after)",
            ):
                with self.subTest(function=function, marker=marker):
                    self.mutate(OWNER, function, marker, marker.replace("if !", "if ", 1))

    def test_sign_claim_is_owner_wide_before_key_take_and_durable_commit(self):
        self.mutate(
            OWNER, "fn sign_original(", "self.admitted.swap(true, Ordering::AcqRel)",
            "self.admitted.load(Ordering::Acquire)",
        )
        self.move_after(
            OWNER, "fn sign_original(",
            "if self.admitted.swap(true, Ordering::AcqRel) {\n"
            "            return Err(Error::ReadbackRequired);\n        }",
            ".ok_or(Error::ReadbackRequired)?;",
        )
        self.mutate(OWNER, "fn sign_original(", ".take()", ".clone()")
        self.mutate(OWNER, "fn sign_original(", ".commit_once(&self.key, || {", ".commit(&self.key, || {")
        for marker in (
            "self.require_subject(&before)?;",
            "before.require_unsigned_phase()?;",
            ".require_registered_key(&key.verifying_key().to_bytes(), current)",
            "drop(key);",
            ".verify_original_head(&after, &signed, current)?;",
        ):
            with self.subTest(marker=marker):
                self.mutate(OWNER, "fn sign_original(", marker)
        self.mutate(
            OWNER, "fn sign_original(", "drop(key);",
            "drop(key);\n        self.admitted.store(false, Ordering::Release);",
        )
        self.mutate(
            OWNER, "fn sign_original(",
            "let current = fresh(started)\n"
            "                        .map_err(|_| LearningOriginalOwnerErrorV1::Binding(\"HEAD claim clock\"))?;",
            "let current = started;",
        )
        self.mutate(
            OWNER, "fn sign_original(", "let current = fresh(started)?;",
            "let current = started;",
        )
        self.mutate(OWNER, "fn sign_original(", "if saved != bytes", "if saved == bytes")

    def test_head_readback_cannot_sign_recover_or_merge_changed_observations(self):
        self.mutate(
            OWNER, "fn read_original(", "let started = now()?;",
            "let _ = self.sign_original(cancelled)?;\n        let started = now()?;",
        )
        self.mutate(OWNER, "fn read_original(", "self.require_subject(&before)?;")
        self.mutate(
            OWNER, "fn read_original(", "if !before.same_original_observation(&after)",
            "if before.same_original_observation(&after)",
        )
        self.mutate(OWNER, "fn read_original(", "if saved != bytes", "if saved == bytes")
        self.mutate(OWNER, "fn read_original(", ".verify_original_head(&after, &signed, current)?;")
        self.move_after(
            OWNER, "fn read_original(", "let current = fresh(started)?;",
            ".verify_original_head(&after, &signed, current)?;",
        )
        self.mutate(
            OWNER, "fn require_subject(",
            "source.subject_binding(&self.source.config)? != self.original_subject",
            "source.subject_binding(&self.source.config)? == self.original_subject",
        )

    def test_wire_keeps_registry_read_only_and_exact_nonce_binding_and_failure_states(self):
        for marker, replacement in (
            ("nonce == 0", "nonce == 1"),
            ("nonce > 128", "nonce > 129"),
            ("binding.is_zero()", "!binding.is_zero()"),
            ("purpose == Purpose::Registry && action != Action::Readback", "purpose == Purpose::Head && action != Action::Readback"),
        ):
            with self.subTest(marker=marker):
                self.mutate(WIRE, "fn new(", marker, replacement)
        for marker, replacement in (
            ("bytes[8] != purpose as u8", "bytes[8] == purpose as u8"),
            ("observed_nonce != nonce || observed_binding != binding", "observed_nonce != nonce && observed_binding != binding"),
            ("Self::new(purpose, action, nonce, binding)", "Ok(Self { purpose, action, nonce, binding })"),
        ):
            with self.subTest(marker=marker):
                self.mutate(WIRE, "fn decode(", marker, replacement)
        self.mutate(
            WIRE, "fn response(", "status != Status::Completed && !payload.is_empty()",
            "status == Status::Completed && !payload.is_empty()",
        )
        self.mutate(
            WIRE, "fn read_response<'a>(", "bytes[..HEADER] != self.encode()",
            "bytes[..HEADER] == self.encode()",
        )
        self.mutate(
            WIRE, "fn read_response<'a>(", "2 if length == 0 => Err(Error::Missing)",
            "2 if length == 0 => Ok(&bytes[55..])",
        )
        original = (ROOT / WIRE).read_text()
        self.assertEqual(original.count('b"HARPC001"'), 1)
        self.assert_protected_rejects(WIRE, original.replace('b"HARPC001"', 'b"HARPC002"', 1))

    def test_head_config_keeps_registered_current_lease_key_and_fixed_expiry(self):
        for marker, replacement in (
            ("self.signature_expires_at < now", "self.signature_expires_at > now"),
            ("self.signature_expires_at > self.writer_lease.expires_at", "self.signature_expires_at < self.writer_lease.expires_at"),
            ("self.signer_id == writer.producer_id", "self.signer_id != writer.producer_id"),
            ("self.signature_expires_at >= at", "self.signature_expires_at < at"),
            ("/*require_current*/ true", "/*require_current*/ false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(CONFIG, "fn authenticate_current(", marker, replacement)
        self.mutate(CONFIG, "fn require_registered_key(", "self.authenticate_current(now)?;")
        self.mutate(
            CONFIG, "fn require_registered_key(", "&signer.verifying_key != verifying_key",
            "&signer.verifying_key == verifying_key",
        )
        self.mutate(
            CONFIG, "fn unsigned_head(", "expires_at: self.signature_expires_at",
            "expires_at: issued_at + 60_000",
        )
        self.mutate(
            CONFIG, "fn binding(", 'b"hepta.original-artifact-head-native.v1"',
            'b"hepta.original-artifact-head-native.v2"',
        )

    def test_complete_head_signature_and_fixed_context_are_reverified(self):
        self.mutate(CONFIG, "fn verify_original_head(", "source.authenticate_current(self, now)?;")
        for marker, replacement in (
            ("signed.witness.issued_at > now", "signed.witness.issued_at < now"),
            ("signed.binding != self.storage_binding", "signed.binding == self.storage_binding"),
            ("signed.witness.head_digest != source.registry_receipt().head_digest", "signed.witness.head_digest == source.registry_receipt().head_digest"),
            ("signed.witness.expires_at != self.signature_expires_at", "signed.witness.expires_at == self.signature_expires_at"),
            ("&& current != signed", "&& current == signed"),
            ("/*require_current_signer*/ true", "/*require_current_signer*/ false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(CONFIG, "fn verify_original_head(", marker, replacement)

    def test_durable_read_preserves_actual_files_complete_equality_and_fresh_validation(self):
        function = "fn read_original_registry_durable("
        for marker, replacement in (
            ("self.require_current_writer(started)?", "self.require_current_writer(0)?"),
            ("checkpoint.authority.grants_any()", "!checkpoint.authority.grants_any()"),
            ("receipt.binding != binding", "receipt.binding == binding"),
            ("before_records != after_records", "before_records == after_records"),
            ("registry.snapshot() != registry_after.snapshot()", "registry.snapshot() == registry_after.snapshot()"),
            ("payload != payload_after", "payload == payload_after"),
            ("current_before != current_after", "current_before == current_after"),
            ("withdrawals_before != withdrawals.snapshot()", "withdrawals_before == withdrawals.snapshot()"),
            ("writer_after.lease_digest != writer.lease_digest", "writer_after.lease_digest == writer.lease_digest"),
            ("/*require_current_signer*/ true", "/*require_current_signer*/ false"),
        ):
            with self.subTest(marker=marker):
                self.mutate(DURABLE, function, marker, replacement)
        self.mutate(
            DURABLE, function,
            "let after_records = self.read_original_publication_checkpoints(&context.operation_id)?;",
            "let after_records = before_records.clone();",
        )
        self.mutate(
            DURABLE, function,
            "validate_artifact_publication_v3(&context.admission, withdrawals, fresh)\n"
            "            .map_err(ArtifactPublicationError::from)?;",
        )
        self.mutate(
            DURABLE, function, "let fresh = clock()?;", "let fresh = started;",
        )
        self.move_after(
            DURABLE, function, "let after_records = self.read_original_publication_checkpoints(&context.operation_id)?;",
            "let fresh = clock()?;",
        )
        self.mutate(
            DURABLE, "fn read_preparation_current(", "self.current_registry_view_bounded(now)?",
            "self.current_registry_view_bounded(0)?",
        )
        self.mutate(
            DURABLE, "fn read_preparation_current(", "current.receipt().binding != binding",
            "current.receipt().binding == binding",
        )
        self.mutate(DURABLE, "fn authority(", "AuthorityPosture::DENY_ALL", "AuthorityPosture::ALLOW_ALL")

    def test_keyless_adapters_cannot_gain_reconnect_signing_or_reconstruction_entrypoints(self):
        for path, forbidden in (
            (CLIENT, ("SigningKey::generate", "UnixStream::connect", "LearningOwnerJournalV1::recover(", "OriginalArtifactPreparedPublicationV1 {")),
            (SERVICE, ("OriginalArtifactHeadOwnerV1::create(", "OriginalArtifactHeadOwnerV1::recover(", "SigningKey::from_bytes")),
            (REGISTRY, ("wire::Action::Sign", "LearningArtifactOwnerService::open(", "sign_original(", "commit_once(", "UnixStream::connect")),
            (DURABLE, ("File::create", "std::fs::write", "std::fs::rename", "SigningKey::generate")),
        ):
            original = (ROOT / path).read_text()
            for marker in forbidden:
                with self.subTest(path=path, marker=marker):
                    self.assert_protected_rejects(
                        path, original + "\nfn injected_original_authority_bypass() { " + marker + " }\n"
                    )


if __name__ == "__main__":
    unittest.main()
