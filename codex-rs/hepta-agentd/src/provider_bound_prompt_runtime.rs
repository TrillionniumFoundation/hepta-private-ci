//! Durable Agentd runtime for strict provider-bound context delivery.
//!
//! A dispatch claim is committed before exact provider request bytes leave the
//! process. The returned lease contains those already-attested bytes; callers
//! must submit them without reconstruction. A crash after the durable claim and
//! before a terminal receipt leaves an unresolved attempt that blocks blind
//! retry until reconciliation is durably recorded.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Mutex;
use std::sync::PoisonError;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use base64::Engine as _;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::MAX_PROVIDER_REQUEST_BYTES_V2;
use codex_hepta_context_compiler::ProviderBoundDeliveryReceiptV2;
use codex_hepta_intelligence::PreparedProviderBoundPromptV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const RUNTIME_SCHEMA: u32 = 1;
const STATE_FILE: &str = "provider-bound-prompt-runtime.json";
const NEXT_FILE: &str = "provider-bound-prompt-runtime.next";
const LOCK_FILE: &str = "provider-bound-prompt-runtime.lock";
const MAX_RUNTIME_ENTRIES: usize = 256;
const MAX_DURABLE_STATE_BYTES: u64 = 96 * 1024 * 1024;
const STAGE_DOMAIN: &[u8] = b"hepta.agentd-provider-bound-stage.v2\0";
const CLAIM_DOMAIN: &[u8] = b"hepta.agentd-provider-bound-dispatch-claim.v2\0";
const TERMINAL_DOMAIN: &[u8] = b"hepta.agentd-provider-bound-terminal.v2\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderBoundStageDispositionV2 {
    Inserted,
    Unchanged,
    ReplacedGeneration,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderBoundDispatchDispositionV2 {
    Claimed,
    ExistingClaim,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProviderBoundTerminalDispositionV2 {
    Recorded,
    Unchanged,
    Reconciled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum AgentdProviderBoundPromptRuntimeErrorV2 {
    InvalidDispatchId,
    InvalidAttemptId,
    InvalidGeneration,
    InvalidTime,
    EmptyDigest(&'static str),
    RequestMissing,
    RequestTooLarge,
    RequestDigestMismatch,
    StageDigestMismatch,
    ClaimDigestMismatch,
    TerminalDigestMismatch,
    StageNotFound,
    StageConflict,
    StaleGeneration,
    DispatchConflict,
    TerminalWithoutDispatch,
    TerminalBindingMismatch,
    TerminalConflict,
    TerminalAlreadyRecorded,
    IndeterminatePending,
    CapacityExceeded,
    CorruptState,
    StateLocked,
    StatePoisoned,
    Unavailable,
    IndeterminateDurability,
    ReopenRequired,
    SourceAuthorityGranted,
}

impl fmt::Display for AgentdProviderBoundPromptRuntimeErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for AgentdProviderBoundPromptRuntimeErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundPromptStageV2 {
    dispatch_id: StableId,
    generation: u64,
    bundle_digest: Digest32,
    canonical_serialization_proof_digest: Digest32,
    canonical_payload_digest: Digest32,
    attachment_digest: Digest32,
    snapshot_successor_digest: Digest32,
    preparation_digest: Digest32,
    provider_request_digest: Digest32,
    provider_request_coverage_digest: Digest32,
    wire_semantic_digest: Digest32,
    tokenizer_identity_digest: Digest32,
    tokenizer_attestation_digest: Digest32,
    exact_token_count: u64,
    exact_request_bytes: Vec<u8>,
    stage_digest: Digest32,
}

impl ProviderBoundPromptStageV2 {
    pub fn from_prepared(
        dispatch_id: StableId,
        generation: u64,
        prepared: &PreparedProviderBoundPromptV2,
    ) -> Result<Self, AgentdProviderBoundPromptRuntimeErrorV2> {
        if prepared.authority().grants_any() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::SourceAuthorityGranted);
        }
        let mut stage = Self {
            dispatch_id,
            generation,
            bundle_digest: prepared.bundle_digest(),
            canonical_serialization_proof_digest: prepared
                .canonical_serialization()
                .proof_digest(),
            canonical_payload_digest: prepared
                .canonical_serialization()
                .canonical_payload()
                .coverage()
                .payload_digest(),
            attachment_digest: prepared.attachment().attachment_digest(),
            snapshot_successor_digest: prepared.snapshot_successor().chain_digest(),
            preparation_digest: prepared.preparation().preparation_digest(),
            provider_request_digest: prepared.provider_request().request_digest(),
            provider_request_coverage_digest: prepared.provider_request().coverage_digest(),
            wire_semantic_digest: prepared.final_tokenization().wire_semantic_digest(),
            tokenizer_identity_digest: prepared.final_tokenization().tokenizer_identity().digest(),
            tokenizer_attestation_digest: prepared.final_tokenization().attestation_digest(),
            exact_token_count: prepared.final_tokenization().token_count(),
            exact_request_bytes: prepared.provider_request().bytes().to_vec(),
            stage_digest: Digest32::ZERO,
        };
        stage.stage_digest = stage.compute_digest();
        stage.validate()?;
        Ok(stage)
    }

    #[must_use]
    pub const fn dispatch_id(&self) -> &StableId {
        &self.dispatch_id
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn bundle_digest(&self) -> Digest32 {
        self.bundle_digest
    }

    #[must_use]
    pub const fn preparation_digest(&self) -> Digest32 {
        self.preparation_digest
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn tokenizer_attestation_digest(&self) -> Digest32 {
        self.tokenizer_attestation_digest
    }

    #[must_use]
    pub const fn exact_token_count(&self) -> u64 {
        self.exact_token_count
    }

    #[must_use]
    pub fn exact_request_bytes(&self) -> &[u8] {
        &self.exact_request_bytes
    }

    #[must_use]
    pub const fn stage_digest(&self) -> Digest32 {
        self.stage_digest
    }

    fn validate(&self) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        if self.dispatch_id.as_str().is_empty() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::InvalidDispatchId);
        }
        if self.generation == 0 {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::InvalidGeneration);
        }
        for (name, digest) in [
            ("bundle", self.bundle_digest),
            (
                "canonical_serialization_proof",
                self.canonical_serialization_proof_digest,
            ),
            ("canonical_payload", self.canonical_payload_digest),
            ("attachment", self.attachment_digest),
            ("snapshot_successor", self.snapshot_successor_digest),
            ("preparation", self.preparation_digest),
            ("provider_request", self.provider_request_digest),
            (
                "provider_request_coverage",
                self.provider_request_coverage_digest,
            ),
            ("wire_semantic", self.wire_semantic_digest),
            ("tokenizer_identity", self.tokenizer_identity_digest),
            (
                "tokenizer_attestation",
                self.tokenizer_attestation_digest,
            ),
            ("stage", self.stage_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        if self.exact_request_bytes.is_empty() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestMissing);
        }
        if self.exact_request_bytes.len() > MAX_PROVIDER_REQUEST_BYTES_V2 {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestTooLarge);
        }
        if self.exact_token_count == 0
            || Digest32::of_bytes(&self.exact_request_bytes) != self.provider_request_digest
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch);
        }
        if self.stage_digest != self.compute_digest() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::StageDigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = STAGE_DOMAIN.to_vec();
        push_id(&mut bytes, &self.dispatch_id);
        push_u64(&mut bytes, self.generation);
        for digest in [
            self.bundle_digest,
            self.canonical_serialization_proof_digest,
            self.canonical_payload_digest,
            self.attachment_digest,
            self.snapshot_successor_digest,
            self.preparation_digest,
            self.provider_request_digest,
            self.provider_request_coverage_digest,
            self.wire_semantic_digest,
            self.tokenizer_identity_digest,
            self.tokenizer_attestation_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_u64(&mut bytes, self.exact_token_count);
        push_u64(
            &mut bytes,
            u64::try_from(self.exact_request_bytes.len()).unwrap_or(u64::MAX),
        );
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProviderBoundDispatchClaimV2 {
    dispatch_id: StableId,
    generation: u64,
    attempt_id: StableId,
    stage_digest: Digest32,
    claimed_at_unix_ms: u64,
    claim_digest: Digest32,
}

impl ProviderBoundDispatchClaimV2 {
    fn new(
        stage: &ProviderBoundPromptStageV2,
        attempt_id: StableId,
        claimed_at_unix_ms: u64,
    ) -> Result<Self, AgentdProviderBoundPromptRuntimeErrorV2> {
        if attempt_id.as_str().is_empty() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::InvalidAttemptId);
        }
        if claimed_at_unix_ms == 0 {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::InvalidTime);
        }
        let mut claim = Self {
            dispatch_id: stage.dispatch_id.clone(),
            generation: stage.generation,
            attempt_id,
            stage_digest: stage.stage_digest,
            claimed_at_unix_ms,
            claim_digest: Digest32::ZERO,
        };
        claim.claim_digest = claim.compute_digest();
        claim.validate_for(stage)?;
        Ok(claim)
    }

    fn validate_for(
        &self,
        stage: &ProviderBoundPromptStageV2,
    ) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        if self.dispatch_id != stage.dispatch_id
            || self.generation != stage.generation
            || self.stage_digest != stage.stage_digest
            || self.claimed_at_unix_ms == 0
            || self.attempt_id.as_str().is_empty()
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::DispatchConflict);
        }
        ensure_digest("dispatch_claim", self.claim_digest)?;
        if self.claim_digest != self.compute_digest() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::ClaimDigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = CLAIM_DOMAIN.to_vec();
        push_id(&mut bytes, &self.dispatch_id);
        push_u64(&mut bytes, self.generation);
        push_id(&mut bytes, &self.attempt_id);
        bytes.extend_from_slice(self.stage_digest.as_array());
        push_u64(&mut bytes, self.claimed_at_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProviderBoundTerminalRecordV2 {
    dispatch_id: StableId,
    generation: u64,
    attempt_id: StableId,
    stage_digest: Digest32,
    claim_digest: Digest32,
    preparation_digest: Digest32,
    attachment_digest: Digest32,
    canonical_serialization_proof_digest: Digest32,
    canonical_payload_digest: Digest32,
    provider_request_digest: Digest32,
    provider_request_coverage_digest: Digest32,
    wire_semantic_digest: Digest32,
    tokenizer_identity_digest: Digest32,
    tokenizer_attestation_digest: Digest32,
    delivery_receipt_digest: Digest32,
    disposition: ContextDeliveryDispositionV2,
    terminal_observed: bool,
    observed_unix_ms: u64,
    terminal_digest: Digest32,
}

impl ProviderBoundTerminalRecordV2 {
    fn from_receipt(
        stage: &ProviderBoundPromptStageV2,
        claim: &ProviderBoundDispatchClaimV2,
        receipt: &ProviderBoundDeliveryReceiptV2,
    ) -> Result<Self, AgentdProviderBoundPromptRuntimeErrorV2> {
        let mut terminal = Self {
            dispatch_id: stage.dispatch_id.clone(),
            generation: stage.generation,
            attempt_id: claim.attempt_id.clone(),
            stage_digest: stage.stage_digest,
            claim_digest: claim.claim_digest,
            preparation_digest: receipt.preparation_digest(),
            attachment_digest: receipt.attachment_digest(),
            canonical_serialization_proof_digest: receipt
                .canonical_serialization_proof_digest(),
            canonical_payload_digest: receipt.canonical_payload_digest(),
            provider_request_digest: receipt.provider_request_digest(),
            provider_request_coverage_digest: receipt.provider_request_coverage_digest(),
            wire_semantic_digest: receipt.wire_semantic_digest(),
            tokenizer_identity_digest: receipt.tokenizer_identity_digest(),
            tokenizer_attestation_digest: receipt.tokenizer_attestation_digest(),
            delivery_receipt_digest: receipt.receipt_digest(),
            disposition: receipt.disposition(),
            terminal_observed: receipt.terminal_observed(),
            observed_unix_ms: receipt.observed_unix_ms(),
            terminal_digest: Digest32::ZERO,
        };
        terminal.terminal_digest = terminal.compute_digest();
        terminal.validate_for(stage, claim)?;
        Ok(terminal)
    }

    fn validate_for(
        &self,
        stage: &ProviderBoundPromptStageV2,
        claim: &ProviderBoundDispatchClaimV2,
    ) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        if self.dispatch_id != stage.dispatch_id
            || self.generation != stage.generation
            || self.attempt_id != claim.attempt_id
            || self.stage_digest != stage.stage_digest
            || self.claim_digest != claim.claim_digest
            || self.preparation_digest != stage.preparation_digest
            || self.attachment_digest != stage.attachment_digest
            || self.canonical_serialization_proof_digest
                != stage.canonical_serialization_proof_digest
            || self.canonical_payload_digest != stage.canonical_payload_digest
            || self.provider_request_digest != stage.provider_request_digest
            || self.provider_request_coverage_digest != stage.provider_request_coverage_digest
            || self.wire_semantic_digest != stage.wire_semantic_digest
            || self.tokenizer_identity_digest != stage.tokenizer_identity_digest
            || self.tokenizer_attestation_digest != stage.tokenizer_attestation_digest
            || self.observed_unix_ms < claim.claimed_at_unix_ms
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalBindingMismatch);
        }
        for (name, digest) in [
            ("delivery_receipt", self.delivery_receipt_digest),
            ("terminal", self.terminal_digest),
        ] {
            ensure_digest(name, digest)?;
        }
        match self.disposition {
            ContextDeliveryDispositionV2::Delivered
            | ContextDeliveryDispositionV2::Rejected
            | ContextDeliveryDispositionV2::NotDispatched => {
                if !self.terminal_observed {
                    return Err(
                        AgentdProviderBoundPromptRuntimeErrorV2::TerminalBindingMismatch,
                    );
                }
            }
            ContextDeliveryDispositionV2::Indeterminate => {
                if self.terminal_observed {
                    return Err(
                        AgentdProviderBoundPromptRuntimeErrorV2::TerminalBindingMismatch,
                    );
                }
            }
        }
        if self.terminal_digest != self.compute_digest() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalDigestMismatch);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = TERMINAL_DOMAIN.to_vec();
        push_id(&mut bytes, &self.dispatch_id);
        push_u64(&mut bytes, self.generation);
        push_id(&mut bytes, &self.attempt_id);
        for digest in [
            self.stage_digest,
            self.claim_digest,
            self.preparation_digest,
            self.attachment_digest,
            self.canonical_serialization_proof_digest,
            self.canonical_payload_digest,
            self.provider_request_digest,
            self.provider_request_coverage_digest,
            self.wire_semantic_digest,
            self.tokenizer_identity_digest,
            self.tokenizer_attestation_digest,
            self.delivery_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(disposition_code(self.disposition));
        bytes.push(u8::from(self.terminal_observed));
        push_u64(&mut bytes, self.observed_unix_ms);
        Digest32::of_bytes(&bytes)
    }

    fn is_final(&self) -> bool {
        self.disposition != ContextDeliveryDispositionV2::Indeterminate
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProviderBoundRuntimeEntryV2 {
    stage: ProviderBoundPromptStageV2,
    dispatch: Option<ProviderBoundDispatchClaimV2>,
    terminal: Option<ProviderBoundTerminalRecordV2>,
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
struct ProviderBoundRuntimeStateV2 {
    entries: BTreeMap<String, ProviderBoundRuntimeEntryV2>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundDispatchLeaseV2 {
    disposition: ProviderBoundDispatchDispositionV2,
    dispatch_id: StableId,
    generation: u64,
    attempt_id: StableId,
    stage_digest: Digest32,
    claim_digest: Digest32,
    provider_request_digest: Digest32,
    provider_request_coverage_digest: Digest32,
    wire_semantic_digest: Digest32,
    tokenizer_attestation_digest: Digest32,
    exact_request_bytes: Vec<u8>,
}

impl ProviderBoundDispatchLeaseV2 {
    #[must_use]
    pub const fn disposition(&self) -> ProviderBoundDispatchDispositionV2 {
        self.disposition
    }

    #[must_use]
    pub const fn dispatch_id(&self) -> &StableId {
        &self.dispatch_id
    }

    #[must_use]
    pub const fn generation(&self) -> u64 {
        self.generation
    }

    #[must_use]
    pub const fn attempt_id(&self) -> &StableId {
        &self.attempt_id
    }

    #[must_use]
    pub const fn claim_digest(&self) -> Digest32 {
        self.claim_digest
    }

    #[must_use]
    pub const fn provider_request_digest(&self) -> Digest32 {
        self.provider_request_digest
    }

    #[must_use]
    pub const fn provider_request_coverage_digest(&self) -> Digest32 {
        self.provider_request_coverage_digest
    }

    #[must_use]
    pub const fn wire_semantic_digest(&self) -> Digest32 {
        self.wire_semantic_digest
    }

    #[must_use]
    pub const fn tokenizer_attestation_digest(&self) -> Digest32 {
        self.tokenizer_attestation_digest
    }

    #[must_use]
    pub fn exact_request_bytes(&self) -> &[u8] {
        &self.exact_request_bytes
    }

    fn from_entry(
        entry: &ProviderBoundRuntimeEntryV2,
        disposition: ProviderBoundDispatchDispositionV2,
    ) -> Result<Self, AgentdProviderBoundPromptRuntimeErrorV2> {
        let claim = entry
            .dispatch
            .as_ref()
            .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::DispatchConflict)?;
        let lease = Self {
            disposition,
            dispatch_id: entry.stage.dispatch_id.clone(),
            generation: entry.stage.generation,
            attempt_id: claim.attempt_id.clone(),
            stage_digest: entry.stage.stage_digest,
            claim_digest: claim.claim_digest,
            provider_request_digest: entry.stage.provider_request_digest,
            provider_request_coverage_digest: entry.stage.provider_request_coverage_digest,
            wire_semantic_digest: entry.stage.wire_semantic_digest,
            tokenizer_attestation_digest: entry.stage.tokenizer_attestation_digest,
            exact_request_bytes: entry.stage.exact_request_bytes.clone(),
        };
        lease.validate()?;
        Ok(lease)
    }

    fn validate(&self) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        if self.generation == 0
            || self.exact_request_bytes.is_empty()
            || self.exact_request_bytes.len() > MAX_PROVIDER_REQUEST_BYTES_V2
            || Digest32::of_bytes(&self.exact_request_bytes) != self.provider_request_digest
        {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::RequestDigestMismatch);
        }
        for (name, digest) in [
            ("stage", self.stage_digest),
            ("claim", self.claim_digest),
            ("provider_request", self.provider_request_digest),
            (
                "provider_request_coverage",
                self.provider_request_coverage_digest,
            ),
            ("wire_semantic", self.wire_semantic_digest),
            (
                "tokenizer_attestation",
                self.tokenizer_attestation_digest,
            ),
        ] {
            ensure_digest(name, digest)?;
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProviderBoundRuntimeSnapshotV2 {
    pub dispatch_id: StableId,
    pub generation: u64,
    pub stage_digest: Digest32,
    pub provider_request_digest: Digest32,
    pub dispatch_attempt_id: Option<StableId>,
    pub dispatch_claim_digest: Option<Digest32>,
    pub terminal_receipt_digest: Option<Digest32>,
    pub terminal_disposition: Option<ContextDeliveryDispositionV2>,
}

pub struct AgentdProviderBoundPromptRuntimeV2 {
    state: Mutex<ProviderBoundRuntimeStateV2>,
    store: Option<ProviderBoundRuntimeStoreV2>,
    poisoned: AtomicBool,
}

impl fmt::Debug for AgentdProviderBoundPromptRuntimeV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let state = self.state.lock().unwrap_or_else(PoisonError::into_inner);
        formatter
            .debug_struct("AgentdProviderBoundPromptRuntimeV2")
            .field("entries", &state.entries.len())
            .field("durable", &self.store.is_some())
            .field("requires_reopen", &self.poisoned.load(Ordering::Acquire))
            .finish()
    }
}

impl Default for AgentdProviderBoundPromptRuntimeV2 {
    fn default() -> Self {
        Self::new()
    }
}

impl AgentdProviderBoundPromptRuntimeV2 {
    #[must_use]
    pub fn new() -> Self {
        Self {
            state: Mutex::new(ProviderBoundRuntimeStateV2::default()),
            store: None,
            poisoned: AtomicBool::new(false),
        }
    }

    pub fn open_state_dir(
        directory: &Path,
    ) -> Result<Self, AgentdProviderBoundPromptRuntimeErrorV2> {
        let (store, state) = ProviderBoundRuntimeStoreV2::open(directory)?;
        validate_state(&state)?;
        Ok(Self {
            state: Mutex::new(state),
            store: Some(store),
            poisoned: AtomicBool::new(false),
        })
    }

    #[must_use]
    pub fn requires_reopen(&self) -> bool {
        self.poisoned.load(Ordering::Acquire)
    }

    pub fn stage_prepared(
        &self,
        dispatch_id: StableId,
        generation: u64,
        prepared: &PreparedProviderBoundPromptV2,
    ) -> Result<ProviderBoundStageDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        let stage = ProviderBoundPromptStageV2::from_prepared(dispatch_id, generation, prepared)?;
        self.stage(stage)
    }

    pub fn claim_dispatch(
        &self,
        dispatch_id: &StableId,
        expected_generation: u64,
        attempt_id: StableId,
        claimed_at_unix_ms: u64,
    ) -> Result<ProviderBoundDispatchLeaseV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        let key = dispatch_id.to_string();
        self.commit_state(|state| {
            let entry = state
                .entries
                .get_mut(&key)
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::StageNotFound)?;
            if entry.stage.generation != expected_generation {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration);
            }
            if entry.terminal.as_ref().is_some_and(|value| value.is_final()) {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalAlreadyRecorded);
            }
            if let Some(existing) = &entry.dispatch {
                if existing.attempt_id != attempt_id {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
                }
                existing.validate_for(&entry.stage)?;
                return ProviderBoundDispatchLeaseV2::from_entry(
                    entry,
                    ProviderBoundDispatchDispositionV2::ExistingClaim,
                );
            }
            let claim = ProviderBoundDispatchClaimV2::new(
                &entry.stage,
                attempt_id,
                claimed_at_unix_ms,
            )?;
            entry.dispatch = Some(claim);
            ProviderBoundDispatchLeaseV2::from_entry(
                entry,
                ProviderBoundDispatchDispositionV2::Claimed,
            )
        })
    }

    pub fn record_terminal(
        &self,
        dispatch_id: &StableId,
        expected_generation: u64,
        attempt_id: &StableId,
        receipt: &ProviderBoundDeliveryReceiptV2,
    ) -> Result<ProviderBoundTerminalDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        let key = dispatch_id.to_string();
        self.commit_state(|state| {
            let entry = state
                .entries
                .get_mut(&key)
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::StageNotFound)?;
            if entry.stage.generation != expected_generation {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration);
            }
            let claim = entry
                .dispatch
                .as_ref()
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::TerminalWithoutDispatch)?;
            if &claim.attempt_id != attempt_id {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalBindingMismatch);
            }
            let terminal = ProviderBoundTerminalRecordV2::from_receipt(
                &entry.stage,
                claim,
                receipt,
            )?;
            record_terminal(entry, terminal)
        })
    }

    pub fn snapshot(
        &self,
        dispatch_id: &StableId,
    ) -> Result<Option<ProviderBoundRuntimeSnapshotV2>, AgentdProviderBoundPromptRuntimeErrorV2> {
        self.ensure_available()?;
        let state = self
            .state
            .lock()
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::StatePoisoned)?;
        Ok(state.entries.get(dispatch_id.as_str()).map(|entry| {
            ProviderBoundRuntimeSnapshotV2 {
                dispatch_id: entry.stage.dispatch_id.clone(),
                generation: entry.stage.generation,
                stage_digest: entry.stage.stage_digest,
                provider_request_digest: entry.stage.provider_request_digest,
                dispatch_attempt_id: entry
                    .dispatch
                    .as_ref()
                    .map(|claim| claim.attempt_id.clone()),
                dispatch_claim_digest: entry.dispatch.as_ref().map(|claim| claim.claim_digest),
                terminal_receipt_digest: entry
                    .terminal
                    .as_ref()
                    .map(|terminal| terminal.delivery_receipt_digest),
                terminal_disposition: entry
                    .terminal
                    .as_ref()
                    .map(|terminal| terminal.disposition),
            }
        }))
    }

    fn stage(
        &self,
        stage: ProviderBoundPromptStageV2,
    ) -> Result<ProviderBoundStageDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        stage.validate()?;
        let key = stage.dispatch_id.to_string();
        self.commit_state(|state| {
            let Some(existing) = state.entries.get(&key) else {
                if state.entries.len() >= MAX_RUNTIME_ENTRIES {
                    return Err(AgentdProviderBoundPromptRuntimeErrorV2::CapacityExceeded);
                }
                state.entries.insert(
                    key,
                    ProviderBoundRuntimeEntryV2 {
                        stage,
                        dispatch: None,
                        terminal: None,
                    },
                );
                return Ok(ProviderBoundStageDispositionV2::Inserted);
            };
            if existing.stage == stage {
                return Ok(ProviderBoundStageDispositionV2::Unchanged);
            }
            if stage.generation <= existing.stage.generation {
                return if stage.generation < existing.stage.generation {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration)
                } else {
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::StageConflict)
                };
            }
            if existing.dispatch.is_some()
                && !existing.terminal.as_ref().is_some_and(|value| value.is_final())
            {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminatePending);
            }
            state.entries.insert(
                key,
                ProviderBoundRuntimeEntryV2 {
                    stage,
                    dispatch: None,
                    terminal: None,
                },
            );
            Ok(ProviderBoundStageDispositionV2::ReplacedGeneration)
        })
    }

    fn ensure_available(&self) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        if self.poisoned.load(Ordering::Acquire) {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::ReopenRequired);
        }
        Ok(())
    }

    fn commit_state<T>(
        &self,
        mutation: impl FnOnce(
            &mut ProviderBoundRuntimeStateV2,
        ) -> Result<T, AgentdProviderBoundPromptRuntimeErrorV2>,
    ) -> Result<T, AgentdProviderBoundPromptRuntimeErrorV2> {
        self.ensure_available()?;
        let mut current = self
            .state
            .lock()
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::StatePoisoned)?;
        let mut next = current.clone();
        let result = mutation(&mut next)?;
        validate_state(&next)?;
        if next != *current {
            if let Some(store) = &self.store {
                match store.persist(&next) {
                    Ok(()) => {}
                    Err(AgentdProviderBoundPromptRuntimeErrorV2::IndeterminateDurability) => {
                        self.poisoned.store(true, Ordering::Release);
                        return Err(
                            AgentdProviderBoundPromptRuntimeErrorV2::IndeterminateDurability,
                        );
                    }
                    Err(error) => return Err(error),
                }
            }
            *current = next;
        }
        Ok(result)
    }

    #[cfg(test)]
    fn record_terminal_for_test(
        &self,
        dispatch_id: &StableId,
        expected_generation: u64,
        attempt_id: &StableId,
        disposition: ContextDeliveryDispositionV2,
        observed_unix_ms: u64,
        receipt_digest: Digest32,
    ) -> Result<ProviderBoundTerminalDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
        let key = dispatch_id.to_string();
        self.commit_state(|state| {
            let entry = state
                .entries
                .get_mut(&key)
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::StageNotFound)?;
            if entry.stage.generation != expected_generation {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::StaleGeneration);
            }
            let claim = entry
                .dispatch
                .as_ref()
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::TerminalWithoutDispatch)?;
            if &claim.attempt_id != attempt_id {
                return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalBindingMismatch);
            }
            let terminal_observed = disposition != ContextDeliveryDispositionV2::Indeterminate;
            let mut terminal = ProviderBoundTerminalRecordV2 {
                dispatch_id: entry.stage.dispatch_id.clone(),
                generation: entry.stage.generation,
                attempt_id: claim.attempt_id.clone(),
                stage_digest: entry.stage.stage_digest,
                claim_digest: claim.claim_digest,
                preparation_digest: entry.stage.preparation_digest,
                attachment_digest: entry.stage.attachment_digest,
                canonical_serialization_proof_digest: entry
                    .stage
                    .canonical_serialization_proof_digest,
                canonical_payload_digest: entry.stage.canonical_payload_digest,
                provider_request_digest: entry.stage.provider_request_digest,
                provider_request_coverage_digest: entry.stage.provider_request_coverage_digest,
                wire_semantic_digest: entry.stage.wire_semantic_digest,
                tokenizer_identity_digest: entry.stage.tokenizer_identity_digest,
                tokenizer_attestation_digest: entry.stage.tokenizer_attestation_digest,
                delivery_receipt_digest: receipt_digest,
                disposition,
                terminal_observed,
                observed_unix_ms,
                terminal_digest: Digest32::ZERO,
            };
            terminal.terminal_digest = terminal.compute_digest();
            terminal.validate_for(&entry.stage, claim)?;
            record_terminal(entry, terminal)
        })
    }
}

fn record_terminal(
    entry: &mut ProviderBoundRuntimeEntryV2,
    terminal: ProviderBoundTerminalRecordV2,
) -> Result<ProviderBoundTerminalDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    if let Some(existing) = &entry.terminal {
        if existing == &terminal {
            return Ok(ProviderBoundTerminalDispositionV2::Unchanged);
        }
        if existing.disposition == ContextDeliveryDispositionV2::Indeterminate
            && terminal.is_final()
            && terminal.observed_unix_ms >= existing.observed_unix_ms
        {
            entry.terminal = Some(terminal);
            return Ok(ProviderBoundTerminalDispositionV2::Reconciled);
        }
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::TerminalConflict);
    }
    entry.terminal = Some(terminal);
    Ok(ProviderBoundTerminalDispositionV2::Recorded)
}

fn validate_state(
    state: &ProviderBoundRuntimeStateV2,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    if state.entries.len() > MAX_RUNTIME_ENTRIES {
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
    }
    for (key, entry) in &state.entries {
        entry.stage.validate()?;
        if key != entry.stage.dispatch_id.as_str() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
        }
        if let Some(claim) = &entry.dispatch {
            claim.validate_for(&entry.stage)?;
        }
        if let Some(terminal) = &entry.terminal {
            let claim = entry
                .dispatch
                .as_ref()
                .ok_or(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?;
            terminal.validate_for(&entry.stage, claim)?;
        }
    }
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredProviderBoundRuntimeStateV2 {
    schema: u32,
    entries: Vec<StoredProviderBoundRuntimeEntryV2>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredProviderBoundRuntimeEntryV2 {
    stage: StoredProviderBoundPromptStageV2,
    dispatch: Option<StoredProviderBoundDispatchClaimV2>,
    terminal: Option<StoredProviderBoundTerminalRecordV2>,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredProviderBoundPromptStageV2 {
    dispatch_id: String,
    generation: u64,
    bundle_digest: [u8; 32],
    canonical_serialization_proof_digest: [u8; 32],
    canonical_payload_digest: [u8; 32],
    attachment_digest: [u8; 32],
    snapshot_successor_digest: [u8; 32],
    preparation_digest: [u8; 32],
    provider_request_digest: [u8; 32],
    provider_request_coverage_digest: [u8; 32],
    wire_semantic_digest: [u8; 32],
    tokenizer_identity_digest: [u8; 32],
    tokenizer_attestation_digest: [u8; 32],
    exact_token_count: u64,
    exact_request_base64: String,
    stage_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredProviderBoundDispatchClaimV2 {
    dispatch_id: String,
    generation: u64,
    attempt_id: String,
    stage_digest: [u8; 32],
    claimed_at_unix_ms: u64,
    claim_digest: [u8; 32],
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct StoredProviderBoundTerminalRecordV2 {
    dispatch_id: String,
    generation: u64,
    attempt_id: String,
    stage_digest: [u8; 32],
    claim_digest: [u8; 32],
    preparation_digest: [u8; 32],
    attachment_digest: [u8; 32],
    canonical_serialization_proof_digest: [u8; 32],
    canonical_payload_digest: [u8; 32],
    provider_request_digest: [u8; 32],
    provider_request_coverage_digest: [u8; 32],
    wire_semantic_digest: [u8; 32],
    tokenizer_identity_digest: [u8; 32],
    tokenizer_attestation_digest: [u8; 32],
    delivery_receipt_digest: [u8; 32],
    disposition: u8,
    terminal_observed: bool,
    observed_unix_ms: u64,
    terminal_digest: [u8; 32],
}

struct ProviderBoundRuntimeStoreV2 {
    root: PathBuf,
    _lock: File,
}

impl ProviderBoundRuntimeStoreV2 {
    fn open(
        directory: &Path,
    ) -> Result<
        (Self, ProviderBoundRuntimeStateV2),
        AgentdProviderBoundPromptRuntimeErrorV2,
    > {
        prepare_state_directory(directory)?;
        let lock_path = directory.join(LOCK_FILE);
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        set_private_file_permissions(&lock_path)?;
        lock.try_lock()
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::StateLocked)?;
        let store = Self {
            root: directory.to_path_buf(),
            _lock: lock,
        };
        store.recover_next_file()?;
        let state_path = directory.join(STATE_FILE);
        if !state_path.exists() {
            return Ok((store, ProviderBoundRuntimeStateV2::default()));
        }
        let mut bytes = Vec::new();
        File::open(&state_path)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?
            .take(MAX_DURABLE_STATE_BYTES + 1)
            .read_to_end(&mut bytes)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
        }
        let stored: StoredProviderBoundRuntimeStateV2 = serde_json::from_slice(&bytes)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?;
        let state = restore_state(stored)?;
        Ok((store, state))
    }

    fn recover_next_file(&self) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        let next_path = self.root.join(NEXT_FILE);
        if !next_path.exists() {
            return Ok(());
        }
        let state_path = self.root.join(STATE_FILE);
        if state_path.exists() {
            std::fs::remove_file(&next_path)
                .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
            return Ok(());
        }
        std::fs::rename(&next_path, &state_path)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        sync_state_directory(&self.root)
    }

    fn persist(
        &self,
        state: &ProviderBoundRuntimeStateV2,
    ) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
        let bytes = serde_json::to_vec(&stored_state(state))
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        if u64::try_from(bytes.len()).unwrap_or(u64::MAX) > MAX_DURABLE_STATE_BYTES {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::CapacityExceeded);
        }
        let next_path = self.root.join(NEXT_FILE);
        let mut next = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&next_path)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        set_private_file_permissions(&next_path)?;
        next.write_all(&bytes)
            .and_then(|()| next.sync_all())
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        std::fs::rename(&next_path, self.root.join(STATE_FILE))
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
        sync_state_directory(&self.root)
    }
}

fn stored_state(state: &ProviderBoundRuntimeStateV2) -> StoredProviderBoundRuntimeStateV2 {
    StoredProviderBoundRuntimeStateV2 {
        schema: RUNTIME_SCHEMA,
        entries: state
            .entries
            .values()
            .map(|entry| StoredProviderBoundRuntimeEntryV2 {
                stage: stored_stage(&entry.stage),
                dispatch: entry.dispatch.as_ref().map(stored_claim),
                terminal: entry.terminal.as_ref().map(stored_terminal),
            })
            .collect(),
    }
}

fn stored_stage(stage: &ProviderBoundPromptStageV2) -> StoredProviderBoundPromptStageV2 {
    StoredProviderBoundPromptStageV2 {
        dispatch_id: stage.dispatch_id.to_string(),
        generation: stage.generation,
        bundle_digest: stage.bundle_digest.into_array(),
        canonical_serialization_proof_digest: stage
            .canonical_serialization_proof_digest
            .into_array(),
        canonical_payload_digest: stage.canonical_payload_digest.into_array(),
        attachment_digest: stage.attachment_digest.into_array(),
        snapshot_successor_digest: stage.snapshot_successor_digest.into_array(),
        preparation_digest: stage.preparation_digest.into_array(),
        provider_request_digest: stage.provider_request_digest.into_array(),
        provider_request_coverage_digest: stage.provider_request_coverage_digest.into_array(),
        wire_semantic_digest: stage.wire_semantic_digest.into_array(),
        tokenizer_identity_digest: stage.tokenizer_identity_digest.into_array(),
        tokenizer_attestation_digest: stage.tokenizer_attestation_digest.into_array(),
        exact_token_count: stage.exact_token_count,
        exact_request_base64: STANDARD_NO_PAD.encode(&stage.exact_request_bytes),
        stage_digest: stage.stage_digest.into_array(),
    }
}

fn stored_claim(
    claim: &ProviderBoundDispatchClaimV2,
) -> StoredProviderBoundDispatchClaimV2 {
    StoredProviderBoundDispatchClaimV2 {
        dispatch_id: claim.dispatch_id.to_string(),
        generation: claim.generation,
        attempt_id: claim.attempt_id.to_string(),
        stage_digest: claim.stage_digest.into_array(),
        claimed_at_unix_ms: claim.claimed_at_unix_ms,
        claim_digest: claim.claim_digest.into_array(),
    }
}

fn stored_terminal(
    terminal: &ProviderBoundTerminalRecordV2,
) -> StoredProviderBoundTerminalRecordV2 {
    StoredProviderBoundTerminalRecordV2 {
        dispatch_id: terminal.dispatch_id.to_string(),
        generation: terminal.generation,
        attempt_id: terminal.attempt_id.to_string(),
        stage_digest: terminal.stage_digest.into_array(),
        claim_digest: terminal.claim_digest.into_array(),
        preparation_digest: terminal.preparation_digest.into_array(),
        attachment_digest: terminal.attachment_digest.into_array(),
        canonical_serialization_proof_digest: terminal
            .canonical_serialization_proof_digest
            .into_array(),
        canonical_payload_digest: terminal.canonical_payload_digest.into_array(),
        provider_request_digest: terminal.provider_request_digest.into_array(),
        provider_request_coverage_digest: terminal
            .provider_request_coverage_digest
            .into_array(),
        wire_semantic_digest: terminal.wire_semantic_digest.into_array(),
        tokenizer_identity_digest: terminal.tokenizer_identity_digest.into_array(),
        tokenizer_attestation_digest: terminal.tokenizer_attestation_digest.into_array(),
        delivery_receipt_digest: terminal.delivery_receipt_digest.into_array(),
        disposition: disposition_code(terminal.disposition),
        terminal_observed: terminal.terminal_observed,
        observed_unix_ms: terminal.observed_unix_ms,
        terminal_digest: terminal.terminal_digest.into_array(),
    }
}

fn restore_state(
    stored: StoredProviderBoundRuntimeStateV2,
) -> Result<ProviderBoundRuntimeStateV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    if stored.schema != RUNTIME_SCHEMA || stored.entries.len() > MAX_RUNTIME_ENTRIES {
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
    }
    let mut state = ProviderBoundRuntimeStateV2::default();
    for stored_entry in stored.entries {
        let stage = restore_stage(stored_entry.stage)?;
        let dispatch = stored_entry.dispatch.map(restore_claim).transpose()?;
        let terminal = stored_entry.terminal.map(restore_terminal).transpose()?;
        let key = stage.dispatch_id.to_string();
        let entry = ProviderBoundRuntimeEntryV2 {
            stage,
            dispatch,
            terminal,
        };
        if state.entries.insert(key, entry).is_some() {
            return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
        }
    }
    validate_state(&state)?;
    Ok(state)
}

fn restore_stage(
    stored: StoredProviderBoundPromptStageV2,
) -> Result<ProviderBoundPromptStageV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    let stage = ProviderBoundPromptStageV2 {
        dispatch_id: parse_id(stored.dispatch_id)?,
        generation: stored.generation,
        bundle_digest: Digest32::from_array(stored.bundle_digest),
        canonical_serialization_proof_digest: Digest32::from_array(
            stored.canonical_serialization_proof_digest,
        ),
        canonical_payload_digest: Digest32::from_array(stored.canonical_payload_digest),
        attachment_digest: Digest32::from_array(stored.attachment_digest),
        snapshot_successor_digest: Digest32::from_array(stored.snapshot_successor_digest),
        preparation_digest: Digest32::from_array(stored.preparation_digest),
        provider_request_digest: Digest32::from_array(stored.provider_request_digest),
        provider_request_coverage_digest: Digest32::from_array(
            stored.provider_request_coverage_digest,
        ),
        wire_semantic_digest: Digest32::from_array(stored.wire_semantic_digest),
        tokenizer_identity_digest: Digest32::from_array(stored.tokenizer_identity_digest),
        tokenizer_attestation_digest: Digest32::from_array(
            stored.tokenizer_attestation_digest,
        ),
        exact_token_count: stored.exact_token_count,
        exact_request_bytes: STANDARD_NO_PAD
            .decode(stored.exact_request_base64)
            .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)?,
        stage_digest: Digest32::from_array(stored.stage_digest),
    };
    stage.validate()?;
    Ok(stage)
}

fn restore_claim(
    stored: StoredProviderBoundDispatchClaimV2,
) -> Result<ProviderBoundDispatchClaimV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    Ok(ProviderBoundDispatchClaimV2 {
        dispatch_id: parse_id(stored.dispatch_id)?,
        generation: stored.generation,
        attempt_id: parse_id(stored.attempt_id)?,
        stage_digest: Digest32::from_array(stored.stage_digest),
        claimed_at_unix_ms: stored.claimed_at_unix_ms,
        claim_digest: Digest32::from_array(stored.claim_digest),
    })
}

fn restore_terminal(
    stored: StoredProviderBoundTerminalRecordV2,
) -> Result<ProviderBoundTerminalRecordV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    Ok(ProviderBoundTerminalRecordV2 {
        dispatch_id: parse_id(stored.dispatch_id)?,
        generation: stored.generation,
        attempt_id: parse_id(stored.attempt_id)?,
        stage_digest: Digest32::from_array(stored.stage_digest),
        claim_digest: Digest32::from_array(stored.claim_digest),
        preparation_digest: Digest32::from_array(stored.preparation_digest),
        attachment_digest: Digest32::from_array(stored.attachment_digest),
        canonical_serialization_proof_digest: Digest32::from_array(
            stored.canonical_serialization_proof_digest,
        ),
        canonical_payload_digest: Digest32::from_array(stored.canonical_payload_digest),
        provider_request_digest: Digest32::from_array(stored.provider_request_digest),
        provider_request_coverage_digest: Digest32::from_array(
            stored.provider_request_coverage_digest,
        ),
        wire_semantic_digest: Digest32::from_array(stored.wire_semantic_digest),
        tokenizer_identity_digest: Digest32::from_array(stored.tokenizer_identity_digest),
        tokenizer_attestation_digest: Digest32::from_array(
            stored.tokenizer_attestation_digest,
        ),
        delivery_receipt_digest: Digest32::from_array(stored.delivery_receipt_digest),
        disposition: decode_disposition(stored.disposition)?,
        terminal_observed: stored.terminal_observed,
        observed_unix_ms: stored.observed_unix_ms,
        terminal_digest: Digest32::from_array(stored.terminal_digest),
    })
}

fn parse_id(
    value: String,
) -> Result<StableId, AgentdProviderBoundPromptRuntimeErrorV2> {
    StableId::new(value).map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::CorruptState)
}

fn ensure_digest(
    name: &'static str,
    digest: Digest32,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    if digest.is_zero() {
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_u64(bytes, u64::try_from(raw.len()).unwrap_or(u64::MAX));
    bytes.extend_from_slice(raw);
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

const fn disposition_code(value: ContextDeliveryDispositionV2) -> u8 {
    match value {
        ContextDeliveryDispositionV2::Delivered => 0,
        ContextDeliveryDispositionV2::Rejected => 1,
        ContextDeliveryDispositionV2::NotDispatched => 2,
        ContextDeliveryDispositionV2::Indeterminate => 3,
    }
}

fn decode_disposition(
    value: u8,
) -> Result<ContextDeliveryDispositionV2, AgentdProviderBoundPromptRuntimeErrorV2> {
    match value {
        0 => Ok(ContextDeliveryDispositionV2::Delivered),
        1 => Ok(ContextDeliveryDispositionV2::Rejected),
        2 => Ok(ContextDeliveryDispositionV2::NotDispatched),
        3 => Ok(ContextDeliveryDispositionV2::Indeterminate),
        _ => Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState),
    }
}

fn prepare_state_directory(
    path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    if let Err(error) = std::fs::create_dir(path)
        && error.kind() != std::io::ErrorKind::AlreadyExists
    {
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::Unavailable);
    }
    let metadata = std::fs::symlink_metadata(path)
        .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)?;
    if !metadata.is_dir() || metadata.file_type().is_symlink() {
        return Err(AgentdProviderBoundPromptRuntimeErrorV2::CorruptState);
    }
    set_private_directory_permissions(path)
}

#[cfg(unix)]
fn set_private_directory_permissions(
    path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o700))
        .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)
}

#[cfg(not(unix))]
fn set_private_directory_permissions(
    _path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    Ok(())
}

#[cfg(unix)]
fn set_private_file_permissions(
    path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    use std::os::unix::fs::PermissionsExt;
    std::fs::set_permissions(path, std::fs::Permissions::from_mode(0o600))
        .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::Unavailable)
}

#[cfg(not(unix))]
fn set_private_file_permissions(
    _path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    Ok(())
}

#[cfg(unix)]
fn sync_state_directory(
    path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|_| AgentdProviderBoundPromptRuntimeErrorV2::IndeterminateDurability)
}

#[cfg(not(unix))]
fn sync_state_directory(
    _path: &Path,
) -> Result<(), AgentdProviderBoundPromptRuntimeErrorV2> {
    Ok(())
}

#[cfg(test)]
#[path = "provider_bound_prompt_runtime_tests.rs"]
mod tests;
