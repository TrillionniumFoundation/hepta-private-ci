"""Original Artifact writer/HEAD source closure, not ordinary adoption evidence.

The independent constants below require every original effect/read edge and
mutate full context, freshness, same-instance and saved-signature controls.
Native execution and daemon/Root cold restart remain separate acceptance gates.
"""
import importlib.util
from pathlib import Path
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("original_artifact_head_proof", ROOT / "scripts/verify_hepta_callers.py")
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)

EXPECTED = {'learning_original_artifact_head_create': (),
 'learning_original_artifact_head_recover': (),
 'learning_original_artifact_head_serve': (),
 'learning_original_artifact_head_sign_original': ('codex-rs/hepta-agentd/src/artifact_original_head_service.rs',),
 'learning_original_artifact_head_read_original': ('codex-rs/hepta-agentd/src/artifact_original_head_service.rs',),
 'learning_original_artifact_head_connection_from_original_stream': (),
 'learning_original_artifact_head_connection_recover_original_stream': (),
 'learning_original_artifact_head_connection_sign_original_registry': (),
 'learning_original_artifact_head_connection_read_original_head': (),
 'learning_original_artifact_registry_source_create': (),
 'learning_original_artifact_registry_source_serve': (),
 'learning_original_artifact_registry_source_connect': (),
 'learning_original_artifact_registry_source_read': ('codex-rs/hepta-agentd/src/artifact_original_head_owner.rs',),
 'learning_original_artifact_registry_source_lane_read': ('codex-rs/hepta-agentd/src/artifact_original_head_owner.rs',),
 'learning_original_artifact_writer_prepare_original_registry': (),
 'learning_original_artifact_writer_read_original_registry_durable': ('codex-rs/hepta-agentd/src/artifact_original_registry_source.rs',),
 'learning_original_artifact_writer_finish_original_registry': (),
 'learning_original_artifact_writer_begin_original_registry': ('codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs',),
 'learning_original_artifact_writer_registry_durable_read': ('codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs',),
 'learning_original_artifact_writer_registry_predecessor_read': ('codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs',),
 'learning_original_artifact_protocol_begin': ('codex-rs/hepta-learning-artifacts/src/owner_host_preparation.rs',
                                               'codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs',
                                               'codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs'),
 'learning_original_artifact_protocol_read_snapshot': ('codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs',
                                                       'codex-rs/hepta-learning-artifacts/src/owner_head_source_claims.rs'),
 'learning_original_artifact_registry_source_encode': ('codex-rs/hepta-agentd/src/artifact_original_head_client.rs',
                                                       'codex-rs/hepta-agentd/src/artifact_original_registry_source.rs'),
 'learning_original_artifact_writer_checkpoint_before_effect': ('codex-rs/hepta-learning-artifacts/src/owner_host.rs',)}

CONTROLS = {
    "codex-rs/hepta-learning-artifacts/src/publication_original.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/publication_original.rs",
        "required": [
            "b\"hepta.learning-artifacts.original-registry-preparation-intent.v1\""
        ],
        "forbidden": [
            "pub fn begin_original_registry",
            "pub fn from_original_registry_snapshot",
            "Deserialize",
            "std::fs",
            "SigningKey"
        ],
        "required_function_order": [
            {
                "function": "fn begin_original_registry(",
                "sequence": [
                    "let mut transaction = Self::begin(",
                    "transaction.intent.intent_digest = digest_original_registry_intent(",
                    "transaction.refresh_state_digest()",
                    "Ok(transaction)"
                ]
            },
            {
                "function": "fn from_original_registry_snapshot(",
                "sequence": [
                    "let expected_intent = digest_original_registry_intent(",
                    "Self::from_snapshot_with_intent_digest(snapshot, expected_intent)"
                ]
            },
            {
                "function": "fn digest_original_registry_intent(",
                "sequence": [
                    "let mut bytes =",
                    "digest_intent(operation_id, admission, predecessor)",
                    "Digest32::of_bytes(&bytes)"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/publication.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/publication.rs",
        "required": [
            "b\"hepta.learning-artifacts.publication-intent.v1\""
        ],
        "forbidden": [
            "pub fn from_snapshot_with_intent_digest",
            "pub(crate) fn from_snapshot_with_intent_digest"
        ],
        "required_function_order": [
            {
                "function": "fn from_snapshot(",
                "sequence": [
                    "let expected_intent = digest_intent(",
                    "Self::from_snapshot_with_intent_digest(snapshot, expected_intent)"
                ]
            },
            {
                "function": "fn from_snapshot_with_intent_digest(",
                "sequence": [
                    "verify_artifact_admission_v3(",
                    "if expected_intent != snapshot.intent.intent_digest",
                    "validate_snapshot_shape(&snapshot)?",
                    "let expected_state = digest_state(",
                    "if expected_state != snapshot.state_digest",
                    "Ok(Self {"
                ]
            },
            {
                "function": "fn digest_intent(",
                "sequence": [
                    "let mut bytes =",
                    "push_id(&mut bytes, operation_id)",
                    "admission.validated_manifest.manifest_digest.as_array()",
                    "admission.withdrawal_scope_digest.as_array()",
                    "admission.withdrawal_head_digest.as_array()",
                    "admission.admission_digest.as_array()",
                    "expected_registry_predecessor_head.as_array()",
                    "Digest32::of_bytes(&bytes)"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_host_preparation.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_host_preparation.rs",
        "required": [],
        "forbidden": [
            "pub fn begin_original_registry_publication",
            "ArtifactPublicationTransactionV1::begin(",
            "resume_publication",
            "SigningKey"
        ],
        "required_function_order": [
            {
                "function": "fn require_original_publication_checkpoint(",
                "sequence": [
                    "transaction.phase() != phase",
                    ".read_original_publication_checkpoint(&transaction.intent().operation_id)?",
                    "ArtifactOwnerHostError::CheckpointMissing",
                    "checkpoint_from_snapshot(",
                    "&transaction.snapshot(),",
                    "original.original_writer_lease_digest,",
                    "ArtifactOwnerHostError::CheckpointMismatch",
                    "Ok(())"
                ]
            },
            {
                "function": "fn begin_original_registry_publication(",
                "sequence": [
                    "self.require_current_writer(now)?",
                    "manifest.producer_id != writer.producer_id",
                    "admission.withdrawal_scope_digest != self.verifier.trust.withdrawal_scope_digest",
                    "withdrawals.scope_digest() != Some(self.verifier.trust.withdrawal_scope_digest)",
                    "ArtifactPublicationTransactionV1::begin_original_registry(",
                    "self.persist_checkpoint(&transaction)?",
                    "Ok(transaction)"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs",
        "required": [
            "original_instance: Arc<()>",
            "transaction: ArtifactPublicationTransactionV1"
        ],
        "forbidden": [
            "impl Clone for OriginalArtifactPreparedPublicationV1",
            "Deserialize",
            "pub original_instance:",
            "pub transaction:",
            "resume_publication",
            "SigningKey"
        ],
        "required_function_order": [
            {
                "function": "fn prepare_original_registry_with_clock(",
                "sequence": [
                    "self.original_preparation_fenced.load(Ordering::Acquire)",
                    "self.recovery_required.is_some()",
                    ".read_original_publication_checkpoint(&context.operation_id)?",
                    "let started = clock()?",
                    "LearningArtifactOwnerHost::read_original_registry_predecessor(",
                    "manifest.producer_id != *self.host.producer_id()",
                    "manifest.bytes_digest != Digest32::of_bytes(payload)",
                    "manifest.encoded_size_bytes != payload.len() as u64",
                    "ArtifactPublicationTransactionV1::begin_original_registry(",
                    "self.recovery_required = Some(context.operation_id.clone())",
                    "self.original_preparation_active = true",
                    "LearningArtifactOwnerHost::begin_original_registry_publication(",
                    "self.host.stage_compatibility_registration(",
                    "self.host.ensure_payload_durable(",
                    "self.host.ensure_registry_durable(",
                    "self.read_original_registry_durable_with_clock(&context, clock)?",
                    "observed.checkpoint().phase != ArtifactPublicationPhaseV1::RegistryDurable",
                    "Arc::clone(&self.original_preparation_instance)"
                ]
            },
            {
                "function": "fn read_original_registry_durable_with_clock(",
                "sequence": [
                    "self.original_preparation_fenced.load(Ordering::Acquire)",
                    "LearningArtifactOwnerHost::read_original_registry_durable(",
                    "OriginalArtifactPreparationErrorV1::Owner(_)",
                    "OriginalArtifactPreparationErrorV1::Publication(_)",
                    "OriginalArtifactPreparationErrorV1::ChangedDuringRead",
                    "OriginalArtifactPreparationErrorV1::Clock",
                    ".store(true, Ordering::Release)",
                    "result"
                ]
            },
            {
                "function": "fn finish_original_registry_with_clock(",
                "sequence": [
                    "Arc::ptr_eq(",
                    "&prepared.original_instance",
                    "&self.original_preparation_instance",
                    "self.recovery_required.as_ref() != Some(&prepared.context.operation_id)",
                    "self.read_original_registry_durable_with_clock(&prepared.context, clock)?",
                    "before.observed_unix_millis() < prepared.observed.observed_unix_millis()",
                    "!before.same_original_read(&prepared.observed)",
                    "before.checkpoint().phase != ArtifactPublicationPhaseV1::RegistryDurable",
                    "signed.binding != self.storage_binding",
                    "signed.witness.head_digest != before.registry_receipt().head_digest",
                    "prepared.context.expected_registry_predecessor_head",
                    "signed.withdrawal_scope_digest != prepared.context.admission.withdrawal_scope_digest",
                    "self.host.ensure_witness_durable(",
                    "self.host.acknowledge(",
                    "self.read_original_registry_durable_with_clock(&prepared.context, clock)?",
                    "after.checkpoint().phase != ArtifactPublicationPhaseV1::Acknowledged",
                    "after.checkpoint().state_digest != receipt.state_digest",
                    "after.current_head() != Some(&signed)",
                    "after.observed_unix_millis() < started",
                    "self.registry = prepared.staged",
                    "self.recovery_required = None",
                    "self.original_preparation_active = false",
                    "Ok(receipt)"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs",
        "required": [],
        "forbidden": [
            "resume_publication",
            "persist_checkpoint",
            "ensure_payload_durable",
            "ensure_registry_durable",
            "ensure_witness_durable",
            "File::create",
            "fs::write",
            "SigningKey",
            "Deserialize",
            "impl Clone for OriginalArtifactRegistryDurableV1"
        ],
        "required_function_order": [
            {
                "function": "fn read_original_publication_checkpoints(",
                "sequence": [
                    "for phase in ordered_phases()",
                    "missing_seen = true",
                    "if missing_seen",
                    "ArtifactOwnerHostError::CheckpointGap",
                    "decode_checkpoint(&read_small_record(&path, MAX_SMALL_RECORD_BYTES)?)?",
                    "checkpoint.operation_id != *operation_id || checkpoint.phase != phase",
                    "checkpoint.intent_digest",
                    "checkpoint.admission_digest",
                    "checkpoint.withdrawal_scope_digest",
                    "checkpoint.expected_registry_predecessor_head",
                    "invariant.is_some_and(|value| value != key)",
                    "observed.push(checkpoint)"
                ]
            },
            {
                "function": "fn read_original_registry_durable(",
                "sequence": [
                    "let started = clock()?",
                    "self.require_current_writer(started)?",
                    "let withdrawals_before = withdrawals.snapshot()",
                    "validate_artifact_publication_v3(",
                    "self.read_original_publication_checkpoints(&context.operation_id)?",
                    "for checkpoint in &before_records",
                    "checkpoint.withdrawal_head_digest != context.admission.withdrawal_head_digest",
                    "checkpoint.original_writer_lease_digest != writer.lease_digest",
                    "checkpoint.authority.grants_any()",
                    "ArtifactPublicationTransactionV1::from_original_registry_snapshot(",
                    "Error::Pending(before.phase)",
                    "if receipt.binding != binding",
                    "self.read_preparation_current(binding, started)?",
                    "read_registry_snapshot(",
                    "ArtifactPublicationTransactionV1::begin_original_registry(",
                    "last.event != original_registration_event(&transaction)?",
                    "read_candidate_payload(",
                    "transaction.record_payload_durable(",
                    "transaction.record_registry_durable(",
                    "read_registry_head_witness(",
                    "checkpoint_from_snapshot(&transaction.snapshot(), writer.lease_digest) != before",
                    "let registry_after = read_registry_snapshot(",
                    "let payload_after = read_candidate_payload(",
                    "self.read_preparation_current(binding, started)?",
                    "self.read_original_publication_checkpoints(&context.operation_id)?",
                    "before_records != after_records",
                    "registry.snapshot() != registry_after.snapshot()",
                    "payload != payload_after",
                    "current_before != current_after",
                    "withdrawals_before != withdrawals.snapshot()",
                    "let fresh = clock()?",
                    "if fresh < started",
                    "self.require_current_writer(fresh)?",
                    "writer_after.lease_digest != writer.lease_digest",
                    "validate_artifact_publication_v3(",
                    "self.verifier.verify_signed_head(",
                    "Ok(OriginalArtifactRegistryDurableV1 {"
                ]
            }
        ]
    },
    "codex-rs/hepta-agentd/src/artifact_original_head_owner.rs": {
        "path": "codex-rs/hepta-agentd/src/artifact_original_head_owner.rs",
        "required": [
            "bytes.get(..8) != Some(b\"HARHS001\".as_slice())"
        ],
        "forbidden": [
            "SigningKey::generate",
            "SigningKey::from_bytes",
            "Keypair",
            "SignedFinalUseGrant",
            "Deserialize",
            "impl Clone for OriginalArtifactHeadOwnerV1"
        ],
        "required_function_order": [
            {
                "function": "fn create(",
                "sequence": [
                    ".require_registered_key(&original_key.verifying_key().to_bytes(), started)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current(&source).await?",
                    "before.require_unsigned_phase()?",
                    "before.subject_binding(&source.config)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&queued_source, &cancelled)?",
                    "!queued_before.same_original_observation(&current_source)",
                    "let current = fresh(started)?",
                    ".require_registered_key(&verifying_key, current)?",
                    "current_source.authenticate_current(",
                    "LearningOwnerJournalV1::create(file, witness, binding)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current(&source).await?",
                    "!before.same_original_observation(&after)",
                    "let current = fresh(started)?",
                    "after.authenticate_current(",
                    ".require_registered_key(&original_key.verifying_key().to_bytes(), current)?",
                    "original_key: Mutex::new(Some(original_key))",
                    "admitted: AtomicBool::new(false)"
                ]
            },
            {
                "function": "fn recover(",
                "sequence": [
                    "OriginalArtifactRegistrySourceClientV1::read_current(&source).await?",
                    "before.subject_binding(&source.config)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&queued_source, &cancelled)?",
                    "!queued_before.same_original_observation(&current_source)",
                    "current_source.authenticate_current(&queued_source.config, fresh(started)?)?",
                    "LearningOwnerJournalV1::recover(file, witness, binding)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current(&source).await?",
                    "!before.same_original_observation(&after)",
                    "after.authenticate_current(&source.config, fresh(started)?)?",
                    "original_key: Mutex::new(None)",
                    "admitted: AtomicBool::new(true)"
                ]
            },
            {
                "function": "fn sign_original(",
                "sequence": [
                    "self.admitted.swap(true, Ordering::AcqRel)",
                    "cancelled.load(Ordering::Acquire)",
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&self.source, cancelled)?",
                    "self.require_subject(&before)?",
                    "before.require_unsigned_phase()?",
                    ".original_key",
                    ".take()",
                    "self.journal.try_lock()",
                    ".commit_once(&self.key, ||",
                    "let current = fresh(started)",
                    ".require_registered_key(&key.verifying_key().to_bytes(), current)",
                    ".unsigned_head(&before, current)",
                    "key.sign(&signed.signing_bytes()).to_bytes()",
                    "encode_record(self.original_subject, &encoded)",
                    "drop(key)",
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&self.source, cancelled)?",
                    "!before.same_original_observation(&after)",
                    "self.read_record()?",
                    "saved != bytes",
                    "decode_record(self.original_subject, &saved)?",
                    "let current = fresh(started)?",
                    "self.require_subject(&after)?",
                    ".verify_original_head(&after, &signed, current)?"
                ]
            },
            {
                "function": "fn read_original(",
                "sequence": [
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&self.source, cancelled)?",
                    "self.require_subject(&before)?",
                    "self.read_record()?",
                    "decode_record(self.original_subject, &bytes)?",
                    "OriginalArtifactRegistrySourceClientV1::read_current_in_lane(&self.source, cancelled)?",
                    "!before.same_original_observation(&after)",
                    "self.read_record()?",
                    "saved != bytes",
                    "let current = fresh(started)?",
                    "self.require_subject(&after)?",
                    ".verify_original_head(&after, &signed, current)?"
                ]
            },
            {
                "function": "fn decode_record(",
                "sequence": [
                    "bytes.len() < 44",
                    "bytes.len() > 16_384",
                    "bytes.get(..8) != Some(",
                    "bytes[8..40] != *subject.as_array()",
                    "if length != bytes.len() - 44",
                    "decode_artifact_head_bytes_v1(&bytes[44..])"
                ]
            }
        ]
    },
    "codex-rs/hepta-agentd/src/artifact_original_head_client.rs": {
        "path": "codex-rs/hepta-agentd/src/artifact_original_head_client.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "connect(",
            "File::",
            "Deserialize",
            "impl Clone for OriginalArtifactHeadConnectionV1"
        ],
        "required_function_order": [
            {
                "function": "fn bind(",
                "sequence": [
                    "require_peer(&peer, &config.signer_id)?",
                    "config.authenticate_current(started)?",
                    "original_owner_command_channel_v1(",
                    "original_head_pidfd",
                    "channel.check_peer_lifetime()?",
                    "let initial_at = fresh(started)?",
                    "config.authenticate_current(initial_at)?"
                ]
            },
            {
                "function": "fn sign_original_registry(",
                "sequence": [
                    "self,",
                    "prepared: OriginalArtifactPreparedPublicationV1",
                    "!matches!(&self.origin, Origin::Fresh)",
                    "OriginalArtifactRegistryDurableV1::encode_for_original_head_source(",
                    "prepared.registry_durable()",
                    "UntrustedArtifactRegistryDurableV1::decode(",
                    "claims.require_unsigned_phase()?",
                    "self.exchange(wire::Action::Sign, claims, cancelled).await?",
                    "Ok((prepared, signed))"
                ]
            },
            {
                "function": "fn exchange(",
                "sequence": [
                    "if started < self.initial_at",
                    "source.authenticate_current(&self.config, started)?",
                    "wire::Request::new(wire::Purpose::Head, action, 1, self.binding)?",
                    "QueueFence(Arc::clone(&abandoned))",
                    "tokio::task::spawn_blocking(",
                    "abandoned.load(Ordering::Acquire) || cancelled.load(Ordering::Acquire)",
                    "self.channel.check_peer_lifetime()?",
                    ".request(&encoded)",
                    "request.read_response(&bytes)",
                    "decode_artifact_head_bytes_v1(payload)?",
                    "channel.channel.check_peer_lifetime()?",
                    "let current = fresh(started)?",
                    ".verify_original_head(&source, &signed, current)?",
                    "Origin::Readonly(Some(expected))",
                    "expected != signed",
                    "Ok(signed)"
                ]
            }
        ]
    },
    "codex-rs/hepta-agentd/src/artifact_original_head_service.rs": {
        "path": "codex-rs/hepta-agentd/src/artifact_original_head_service.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "LearningOwnerJournalV1::create",
            "LearningOwnerJournalV1::recover",
            "File::",
            "connect(",
            "Deserialize"
        ],
        "required_function_order": [
            {
                "function": "fn serve_commands(",
                "sequence": [
                    "require_peer(&consumer, &self.source.config.writer_lease.producer_id)?",
                    ".try_acquire_owned()",
                    "original_owner_command_channel_v1(",
                    "original_consumer_pidfd",
                    "QueueFence(Arc::clone(&cancelled))",
                    "tokio::task::spawn_blocking(",
                    "for nonce in 1..=128",
                    "channel.exchange(",
                    "wire::Request::decode(bytes, wire::Purpose::Head, nonce, binding)?",
                    "original.source.config.authenticate_current(started)?",
                    "wire::Action::Sign => original.sign_original(&cancelled)",
                    "wire::Action::Readback => original.read_original(&cancelled)",
                    ".authenticate_current(fresh(started)?)?",
                    "Err(Error::Missing)",
                    "Err(Error::Pending)",
                    "Err(Error::ReadbackRequired)",
                    "Err(error) => return Err(failure.unwrap_or(Error::Transport(error)))"
                ]
            }
        ]
    },
    "codex-rs/hepta-agentd/src/artifact_original_registry_source.rs": {
        "path": "codex-rs/hepta-agentd/src/artifact_original_registry_source.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "connect(",
            "LearningArtifactOwnerService::open",
            "prepare_original_registry(",
            "finish_original_registry(",
            "resume_publication",
            "Deserialize"
        ],
        "required_function_order": [
            {
                "function": "fn from_original_writer(",
                "sequence": [
                    "writer: Arc<Mutex<LearningArtifactOwnerService>>",
                    "config.authenticate_current(now()?)?",
                    "config.binding()?",
                    "connections: Arc::new(Semaphore::new(4))"
                ]
            },
            {
                "function": "fn serve_reads(",
                "sequence": [
                    "require_peer(&consumer, &self.config.signer_id)?",
                    ".try_acquire_owned()",
                    "original_owner_command_channel_v1(",
                    "original_consumer_pidfd",
                    "QueueFence(Arc::clone(&cancelled))",
                    "tokio::task::spawn_blocking(",
                    "for nonce in 1..=128",
                    "channel.exchange(",
                    "original.respond(bytes, nonce)",
                    "Err(error) => return Err(failure.unwrap_or(Error::Transport(error)))"
                ]
            },
            {
                "function": "fn respond(",
                "sequence": [
                    "wire::Request::decode(bytes, wire::Purpose::Registry, nonce, self.binding)?",
                    "self.config.authenticate_current(started)?",
                    "self.writer.try_lock()",
                    "LearningArtifactOwnerService::read_original_registry_durable(",
                    "drop(writer)",
                    "OriginalArtifactRegistryDurableV1::encode_for_original_head_source(&observed, &self.config)?",
                    "UntrustedArtifactRegistryDurableV1::decode(",
                    "claims.authenticate_current(&self.config, fresh(started)?)?",
                    "request.response(wire::Status::Completed, &encoded)"
                ]
            },
            {
                "function": "fn from_original_stream(",
                "sequence": [
                    "require_peer(&peer, &config.writer_lease.producer_id)?",
                    "config.authenticate_current(started)?",
                    "original_owner_command_channel_v1(",
                    "original_writer_pidfd",
                    "channel.check_peer_lifetime()?",
                    "let observed = fresh(started)?",
                    "config.authenticate_current(observed)?",
                    "next: 1",
                    "source_at: 0",
                    "subject: None"
                ]
            },
            {
                "function": "fn read_current_in_lane(",
                "sequence": [
                    ".try_lock()",
                    ".take()",
                    "let started = now()?",
                    "started < self.initial_at || cancelled.load(Ordering::Acquire)",
                    "self.config.authenticate_current(started)?",
                    "wire::Purpose::Registry",
                    "wire::Action::Readback",
                    "channel.next.checked_add(1)",
                    "channel.peer.check_peer_lifetime()?",
                    "channel.peer.request(&request.encode())?",
                    "request.read_response(&bytes)?",
                    "UntrustedArtifactRegistryDurableV1::decode(payload, &self.config)?",
                    "channel.peer.check_peer_lifetime()?",
                    "let current = fresh(started)?",
                    "source.authenticate_current(&self.config, current)?",
                    "source.subject_binding(&self.config)?",
                    "source.observed_unix_millis() < channel.source_at",
                    "channel.subject.is_some_and(|old| old != binding)",
                    "cancelled.load(Ordering::Acquire)",
                    "channel.source_at = source.observed_unix_millis()",
                    "channel.subject = Some(binding)",
                    "*self.channel.try_lock().map_err(|_| Error::Busy)? = Some(channel)",
                    "Ok(source)"
                ]
            }
        ]
    },
    "codex-rs/hepta-agentd/src/artifact_original_head_wire.rs": {
        "path": "codex-rs/hepta-agentd/src/artifact_original_head_wire.rs",
        "required": [
            "const HEADER: usize = 50",
            "MAX_BYTES: usize = 16_384"
        ],
        "forbidden": [
            "SigningKey",
            "Deserialize",
            "pub payload:",
            "pub key:"
        ],
        "required_function_order": [
            {
                "function": "fn new(",
                "sequence": [
                    "nonce == 0",
                    "nonce > 128",
                    "binding.is_zero()",
                    "purpose == Purpose::Registry && action != Action::Readback"
                ]
            },
            {
                "function": "fn decode(",
                "sequence": [
                    "bytes.len() != HEADER",
                    "bytes.get(..8) != Some(MAGIC.as_slice())",
                    "bytes[8] != purpose as u8",
                    "let action = match bytes[9]",
                    "observed_nonce != nonce || observed_binding != binding",
                    "Self::new(purpose, action, nonce, binding)"
                ]
            }
        ],
        "required_order": [
            [
                "fn read_response",
                "bytes.len() < HEADER + 5",
                "bytes.len() > MAX_BYTES",
                "bytes[..HEADER] != self.encode()",
                "bytes.len() != HEADER + 5 + length",
                "1 if length > 0",
                "2 if length == 0",
                "3 if length == 0",
                "4 if length == 0",
                "5 if length == 0"
            ]
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_head_source.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_head_source.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "Deserialize",
            "FinalUseGrant"
        ],
        "required_function_order": [
            {
                "function": "fn binding(",
                "sequence": [
                    "verifier.trust_digest().as_array()",
                    "self.storage_binding.as_array()",
                    "self.writer_lease_digest().as_array()",
                    "crate::publication::digest_original_registry_intent(",
                    "&self.publication.operation_id",
                    "&self.publication.admission",
                    "self.publication.expected_registry_predecessor_head",
                    "push_id(&mut bytes, &self.signer_id)",
                    "self.authority_epoch.to_be_bytes()",
                    "self.signature_expires_at.to_be_bytes()"
                ]
            },
            {
                "function": "fn authenticate_current(",
                "sequence": [
                    "verifier.verify_writer_lease(&self.writer_lease, now)?",
                    "self.storage_binding.is_zero()",
                    "manifest.producer_id != writer.producer_id",
                    "self.signer_id == writer.producer_id",
                    "self.signature_expires_at < now",
                    "self.signature_expires_at > self.writer_lease.expires_at",
                    "self.signature_expires_at > manifest.expires_at",
                    "verify_artifact_admission_v3(",
                    "self.signature_expires_at > signer.expires_at",
                    ".is_some_and(|at| self.signature_expires_at >= at)",
                    "writer.signer_id == signer.signer_id || writer.verifying_key == signer.verifying_key",
                    "verify_signer_context("
                ]
            },
            {
                "function": "fn require_registered_key(",
                "sequence": [
                    "self.authenticate_current(now)?",
                    "entry.signer_id == self.signer_id",
                    "&signer.verifying_key != verifying_key",
                    "Error::InvalidKey"
                ]
            },
            {
                "function": "fn verify_original_head(",
                "sequence": [
                    "source.authenticate_current(self, now)?",
                    "signed.witness.issued_at > now",
                    "signed.withdrawal_scope_digest != self.trust.withdrawal_scope_digest",
                    "signed.binding != self.storage_binding",
                    "signed.witness.registry_id != self.trust.registry_id",
                    "signed.witness.generation != self.expected_generation(source)?",
                    "signed.witness.head_digest != source.registry_receipt().head_digest",
                    "signed.witness.predecessor_head_digest",
                    "signed.witness.authority_epoch != self.authority_epoch",
                    "signed.witness.signer_id != self.signer_id",
                    "signed.witness.signing_key_digest != Digest32::of_bytes(&signer.verifying_key)",
                    "signed.witness.expires_at != self.signature_expires_at",
                    "current != signed",
                    "verifier.verify_signed_head("
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_head_source_claims.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_head_source_claims.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "File::",
            "persist_checkpoint",
            "resume_publication"
        ],
        "required_function_order": [
            {
                "function": "fn authority(",
                "sequence": [
                    "fn authority(",
                    "AuthorityPosture::DENY_ALL"
                ]
            },
            {
                "function": "fn require_unsigned_phase(",
                "sequence": [
                    "self.checkpoint.phase != ArtifactPublicationPhaseV1::RegistryDurable",
                    "self.checkpoint.witness_receipt.is_some()",
                    "self.checkpoint.acknowledged_at.is_some()",
                    "head.witness.head_digest == self.registry_receipt().head_digest"
                ]
            },
            {
                "function": "fn authenticate_current(",
                "sequence": [
                    "config.authenticate_current(now)?",
                    "self.observed_at > now",
                    "self.observed_at < context.admission.admitted_at",
                    "self.trust_digest != verifier.trust_digest()",
                    "self.writer_lease_digest != config.writer_lease_digest()",
                    "checkpoint.operation_id != context.operation_id",
                    "checkpoint.original_writer_lease_digest != self.writer_lease_digest",
                    "checkpoint.admission_digest != context.admission.admission_digest",
                    "checkpoint.withdrawal_scope_digest != context.admission.withdrawal_scope_digest",
                    "checkpoint.withdrawal_head_digest != context.admission.withdrawal_head_digest",
                    "checkpoint.expected_registry_predecessor_head",
                    "checkpoint.authority.grants_any()",
                    "receipt != self.receipt",
                    "receipt.binding != config.storage_binding",
                    "receipt.head_digest != self.registry.head_digest",
                    "ArtifactPublicationTransactionV1::from_original_registry_snapshot(",
                    "crate::storage::encode_snapshot(&registry, receipt.binding)?",
                    "canonical.len() != receipt.encoded_bytes",
                    "registry.records().len() != receipt.records",
                    "Digest32::of_bytes(&canonical) != receipt.file_digest",
                    "last.event != original_registration_event(&transaction)?",
                    "verifier.verify_signed_head(",
                    "witness.file_digest != Digest32::of_bytes(&encoded)",
                    "witness.encoded_bytes != encoded.len()"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_head_source_codec.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_head_source_codec.rs",
        "required": [],
        "forbidden": [
            "SigningKey",
            "File::",
            "persist_checkpoint",
            "resume_publication",
            "Deserialize"
        ],
        "required_function_order": [
            {
                "function": "fn encode_for_original_head_source(",
                "sequence": [
                    "self.writer_lease() != &config.writer_lease",
                    "self.trust_digest()",
                    "ArtifactRegistry::from_snapshot(self.registry_snapshot().clone())?",
                    "encode_checkpoint(self.checkpoint())",
                    "self.writer_lease().signature",
                    "for value in [&checkpoint, &registry_bytes, &head, &lease]",
                    "self.trust_digest().as_array()",
                    "self.observed_unix_millis().to_be_bytes()",
                    "bytes.len() > MAX_BYTES",
                    "decode_source(&bytes, config)?",
                    "decoded.authenticate_current(config, self.observed_unix_millis())?"
                ]
            },
            {
                "function": "fn decode_source(",
                "sequence": [
                    "bytes.len() > MAX_BYTES",
                    "bytes.get(..8) != Some(MAGIC.as_slice())",
                    "let checkpoint_bytes = field(&mut cursor)?",
                    "let registry_bytes = field(&mut cursor)?",
                    "let head_bytes = field(&mut cursor)?",
                    "let lease_bytes = field(&mut cursor)?",
                    "cursor.len() != 40",
                    "encode_checkpoint(&checkpoint) != checkpoint_bytes",
                    "crate::storage::decode_registry_snapshot_bytes(registry_bytes, receipt)?",
                    "decode_artifact_head_bytes_v1(head_bytes)?",
                    "expected_lease.extend_from_slice(&config.writer_lease.signature)",
                    "lease_bytes != expected_lease",
                    "UntrustedArtifactRegistryDurableV1 {",
                    "value.authenticate_current(config, observed_at)?"
                ]
            },
            {
                "function": "fn decode_artifact_head_bytes_v1(",
                "sequence": [
                    "bytes.is_empty() || bytes.len() > MAX_BYTES",
                    "decode_signed_head(bytes)?",
                    "encode_signed_head(&value) != bytes"
                ]
            }
        ]
    },
    "codex-rs/hepta-learning-artifacts/src/owner_host.rs": {
        "path": "codex-rs/hepta-learning-artifacts/src/owner_host.rs",
        "required": [],
        "forbidden": [],
        "required_function_order": [
            {
                "function": "fn ensure_payload_durable(",
                "sequence": [
                    "self.require_current_writer(now)?",
                    "self.require_original_publication_checkpoint(",
                    "ArtifactPublicationPhaseV1::Prepared",
                    "write_candidate_payload_beneath(",
                    "self.persist_checkpoint(transaction)?"
                ]
            },
            {
                "function": "fn ensure_registry_durable(",
                "sequence": [
                    "self.require_current_writer(now)?",
                    "self.require_original_publication_checkpoint(",
                    "ArtifactPublicationPhaseV1::PayloadDurable",
                    "write_registry_snapshot_beneath(",
                    "self.persist_checkpoint(transaction)?"
                ]
            },
            {
                "function": "fn ensure_witness_durable(",
                "sequence": [
                    "self.require_current_writer(now)?",
                    "self.require_original_publication_checkpoint(",
                    "ArtifactPublicationPhaseV1::RegistryDurable",
                    "self.discover_current_head(now)?",
                    "write_registry_head_witness_beneath(",
                    "self.persist_signed_head_record(signed)?",
                    "transaction.record_witness_durable(",
                    "self.persist_checkpoint(transaction)?"
                ]
            },
            {
                "function": "fn acknowledge(",
                "sequence": [
                    "self.require_current_writer(now)?",
                    "self.require_original_publication_checkpoint(",
                    "ArtifactPublicationPhaseV1::WitnessDurable",
                    "transaction.acknowledge(",
                    "self.persist_checkpoint(transaction)?"
                ]
            }
        ]
    }
}


class OriginalArtifactHeadSourceClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / "CALLERS.toml").read_text())
        cls.boundaries = {row.identifier: row for row in PROOF._boundary_rows(cls.manifest)}

    def verify_text(self, path, text):
        rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
        self.assertTrue(rows)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(text)
            PROOF._verify_protected_files(root, {"protected_file": rows})

    def check_controls(self, paths):
        for path in paths:
            control = CONTROLS[path]
            source = (ROOT / path).read_text()
            self.verify_text(path, source)
            rows = [row for row in self.manifest["protected_file"] if row["path"] == path]
            self.assertIn(control, rows)
            for item in control["required_function_order"]:
                function = item["function"]
                code = PROOF._strip_rust_non_code(source)
                self.assertEqual(code.count(function), 1)
                start = code.index(function)
                end = PROOF._rust_item_end(code, start)
                self.assertIsNotNone(end)
                cursor = start
                for marker in item["sequence"]:
                    with self.subTest(path=path, function=function, marker=marker):
                        at = source.index(marker, cursor, end + 1)
                        cursor = at + len(marker)
                        changed = source[:at] + source[cursor:]
                        with self.assertRaises(PROOF.VerificationFailure):
                            self.verify_text(path, changed)
            for sequence in control.get("required_order", []):
                cursor = 0
                for marker in sequence:
                    with self.subTest(path=path, order_marker=marker):
                        at = source.index(marker, cursor)
                        cursor = at + len(marker)
                        with self.assertRaises(PROOF.VerificationFailure):
                            self.verify_text(path, source[:at] + source[cursor:])
            for marker in control["forbidden"]:
                with self.subTest(path=path, forbidden=marker):
                    with self.assertRaises(PROOF.VerificationFailure):
                        self.verify_text(path, source + "\n" + marker)

    def test_original_edges_and_unregistered_native_entrances_remain_exact(self):
        paths = {path for identifier in EXPECTED for path in
                 (self.boundaries[identifier].definition_path, *self.boundaries[identifier].product_callers)}
        sources = {path: PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
                   for path in paths}
        for identifier, expected in EXPECTED.items():
            with self.subTest(boundary=identifier):
                row = self.boundaries[identifier]
                self.assertEqual(row.product_callers, expected)
                self.assertIn(identifier, self.manifest["privileged_inventory"]["required_boundary_ids"])
                PROOF._verify_boundary(ROOT, row, sources, ())
                method = row.symbol.rsplit("::", 1)[-1]
                extra = dict(sources)
                extra["codex-rs/hepta-agentd/src/unregistered_artifact_owner.rs"] = (
                    f"fn bypass(owner: &{row.receiver_type}) {{ owner.{method}(); }}")
                with self.assertRaisesRegex(PROOF.VerificationFailure, "unexpected"):
                    PROOF._verify_boundary(ROOT, row, extra, ())
        self.assertTrue(all(value is False for value in self.manifest["authority"].values()))

    def test_cold_protocol_and_low_level_effects(self):
        self.check_controls(['codex-rs/hepta-learning-artifacts/src/publication_original.rs', 'codex-rs/hepta-learning-artifacts/src/publication.rs', 'codex-rs/hepta-learning-artifacts/src/owner_host_preparation.rs', 'codex-rs/hepta-learning-artifacts/src/owner_host.rs'])

    def test_fresh_writer_continuation(self):
        self.check_controls(['codex-rs/hepta-learning-artifacts/src/owner_service_preparation.rs'])

    def test_physical_original_registry(self):
        self.check_controls(['codex-rs/hepta-learning-artifacts/src/owner_host_registry_durable.rs'])

    def test_original_key_and_saved_signature(self):
        self.check_controls(['codex-rs/hepta-agentd/src/artifact_original_head_owner.rs'])

    def test_original_command_and_unknown_effect(self):
        self.check_controls(['codex-rs/hepta-agentd/src/artifact_original_head_client.rs', 'codex-rs/hepta-agentd/src/artifact_original_head_service.rs'])

    def test_original_process_pinned_source(self):
        self.check_controls(['codex-rs/hepta-agentd/src/artifact_original_registry_source.rs'])

    def test_registered_context_and_complete_claims(self):
        self.check_controls(['codex-rs/hepta-learning-artifacts/src/owner_head_source.rs', 'codex-rs/hepta-learning-artifacts/src/owner_head_source_claims.rs'])

    def test_canonical_purpose_and_bytes(self):
        self.check_controls(['codex-rs/hepta-agentd/src/artifact_original_head_wire.rs', 'codex-rs/hepta-learning-artifacts/src/owner_head_source_codec.rs'])


if __name__ == "__main__":
    unittest.main()
