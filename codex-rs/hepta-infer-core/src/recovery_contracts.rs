//! Post-effect recovery contracts whose freshness is independent from the
//! original dispatch lease.
//!
//! A dispatch lease may expire after an external effect starts. That expiry
//! prevents another effect, but it cannot make terminal truth unverifiable.
//! Recovery therefore re-verifies the historical signed execution bundle for
//! identity and requires a fresh, separately signed terminal receipt or a fresh
//! two-person retirement approval.

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

use crate::control_contracts::ControlSignature;
use crate::control_contracts::ExecutionAuthorityBundle;
use crate::control_contracts::OutputClassification;
use crate::control_contracts::OutputStorageMode;
use crate::control_contracts::ReconciledTerminalStatus;
use crate::control_contracts::SignedExecutionAuthorityBundle;
use crate::control_contracts::TrustKey;
use crate::control_contracts::TrustRole;

const SCHEMA_VERSION: u32 = 1;
const MAX_ID_BYTES: usize = 128;
const MAX_REASON_BYTES: usize = 4096;
const MAX_REFERENCE_BYTES: usize = 2048;
const MAX_LEASE_LIFETIME_MS: u64 = 24 * 60 * 60 * 1000;
const MAX_RECEIPT_LIFETIME_MS: u64 = 15 * 60 * 1000;
const MAX_RETIREMENT_LIFETIME_MS: u64 = 15 * 60 * 1000;
const MAX_OUTPUT_TTL_MS: u64 = 30 * 24 * 60 * 60 * 1000;
const MAX_TRUST_KEYS: usize = 64;

/// Historical execution identity, authenticated again for recovery without
/// asserting that its original dispatch leases are still live.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RecoveryExecutionPlan {
    request_id: String,
    principal_id: String,
    execution_authority_epoch: u64,
    bundle_digest: String,
    manifest_digest: String,
    quota_lease_digest: String,
    resource_lease_digest: String,
    output_policy_digest: String,
    execution_binding_digest: String,
    provider_id: String,
    model_id: String,
    model_digest: String,
    worker_id: String,
    worker_generation: u64,
    authenticated_keys: BTreeMap<TrustRole, String>,
}

impl RecoveryExecutionPlan {
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub fn principal_id(&self) -> &str {
        &self.principal_id
    }

    pub fn execution_authority_epoch(&self) -> u64 {
        self.execution_authority_epoch
    }

    pub fn bundle_digest(&self) -> &str {
        &self.bundle_digest
    }

    pub fn manifest_digest(&self) -> &str {
        &self.manifest_digest
    }

    pub fn quota_lease_digest(&self) -> &str {
        &self.quota_lease_digest
    }

    pub fn resource_lease_digest(&self) -> &str {
        &self.resource_lease_digest
    }

    pub fn output_policy_digest(&self) -> &str {
        &self.output_policy_digest
    }

    pub fn execution_binding_digest(&self) -> &str {
        &self.execution_binding_digest
    }

    pub fn provider_id(&self) -> &str {
        &self.provider_id
    }

    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    pub fn model_digest(&self) -> &str {
        &self.model_digest
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    pub fn worker_generation(&self) -> u64 {
        self.worker_generation
    }

    pub fn authenticated_keys(&self) -> &BTreeMap<TrustRole, String> {
        &self.authenticated_keys
    }
}

/// Re-verify the original four-authority bundle for identity after its dispatch
/// leases have expired. No new effect may be started from this capability.
pub fn verify_execution_plan_for_recovery(
    trust_keys: &[TrustKey],
    signed: &SignedExecutionAuthorityBundle,
) -> Result<RecoveryExecutionPlan, RecoveryContractError> {
    validate_trust_set(trust_keys)?;
    let bundle = &signed.bundle;
    validate_historical_bundle(bundle)?;
    if signed.signatures.len() < 4 || signed.signatures.len() > 16 {
        return Err(RecoveryContractError::SignatureQuorum);
    }
    let message = bundle
        .signing_bytes()
        .map_err(|_| RecoveryContractError::InvalidExecutionPlan)?;
    let required = [
        (
            TrustRole::ManifestAuthority,
            bundle.manifest.issuer_id.as_str(),
        ),
        (
            TrustRole::QuotaAuthority,
            bundle.quota_lease.authority_id.as_str(),
        ),
        (
            TrustRole::ResourceAuthority,
            bundle.resource_lease.authority_id.as_str(),
        ),
        (
            TrustRole::DataAuthority,
            bundle.output_policy.authority_id.as_str(),
        ),
    ];
    let mut authenticated_keys = BTreeMap::new();
    let mut used_keys = BTreeSet::new();
    let mut used_public_keys = BTreeSet::new();
    for (role, signer_id) in required {
        let candidate = signed
            .signatures
            .iter()
            .find(|candidate| {
                candidate.signer_id == signer_id
                    && trust_keys.iter().any(|key| {
                        key.key_id == candidate.key_id
                            && key.signer_id == signer_id
                            && key.role == role
                    })
            })
            .ok_or(RecoveryContractError::SignatureQuorum)?;
        let public_key = trust_keys
            .iter()
            .find(|key| key.key_id == candidate.key_id)
            .ok_or(RecoveryContractError::UnknownTrustKey)?
            .verifying_key;
        if !used_keys.insert(candidate.key_id.clone()) || !used_public_keys.insert(public_key) {
            return Err(RecoveryContractError::SignatureQuorum);
        }
        verify_signature(
            trust_keys,
            role,
            signer_id,
            bundle.manifest.authority_epoch,
            candidate,
            &message,
        )?;
        authenticated_keys.insert(role, candidate.key_id.clone());
    }

    let manifest_digest = digest_json(b"hepta.inference-control.manifest.v1\0", &bundle.manifest)?;
    let quota_lease_digest = digest_json(
        b"hepta.inference-control.quota-lease.v1\0",
        &bundle.quota_lease,
    )?;
    let resource_lease_digest = digest_json(
        b"hepta.inference-control.resource-lease.v1\0",
        &bundle.resource_lease,
    )?;
    let output_policy_digest = digest_json(
        b"hepta.inference-control.output-policy.v1\0",
        &bundle.output_policy,
    )?;
    let bundle_digest = bundle
        .digest()
        .map_err(|_| RecoveryContractError::InvalidExecutionPlan)?;
    let binding_payload = serde_json::to_vec(&(
        &bundle.request_id,
        &bundle.principal_id,
        bundle.manifest.authority_epoch,
        &manifest_digest,
        &quota_lease_digest,
        &resource_lease_digest,
        &output_policy_digest,
        &bundle.manifest.payload_digest,
    ))
    .map_err(|_| RecoveryContractError::InvalidExecutionPlan)?;
    let execution_binding_digest = digest_domain(
        b"hepta.inference-control.execution-binding.v1\0",
        &binding_payload,
    )?;

    Ok(RecoveryExecutionPlan {
        request_id: bundle.request_id.clone(),
        principal_id: bundle.principal_id.clone(),
        execution_authority_epoch: bundle.manifest.authority_epoch,
        bundle_digest,
        manifest_digest,
        quota_lease_digest,
        resource_lease_digest,
        output_policy_digest,
        execution_binding_digest,
        provider_id: bundle.manifest.provider_id.clone(),
        model_id: bundle.manifest.model_id.clone(),
        model_digest: bundle.manifest.model_digest.clone(),
        worker_id: bundle.resource_lease.worker_id.clone(),
        worker_generation: bundle.resource_lease.worker_generation,
        authenticated_keys,
    })
}

/// Fresh signed terminal and usage evidence for a historical execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryReconciliationReceipt {
    pub schema_version: u32,
    pub issuer_id: String,
    pub issuer_authority_epoch: u64,
    pub execution_authority_epoch: u64,
    pub request_id: String,
    pub principal_id: String,
    pub execution_binding_digest: String,
    pub dispatch_digest: String,
    pub thread_id: String,
    pub turn_id: String,
    pub provider_id: String,
    pub model_digest: String,
    pub terminal_sequence: u64,
    pub terminal_status: ReconciledTerminalStatus,
    #[serde(default)]
    pub output_digest: Option<String>,
    #[serde(default)]
    pub encrypted_output_reference: Option<String>,
    #[serde(default)]
    pub observed_output_tokens: Option<u64>,
    #[serde(default)]
    pub usage_microunits: Option<u64>,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl RecoveryReconciliationReceipt {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, RecoveryContractError> {
        signing_bytes(
            b"hepta.inference-control.recovery-reconciliation.v1\0",
            self,
        )
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedRecoveryReconciliationReceipt {
    pub receipt: RecoveryReconciliationReceipt,
    pub signature: ControlSignature,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedRecoveryReconciliationReceipt {
    receipt: RecoveryReconciliationReceipt,
    receipt_digest: String,
    authenticated_key_id: String,
}

impl VerifiedRecoveryReconciliationReceipt {
    pub fn receipt(&self) -> &RecoveryReconciliationReceipt {
        &self.receipt
    }

    pub fn receipt_digest(&self) -> &str {
        &self.receipt_digest
    }

    pub fn authenticated_key_id(&self) -> &str {
        &self.authenticated_key_id
    }

    /// Recheck the fresh signed window independently from the dispatch lease.
    pub fn assert_valid_at(&self, now_unix_ms: u64) -> Result<(), RecoveryContractError> {
        validate_fresh_window(
            now_unix_ms,
            self.receipt.issued_at_unix_ms,
            self.receipt.expires_at_unix_ms,
            MAX_RECEIPT_LIFETIME_MS,
        )
    }
}

pub fn verify_recovery_reconciliation_receipt(
    now_unix_ms: u64,
    trust_keys: &[TrustKey],
    plan: &RecoveryExecutionPlan,
    signed: &SignedRecoveryReconciliationReceipt,
) -> Result<VerifiedRecoveryReconciliationReceipt, RecoveryContractError> {
    validate_trust_set(trust_keys)?;
    let receipt = &signed.receipt;
    validate_reconciliation(now_unix_ms, receipt)?;
    if receipt.request_id != plan.request_id
        || receipt.principal_id != plan.principal_id
        || receipt.execution_authority_epoch != plan.execution_authority_epoch
        || receipt.execution_binding_digest != plan.execution_binding_digest
        || receipt.provider_id != plan.provider_id
        || receipt.model_digest != plan.model_digest
    {
        return Err(RecoveryContractError::BindingMismatch);
    }
    let message = receipt.signing_bytes()?;
    verify_signature(
        trust_keys,
        TrustRole::ReconciliationIssuer,
        &receipt.issuer_id,
        receipt.issuer_authority_epoch,
        &signed.signature,
        &message,
    )?;
    let receipt_digest = digest_json(
        b"hepta.inference-control.recovery-reconciliation-digest.v1\0",
        receipt,
    )?;
    Ok(VerifiedRecoveryReconciliationReceipt {
        receipt: receipt.clone(),
        receipt_digest,
        authenticated_key_id: signed.signature.key_id.clone(),
    })
}

/// Fresh two-person retirement approval for an execution whose terminal state
/// cannot be recovered independently.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RecoveryIndeterminateRetirement {
    pub schema_version: u32,
    pub operator_authority_epoch: u64,
    pub execution_authority_epoch: u64,
    pub request_id: String,
    pub principal_id: String,
    pub execution_binding_digest: String,
    pub dispatch_digest: String,
    pub record_revision: u64,
    pub reason_code: String,
    pub reason: String,
    pub issued_at_unix_ms: u64,
    pub expires_at_unix_ms: u64,
}

impl RecoveryIndeterminateRetirement {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, RecoveryContractError> {
        signing_bytes(b"hepta.inference-control.recovery-retirement.v1\0", self)
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedRecoveryIndeterminateRetirement {
    pub retirement: RecoveryIndeterminateRetirement,
    pub approvals: Vec<ControlSignature>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedRecoveryRetirement {
    retirement: RecoveryIndeterminateRetirement,
    retirement_digest: String,
    operator_ids: [String; 2],
    key_ids: [String; 2],
    key_fingerprints: [String; 2],
}

impl VerifiedRecoveryRetirement {
    pub fn retirement(&self) -> &RecoveryIndeterminateRetirement {
        &self.retirement
    }

    pub fn retirement_digest(&self) -> &str {
        &self.retirement_digest
    }

    pub fn operator_ids(&self) -> &[String; 2] {
        &self.operator_ids
    }

    pub fn key_ids(&self) -> &[String; 2] {
        &self.key_ids
    }

    /// Domain-separated fingerprints of the two independently verified public keys.
    pub fn key_fingerprints(&self) -> &[String; 2] {
        &self.key_fingerprints
    }

    /// Recheck the fresh signed approval window when the durable owner applies it.
    pub fn assert_valid_at(&self, now_unix_ms: u64) -> Result<(), RecoveryContractError> {
        validate_fresh_window(
            now_unix_ms,
            self.retirement.issued_at_unix_ms,
            self.retirement.expires_at_unix_ms,
            MAX_RETIREMENT_LIFETIME_MS,
        )
    }
}

pub fn verify_recovery_retirement(
    now_unix_ms: u64,
    trust_keys: &[TrustKey],
    plan: &RecoveryExecutionPlan,
    signed: &SignedRecoveryIndeterminateRetirement,
) -> Result<VerifiedRecoveryRetirement, RecoveryContractError> {
    validate_trust_set(trust_keys)?;
    let retirement = &signed.retirement;
    validate_retirement(now_unix_ms, retirement)?;
    if retirement.request_id != plan.request_id
        || retirement.principal_id != plan.principal_id
        || retirement.execution_authority_epoch != plan.execution_authority_epoch
        || retirement.execution_binding_digest != plan.execution_binding_digest
    {
        return Err(RecoveryContractError::BindingMismatch);
    }
    if signed.approvals.len() != 2 {
        return Err(RecoveryContractError::SignatureQuorum);
    }
    let first = &signed.approvals[0];
    let second = &signed.approvals[1];
    if first.key_id == second.key_id || first.signer_id == second.signer_id {
        return Err(RecoveryContractError::SignatureQuorum);
    }
    let first_key = trust_keys
        .iter()
        .find(|key| key.key_id == first.key_id)
        .ok_or(RecoveryContractError::UnknownTrustKey)?;
    let second_key = trust_keys
        .iter()
        .find(|key| key.key_id == second.key_id)
        .ok_or(RecoveryContractError::UnknownTrustKey)?;
    if first_key.verifying_key == second_key.verifying_key {
        return Err(RecoveryContractError::SignatureQuorum);
    }
    let message = retirement.signing_bytes()?;
    verify_signature(
        trust_keys,
        TrustRole::RetirementOperator,
        &first.signer_id,
        retirement.operator_authority_epoch,
        first,
        &message,
    )?;
    verify_signature(
        trust_keys,
        TrustRole::RetirementOperator,
        &second.signer_id,
        retirement.operator_authority_epoch,
        second,
        &message,
    )?;
    let retirement_digest = digest_json(
        b"hepta.inference-control.recovery-retirement-digest.v1\0",
        retirement,
    )?;
    Ok(VerifiedRecoveryRetirement {
        retirement: retirement.clone(),
        retirement_digest,
        operator_ids: [first.signer_id.clone(), second.signer_id.clone()],
        key_ids: [first.key_id.clone(), second.key_id.clone()],
        key_fingerprints: [
            digest_domain(
                b"hepta.inference-control.retirement-verifying-key.v1\0",
                &first_key.verifying_key,
            )?,
            digest_domain(
                b"hepta.inference-control.retirement-verifying-key.v1\0",
                &second_key.verifying_key,
            )?,
        ],
    })
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RecoveryContractError {
    InvalidTrust,
    UnknownTrustKey,
    InvalidSignature,
    SignatureQuorum,
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidExecutionPlan,
    InvalidReceipt,
    InvalidRetirement,
    BindingMismatch,
    NotYetValid,
    Expired,
    CapacityExceeded,
}

impl fmt::Display for RecoveryContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RecoveryContractError {}

fn validate_historical_bundle(
    bundle: &ExecutionAuthorityBundle,
) -> Result<(), RecoveryContractError> {
    if bundle.schema_version != SCHEMA_VERSION
        || bundle.manifest.schema_version != SCHEMA_VERSION
        || bundle.quota_lease.schema_version != SCHEMA_VERSION
        || bundle.resource_lease.schema_version != SCHEMA_VERSION
        || bundle.output_policy.schema_version != SCHEMA_VERSION
    {
        return Err(RecoveryContractError::InvalidExecutionPlan);
    }
    validate_id(&bundle.request_id, "request")?;
    validate_id(&bundle.principal_id, "principal")?;
    for (value, field) in [
        (&bundle.manifest.manifest_id, "manifest"),
        (&bundle.manifest.issuer_id, "manifest issuer"),
        (&bundle.manifest.provider_id, "provider"),
        (&bundle.manifest.model_id, "model"),
        (&bundle.manifest.model_revision, "model revision"),
        (&bundle.manifest.tokenizer_id, "tokenizer"),
        (&bundle.manifest.tokenizer_version, "tokenizer version"),
        (&bundle.manifest.template_id, "template"),
        (&bundle.manifest.runtime_abi, "runtime ABI"),
        (&bundle.manifest.adapter_abi, "adapter ABI"),
        (&bundle.quota_lease.lease_id, "quota lease"),
        (&bundle.quota_lease.authority_id, "quota authority"),
        (&bundle.quota_lease.request_id, "quota request"),
        (&bundle.quota_lease.principal_id, "quota principal"),
        (&bundle.resource_lease.lease_id, "resource lease"),
        (&bundle.resource_lease.authority_id, "resource authority"),
        (&bundle.resource_lease.request_id, "resource request"),
        (&bundle.resource_lease.worker_id, "worker"),
        (&bundle.output_policy.policy_id, "output policy"),
        (&bundle.output_policy.authority_id, "data authority"),
    ] {
        validate_id(value, field)?;
    }
    for (value, field) in [
        (&bundle.manifest.model_digest, "model"),
        (&bundle.manifest.tokenizer_digest, "tokenizer"),
        (&bundle.manifest.template_digest, "template"),
        (&bundle.manifest.runtime_digest, "runtime"),
        (&bundle.manifest.adapter_digest, "adapter"),
        (&bundle.manifest.payload_digest, "payload"),
        (&bundle.manifest.policy_digest, "policy"),
        (&bundle.quota_lease.manifest_digest, "quota manifest"),
        (&bundle.resource_lease.manifest_digest, "resource manifest"),
        (
            &bundle.resource_lease.accelerator_profile_digest,
            "accelerator profile",
        ),
    ] {
        validate_digest(value, field)?;
    }
    validate_historical_window(
        bundle.quota_lease.valid_from_unix_ms,
        bundle.quota_lease.valid_until_unix_ms,
        MAX_LEASE_LIFETIME_MS,
    )?;
    validate_historical_window(
        bundle.resource_lease.valid_from_unix_ms,
        bundle.resource_lease.valid_until_unix_ms,
        MAX_LEASE_LIFETIME_MS,
    )?;
    if bundle.manifest.authority_epoch == 0
        || bundle.quota_lease.authority_epoch != bundle.manifest.authority_epoch
        || bundle.resource_lease.authority_epoch != bundle.manifest.authority_epoch
        || bundle.output_policy.authority_epoch != bundle.manifest.authority_epoch
        || bundle.request_id != bundle.quota_lease.request_id
        || bundle.request_id != bundle.resource_lease.request_id
        || bundle.principal_id != bundle.quota_lease.principal_id
        || bundle.quota_lease.maximum_input_tokens == 0
        || bundle.quota_lease.maximum_output_tokens == 0
        || bundle.quota_lease.maximum_cost_microunits == 0
        || bundle.resource_lease.worker_generation == 0
        || bundle.resource_lease.cpu_millis == 0
        || bundle.resource_lease.memory_bytes == 0
        || bundle.output_policy.maximum_retention_ms == 0
        || bundle.output_policy.maximum_retention_ms > MAX_OUTPUT_TTL_MS
        || bundle.output_policy.delete_after_unix_ms == 0
    {
        return Err(RecoveryContractError::InvalidExecutionPlan);
    }
    match bundle.output_policy.storage_mode {
        OutputStorageMode::DigestOnly => {
            if bundle.output_policy.encryption_key_id.is_some()
                || bundle.output_policy.encrypted_store_namespace.is_some()
            {
                return Err(RecoveryContractError::InvalidExecutionPlan);
            }
        }
        OutputStorageMode::ExternalEncrypted => {
            validate_id(
                bundle
                    .output_policy
                    .encryption_key_id
                    .as_deref()
                    .ok_or(RecoveryContractError::InvalidExecutionPlan)?,
                "encryption key",
            )?;
            validate_id(
                bundle
                    .output_policy
                    .encrypted_store_namespace
                    .as_deref()
                    .ok_or(RecoveryContractError::InvalidExecutionPlan)?,
                "encrypted namespace",
            )?;
        }
    }
    if matches!(
        bundle.output_policy.classification,
        OutputClassification::Confidential | OutputClassification::Restricted
    ) && bundle.output_policy.storage_mode != OutputStorageMode::ExternalEncrypted
    {
        return Err(RecoveryContractError::InvalidExecutionPlan);
    }
    let manifest_digest = digest_json(b"hepta.inference-control.manifest.v1\0", &bundle.manifest)?;
    if bundle.quota_lease.manifest_digest != manifest_digest
        || bundle.resource_lease.manifest_digest != manifest_digest
    {
        return Err(RecoveryContractError::BindingMismatch);
    }
    Ok(())
}

fn validate_reconciliation(
    now_unix_ms: u64,
    receipt: &RecoveryReconciliationReceipt,
) -> Result<(), RecoveryContractError> {
    if receipt.schema_version != SCHEMA_VERSION
        || receipt.issuer_authority_epoch == 0
        || receipt.execution_authority_epoch == 0
        || receipt.terminal_sequence == 0
    {
        return Err(RecoveryContractError::InvalidReceipt);
    }
    for (value, field) in [
        (&receipt.issuer_id, "reconciliation issuer"),
        (&receipt.request_id, "request"),
        (&receipt.principal_id, "principal"),
        (&receipt.thread_id, "thread"),
        (&receipt.turn_id, "turn"),
        (&receipt.provider_id, "provider"),
    ] {
        validate_id(value, field)?;
    }
    for (value, field) in [
        (&receipt.execution_binding_digest, "execution binding"),
        (&receipt.dispatch_digest, "dispatch"),
        (&receipt.model_digest, "model"),
    ] {
        validate_digest(value, field)?;
    }
    validate_fresh_window(
        now_unix_ms,
        receipt.issued_at_unix_ms,
        receipt.expires_at_unix_ms,
        MAX_RECEIPT_LIFETIME_MS,
    )?;
    if receipt.terminal_status == ReconciledTerminalStatus::Completed
        && receipt.output_digest.is_none()
    {
        return Err(RecoveryContractError::InvalidReceipt);
    }
    if let Some(digest) = &receipt.output_digest {
        validate_digest(digest, "output")?;
    }
    if let Some(reference) = &receipt.encrypted_output_reference {
        validate_reference(reference)?;
    }
    Ok(())
}

fn validate_retirement(
    now_unix_ms: u64,
    retirement: &RecoveryIndeterminateRetirement,
) -> Result<(), RecoveryContractError> {
    if retirement.schema_version != SCHEMA_VERSION
        || retirement.operator_authority_epoch == 0
        || retirement.execution_authority_epoch == 0
        || retirement.record_revision == 0
        || retirement.reason.is_empty()
        || retirement.reason.len() > MAX_REASON_BYTES
    {
        return Err(RecoveryContractError::InvalidRetirement);
    }
    for (value, field) in [
        (&retirement.request_id, "request"),
        (&retirement.principal_id, "principal"),
        (&retirement.reason_code, "retirement reason code"),
    ] {
        validate_id(value, field)?;
    }
    for (value, field) in [
        (&retirement.execution_binding_digest, "execution binding"),
        (&retirement.dispatch_digest, "dispatch"),
    ] {
        validate_digest(value, field)?;
    }
    validate_fresh_window(
        now_unix_ms,
        retirement.issued_at_unix_ms,
        retirement.expires_at_unix_ms,
        MAX_RETIREMENT_LIFETIME_MS,
    )
}

fn validate_trust_set(trust_keys: &[TrustKey]) -> Result<(), RecoveryContractError> {
    if trust_keys.is_empty() || trust_keys.len() > MAX_TRUST_KEYS {
        return Err(RecoveryContractError::InvalidTrust);
    }
    let mut ids = BTreeSet::new();
    let mut bindings = BTreeSet::new();
    for key in trust_keys {
        validate_id(&key.key_id, "trust key")?;
        validate_id(&key.signer_id, "trust signer")?;
        if !ids.insert(key.key_id.clone())
            || !bindings.insert((key.verifying_key, key.signer_id.clone(), key.role))
            || key.not_before_authority_epoch == 0
            || key.not_after_authority_epoch < key.not_before_authority_epoch
            || key
                .revoked_at_authority_epoch
                .is_some_and(|epoch| epoch < key.not_before_authority_epoch)
        {
            return Err(RecoveryContractError::InvalidTrust);
        }
        let verifying_key = VerifyingKey::from_bytes(&key.verifying_key)
            .map_err(|_| RecoveryContractError::InvalidTrust)?;
        if verifying_key.is_weak() {
            return Err(RecoveryContractError::InvalidTrust);
        }
    }
    Ok(())
}

fn verify_signature(
    trust_keys: &[TrustKey],
    expected_role: TrustRole,
    expected_signer_id: &str,
    authority_epoch: u64,
    signed: &ControlSignature,
    message: &[u8],
) -> Result<(), RecoveryContractError> {
    if signed.signer_id != expected_signer_id {
        return Err(RecoveryContractError::BindingMismatch);
    }
    let key = trust_keys
        .iter()
        .find(|key| key.key_id == signed.key_id)
        .ok_or(RecoveryContractError::UnknownTrustKey)?;
    if key.signer_id != signed.signer_id
        || key.role != expected_role
        || authority_epoch < key.not_before_authority_epoch
        || authority_epoch > key.not_after_authority_epoch
        || key
            .revoked_at_authority_epoch
            .is_some_and(|revoked| authority_epoch >= revoked)
    {
        return Err(RecoveryContractError::InvalidTrust);
    }
    let verifying_key = VerifyingKey::from_bytes(&key.verifying_key)
        .map_err(|_| RecoveryContractError::InvalidTrust)?;
    let signature = Signature::from_slice(&signed.signature)
        .map_err(|_| RecoveryContractError::InvalidSignature)?;
    verifying_key
        .verify_strict(message, &signature)
        .map_err(|_| RecoveryContractError::InvalidSignature)
}

fn validate_historical_window(
    not_before_unix_ms: u64,
    not_after_unix_ms: u64,
    maximum_lifetime_ms: u64,
) -> Result<(), RecoveryContractError> {
    if not_before_unix_ms == 0
        || not_after_unix_ms <= not_before_unix_ms
        || not_after_unix_ms - not_before_unix_ms > maximum_lifetime_ms
    {
        return Err(RecoveryContractError::InvalidExecutionPlan);
    }
    Ok(())
}

fn validate_fresh_window(
    now_unix_ms: u64,
    not_before_unix_ms: u64,
    not_after_unix_ms: u64,
    maximum_lifetime_ms: u64,
) -> Result<(), RecoveryContractError> {
    if not_before_unix_ms == 0
        || not_after_unix_ms <= not_before_unix_ms
        || not_after_unix_ms - not_before_unix_ms > maximum_lifetime_ms
    {
        return Err(RecoveryContractError::Expired);
    }
    if now_unix_ms < not_before_unix_ms {
        return Err(RecoveryContractError::NotYetValid);
    }
    if now_unix_ms >= not_after_unix_ms {
        return Err(RecoveryContractError::Expired);
    }
    Ok(())
}

fn validate_id(value: &str, field: &'static str) -> Result<(), RecoveryContractError> {
    if value.is_empty()
        || value.len() > MAX_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(RecoveryContractError::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), RecoveryContractError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(RecoveryContractError::InvalidDigest(field));
    }
    Ok(())
}

fn validate_reference(value: &str) -> Result<(), RecoveryContractError> {
    if value.is_empty()
        || value.len() > MAX_REFERENCE_BYTES
        || value.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err(RecoveryContractError::InvalidReceipt);
    }
    Ok(())
}

fn signing_bytes<T: Serialize>(domain: &[u8], value: &T) -> Result<Vec<u8>, RecoveryContractError> {
    let payload = serde_json::to_vec(value).map_err(|_| RecoveryContractError::InvalidReceipt)?;
    if payload.len() > 8 * 1024 * 1024 {
        return Err(RecoveryContractError::CapacityExceeded);
    }
    let mut bytes = domain.to_vec();
    bytes.extend(payload);
    Ok(bytes)
}

fn digest_json<T: Serialize>(domain: &[u8], value: &T) -> Result<String, RecoveryContractError> {
    let payload =
        serde_json::to_vec(value).map_err(|_| RecoveryContractError::InvalidExecutionPlan)?;
    digest_domain(domain, &payload)
}

fn digest_domain(domain: &[u8], payload: &[u8]) -> Result<String, RecoveryContractError> {
    if payload.len() > 8 * 1024 * 1024 {
        return Err(RecoveryContractError::CapacityExceeded);
    }
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((payload.len() as u64).to_be_bytes());
    hash.update(payload);
    Ok(format!("{:x}", hash.finalize()))
}
