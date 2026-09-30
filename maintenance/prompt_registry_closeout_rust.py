#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text.rstrip() + "\n", encoding="utf-8")


def replace_once(path: str, old: str, new: str, marker: str) -> None:
    text = read(path)
    if marker in text:
        return
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one replacement anchor for {marker!r}")
    write(path, text.replace(old, new, 1))


def append_once(path: str, marker: str, block: str) -> None:
    text = read(path)
    if marker in text:
        return
    write(path, text.rstrip() + "\n\n" + block.strip() + "\n")


EXT = "codex-rs/ext/hepta-prompt/src/lib.rs"
TESTS = "codex-rs/ext/hepta-prompt/src/lib_tests.rs"
REGISTRY_LIB = "codex-rs/hepta-prompt-registry/src/lib.rs"
GOVERNANCE = "codex-rs/hepta-prompt-registry/src/governance.rs"

replace_once(
    EXT,
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderPolicyContributor;",
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\nuse codex_extension_api::ModelProviderPolicyContributor;",
    "use codex_extension_api::ModelProviderOutputBatch;",
)
replace_once(
    EXT,
    "                    provider_request_digest,\n                    dispatch_unix_ms,\n                }),",
    "                    provider_request_digest,\n                    dispatch_unix_ms,\n                    last_output_sequence: 0,\n                }),",
    "last_output_sequence: 0,",
)
replace_once(
    EXT,
    "    provider_request_digest: Digest32,\n    dispatch_unix_ms: u64,\n}",
    "    provider_request_digest: Digest32,\n    dispatch_unix_ms: u64,\n    last_output_sequence: u64,\n}",
    "last_output_sequence: u64,",
)
replace_once(
    EXT,
    "impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {\n    fn finish(",
    '''impl ModelProviderAttemptLease for PromptRuntimeAttemptLease {
    fn authorize_output<'a>(
        &'a mut self,
        batch: ModelProviderOutputBatch,
    ) -> ModelProviderPolicyFuture<'a, ModelProviderOutputDecision> {
        Box::pin(async move {
            batch.validate()?;
            let expected_sequence = self
                .last_output_sequence
                .checked_add(1)
                .ok_or_else(|| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_output_sequence_invalid",
                        "provider output sequence overflowed",
                    )
                })?;
            if batch.sequence != expected_sequence {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_output_sequence_invalid",
                    "provider output sequence was replayed, skipped, or reordered",
                ));
            }

            let current = self
                .host
                .prepare(PromptRuntimePrepareRequest {
                    thread_id: self.thread_id.clone(),
                    turn_id: self.turn_id.clone(),
                    model_context_window: None,
                })
                .await
                .map_err(|error| {
                    ModelProviderPolicyError::new(
                        error.reason_code().to_owned(),
                        error.detail().to_owned(),
                    )
                })?
                .ok_or_else(|| {
                    ModelProviderPolicyError::new(
                        "prompt_runtime_output_attachment_removed",
                        "the source-bound prompt attachment is no longer current",
                    )
                })?;
            if current != self.attachment {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_output_binding_changed",
                    "the source-bound prompt attachment changed during provider execution",
                ));
            }
            if current_unix_ms().map_err(runtime_policy_error)? >= current.deadline_ms {
                return Err(ModelProviderPolicyError::new(
                    "prompt_runtime_output_expired",
                    "the source-bound prompt attachment expired before output release",
                ));
            }

            self.last_output_sequence = batch.sequence;
            Ok(ModelProviderOutputDecision::Allow)
        })
    }

    fn finish(''',
    "prompt_runtime_output_sequence_invalid",
)

replace_once(
    TESTS,
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderPolicyContributor;",
    "use codex_extension_api::ModelProviderInvocationInput;\nuse codex_extension_api::ModelProviderOutputBatch;\nuse codex_extension_api::ModelProviderOutputDecision;\nuse codex_extension_api::ModelProviderPolicyContributor;",
    "use codex_extension_api::ModelProviderOutputBatch;",
)
replace_once(
    TESTS,
    '''fn provider_digest(value: &str) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(digest(value).to_string())
        .unwrap_or_else(|error| panic!("valid provider digest: {}", error.detail()))
}
''',
    '''fn provider_digest(value: &str) -> ModelProviderSha256Digest {
    ModelProviderSha256Digest::parse(digest(value).to_string())
        .unwrap_or_else(|error| panic!("valid provider digest: {}", error.detail()))
}

fn output_batch(sequence: u64, label: &str) -> ModelProviderOutputBatch {
    ModelProviderOutputBatch {
        sequence,
        event_sha256: provider_digest(label),
        encoded_bytes: 64,
    }
}
''',
    "fn output_batch(sequence: u64, label: &str)",
)

append_once(
    TESTS,
    "provider_output_revocation_before_first_event_fails_closed",
    r'''
#[tokio::test]
async fn provider_output_revocation_before_first_event_fails_closed() {
    let withdrawn = Arc::new(AtomicBool::new(false));
    let terminal_records = Arc::new(StdMutex::new(Vec::new()));
    let prepared = attachment();
    let flag = Arc::clone(&withdrawn);
    let records = Arc::clone(&terminal_records);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-output-before-first",
        move |_| {
            let result = if flag.load(Ordering::Acquire) {
                Err(PromptRuntimeHostError::new(
                    "prompt_final_use_revoked",
                    "selection revoked",
                ))
            } else {
                Ok(Some(prepared.clone()))
            };
            Box::pin(std::future::ready(result))
        },
        |_| Box::pin(std::future::ready(Ok(()))),
        move |record| {
            let records = Arc::clone(&records);
            Box::pin(async move {
                records
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner)
                    .push(record);
                Ok(())
            })
        },
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id = ThreadId::from_string(thread_store.level_id())
        .unwrap_or_else(|error| panic!("thread: {error}"));
    let fragments = extension
        .contribute_turn_context(TurnContextContributionInput {
            thread_id,
            turn_id: turn_store.level_id(),
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            model_context_window: Some(128_000),
        })
        .await;
    assert_eq!(fragments.len(), 1);

    let provider_config = provider_digest("provider-config:output-before-first");
    let endpoint = provider_digest("endpoint:output-before-first");
    let logical = provider_digest("logical:output-before-first");
    let wire = provider_digest("wire:output-before-first");
    let decision = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:output-before-first",
            request_binding_id: "provider-request:output-before-first",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await
        .unwrap_or_else(|error| panic!("provider begin: {}", error.detail()));
    let ModelProviderPolicyDecision::Allow { mut lease } = decision else {
        panic!("provider attempt must be admitted before revocation");
    };

    withdrawn.store(true, Ordering::Release);
    let error = lease
        .authorize_output(output_batch(1, "event:output-before-first"))
        .await
        .expect_err("revocation before the first event must stop release");
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    lease
        .finish(ModelProviderTerminal::Indeterminate {
            reason_code: "provider_output_authorization_failed".to_owned(),
            partial_response_sha256: None,
        })
        .await
        .unwrap_or_else(|error| panic!("terminal: {}", error.detail()));

    let records = terminal_records
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    assert_eq!(records.len(), 1);
    assert_eq!(records[0].outcome, PromptRuntimeTerminalOutcomeV1::Indeterminate);
    assert!(records[0].delivery_observation.is_none());
}

#[tokio::test]
async fn provider_output_revocation_after_first_event_fails_closed() {
    let withdrawn = Arc::new(AtomicBool::new(false));
    let prepared = attachment();
    let flag = Arc::clone(&withdrawn);
    let host = PromptRuntimeHost::new(
        "prompt-runtime-output-mid-stream",
        move |_| {
            let result = if flag.load(Ordering::Acquire) {
                Err(PromptRuntimeHostError::new(
                    "prompt_final_use_revoked",
                    "selection revoked",
                ))
            } else {
                Ok(Some(prepared.clone()))
            };
            Box::pin(std::future::ready(result))
        },
        |_| Box::pin(std::future::ready(Ok(()))),
        |_| Box::pin(std::future::ready(Ok(()))),
    )
    .unwrap_or_else(|error| panic!("host: {error}"));
    let extension = PromptRuntimeExtension { host };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id = ThreadId::from_string(thread_store.level_id())
        .unwrap_or_else(|error| panic!("thread: {error}"));
    let _ = extension
        .contribute_turn_context(TurnContextContributionInput {
            thread_id,
            turn_id: turn_store.level_id(),
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            model_context_window: Some(128_000),
        })
        .await;

    let provider_config = provider_digest("provider-config:output-mid-stream");
    let endpoint = provider_digest("endpoint:output-mid-stream");
    let logical = provider_digest("logical:output-mid-stream");
    let wire = provider_digest("wire:output-mid-stream");
    let decision = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:output-mid-stream",
            request_binding_id: "provider-request:output-mid-stream",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::WebSocket,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await
        .unwrap_or_else(|error| panic!("provider begin: {}", error.detail()));
    let ModelProviderPolicyDecision::Allow { mut lease } = decision else {
        panic!("provider attempt must be admitted");
    };
    let first = lease
        .authorize_output(output_batch(1, "event:output-mid-stream:1"))
        .await
        .unwrap_or_else(|error| panic!("first output: {}", error.detail()));
    assert_eq!(first, ModelProviderOutputDecision::Allow);

    withdrawn.store(true, Ordering::Release);
    let error = lease
        .authorize_output(output_batch(2, "event:output-mid-stream:2"))
        .await
        .expect_err("mid-stream revocation must stop the next event");
    assert_eq!(error.reason_code(), "prompt_final_use_revoked");
    lease
        .finish(ModelProviderTerminal::Indeterminate {
            reason_code: "provider_output_authorization_failed".to_owned(),
            partial_response_sha256: Some(provider_digest("partial-response")),
        })
        .await
        .unwrap_or_else(|error| panic!("terminal: {}", error.detail()));
}

#[tokio::test]
async fn provider_output_sequence_replay_fails_closed() {
    let dispatches = Arc::new(StdMutex::new(Vec::new()));
    let records = Arc::new(StdMutex::new(Vec::new()));
    let extension = PromptRuntimeExtension {
        host: host(Arc::clone(&dispatches), Arc::clone(&records)),
    };
    let (session_store, thread_store, turn_store) = stores();
    let thread_id = ThreadId::from_string(thread_store.level_id())
        .unwrap_or_else(|error| panic!("thread: {error}"));
    let _ = extension
        .contribute_turn_context(TurnContextContributionInput {
            thread_id,
            turn_id: turn_store.level_id(),
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            model_context_window: None,
        })
        .await;

    let provider_config = provider_digest("provider-config:output-replay");
    let endpoint = provider_digest("endpoint:output-replay");
    let logical = provider_digest("logical:output-replay");
    let wire = provider_digest("wire:output-replay");
    let decision = extension
        .begin(ModelProviderInvocationInput {
            schema_version: codex_extension_api::MODEL_PROVIDER_POLICY_INPUT_SCHEMA_VERSION,
            session_store: &session_store,
            thread_store: &thread_store,
            turn_store: &turn_store,
            attempt_id: "provider-attempt:output-replay",
            request_binding_id: "provider-request:output-replay",
            thread_id: thread_store.level_id(),
            turn_id: turn_store.level_id(),
            request_kind: ModelProviderRequestKind::Turn,
            provider_id: "test-provider",
            provider_config_sha256: &provider_config,
            model: "gpt-test",
            transport: ModelProviderTransport::Http,
            endpoint_sha256: &endpoint,
            logical_request_sha256: &logical,
            wire_semantic_sha256: &wire,
            ephemeral_input_sha256: None,
            ephemeral_input_witness_sha256: None,
            previous_response_id_sha256: None,
            generate: true,
        })
        .await
        .unwrap_or_else(|error| panic!("provider begin: {}", error.detail()));
    let ModelProviderPolicyDecision::Allow { mut lease } = decision else {
        panic!("provider attempt must be admitted");
    };
    assert_eq!(
        lease
            .authorize_output(output_batch(1, "event:output-replay:1"))
            .await
            .unwrap_or_else(|error| panic!("first output: {}", error.detail())),
        ModelProviderOutputDecision::Allow
    );
    let error = lease
        .authorize_output(output_batch(1, "event:output-replay:duplicate"))
        .await
        .expect_err("replayed output sequence must be rejected");
    assert_eq!(error.reason_code(), "prompt_runtime_output_sequence_invalid");
    lease
        .finish(ModelProviderTerminal::Indeterminate {
            reason_code: "provider_output_sequence_invalid".to_owned(),
            partial_response_sha256: None,
        })
        .await
        .unwrap_or_else(|error| panic!("terminal: {}", error.detail()));
}
''',
)

GOVERNANCE_SOURCE = r'''
//! Versioned retention and external authority-fencing contracts.
//!
//! These values are deliberately separate from checkpoint activation. They can
//! be persisted by an owner or deployment controller, but constructing a value
//! never grants authority, proves physical erasure, or activates a checkpoint.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Serialize;

pub const RETENTION_POLICY_VERSION_V1: u32 = 1;
pub const AUTHORITY_FENCE_VERSION_V1: u32 = 1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetentionPolicyV1 {
    pub revoked_payload_min_age_ms: u64,
    pub retired_payload_min_age_ms: u64,
    pub audit_metadata_min_age_ms: u64,
    pub tombstone_min_age_ms: u64,
    pub checkpoint_confirmations: u32,
    pub secure_disposal_required: bool,
}

impl RetentionPolicyV1 {
    pub fn validate(&self) -> Result<(), GovernanceError> {
        if self.checkpoint_confirmations == 0
            || self.audit_metadata_min_age_ms < self.revoked_payload_min_age_ms
            || self.audit_metadata_min_age_ms < self.retired_payload_min_age_ms
            || self.tombstone_min_age_ms < self.audit_metadata_min_age_ms
        {
            return Err(GovernanceError::InvalidRetentionPolicy);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-registry.retention-policy.v1".to_vec();
        bytes.extend_from_slice(&self.revoked_payload_min_age_ms.to_be_bytes());
        bytes.extend_from_slice(&self.retired_payload_min_age_ms.to_be_bytes());
        bytes.extend_from_slice(&self.audit_metadata_min_age_ms.to_be_bytes());
        bytes.extend_from_slice(&self.tombstone_min_age_ms.to_be_bytes());
        bytes.extend_from_slice(&self.checkpoint_confirmations.to_be_bytes());
        bytes.push(u8::from(self.secure_disposal_required));
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PhysicalDisposalStateV1 {
    LogicalUseFenced,
    PayloadExtentReleased,
    BackupReleased,
    CheckpointConfirmed,
    IndependentlyVerified,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct RetentionDecisionV1 {
    pub policy_version: u32,
    pub policy_digest: Digest32,
    pub decision_wall_time_ms: u64,
    pub decision_monotonic_epoch: u64,
    pub eligible_since_ms: u64,
    pub last_gc_attempt_ms: Option<u64>,
    pub last_gc_failure: Option<StableId>,
    pub physical_disposal_state: PhysicalDisposalStateV1,
}

impl RetentionDecisionV1 {
    pub fn validate(&self, policy: &RetentionPolicyV1) -> Result<(), GovernanceError> {
        policy.validate()?;
        if self.policy_version != RETENTION_POLICY_VERSION_V1
            || self.policy_digest != policy.compute_digest()
            || self.decision_wall_time_ms == 0
            || self.decision_monotonic_epoch == 0
            || self.eligible_since_ms > self.decision_wall_time_ms
            || self
                .last_gc_attempt_ms
                .is_some_and(|attempt| attempt < self.eligible_since_ms)
        {
            return Err(GovernanceError::InvalidRetentionDecision);
        }
        if policy.secure_disposal_required
            && self.physical_disposal_state < PhysicalDisposalStateV1::CheckpointConfirmed
        {
            return Err(GovernanceError::SecureDisposalEvidenceRequired);
        }
        Ok(())
    }

    #[must_use]
    pub fn physical_erasure_independently_verified(&self) -> bool {
        self.physical_disposal_state == PhysicalDisposalStateV1::IndependentlyVerified
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct AuthorityFenceV1 {
    pub version: u32,
    pub authority_epoch: u64,
    pub owner_instance_id: StableId,
    pub checkpoint_sequence: u64,
    pub handoff_nonce: Digest32,
    pub storage_generation: u64,
    pub transport_generation: u64,
}

impl AuthorityFenceV1 {
    pub fn validate(&self) -> Result<(), GovernanceError> {
        if self.version != AUTHORITY_FENCE_VERSION_V1
            || self.authority_epoch == 0
            || self.checkpoint_sequence == 0
            || self.handoff_nonce.is_zero()
            || self.storage_generation == 0
            || self.transport_generation == 0
        {
            return Err(GovernanceError::InvalidAuthorityFence);
        }
        Ok(())
    }

    pub fn authorize_current(&self, presented: &Self) -> Result<(), GovernanceError> {
        self.validate()?;
        presented.validate()?;
        if self != presented {
            return Err(GovernanceError::StaleAuthorityFence);
        }
        Ok(())
    }

    pub fn validate_successor(&self, successor: &Self) -> Result<(), GovernanceError> {
        self.validate()?;
        successor.validate()?;
        if successor.authority_epoch <= self.authority_epoch
            || successor.checkpoint_sequence < self.checkpoint_sequence
            || successor.storage_generation <= self.storage_generation
            || successor.transport_generation <= self.transport_generation
            || successor.owner_instance_id == self.owner_instance_id
            || successor.handoff_nonce == self.handoff_nonce
        {
            return Err(GovernanceError::InvalidAuthoritySuccessor);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.prompt-registry.authority-fence.v1".to_vec();
        bytes.extend_from_slice(&self.version.to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        let owner = self.owner_instance_id.as_str().as_bytes();
        bytes.extend_from_slice(&u32::try_from(owner.len()).unwrap_or(u32::MAX).to_be_bytes());
        bytes.extend_from_slice(owner);
        bytes.extend_from_slice(&self.checkpoint_sequence.to_be_bytes());
        bytes.extend_from_slice(self.handoff_nonce.as_array());
        bytes.extend_from_slice(&self.storage_generation.to_be_bytes());
        bytes.extend_from_slice(&self.transport_generation.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GovernanceError {
    InvalidRetentionPolicy,
    InvalidRetentionDecision,
    SecureDisposalEvidenceRequired,
    InvalidAuthorityFence,
    StaleAuthorityFence,
    InvalidAuthoritySuccessor,
}

impl fmt::Display for GovernanceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for GovernanceError {}

#[cfg(test)]
mod tests {
    use super::*;

    fn policy() -> RetentionPolicyV1 {
        RetentionPolicyV1 {
            revoked_payload_min_age_ms: 60_000,
            retired_payload_min_age_ms: 120_000,
            audit_metadata_min_age_ms: 300_000,
            tombstone_min_age_ms: 600_000,
            checkpoint_confirmations: 2,
            secure_disposal_required: true,
        }
    }

    fn fence(owner: &str, epoch: u64, storage: u64, transport: u64) -> AuthorityFenceV1 {
        AuthorityFenceV1 {
            version: AUTHORITY_FENCE_VERSION_V1,
            authority_epoch: epoch,
            owner_instance_id: StableId::new(owner)
                .unwrap_or_else(|error| panic!("owner: {error}")),
            checkpoint_sequence: epoch,
            handoff_nonce: Digest32::of_bytes(format!("nonce:{owner}:{epoch}").as_bytes()),
            storage_generation: storage,
            transport_generation: transport,
        }
    }

    #[test]
    fn retention_policy_digest_and_disposal_evidence_fail_closed() {
        let policy = policy();
        policy.validate().unwrap_or_else(|error| panic!("policy: {error}"));
        let mut decision = RetentionDecisionV1 {
            policy_version: RETENTION_POLICY_VERSION_V1,
            policy_digest: policy.compute_digest(),
            decision_wall_time_ms: 700_000,
            decision_monotonic_epoch: 7,
            eligible_since_ms: 600_000,
            last_gc_attempt_ms: Some(650_000),
            last_gc_failure: None,
            physical_disposal_state: PhysicalDisposalStateV1::PayloadExtentReleased,
        };
        assert_eq!(
            decision.validate(&policy),
            Err(GovernanceError::SecureDisposalEvidenceRequired)
        );
        decision.physical_disposal_state = PhysicalDisposalStateV1::CheckpointConfirmed;
        decision
            .validate(&policy)
            .unwrap_or_else(|error| panic!("decision: {error}"));
        assert!(!decision.physical_erasure_independently_verified());
        decision.physical_disposal_state = PhysicalDisposalStateV1::IndependentlyVerified;
        assert!(decision.physical_erasure_independently_verified());
    }

    #[test]
    fn retention_policy_digest_tampering_is_rejected() {
        let policy = policy();
        let decision = RetentionDecisionV1 {
            policy_version: RETENTION_POLICY_VERSION_V1,
            policy_digest: Digest32::of_bytes(b"wrong-policy"),
            decision_wall_time_ms: 700_000,
            decision_monotonic_epoch: 7,
            eligible_since_ms: 600_000,
            last_gc_attempt_ms: None,
            last_gc_failure: None,
            physical_disposal_state: PhysicalDisposalStateV1::IndependentlyVerified,
        };
        assert_eq!(
            decision.validate(&policy),
            Err(GovernanceError::InvalidRetentionDecision)
        );
    }

    #[test]
    fn stale_storage_or_transport_generation_is_rejected() {
        let current = fence("owner:current", 4, 8, 11);
        current
            .authorize_current(&current)
            .unwrap_or_else(|error| panic!("current: {error}"));
        let stale_storage = fence("owner:current", 4, 7, 11);
        assert_eq!(
            current.authorize_current(&stale_storage),
            Err(GovernanceError::StaleAuthorityFence)
        );
        let stale_transport = fence("owner:current", 4, 8, 10);
        assert_eq!(
            current.authorize_current(&stale_transport),
            Err(GovernanceError::StaleAuthorityFence)
        );
    }

    #[test]
    fn handoff_requires_monotonic_new_owner_generations() {
        let current = fence("owner:current", 4, 8, 11);
        let successor = fence("owner:successor", 5, 9, 12);
        current
            .validate_successor(&successor)
            .unwrap_or_else(|error| panic!("successor: {error}"));
        let stale = fence("owner:successor", 5, 8, 12);
        assert_eq!(
            current.validate_successor(&stale),
            Err(GovernanceError::InvalidAuthoritySuccessor)
        );
    }
}
'''
write(GOVERNANCE, GOVERNANCE_SOURCE)

replace_once(
    REGISTRY_LIB,
    "mod failure;\nmod protocol;",
    "mod failure;\nmod governance;\nmod protocol;",
    "mod governance;",
)
replace_once(
    REGISTRY_LIB,
    "pub use failure::PromptRegistryRecoveryV1;\npub use protocol::PromptFactorV1;",
    '''pub use failure::PromptRegistryRecoveryV1;
pub use governance::AUTHORITY_FENCE_VERSION_V1;
pub use governance::AuthorityFenceV1;
pub use governance::GovernanceError;
pub use governance::PhysicalDisposalStateV1;
pub use governance::RETENTION_POLICY_VERSION_V1;
pub use governance::RetentionDecisionV1;
pub use governance::RetentionPolicyV1;
pub use protocol::PromptFactorV1;''',
    "pub use governance::AuthorityFenceV1;",
)

print("prompt.registry Rust closeout patch applied")
