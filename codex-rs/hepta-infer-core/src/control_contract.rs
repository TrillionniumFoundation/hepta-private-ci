//! Versioned production-control contracts for native inference execution.
//!
//! This module is deliberately authority-free: it verifies independently signed
//! admission, settlement and retirement evidence, but it owns no signing key and
//! cannot dispatch a provider.  Only the opaque verified wrappers returned here
//! may cross into the durable settlement writer.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use ed25519_dalek::Signature;
use ed25519_dalek::VerifyingKey;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

pub const INFERENCE_CONTROL_SCHEMA_VERSION: u32 = 1;
pub const MAX_SETTLEMENT_LIFETIME_MS: u64 = 15 * 60 * 1_000;
pub const MAX_RETIREMENT_LIFETIME_MS: u64 = 60 * 60 * 1_000;
const MAX_TRUST_KEYS: usize = 16;
const MAX_RETIREMENT_APPROVALS: usize = 16;
const MAX_TEXT_BYTES: usize = 512;
const MAX_REASON_BYTES: usize = 4_096;

pub type Digest32 = [u8; 32];

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ControlContractError {
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidManifest,
    InvalidQuotaLease,
    InvalidResourceLease,
    InvalidAdmission,
    InvalidTrust,
    InvalidSignature,
    Expired,
    NotYetValid,
    BindingMismatch(&'static str),
    Replay,
    Equivocation,
    NonMonotonicUsage,
    TerminalConflict,
    InvalidRetirement,
    InsufficientRetirementQuorum,
    DuplicateApproval,
    Encoding,
}

impl fmt::Display for ControlContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ControlContractError {}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionManifestV1 {
    pub schema_version: u32,
    pub provider_id: String,
    pub model_id: String,
    pub model_revision: String,
    pub model_sha256: Digest32,
    pub tokenizer_id: String,
    pub tokenizer_revision: String,
    pub tokenizer_sha256: Digest32,
    pub vocabulary_sha256: Digest32,
    pub normalization_policy_sha256: Digest32,
    pub template_id: String,
    pub template_revision: String,
    pub template_sha256: Digest32,
    pub runtime_abi: String,
    pub runtime_sha256: Digest32,
    pub adapter_abi: String,
    pub adapter_sha256: Digest32,
    pub execution_policy_sha256: Digest32,
}

impl ExecutionManifestV1 {
    pub fn validate(&self) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION {
            return Err(ControlContractError::InvalidManifest);
        }
        for (label, value) in [
            ("provider", self.provider_id.as_str()),
            ("model", self.model_id.as_str()),
            ("model revision", self.model_revision.as_str()),
            ("tokenizer", self.tokenizer_id.as_str()),
            ("tokenizer revision", self.tokenizer_revision.as_str()),
            ("template", self.template_id.as_str()),
            ("template revision", self.template_revision.as_str()),
            ("runtime ABI", self.runtime_abi.as_str()),
            ("adapter ABI", self.adapter_abi.as_str()),
        ] {
            validate_identity(value, label)?;
        }
        for (label, value) in [
            ("model", self.model_sha256),
            ("tokenizer", self.tokenizer_sha256),
            ("vocabulary", self.vocabulary_sha256),
            ("normalization policy", self.normalization_policy_sha256),
            ("template", self.template_sha256),
            ("runtime", self.runtime_sha256),
            ("adapter", self.adapter_sha256),
            ("execution policy", self.execution_policy_sha256),
        ] {
            validate_digest(value, label)?;
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Digest32, ControlContractError> {
        self.validate()?;
        domain_digest(
            b"hepta.inference.control.execution-manifest.v1\0",
            self,
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaLeaseV1 {
    pub schema_version: u32,
    pub lease_id: String,
    pub subject_id: String,
    pub authority_epoch: u64,
    pub policy_sha256: Digest32,
    pub reserved_requests: u64,
    pub reserved_input_tokens: u64,
    pub reserved_output_tokens: u64,
    pub reserved_cost_micros: u64,
    pub maximum_concurrency: u32,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl QuotaLeaseV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.authority_epoch == 0
            || self.reserved_requests == 0
            || self.reserved_output_tokens == 0
            || self.maximum_concurrency == 0
        {
            return Err(ControlContractError::InvalidQuotaLease);
        }
        validate_identity(&self.lease_id, "quota lease")?;
        validate_identity(&self.subject_id, "quota subject")?;
        validate_digest(self.policy_sha256, "quota policy")?;
        validate_window(
            self.not_before_unix_ms,
            self.expires_at_unix_ms,
            now_unix_ms,
        )?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceLeaseV1 {
    pub schema_version: u32,
    pub lease_id: String,
    pub resource_owner_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub provider_id: String,
    pub model_sha256: Digest32,
    pub device_class: String,
    pub device_instance_sha256: Digest32,
    pub reserved_memory_bytes: u64,
    pub reserved_compute_millis: u64,
    pub authority_epoch: u64,
    pub not_before_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl ResourceLeaseV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.worker_generation == 0
            || self.reserved_memory_bytes == 0
            || self.reserved_compute_millis == 0
            || self.authority_epoch == 0
        {
            return Err(ControlContractError::InvalidResourceLease);
        }
        for (label, value) in [
            ("resource lease", self.lease_id.as_str()),
            ("resource owner", self.resource_owner_id.as_str()),
            ("worker", self.worker_id.as_str()),
            ("provider", self.provider_id.as_str()),
            ("device class", self.device_class.as_str()),
        ] {
            validate_identity(value, label)?;
        }
        validate_digest(self.model_sha256, "resource model")?;
        validate_digest(self.device_instance_sha256, "device instance")?;
        validate_window(
            self.not_before_unix_ms,
            self.expires_at_unix_ms,
            now_unix_ms,
        )?;
        Ok(())
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AdmissionBundleV1 {
    pub schema_version: u32,
    pub request_id: String,
    pub principal_id: String,
    pub payload_sha256: Digest32,
    pub prompt_sha256: Digest32,
    pub execution_manifest: ExecutionManifestV1,
    pub quota_lease: QuotaLeaseV1,
    pub resource_lease: ResourceLeaseV1,
    pub final_use_witness_sha256: Digest32,
    pub deadline_unix_ms: u64,
}

impl AdmissionBundleV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.deadline_unix_ms <= now_unix_ms
        {
            return Err(ControlContractError::InvalidAdmission);
        }
        validate_identity(&self.request_id, "request")?;
        validate_identity(&self.principal_id, "principal")?;
        validate_digest(self.payload_sha256, "payload")?;
        validate_digest(self.prompt_sha256, "prompt")?;
        validate_digest(self.final_use_witness_sha256, "final-use witness")?;
        self.execution_manifest.validate()?;
        self.quota_lease.validate(now_unix_ms)?;
        self.resource_lease.validate(now_unix_ms)?;
        if self.quota_lease.subject_id != self.principal_id
            || self.resource_lease.provider_id != self.execution_manifest.provider_id
            || self.resource_lease.model_sha256 != self.execution_manifest.model_sha256
            || self.resource_lease.authority_epoch != self.quota_lease.authority_epoch
        {
            return Err(ControlContractError::InvalidAdmission);
        }
        Ok(())
    }

    pub fn digest(&self, now_unix_ms: u64) -> Result<Digest32, ControlContractError> {
        self.validate(now_unix_ms)?;
        domain_digest(b"hepta.inference.control.admission-bundle.v1\0", self)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SettlementTerminalV1 {
    Succeeded,
    Failed,
    Interrupted,
    Cancelled,
    TimedOut,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
pub enum OutputRetentionV1 {
    DigestOnly,
    EncryptedBlob {
        blob_id: String,
        ciphertext_sha256: Digest32,
        key_id: String,
        key_epoch: u64,
        delete_after_unix_ms: u64,
    },
}

impl OutputRetentionV1 {
    fn validate(&self, issued_at_unix_ms: u64) -> Result<(), ControlContractError> {
        match self {
            Self::DigestOnly => Ok(()),
            Self::EncryptedBlob {
                blob_id,
                ciphertext_sha256,
                key_id,
                key_epoch,
                delete_after_unix_ms,
            } => {
                validate_identity(blob_id, "encrypted output blob")?;
                validate_identity(key_id, "output key")?;
                validate_digest(*ciphertext_sha256, "output ciphertext")?;
                if *key_epoch == 0 || *delete_after_unix_ms <= issued_at_unix_ms {
                    return Err(ControlContractError::InvalidAdmission);
                }
                Ok(())
            }
        }
    }
}

/// Provider data before signature verification.  This value is never accepted
/// directly by the durable control owner.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct UntrustedProviderObservationV1 {
    pub request_id: String,
    pub dispatch_sha256: Digest32,
    pub provider_id: String,
    pub model_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_sequence: u64,
    pub terminal: SettlementTerminalV1,
    pub output_sha256: Option<Digest32>,
    pub observed_input_tokens: Option<u64>,
    pub observed_output_tokens: Option<u64>,
    pub observed_cost_micros: Option<u64>,
    pub observed_at_unix_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SettlementReceiptV1 {
    pub schema_version: u32,
    pub receipt_id: String,
    pub request_id: String,
    pub admission_sha256: Digest32,
    pub manifest_sha256: Digest32,
    pub dispatch_sha256: Digest32,
    pub provider_id: String,
    pub model_id: String,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_sequence: u64,
    pub terminal: SettlementTerminalV1,
    pub output_sha256: Option<Digest32>,
    pub output_retention: OutputRetentionV1,
    pub observed_input_tokens: Option<u64>,
    pub observed_output_tokens: Option<u64>,
    pub observed_cost_micros: Option<u64>,
    pub authority_epoch: u64,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl SettlementReceiptV1 {
    pub fn from_observation(
        receipt_id: String,
        admission_sha256: Digest32,
        manifest_sha256: Digest32,
        output_retention: OutputRetentionV1,
        authority_epoch: u64,
        expires_at_unix_ms: u64,
        observation: UntrustedProviderObservationV1,
    ) -> Self {
        Self {
            schema_version: INFERENCE_CONTROL_SCHEMA_VERSION,
            receipt_id,
            request_id: observation.request_id,
            admission_sha256,
            manifest_sha256,
            dispatch_sha256: observation.dispatch_sha256,
            provider_id: observation.provider_id,
            model_id: observation.model_id,
            thread_id: observation.thread_id,
            turn_id: observation.turn_id,
            provider_sequence: observation.provider_sequence,
            terminal: observation.terminal,
            output_sha256: observation.output_sha256,
            output_retention,
            observed_input_tokens: observation.observed_input_tokens,
            observed_output_tokens: observation.observed_output_tokens,
            observed_cost_micros: observation.observed_cost_micros,
            authority_epoch,
            issued_at_unix_ms: observation.observed_at_unix_ms,
            expires_at_unix_ms,
        }
    }

    pub fn signing_bytes(&self) -> Result<Vec<u8>, ControlContractError> {
        self.validate()?;
        let mut bytes = b"hepta.inference.control.settlement-receipt.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| ControlContractError::Encoding)?);
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<Digest32, ControlContractError> {
        self.validate()?;
        domain_digest(b"hepta.inference.control.settlement-receipt.v1\0", self)
    }

    fn validate(&self) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.provider_sequence == 0
            || self.authority_epoch == 0
            || self.issued_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.issued_at_unix_ms
            || self.expires_at_unix_ms - self.issued_at_unix_ms
                > MAX_SETTLEMENT_LIFETIME_MS
        {
            return Err(ControlContractError::InvalidAdmission);
        }
        for (label, value) in [
            ("settlement receipt", self.receipt_id.as_str()),
            ("request", self.request_id.as_str()),
            ("provider", self.provider_id.as_str()),
            ("model", self.model_id.as_str()),
            ("thread", self.thread_id.as_str()),
            ("turn", self.turn_id.as_str()),
        ] {
            validate_identity(value, label)?;
        }
        for (label, value) in [
            ("admission", self.admission_sha256),
            ("manifest", self.manifest_sha256),
            ("dispatch", self.dispatch_sha256),
        ] {
            validate_digest(value, label)?;
        }
        if let Some(output) = self.output_sha256 {
            validate_digest(output, "output")?;
        }
        if self.terminal == SettlementTerminalV1::Succeeded && self.output_sha256.is_none() {
            return Err(ControlContractError::InvalidAdmission);
        }
        self.output_retention.validate(self.issued_at_unix_ms)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedSettlementReceiptV1 {
    pub signer_key_id: String,
    pub receipt: SettlementReceiptV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RotatingTrustKeyV1 {
    pub key_id: String,
    pub verifying_key: Digest32,
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
}

#[derive(Clone)]
struct PinnedTrustKey {
    key_id: String,
    key: VerifyingKey,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct SettlementFrontier {
    provider_sequence: u64,
    receipt_sha256: Digest32,
    terminal: SettlementTerminalV1,
    observed_input_tokens: Option<u64>,
    observed_output_tokens: Option<u64>,
    observed_cost_micros: Option<u64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum VerificationDispositionV1 {
    Advanced,
    Idempotent,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedSettlementReceiptV1 {
    receipt: SettlementReceiptV1,
    receipt_sha256: Digest32,
    trust_key_id: String,
    disposition: VerificationDispositionV1,
}

impl VerifiedSettlementReceiptV1 {
    pub fn receipt(&self) -> &SettlementReceiptV1 {
        &self.receipt
    }

    pub const fn receipt_sha256(&self) -> Digest32 {
        self.receipt_sha256
    }

    pub fn trust_key_id(&self) -> &str {
        &self.trust_key_id
    }

    pub const fn disposition(&self) -> VerificationDispositionV1 {
        self.disposition
    }
}

pub struct SettlementVerifierV1 {
    keys: Vec<PinnedTrustKey>,
    frontier_by_request: BTreeMap<String, SettlementFrontier>,
}

impl fmt::Debug for SettlementVerifierV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("SettlementVerifierV1([PINNED TRUST])")
    }
}

impl SettlementVerifierV1 {
    pub fn new(keys: Vec<RotatingTrustKeyV1>) -> Result<Self, ControlContractError> {
        Ok(Self {
            keys: pin_keys(keys)?,
            frontier_by_request: BTreeMap::new(),
        })
    }

    pub fn verify(
        &mut self,
        signed: &SignedSettlementReceiptV1,
        expected_request_id: &str,
        expected_admission_sha256: Digest32,
        expected_manifest_sha256: Digest32,
        expected_dispatch_sha256: Digest32,
        now_unix_ms: u64,
    ) -> Result<VerifiedSettlementReceiptV1, ControlContractError> {
        let receipt = &signed.receipt;
        receipt.validate()?;
        if receipt.request_id != expected_request_id {
            return Err(ControlContractError::BindingMismatch("request"));
        }
        if receipt.admission_sha256 != expected_admission_sha256 {
            return Err(ControlContractError::BindingMismatch("admission"));
        }
        if receipt.manifest_sha256 != expected_manifest_sha256 {
            return Err(ControlContractError::BindingMismatch("manifest"));
        }
        if receipt.dispatch_sha256 != expected_dispatch_sha256 {
            return Err(ControlContractError::BindingMismatch("dispatch"));
        }
        if now_unix_ms < receipt.issued_at_unix_ms {
            return Err(ControlContractError::NotYetValid);
        }
        if now_unix_ms >= receipt.expires_at_unix_ms {
            return Err(ControlContractError::Expired);
        }
        let input = receipt.signing_bytes()?;
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| ControlContractError::InvalidSignature)?;
        let trust_key_id = verify_key(
            &self.keys,
            &signed.signer_key_id,
            receipt.authority_epoch,
            &input,
            &signature,
        )?
        .to_string();
        let receipt_sha256 = receipt.digest()?;
        let disposition = match self.frontier_by_request.get(&receipt.request_id) {
            None => VerificationDispositionV1::Advanced,
            Some(previous) if receipt.provider_sequence < previous.provider_sequence => {
                return Err(ControlContractError::Replay);
            }
            Some(previous) if receipt.provider_sequence == previous.provider_sequence => {
                if receipt_sha256 != previous.receipt_sha256 {
                    return Err(ControlContractError::Equivocation);
                }
                VerificationDispositionV1::Idempotent
            }
            Some(previous) => {
                validate_monotonic(previous, receipt)?;
                VerificationDispositionV1::Advanced
            }
        };
        if disposition == VerificationDispositionV1::Advanced {
            self.frontier_by_request.insert(
                receipt.request_id.clone(),
                SettlementFrontier {
                    provider_sequence: receipt.provider_sequence,
                    receipt_sha256,
                    terminal: receipt.terminal,
                    observed_input_tokens: receipt.observed_input_tokens,
                    observed_output_tokens: receipt.observed_output_tokens,
                    observed_cost_micros: receipt.observed_cost_micros,
                },
            );
        }
        Ok(VerifiedSettlementReceiptV1 {
            receipt: receipt.clone(),
            receipt_sha256,
            trust_key_id,
            disposition,
        })
    }
}

fn validate_monotonic(
    previous: &SettlementFrontier,
    next: &SettlementReceiptV1,
) -> Result<(), ControlContractError> {
    if previous.terminal != SettlementTerminalV1::Indeterminate
        && previous.terminal != next.terminal
    {
        return Err(ControlContractError::TerminalConflict);
    }
    for (before, after) in [
        (previous.observed_input_tokens, next.observed_input_tokens),
        (previous.observed_output_tokens, next.observed_output_tokens),
        (previous.observed_cost_micros, next.observed_cost_micros),
    ] {
        if before.is_some_and(|value| after.is_none_or(|candidate| candidate < value)) {
            return Err(ControlContractError::NonMonotonicUsage);
        }
    }
    Ok(())
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IndeterminateRetirementProposalV1 {
    pub schema_version: u32,
    pub proposal_id: String,
    pub request_id: String,
    pub admission_sha256: Digest32,
    pub manifest_sha256: Digest32,
    pub dispatch_sha256: Digest32,
    pub reason_code: String,
    pub reason: String,
    pub proposed_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
    pub required_approvals: u8,
    pub nonce: Digest32,
}

impl IndeterminateRetirementProposalV1 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.proposed_at_unix_ms == 0
            || self.expires_at_unix_ms <= self.proposed_at_unix_ms
            || self.expires_at_unix_ms - self.proposed_at_unix_ms
                > MAX_RETIREMENT_LIFETIME_MS
            || now_unix_ms < self.proposed_at_unix_ms
            || now_unix_ms >= self.expires_at_unix_ms
            || self.required_approvals < 2
            || usize::from(self.required_approvals) > MAX_RETIREMENT_APPROVALS
            || self.reason.is_empty()
            || self.reason.len() > MAX_REASON_BYTES
        {
            return Err(ControlContractError::InvalidRetirement);
        }
        for (label, value) in [
            ("retirement proposal", self.proposal_id.as_str()),
            ("request", self.request_id.as_str()),
            ("retirement reason code", self.reason_code.as_str()),
        ] {
            validate_identity(value, label)?;
        }
        for (label, value) in [
            ("admission", self.admission_sha256),
            ("manifest", self.manifest_sha256),
            ("dispatch", self.dispatch_sha256),
            ("retirement nonce", self.nonce),
        ] {
            validate_digest(value, label)?;
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Digest32, ControlContractError> {
        domain_digest(
            b"hepta.inference.control.indeterminate-retirement.v1\0",
            self,
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RetirementApprovalV1 {
    pub schema_version: u32,
    pub proposal_sha256: Digest32,
    pub approver_id: String,
    pub authority_epoch: u64,
    pub approved: bool,
    pub issued_at_unix_ms: u64,
}

impl RetirementApprovalV1 {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, ControlContractError> {
        if self.schema_version != INFERENCE_CONTROL_SCHEMA_VERSION
            || self.authority_epoch == 0
            || self.issued_at_unix_ms == 0
            || !self.approved
        {
            return Err(ControlContractError::InvalidRetirement);
        }
        validate_digest(self.proposal_sha256, "retirement proposal")?;
        validate_identity(&self.approver_id, "retirement approver")?;
        let mut bytes = b"hepta.inference.control.retirement-approval.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| ControlContractError::Encoding)?);
        Ok(bytes)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedRetirementApprovalV1 {
    pub signer_key_id: String,
    pub approval: RetirementApprovalV1,
    pub signature: Vec<u8>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedRetirementReceiptV1 {
    proposal: IndeterminateRetirementProposalV1,
    proposal_sha256: Digest32,
    approval_key_ids: Vec<String>,
    receipt_sha256: Digest32,
}

impl VerifiedRetirementReceiptV1 {
    pub fn proposal(&self) -> &IndeterminateRetirementProposalV1 {
        &self.proposal
    }

    pub const fn proposal_sha256(&self) -> Digest32 {
        self.proposal_sha256
    }

    pub fn approval_key_ids(&self) -> &[String] {
        &self.approval_key_ids
    }

    pub const fn receipt_sha256(&self) -> Digest32 {
        self.receipt_sha256
    }
}

pub struct RetirementVerifierV1 {
    keys: Vec<PinnedTrustKey>,
    consumed_proposals: BTreeSet<Digest32>,
}

impl fmt::Debug for RetirementVerifierV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("RetirementVerifierV1([PINNED QUORUM TRUST])")
    }
}

impl RetirementVerifierV1 {
    pub fn new(keys: Vec<RotatingTrustKeyV1>) -> Result<Self, ControlContractError> {
        Ok(Self {
            keys: pin_keys(keys)?,
            consumed_proposals: BTreeSet::new(),
        })
    }

    pub fn verify(
        &mut self,
        proposal: &IndeterminateRetirementProposalV1,
        approvals: &[SignedRetirementApprovalV1],
        expected_request_id: &str,
        expected_admission_sha256: Digest32,
        expected_manifest_sha256: Digest32,
        expected_dispatch_sha256: Digest32,
        now_unix_ms: u64,
    ) -> Result<VerifiedRetirementReceiptV1, ControlContractError> {
        proposal.validate(now_unix_ms)?;
        if proposal.request_id != expected_request_id
            || proposal.admission_sha256 != expected_admission_sha256
            || proposal.manifest_sha256 != expected_manifest_sha256
            || proposal.dispatch_sha256 != expected_dispatch_sha256
        {
            return Err(ControlContractError::BindingMismatch("retirement"));
        }
        let proposal_sha256 = proposal.digest()?;
        if self.consumed_proposals.contains(&proposal_sha256) {
            return Err(ControlContractError::Replay);
        }
        let mut approvers = BTreeSet::new();
        let mut key_ids = BTreeSet::new();
        for signed in approvals {
            if signed.approval.proposal_sha256 != proposal_sha256
                || signed.approval.issued_at_unix_ms < proposal.proposed_at_unix_ms
                || signed.approval.issued_at_unix_ms >= proposal.expires_at_unix_ms
            {
                return Err(ControlContractError::InvalidRetirement);
            }
            let input = signed.approval.signing_bytes()?;
            let signature = Signature::from_slice(&signed.signature)
                .map_err(|_| ControlContractError::InvalidSignature)?;
            let key_id = verify_key(
                &self.keys,
                &signed.signer_key_id,
                signed.approval.authority_epoch,
                &input,
                &signature,
            )?;
            if !approvers.insert(signed.approval.approver_id.clone())
                || !key_ids.insert(key_id.to_string())
            {
                return Err(ControlContractError::DuplicateApproval);
            }
        }
        if approvers.len() < usize::from(proposal.required_approvals) {
            return Err(ControlContractError::InsufficientRetirementQuorum);
        }
        let approval_key_ids: Vec<String> = key_ids.into_iter().collect();
        let receipt_sha256 = retirement_receipt_digest(proposal_sha256, &approval_key_ids);
        self.consumed_proposals.insert(proposal_sha256);
        Ok(VerifiedRetirementReceiptV1 {
            proposal: proposal.clone(),
            proposal_sha256,
            approval_key_ids,
            receipt_sha256,
        })
    }
}

fn pin_keys(keys: Vec<RotatingTrustKeyV1>) -> Result<Vec<PinnedTrustKey>, ControlContractError> {
    if keys.is_empty() || keys.len() > MAX_TRUST_KEYS {
        return Err(ControlContractError::InvalidTrust);
    }
    let mut ids = BTreeSet::new();
    let mut public_keys = BTreeSet::new();
    let mut pinned = Vec::with_capacity(keys.len());
    for candidate in keys {
        validate_identity(&candidate.key_id, "trust key")?;
        let key = VerifyingKey::from_bytes(&candidate.verifying_key)
            .map_err(|_| ControlContractError::InvalidTrust)?;
        if key.is_weak()
            || candidate.not_before_authority_epoch == 0
            || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
            || !ids.insert(candidate.key_id.clone())
            || !public_keys.insert(candidate.verifying_key)
        {
            return Err(ControlContractError::InvalidTrust);
        }
        pinned.push(PinnedTrustKey {
            key_id: candidate.key_id,
            key,
            not_before_authority_epoch: candidate.not_before_authority_epoch,
            not_after_authority_epoch: candidate.not_after_authority_epoch,
        });
    }
    Ok(pinned)
}

fn verify_key<'a>(
    keys: &'a [PinnedTrustKey],
    key_id: &str,
    authority_epoch: u64,
    input: &[u8],
    signature: &Signature,
) -> Result<&'a str, ControlContractError> {
    let candidate = keys
        .iter()
        .find(|candidate| candidate.key_id == key_id)
        .ok_or(ControlContractError::InvalidSignature)?;
    if authority_epoch < candidate.not_before_authority_epoch
        || authority_epoch > candidate.not_after_authority_epoch
        || candidate.key.verify_strict(input, signature).is_err()
    {
        return Err(ControlContractError::InvalidSignature);
    }
    Ok(&candidate.key_id)
}

fn retirement_receipt_digest(
    proposal_sha256: Digest32,
    approval_key_ids: &[String],
) -> Digest32 {
    let mut hasher = Sha256::new();
    hasher.update(b"hepta.inference.control.retirement-receipt.v1\0");
    hasher.update(proposal_sha256);
    for key_id in approval_key_ids {
        hasher.update((key_id.len() as u64).to_be_bytes());
        hasher.update(key_id.as_bytes());
    }
    hasher.finalize().into()
}

fn domain_digest<T: Serialize>(domain: &[u8], value: &T) -> Result<Digest32, ControlContractError> {
    let payload = serde_json::to_vec(value).map_err(|_| ControlContractError::Encoding)?;
    let mut hasher = Sha256::new();
    hasher.update((domain.len() as u64).to_be_bytes());
    hasher.update(domain);
    hasher.update((payload.len() as u64).to_be_bytes());
    hasher.update(payload);
    Ok(hasher.finalize().into())
}

fn validate_identity(value: &str, label: &'static str) -> Result<(), ControlContractError> {
    if value.is_empty()
        || value.len() > MAX_TEXT_BYTES
        || value.as_bytes().contains(&0)
        || value.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err(ControlContractError::InvalidIdentity(label));
    }
    Ok(())
}

fn validate_digest(value: Digest32, label: &'static str) -> Result<(), ControlContractError> {
    if value == [0; 32] {
        return Err(ControlContractError::InvalidDigest(label));
    }
    Ok(())
}

fn validate_window(
    not_before_unix_ms: u64,
    expires_at_unix_ms: u64,
    now_unix_ms: u64,
) -> Result<(), ControlContractError> {
    if not_before_unix_ms == 0 || expires_at_unix_ms <= not_before_unix_ms {
        return Err(ControlContractError::InvalidAdmission);
    }
    if now_unix_ms < not_before_unix_ms {
        return Err(ControlContractError::NotYetValid);
    }
    if now_unix_ms >= expires_at_unix_ms {
        return Err(ControlContractError::Expired);
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    use super::*;

    const NOW: u64 = 1_800_000_000_000;

    fn digest(byte: u8) -> Digest32 {
        [byte; 32]
    }

    fn signing_key(byte: u8) -> SigningKey {
        SigningKey::from_bytes(&[byte; 32])
    }

    fn trust(key_id: &str, key: &SigningKey) -> RotatingTrustKeyV1 {
        RotatingTrustKeyV1 {
            key_id: key_id.into(),
            verifying_key: key.verifying_key().to_bytes(),
            not_before_authority_epoch: 1,
            not_after_authority_epoch: 9,
        }
    }

    fn receipt(sequence: u64, terminal: SettlementTerminalV1, tokens: u64) -> SettlementReceiptV1 {
        SettlementReceiptV1 {
            schema_version: 1,
            receipt_id: format!("receipt-{sequence}"),
            request_id: "request-1".into(),
            admission_sha256: digest(1),
            manifest_sha256: digest(2),
            dispatch_sha256: digest(3),
            provider_id: "provider-1".into(),
            model_id: "model-1".into(),
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            provider_sequence: sequence,
            terminal,
            output_sha256: Some(digest(4)),
            output_retention: OutputRetentionV1::DigestOnly,
            observed_input_tokens: Some(10),
            observed_output_tokens: Some(tokens),
            observed_cost_micros: Some(100 + tokens),
            authority_epoch: 3,
            issued_at_unix_ms: NOW,
            expires_at_unix_ms: NOW + 60_000,
        }
    }

    fn signed_receipt(
        key_id: &str,
        key: &SigningKey,
        receipt: SettlementReceiptV1,
    ) -> SignedSettlementReceiptV1 {
        let signature = key.sign(&receipt.signing_bytes().expect("valid receipt"));
        SignedSettlementReceiptV1 {
            signer_key_id: key_id.into(),
            receipt,
            signature: signature.to_bytes().to_vec(),
        }
    }

    #[test]
    fn settlement_verifier_rejects_tampering_and_usage_regression() {
        let key = signing_key(7);
        let mut verifier = SettlementVerifierV1::new(vec![trust("settlement-a", &key)])
            .expect("trust");
        let first = signed_receipt(
            "settlement-a",
            &key,
            receipt(1, SettlementTerminalV1::Indeterminate, 20),
        );
        verifier
            .verify(&first, "request-1", digest(1), digest(2), digest(3), NOW + 1)
            .expect("first receipt");

        let regressed = signed_receipt(
            "settlement-a",
            &key,
            receipt(2, SettlementTerminalV1::Succeeded, 19),
        );
        assert_eq!(
            verifier.verify(
                &regressed,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                NOW + 1,
            ),
            Err(ControlContractError::NonMonotonicUsage)
        );

        let mut tampered = first.clone();
        tampered.receipt.dispatch_sha256 = digest(9);
        assert_eq!(
            verifier.verify(
                &tampered,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                NOW + 1,
            ),
            Err(ControlContractError::BindingMismatch("dispatch"))
        );
    }

    #[test]
    fn exact_settlement_retry_is_idempotent_but_equivocation_is_rejected() {
        let key = signing_key(8);
        let mut verifier = SettlementVerifierV1::new(vec![trust("settlement-a", &key)])
            .expect("trust");
        let signed = signed_receipt(
            "settlement-a",
            &key,
            receipt(4, SettlementTerminalV1::Succeeded, 24),
        );
        verifier
            .verify(&signed, "request-1", digest(1), digest(2), digest(3), NOW + 1)
            .expect("first");
        let retry = verifier
            .verify(&signed, "request-1", digest(1), digest(2), digest(3), NOW + 1)
            .expect("retry");
        assert_eq!(retry.disposition(), VerificationDispositionV1::Idempotent);

        let conflicting = signed_receipt(
            "settlement-a",
            &key,
            receipt(4, SettlementTerminalV1::Succeeded, 25),
        );
        assert_eq!(
            verifier.verify(
                &conflicting,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                NOW + 1,
            ),
            Err(ControlContractError::Equivocation)
        );
    }

    fn proposal() -> IndeterminateRetirementProposalV1 {
        IndeterminateRetirementProposalV1 {
            schema_version: 1,
            proposal_id: "retire-1".into(),
            request_id: "request-1".into(),
            admission_sha256: digest(1),
            manifest_sha256: digest(2),
            dispatch_sha256: digest(3),
            reason_code: "provider_evidence_unrecoverable".into(),
            reason: "Provider and adapter retention windows expired after audited reconciliation attempts".into(),
            proposed_at_unix_ms: NOW,
            expires_at_unix_ms: NOW + 60_000,
            required_approvals: 2,
            nonce: digest(5),
        }
    }

    fn approval(
        proposal_sha256: Digest32,
        approver_id: &str,
        key_id: &str,
        key: &SigningKey,
    ) -> SignedRetirementApprovalV1 {
        let approval = RetirementApprovalV1 {
            schema_version: 1,
            proposal_sha256,
            approver_id: approver_id.into(),
            authority_epoch: 3,
            approved: true,
            issued_at_unix_ms: NOW + 1,
        };
        let signature = key.sign(&approval.signing_bytes().expect("approval"));
        SignedRetirementApprovalV1 {
            signer_key_id: key_id.into(),
            approval,
            signature: signature.to_bytes().to_vec(),
        }
    }

    #[test]
    fn retirement_requires_distinct_cryptographic_quorum_and_is_single_use() {
        let key_a = signing_key(11);
        let key_b = signing_key(12);
        let mut verifier = RetirementVerifierV1::new(vec![
            trust("retirement-a", &key_a),
            trust("retirement-b", &key_b),
        ])
        .expect("trust");
        let proposal = proposal();
        let proposal_sha256 = proposal.digest().expect("proposal digest");
        let approvals = vec![
            approval(
                proposal_sha256,
                "operator-a",
                "retirement-a",
                &key_a,
            ),
            approval(
                proposal_sha256,
                "operator-b",
                "retirement-b",
                &key_b,
            ),
        ];
        let receipt = verifier
            .verify(
                &proposal,
                &approvals,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                NOW + 2,
            )
            .expect("quorum");
        assert_eq!(receipt.approval_key_ids().len(), 2);
        assert_eq!(
            verifier.verify(
                &proposal,
                &approvals,
                "request-1",
                digest(1),
                digest(2),
                digest(3),
                NOW + 2,
            ),
            Err(ControlContractError::Replay)
        );
    }

    #[test]
    fn admission_binds_exact_model_tokenizer_template_runtime_and_leases() {
        let manifest = ExecutionManifestV1 {
            schema_version: 1,
            provider_id: "provider-1".into(),
            model_id: "model-1".into(),
            model_revision: "r1".into(),
            model_sha256: digest(1),
            tokenizer_id: "tokenizer-1".into(),
            tokenizer_revision: "r1".into(),
            tokenizer_sha256: digest(2),
            vocabulary_sha256: digest(3),
            normalization_policy_sha256: digest(4),
            template_id: "template-1".into(),
            template_revision: "r1".into(),
            template_sha256: digest(5),
            runtime_abi: "runtime.v1".into(),
            runtime_sha256: digest(6),
            adapter_abi: "adapter.v1".into(),
            adapter_sha256: digest(7),
            execution_policy_sha256: digest(8),
        };
        let admission = AdmissionBundleV1 {
            schema_version: 1,
            request_id: "request-1".into(),
            principal_id: "principal-1".into(),
            payload_sha256: digest(9),
            prompt_sha256: digest(10),
            execution_manifest: manifest,
            quota_lease: QuotaLeaseV1 {
                schema_version: 1,
                lease_id: "quota-1".into(),
                subject_id: "principal-1".into(),
                authority_epoch: 3,
                policy_sha256: digest(11),
                reserved_requests: 1,
                reserved_input_tokens: 100,
                reserved_output_tokens: 100,
                reserved_cost_micros: 1_000,
                maximum_concurrency: 1,
                not_before_unix_ms: NOW - 1,
                expires_at_unix_ms: NOW + 60_000,
            },
            resource_lease: ResourceLeaseV1 {
                schema_version: 1,
                lease_id: "resource-1".into(),
                resource_owner_id: "fleet-1".into(),
                worker_id: "worker-1".into(),
                worker_generation: 4,
                provider_id: "provider-1".into(),
                model_sha256: digest(1),
                device_class: "gpu".into(),
                device_instance_sha256: digest(12),
                reserved_memory_bytes: 1_024,
                reserved_compute_millis: 10_000,
                authority_epoch: 3,
                not_before_unix_ms: NOW - 1,
                expires_at_unix_ms: NOW + 60_000,
            },
            final_use_witness_sha256: digest(13),
            deadline_unix_ms: NOW + 30_000,
        };
        assert_ne!(admission.digest(NOW).expect("admission"), [0; 32]);
    }
}
