//! Exact authority, resource, reconciliation, retirement, and output-retention contracts.
//!
//! These types are intentionally independent from provider adapters. A host may
//! parse untrusted JSON into the signed envelopes, but only the verifier-owned
//! `VerifiedExecutionPlan`, `VerifiedReconciliationReceipt`, and
//! `VerifiedRetirement` capabilities may cross into the durable writer.

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

const EXECUTION_SCHEMA_VERSION: u32 = 1;
const RECONCILIATION_SCHEMA_VERSION: u32 = 1;
const RETIREMENT_SCHEMA_VERSION: u32 = 1;
const MAX_TRUST_KEYS: usize = 64;
const MAX_SIGNATURES: usize = 16;
const MAX_ID_BYTES: usize = 128;
const MAX_REASON_BYTES: usize = 4096;
const MAX_REFERENCE_BYTES: usize = 2048;
const MAX_LEASE_LIFETIME_MS: u64 = 24 * 60 * 60 * 1000;
const MAX_RECEIPT_LIFETIME_MS: u64 = 15 * 60 * 1000;
const MAX_RETIREMENT_LIFETIME_MS: u64 = 15 * 60 * 1000;
const MAX_OUTPUT_TTL_MS: u64 = 30 * 24 * 60 * 60 * 1000;

/// A trust role cannot be substituted for another role even when the same
/// public key was accidentally provisioned in both places.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TrustRole {
    ManifestAuthority,
    QuotaAuthority,
    ResourceAuthority,
    DataAuthority,
    ReconciliationIssuer,
    RetirementOperator,
}

/// One rotation-bounded Ed25519 public key.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct TrustKey {
    pub key_id: String,
    pub signer_id: String,
    pub role: TrustRole,
    pub verifying_key: [u8; 32],
    pub not_before_authority_epoch: u64,
    pub not_after_authority_epoch: u64,
    #[serde(default)]
    pub revoked_at_authority_epoch: Option<u64>,
}

#[derive(Clone)]
struct PinnedTrustKey {
    key_id: String,
    signer_id: String,
    role: TrustRole,
    verifying_key: VerifyingKey,
    not_before_authority_epoch: u64,
    not_after_authority_epoch: u64,
    revoked_at_authority_epoch: Option<u64>,
}

/// Rotation-aware pinned trust store. It contains public keys only.
#[derive(Clone)]
pub struct ControlTrustStore {
    keys: BTreeMap<String, PinnedTrustKey>,
}

impl fmt::Debug for ControlTrustStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ControlTrustStore([PINNED INFERENCE-CONTROL TRUST])")
    }
}

impl ControlTrustStore {
    pub fn new(keys: Vec<TrustKey>) -> Result<Self, ContractError> {
        if keys.is_empty() || keys.len() > MAX_TRUST_KEYS {
            return Err(ContractError::InvalidTrust);
        }
        let mut pinned = BTreeMap::new();
        let mut public_bindings = BTreeSet::new();
        for candidate in keys {
            validate_id(&candidate.key_id, "trust key")?;
            validate_id(&candidate.signer_id, "trust signer")?;
            if candidate.not_before_authority_epoch == 0
                || candidate.not_after_authority_epoch < candidate.not_before_authority_epoch
                || candidate
                    .revoked_at_authority_epoch
                    .is_some_and(|epoch| epoch < candidate.not_before_authority_epoch)
            {
                return Err(ContractError::InvalidTrust);
            }
            let verifying_key = VerifyingKey::from_bytes(&candidate.verifying_key)
                .map_err(|_| ContractError::InvalidTrust)?;
            if verifying_key.is_weak()
                || !public_bindings.insert((
                    candidate.verifying_key,
                    candidate.signer_id.clone(),
                    candidate.role,
                ))
            {
                return Err(ContractError::InvalidTrust);
            }
            let key_id = candidate.key_id.clone();
            if pinned
                .insert(
                    key_id.clone(),
                    PinnedTrustKey {
                        key_id,
                        signer_id: candidate.signer_id,
                        role: candidate.role,
                        verifying_key,
                        not_before_authority_epoch: candidate.not_before_authority_epoch,
                        not_after_authority_epoch: candidate.not_after_authority_epoch,
                        revoked_at_authority_epoch: candidate.revoked_at_authority_epoch,
                    },
                )
                .is_some()
            {
                return Err(ContractError::InvalidTrust);
            }
        }
        Ok(Self { keys: pinned })
    }

    fn verify(
        &self,
        expected_role: TrustRole,
        expected_signer_id: &str,
        authority_epoch: u64,
        signed: &ControlSignature,
        message: &[u8],
    ) -> Result<(), ContractError> {
        if signed.signer_id != expected_signer_id {
            return Err(ContractError::SignerMismatch);
        }
        let key = self
            .keys
            .get(&signed.key_id)
            .ok_or(ContractError::UnknownTrustKey)?;
        if key.key_id != signed.key_id
            || key.signer_id != signed.signer_id
            || key.role != expected_role
            || authority_epoch < key.not_before_authority_epoch
            || authority_epoch > key.not_after_authority_epoch
            || key
                .revoked_at_authority_epoch
                .is_some_and(|revoked| authority_epoch >= revoked)
        {
            return Err(ContractError::InvalidTrust);
        }
        let signature = Signature::from_slice(&signed.signature)
            .map_err(|_| ContractError::InvalidSignature)?;
        key.verifying_key
            .verify_strict(message, &signature)
            .map_err(|_| ContractError::InvalidSignature)
    }
}

/// Detached control-plane signature.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ControlSignature {
    pub key_id: String,
    pub signer_id: String,
    pub signature: Vec<u8>,
}

/// Exact model and runtime identity. A mutable model name is not sufficient.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionManifest {
    pub schema_version: u32,
    pub manifest_id: String,
    pub issuer_id: String,
    pub authority_epoch: u64,
    pub provider_id: String,
    pub model_id: String,
    pub model_revision: String,
    pub model_digest: String,
    pub tokenizer_id: String,
    pub tokenizer_version: String,
    pub tokenizer_digest: String,
    pub template_id: String,
    pub template_digest: String,
    pub runtime_abi: String,
    pub runtime_digest: String,
    pub adapter_abi: String,
    pub adapter_digest: String,
    pub payload_digest: String,
    pub policy_digest: String,
}

/// Economically meaningful reservation. Values are upper bounds, not observed
/// provider billing claims.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaLease {
    pub schema_version: u32,
    pub lease_id: String,
    pub authority_id: String,
    pub authority_epoch: u64,
    pub request_id: String,
    pub principal_id: String,
    pub manifest_digest: String,
    pub maximum_input_tokens: u64,
    pub maximum_output_tokens: u64,
    pub maximum_cost_microunits: u64,
    pub valid_from_unix_ms: u64,
    pub valid_until_unix_ms: u64,
}

/// Exact host capacity reservation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResourceLease {
    pub schema_version: u32,
    pub lease_id: String,
    pub authority_id: String,
    pub authority_epoch: u64,
    pub request_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub manifest_digest: String,
    pub cpu_millis: u64,
    pub memory_bytes: u64,
    pub accelerator_count: u32,
    pub accelerator_profile_digest: String,
    pub valid_from_unix_ms: u64,
    pub valid_until_unix_ms: u64,
}

/// Data sensitivity declared before execution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputClassification {
    Public,
    Internal,
    Confidential,
    Restricted,
}

/// The active journal never stores raw model output on the production path.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum OutputStorageMode {
    DigestOnly,
    ExternalEncrypted,
}

/// Output retention and deletion authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct OutputDataPolicy {
    pub schema_version: u32,
    pub policy_id: String,
    pub authority_id: String,
    pub authority_epoch: u64,
    pub classification: OutputClassification,
    pub storage_mode: OutputStorageMode,
    pub maximum_retention_ms: u64,
    pub delete_after_unix_ms: u64,
    #[serde(default)]
    pub encryption_key_id: Option<String>,
    #[serde(default)]
    pub encrypted_store_namespace: Option<String>,
}

/// Joint semantic payload signed by four independent authority roles.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ExecutionAuthorityBundle {
    pub schema_version: u32,
    pub request_id: String,
    pub principal_id: String,
    pub manifest: ExecutionManifest,
    pub quota_lease: QuotaLease,
    pub resource_lease: ResourceLease,
    pub output_policy: OutputDataPolicy,
}

/// Signed exact execution plan.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedExecutionAuthorityBundle {
    pub bundle: ExecutionAuthorityBundle,
    pub signatures: Vec<ControlSignature>,
}

impl ExecutionAuthorityBundle {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, ContractError> {
        let mut bytes = b"hepta.inference-control.execution-authority.v1\0".to_vec();
        bytes.extend(
            serde_json::to_vec(self).map_err(|_| ContractError::InvalidExecutionAuthority)?,
        );
        Ok(bytes)
    }

    pub fn digest(&self) -> Result<String, ContractError> {
        digest_domain(
            b"hepta.inference-control.execution-authority-digest.v1\0",
            &serde_json::to_vec(self).map_err(|_| ContractError::InvalidExecutionAuthority)?,
        )
    }
}

/// Unforgeable-by-type result of validating every execution authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedExecutionPlan {
    request_id: String,
    principal_id: String,
    authority_epoch: u64,
    manifest: ExecutionManifest,
    quota_lease: QuotaLease,
    resource_lease: ResourceLease,
    output_policy: OutputDataPolicy,
    bundle_digest: String,
    manifest_digest: String,
    quota_lease_digest: String,
    resource_lease_digest: String,
    output_policy_digest: String,
    execution_binding_digest: String,
    authenticated_keys: BTreeMap<TrustRole, String>,
}

impl VerifiedExecutionPlan {
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    pub fn principal_id(&self) -> &str {
        &self.principal_id
    }

    pub fn authority_epoch(&self) -> u64 {
        self.authority_epoch
    }

    pub fn manifest(&self) -> &ExecutionManifest {
        &self.manifest
    }

    pub fn quota_lease(&self) -> &QuotaLease {
        &self.quota_lease
    }

    pub fn resource_lease(&self) -> &ResourceLease {
        &self.resource_lease
    }

    pub fn output_policy(&self) -> &OutputDataPolicy {
        &self.output_policy
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

    pub fn authenticated_keys(&self) -> &BTreeMap<TrustRole, String> {
        &self.authenticated_keys
    }

    pub fn valid_until_unix_ms(&self) -> u64 {
        self.quota_lease
            .valid_until_unix_ms
            .min(self.resource_lease.valid_until_unix_ms)
            .min(self.output_policy.delete_after_unix_ms)
    }

    pub fn assert_valid_at(&self, now_unix_ms: u64) -> Result<(), ContractError> {
        if now_unix_ms < self.quota_lease.valid_from_unix_ms
            || now_unix_ms >= self.quota_lease.valid_until_unix_ms
            || now_unix_ms < self.resource_lease.valid_from_unix_ms
            || now_unix_ms >= self.resource_lease.valid_until_unix_ms
            || now_unix_ms >= self.output_policy.delete_after_unix_ms
        {
            return Err(ContractError::Expired);
        }
        Ok(())
    }
}

/// Verify manifest, quota, resource, and data authorities over one exact bundle.
pub fn verify_execution_plan(
    now_unix_ms: u64,
    trust: &ControlTrustStore,
    signed: &SignedExecutionAuthorityBundle,
) -> Result<VerifiedExecutionPlan, ContractError> {
    let bundle = &signed.bundle;
    validate_execution_bundle(now_unix_ms, bundle)?;
    if signed.signatures.len() < 4 || signed.signatures.len() > MAX_SIGNATURES {
        return Err(ContractError::SignatureQuorum);
    }
    let signing_bytes = bundle.signing_bytes()?;
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
    let mut consumed_signatures = BTreeSet::new();
    let mut consumed_public_keys = BTreeSet::new();
    for (role, signer_id) in required {
        let signature = signed
            .signatures
            .iter()
            .find(|signature| {
                signature.signer_id == signer_id
                    && trust
                        .keys
                        .get(&signature.key_id)
                        .is_some_and(|key| key.role == role)
            })
            .ok_or(ContractError::SignatureQuorum)?;
        let public_key = trust
            .keys
            .get(&signature.key_id)
            .ok_or(ContractError::UnknownTrustKey)?
            .verifying_key
            .to_bytes();
        if !consumed_signatures.insert(signature.key_id.clone())
            || !consumed_public_keys.insert(public_key)
        {
            return Err(ContractError::SignatureQuorum);
        }
        trust.verify(
            role,
            signer_id,
            bundle.manifest.authority_epoch,
            signature,
            &signing_bytes,
        )?;
        authenticated_keys.insert(role, signature.key_id.clone());
    }

    let manifest_bytes =
        serde_json::to_vec(&bundle.manifest).map_err(|_| ContractError::InvalidManifest)?;
    let quota_bytes =
        serde_json::to_vec(&bundle.quota_lease).map_err(|_| ContractError::InvalidQuotaLease)?;
    let resource_bytes = serde_json::to_vec(&bundle.resource_lease)
        .map_err(|_| ContractError::InvalidResourceLease)?;
    let policy_bytes =
        serde_json::to_vec(&bundle.output_policy).map_err(|_| ContractError::InvalidDataPolicy)?;
    let manifest_digest = digest_domain(b"hepta.inference-control.manifest.v1\0", &manifest_bytes)?;
    let quota_lease_digest =
        digest_domain(b"hepta.inference-control.quota-lease.v1\0", &quota_bytes)?;
    let resource_lease_digest = digest_domain(
        b"hepta.inference-control.resource-lease.v1\0",
        &resource_bytes,
    )?;
    let output_policy_digest =
        digest_domain(b"hepta.inference-control.output-policy.v1\0", &policy_bytes)?;
    let bundle_digest = bundle.digest()?;
    let execution_binding_digest = digest_domain(
        b"hepta.inference-control.execution-binding.v1\0",
        &serde_json::to_vec(&(
            &bundle.request_id,
            &bundle.principal_id,
            bundle.manifest.authority_epoch,
            &manifest_digest,
            &quota_lease_digest,
            &resource_lease_digest,
            &output_policy_digest,
            &bundle.manifest.payload_digest,
        ))
        .map_err(|_| ContractError::InvalidExecutionAuthority)?,
    )?;

    Ok(VerifiedExecutionPlan {
        request_id: bundle.request_id.clone(),
        principal_id: bundle.principal_id.clone(),
        authority_epoch: bundle.manifest.authority_epoch,
        manifest: bundle.manifest.clone(),
        quota_lease: bundle.quota_lease.clone(),
        resource_lease: bundle.resource_lease.clone(),
        output_policy: bundle.output_policy.clone(),
        bundle_digest,
        manifest_digest,
        quota_lease_digest,
        resource_lease_digest,
        output_policy_digest,
        execution_binding_digest,
        authenticated_keys,
    })
}

/// Provider terminal state accepted by the reconciliation verifier.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ReconciledTerminalStatus {
    Completed,
    Failed,
    Interrupted,
}

/// Exact post-crash provider/adapter evidence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReconciliationReceipt {
    pub schema_version: u32,
    pub issuer_id: String,
    pub authority_epoch: u64,
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

/// Signed reconciliation evidence.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedReconciliationReceipt {
    pub receipt: ReconciliationReceipt,
    pub signature: ControlSignature,
}

impl ReconciliationReceipt {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, ContractError> {
        let mut bytes = b"hepta.inference-control.reconciliation.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| ContractError::InvalidReconciliation)?);
        Ok(bytes)
    }
}

/// Verified terminal capability. Its fields are read-only to durable callers.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedReconciliationReceipt {
    receipt: ReconciliationReceipt,
    receipt_digest: String,
    authenticated_key_id: String,
}

impl VerifiedReconciliationReceipt {
    pub fn receipt(&self) -> &ReconciliationReceipt {
        &self.receipt
    }

    pub fn receipt_digest(&self) -> &str {
        &self.receipt_digest
    }

    pub fn authenticated_key_id(&self) -> &str {
        &self.authenticated_key_id
    }

    /// Recheck the signed receipt window at the durable consumption boundary.
    pub fn assert_valid_at(&self, now_unix_ms: u64) -> Result<(), ContractError> {
        validate_time_window(
            now_unix_ms,
            self.receipt.issued_at_unix_ms,
            self.receipt.expires_at_unix_ms,
            MAX_RECEIPT_LIFETIME_MS,
        )
    }
}

/// Verify a signed terminal receipt against one exact execution plan.
pub fn verify_reconciliation_receipt(
    now_unix_ms: u64,
    trust: &ControlTrustStore,
    plan: &VerifiedExecutionPlan,
    signed: &SignedReconciliationReceipt,
) -> Result<VerifiedReconciliationReceipt, ContractError> {
    plan.assert_valid_at(now_unix_ms)?;
    let receipt = &signed.receipt;
    validate_reconciliation(now_unix_ms, receipt)?;
    if receipt.request_id != plan.request_id
        || receipt.principal_id != plan.principal_id
        || receipt.execution_binding_digest != plan.execution_binding_digest
        || receipt.provider_id != plan.manifest.provider_id
        || receipt.model_digest != plan.manifest.model_digest
        || receipt.authority_epoch != plan.authority_epoch
    {
        return Err(ContractError::BindingMismatch);
    }
    let signing_bytes = receipt.signing_bytes()?;
    trust.verify(
        TrustRole::ReconciliationIssuer,
        &receipt.issuer_id,
        receipt.authority_epoch,
        &signed.signature,
        &signing_bytes,
    )?;
    let receipt_digest = digest_domain(
        b"hepta.inference-control.reconciliation-digest.v1\0",
        &serde_json::to_vec(receipt).map_err(|_| ContractError::InvalidReconciliation)?,
    )?;
    Ok(VerifiedReconciliationReceipt {
        receipt: receipt.clone(),
        receipt_digest,
        authenticated_key_id: signed.signature.key_id.clone(),
    })
}

/// Two-person release request for an otherwise unreconciled execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct IndeterminateRetirement {
    pub schema_version: u32,
    pub authority_epoch: u64,
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

/// Signed dual-control retirement.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SignedIndeterminateRetirement {
    pub retirement: IndeterminateRetirement,
    pub approvals: Vec<ControlSignature>,
}

impl IndeterminateRetirement {
    pub fn signing_bytes(&self) -> Result<Vec<u8>, ContractError> {
        let mut bytes = b"hepta.inference-control.indeterminate-retirement.v1\0".to_vec();
        bytes.extend(serde_json::to_vec(self).map_err(|_| ContractError::InvalidRetirement)?);
        Ok(bytes)
    }
}

/// Verified two-person retirement capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct VerifiedRetirement {
    retirement: IndeterminateRetirement,
    retirement_digest: String,
    operator_ids: [String; 2],
    key_ids: [String; 2],
    key_fingerprints: [String; 2],
}

impl VerifiedRetirement {
    pub fn retirement(&self) -> &IndeterminateRetirement {
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

    /// Recheck the signed approval window at the durable consumption boundary.
    pub fn assert_valid_at(&self, now_unix_ms: u64) -> Result<(), ContractError> {
        validate_time_window(
            now_unix_ms,
            self.retirement.issued_at_unix_ms,
            self.retirement.expires_at_unix_ms,
            MAX_RETIREMENT_LIFETIME_MS,
        )
    }
}

/// Require two distinct operators and keys over the exact retirement payload.
pub fn verify_indeterminate_retirement(
    now_unix_ms: u64,
    trust: &ControlTrustStore,
    plan: &VerifiedExecutionPlan,
    signed: &SignedIndeterminateRetirement,
) -> Result<VerifiedRetirement, ContractError> {
    plan.assert_valid_at(now_unix_ms)?;
    let retirement = &signed.retirement;
    validate_retirement(now_unix_ms, retirement)?;
    if retirement.request_id != plan.request_id
        || retirement.principal_id != plan.principal_id
        || retirement.execution_binding_digest != plan.execution_binding_digest
        || retirement.authority_epoch != plan.authority_epoch
    {
        return Err(ContractError::BindingMismatch);
    }
    if signed.approvals.len() != 2 {
        return Err(ContractError::SignatureQuorum);
    }
    let first = &signed.approvals[0];
    let second = &signed.approvals[1];
    if first.key_id == second.key_id || first.signer_id == second.signer_id {
        return Err(ContractError::SignatureQuorum);
    }
    let first_key = trust
        .keys
        .get(&first.key_id)
        .ok_or(ContractError::UnknownTrustKey)?;
    let second_key = trust
        .keys
        .get(&second.key_id)
        .ok_or(ContractError::UnknownTrustKey)?;
    if first_key.verifying_key == second_key.verifying_key {
        return Err(ContractError::SignatureQuorum);
    }
    let signing_bytes = retirement.signing_bytes()?;
    trust.verify(
        TrustRole::RetirementOperator,
        &first.signer_id,
        retirement.authority_epoch,
        first,
        &signing_bytes,
    )?;
    trust.verify(
        TrustRole::RetirementOperator,
        &second.signer_id,
        retirement.authority_epoch,
        second,
        &signing_bytes,
    )?;
    let retirement_digest = digest_domain(
        b"hepta.inference-control.indeterminate-retirement-digest.v1\0",
        &serde_json::to_vec(retirement).map_err(|_| ContractError::InvalidRetirement)?,
    )?;
    Ok(VerifiedRetirement {
        retirement: retirement.clone(),
        retirement_digest,
        operator_ids: [first.signer_id.clone(), second.signer_id.clone()],
        key_ids: [first.key_id.clone(), second.key_id.clone()],
        key_fingerprints: [
            digest_domain(
                b"hepta.inference-control.retirement-verifying-key.v1\0",
                &first_key.verifying_key.to_bytes(),
            )?,
            digest_domain(
                b"hepta.inference-control.retirement-verifying-key.v1\0",
                &second_key.verifying_key.to_bytes(),
            )?,
        ],
    })
}

/// Non-plaintext journal representation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProtectedOutput {
    pub output_digest: String,
    pub classification: OutputClassification,
    pub storage_mode: OutputStorageMode,
    pub delete_after_unix_ms: u64,
    #[serde(default)]
    pub encrypted_reference: Option<String>,
    #[serde(default)]
    pub ciphertext_digest: Option<String>,
    #[serde(default)]
    pub encryption_key_id: Option<String>,
}

impl ProtectedOutput {
    /// Validate deserialized protection metadata against the signed data policy.
    /// This binds metadata only; the vault adapter still owns actual encryption.
    pub fn assert_matches_policy(
        &self,
        now_unix_ms: u64,
        policy: &OutputDataPolicy,
    ) -> Result<(), ContractError> {
        validate_output_policy(now_unix_ms, policy)?;
        self.validate_structure()?;
        if self.classification != policy.classification
            || self.storage_mode != policy.storage_mode
            || self.delete_after_unix_ms != policy.delete_after_unix_ms
            || self.encryption_key_id != policy.encryption_key_id
        {
            return Err(ContractError::InvalidDataPolicy);
        }
        Ok(())
    }

    // Structural validity is independent from wall time so expired historical
    // references remain replayable for the separately verified deletion policy.
    fn validate_structure(&self) -> Result<(), ContractError> {
        validate_digest(&self.output_digest, "output")?;
        if self.delete_after_unix_ms == 0 {
            return Err(ContractError::InvalidDataPolicy);
        }
        match self.storage_mode {
            OutputStorageMode::DigestOnly => {
                if self.encrypted_reference.is_some()
                    || self.ciphertext_digest.is_some()
                    || self.encryption_key_id.is_some()
                    || matches!(
                        self.classification,
                        OutputClassification::Confidential | OutputClassification::Restricted
                    )
                {
                    return Err(ContractError::InvalidDataPolicy);
                }
            }
            OutputStorageMode::ExternalEncrypted => {
                validate_reference(
                    self.encrypted_reference
                        .as_deref()
                        .ok_or(ContractError::InvalidDataPolicy)?,
                )?;
                validate_digest(
                    self.ciphertext_digest
                        .as_deref()
                        .ok_or(ContractError::InvalidDataPolicy)?,
                    "ciphertext",
                )?;
                validate_id(
                    self.encryption_key_id
                        .as_deref()
                        .ok_or(ContractError::InvalidDataPolicy)?,
                    "encryption key",
                )?;
            }
        }
        Ok(())
    }

    /// Produce a digest-only representation. This is valid only for a policy
    /// which selected digest-only persistence.
    pub fn digest_only(
        now_unix_ms: u64,
        policy: &OutputDataPolicy,
        output: &[u8],
    ) -> Result<Self, ContractError> {
        validate_output_policy(now_unix_ms, policy)?;
        if policy.storage_mode != OutputStorageMode::DigestOnly {
            return Err(ContractError::InvalidDataPolicy);
        }
        Ok(Self {
            output_digest: digest_domain(b"hepta.inference-control.output.v1\0", output)?,
            classification: policy.classification,
            storage_mode: policy.storage_mode,
            delete_after_unix_ms: policy.delete_after_unix_ms,
            encrypted_reference: None,
            ciphertext_digest: None,
            encryption_key_id: None,
        })
    }

    /// Bind externally encrypted bytes. The control journal stores only this
    /// metadata; encryption is performed by the selected key-management adapter.
    pub fn external_encrypted(
        now_unix_ms: u64,
        policy: &OutputDataPolicy,
        plaintext_output: &[u8],
        encrypted_reference: String,
        ciphertext_digest: String,
    ) -> Result<Self, ContractError> {
        validate_output_policy(now_unix_ms, policy)?;
        if policy.storage_mode != OutputStorageMode::ExternalEncrypted {
            return Err(ContractError::InvalidDataPolicy);
        }
        validate_reference(&encrypted_reference)?;
        validate_digest(&ciphertext_digest, "ciphertext")?;
        let encryption_key_id = policy
            .encryption_key_id
            .clone()
            .ok_or(ContractError::InvalidDataPolicy)?;
        Ok(Self {
            output_digest: digest_domain(b"hepta.inference-control.output.v1\0", plaintext_output)?,
            classification: policy.classification,
            storage_mode: policy.storage_mode,
            delete_after_unix_ms: policy.delete_after_unix_ms,
            encrypted_reference: Some(encrypted_reference),
            ciphertext_digest: Some(ciphertext_digest),
            encryption_key_id: Some(encryption_key_id),
        })
    }

    pub fn journal_marker(&self) -> Result<String, ContractError> {
        self.validate_structure()?;
        let json = serde_json::to_vec(self).map_err(|_| ContractError::InvalidDataPolicy)?;
        Ok(format!(
            "hepta-protected-output-v1:{}",
            digest_domain(b"hepta.inference-control.protected-output.v1\0", &json)?
        ))
    }
}

/// Contract-validation failure.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContractError {
    InvalidTrust,
    UnknownTrustKey,
    InvalidSignature,
    SignatureQuorum,
    SignerMismatch,
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidManifest,
    InvalidQuotaLease,
    InvalidResourceLease,
    InvalidDataPolicy,
    InvalidExecutionAuthority,
    InvalidReconciliation,
    InvalidRetirement,
    BindingMismatch,
    NotYetValid,
    Expired,
    CapacityExceeded,
}

impl fmt::Display for ContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContractError {}

fn validate_execution_bundle(
    now_unix_ms: u64,
    bundle: &ExecutionAuthorityBundle,
) -> Result<(), ContractError> {
    if bundle.schema_version != EXECUTION_SCHEMA_VERSION
        || bundle.manifest.schema_version != EXECUTION_SCHEMA_VERSION
        || bundle.quota_lease.schema_version != EXECUTION_SCHEMA_VERSION
        || bundle.resource_lease.schema_version != EXECUTION_SCHEMA_VERSION
        || bundle.output_policy.schema_version != EXECUTION_SCHEMA_VERSION
    {
        return Err(ContractError::InvalidExecutionAuthority);
    }
    validate_id(&bundle.request_id, "request")?;
    validate_id(&bundle.principal_id, "principal")?;
    validate_manifest(&bundle.manifest)?;
    let manifest_digest = digest_domain(
        b"hepta.inference-control.manifest.v1\0",
        &serde_json::to_vec(&bundle.manifest).map_err(|_| ContractError::InvalidManifest)?,
    )?;
    validate_quota_lease(now_unix_ms, &bundle.quota_lease)?;
    validate_resource_lease(now_unix_ms, &bundle.resource_lease)?;
    validate_output_policy(now_unix_ms, &bundle.output_policy)?;
    if bundle.request_id != bundle.quota_lease.request_id
        || bundle.request_id != bundle.resource_lease.request_id
        || bundle.principal_id != bundle.quota_lease.principal_id
        || bundle.manifest.authority_epoch != bundle.quota_lease.authority_epoch
        || bundle.manifest.authority_epoch != bundle.resource_lease.authority_epoch
        || bundle.manifest.authority_epoch != bundle.output_policy.authority_epoch
        || bundle.quota_lease.manifest_digest != manifest_digest
        || bundle.resource_lease.manifest_digest != manifest_digest
    {
        return Err(ContractError::BindingMismatch);
    }
    Ok(())
}

fn validate_manifest(manifest: &ExecutionManifest) -> Result<(), ContractError> {
    if manifest.schema_version != EXECUTION_SCHEMA_VERSION || manifest.authority_epoch == 0 {
        return Err(ContractError::InvalidManifest);
    }
    for (value, field) in [
        (&manifest.manifest_id, "manifest"),
        (&manifest.issuer_id, "manifest issuer"),
        (&manifest.provider_id, "provider"),
        (&manifest.model_id, "model"),
        (&manifest.model_revision, "model revision"),
        (&manifest.tokenizer_id, "tokenizer"),
        (&manifest.tokenizer_version, "tokenizer version"),
        (&manifest.template_id, "template"),
        (&manifest.runtime_abi, "runtime ABI"),
        (&manifest.adapter_abi, "adapter ABI"),
    ] {
        validate_id(value, field)?;
    }
    for (value, field) in [
        (&manifest.model_digest, "model"),
        (&manifest.tokenizer_digest, "tokenizer"),
        (&manifest.template_digest, "template"),
        (&manifest.runtime_digest, "runtime"),
        (&manifest.adapter_digest, "adapter"),
        (&manifest.payload_digest, "payload"),
        (&manifest.policy_digest, "policy"),
    ] {
        validate_digest(value, field)?;
    }
    Ok(())
}

fn validate_quota_lease(now_unix_ms: u64, lease: &QuotaLease) -> Result<(), ContractError> {
    for (value, field) in [
        (&lease.lease_id, "quota lease"),
        (&lease.authority_id, "quota authority"),
        (&lease.request_id, "request"),
        (&lease.principal_id, "principal"),
    ] {
        validate_id(value, field)?;
    }
    validate_digest(&lease.manifest_digest, "quota manifest")?;
    validate_time_window(
        now_unix_ms,
        lease.valid_from_unix_ms,
        lease.valid_until_unix_ms,
        MAX_LEASE_LIFETIME_MS,
    )?;
    if lease.authority_epoch == 0
        || lease.maximum_input_tokens == 0
        || lease.maximum_output_tokens == 0
        || lease.maximum_cost_microunits == 0
    {
        return Err(ContractError::InvalidQuotaLease);
    }
    Ok(())
}

fn validate_resource_lease(now_unix_ms: u64, lease: &ResourceLease) -> Result<(), ContractError> {
    for (value, field) in [
        (&lease.lease_id, "resource lease"),
        (&lease.authority_id, "resource authority"),
        (&lease.request_id, "request"),
        (&lease.worker_id, "worker"),
    ] {
        validate_id(value, field)?;
    }
    validate_digest(&lease.manifest_digest, "resource manifest")?;
    validate_digest(&lease.accelerator_profile_digest, "accelerator profile")?;
    validate_time_window(
        now_unix_ms,
        lease.valid_from_unix_ms,
        lease.valid_until_unix_ms,
        MAX_LEASE_LIFETIME_MS,
    )?;
    if lease.authority_epoch == 0
        || lease.worker_generation == 0
        || lease.cpu_millis == 0
        || lease.memory_bytes == 0
    {
        return Err(ContractError::InvalidResourceLease);
    }
    Ok(())
}

fn validate_output_policy(
    now_unix_ms: u64,
    policy: &OutputDataPolicy,
) -> Result<(), ContractError> {
    for (value, field) in [
        (&policy.policy_id, "output policy"),
        (&policy.authority_id, "data authority"),
    ] {
        validate_id(value, field)?;
    }
    if policy.authority_epoch == 0
        || policy.maximum_retention_ms == 0
        || policy.maximum_retention_ms > MAX_OUTPUT_TTL_MS
        || policy.delete_after_unix_ms <= now_unix_ms
        || policy.delete_after_unix_ms - now_unix_ms > policy.maximum_retention_ms
    {
        return Err(ContractError::InvalidDataPolicy);
    }
    match policy.storage_mode {
        OutputStorageMode::DigestOnly => {
            if policy.encryption_key_id.is_some() || policy.encrypted_store_namespace.is_some() {
                return Err(ContractError::InvalidDataPolicy);
            }
        }
        OutputStorageMode::ExternalEncrypted => {
            let key = policy
                .encryption_key_id
                .as_deref()
                .ok_or(ContractError::InvalidDataPolicy)?;
            let namespace = policy
                .encrypted_store_namespace
                .as_deref()
                .ok_or(ContractError::InvalidDataPolicy)?;
            validate_id(key, "encryption key")?;
            validate_id(namespace, "encrypted store namespace")?;
        }
    }
    if matches!(
        policy.classification,
        OutputClassification::Confidential | OutputClassification::Restricted
    ) && policy.storage_mode != OutputStorageMode::ExternalEncrypted
    {
        return Err(ContractError::InvalidDataPolicy);
    }
    Ok(())
}

fn validate_reconciliation(
    now_unix_ms: u64,
    receipt: &ReconciliationReceipt,
) -> Result<(), ContractError> {
    if receipt.schema_version != RECONCILIATION_SCHEMA_VERSION
        || receipt.authority_epoch == 0
        || receipt.terminal_sequence == 0
    {
        return Err(ContractError::InvalidReconciliation);
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
    validate_time_window(
        now_unix_ms,
        receipt.issued_at_unix_ms,
        receipt.expires_at_unix_ms,
        MAX_RECEIPT_LIFETIME_MS,
    )?;
    if receipt.terminal_status == ReconciledTerminalStatus::Completed
        && receipt.output_digest.is_none()
    {
        return Err(ContractError::InvalidReconciliation);
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
    retirement: &IndeterminateRetirement,
) -> Result<(), ContractError> {
    if retirement.schema_version != RETIREMENT_SCHEMA_VERSION
        || retirement.authority_epoch == 0
        || retirement.record_revision == 0
        || retirement.reason.is_empty()
        || retirement.reason.len() > MAX_REASON_BYTES
    {
        return Err(ContractError::InvalidRetirement);
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
    validate_time_window(
        now_unix_ms,
        retirement.issued_at_unix_ms,
        retirement.expires_at_unix_ms,
        MAX_RETIREMENT_LIFETIME_MS,
    )
}

fn validate_time_window(
    now_unix_ms: u64,
    not_before_unix_ms: u64,
    not_after_unix_ms: u64,
    maximum_lifetime_ms: u64,
) -> Result<(), ContractError> {
    if not_before_unix_ms == 0
        || not_after_unix_ms <= not_before_unix_ms
        || not_after_unix_ms - not_before_unix_ms > maximum_lifetime_ms
    {
        return Err(ContractError::Expired);
    }
    if now_unix_ms < not_before_unix_ms {
        return Err(ContractError::NotYetValid);
    }
    if now_unix_ms >= not_after_unix_ms {
        return Err(ContractError::Expired);
    }
    Ok(())
}

fn validate_id(value: &str, field: &'static str) -> Result<(), ContractError> {
    if value.is_empty()
        || value.len() > MAX_ID_BYTES
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-/".contains(&byte))
    {
        return Err(ContractError::InvalidIdentity(field));
    }
    Ok(())
}

fn validate_reference(value: &str) -> Result<(), ContractError> {
    if value.is_empty()
        || value.len() > MAX_REFERENCE_BYTES
        || value.bytes().any(|byte| byte.is_ascii_control())
    {
        return Err(ContractError::InvalidDataPolicy);
    }
    Ok(())
}

fn validate_digest(value: &str, field: &'static str) -> Result<(), ContractError> {
    if value.len() != 64
        || value.bytes().all(|byte| byte == b'0')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err(ContractError::InvalidDigest(field));
    }
    Ok(())
}

fn digest_domain(domain: &[u8], payload: &[u8]) -> Result<String, ContractError> {
    if payload.len() > 8 * 1024 * 1024 {
        return Err(ContractError::CapacityExceeded);
    }
    let mut hash = Sha256::new();
    hash.update(domain);
    hash.update((payload.len() as u64).to_be_bytes());
    hash.update(payload);
    Ok(format!("{:x}", hash.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::Signer;
    use ed25519_dalek::SigningKey;

    const NOW: u64 = 1_000_000;

    struct Keys {
        manifest: SigningKey,
        quota: SigningKey,
        resource: SigningKey,
        data: SigningKey,
        receipt: SigningKey,
        operator_a: SigningKey,
        operator_b: SigningKey,
    }

    fn keys() -> Keys {
        Keys {
            manifest: SigningKey::from_bytes(&[1; 32]),
            quota: SigningKey::from_bytes(&[2; 32]),
            resource: SigningKey::from_bytes(&[3; 32]),
            data: SigningKey::from_bytes(&[4; 32]),
            receipt: SigningKey::from_bytes(&[5; 32]),
            operator_a: SigningKey::from_bytes(&[6; 32]),
            operator_b: SigningKey::from_bytes(&[7; 32]),
        }
    }

    fn trust(keys: &Keys) -> ControlTrustStore {
        let entry =
            |key_id: &str, signer_id: &str, role: TrustRole, key: &SigningKey| -> TrustKey {
                TrustKey {
                    key_id: key_id.to_string(),
                    signer_id: signer_id.to_string(),
                    role,
                    verifying_key: key.verifying_key().to_bytes(),
                    not_before_authority_epoch: 1,
                    not_after_authority_epoch: 9,
                    revoked_at_authority_epoch: None,
                }
            };
        ControlTrustStore::new(vec![
            entry(
                "manifest-key",
                "manifest-authority",
                TrustRole::ManifestAuthority,
                &keys.manifest,
            ),
            entry(
                "quota-key",
                "quota-authority",
                TrustRole::QuotaAuthority,
                &keys.quota,
            ),
            entry(
                "resource-key",
                "resource-authority",
                TrustRole::ResourceAuthority,
                &keys.resource,
            ),
            entry(
                "data-key",
                "data-authority",
                TrustRole::DataAuthority,
                &keys.data,
            ),
            entry(
                "receipt-key",
                "provider-reconciler",
                TrustRole::ReconciliationIssuer,
                &keys.receipt,
            ),
            entry(
                "operator-key-a",
                "operator-a",
                TrustRole::RetirementOperator,
                &keys.operator_a,
            ),
            entry(
                "operator-key-b",
                "operator-b",
                TrustRole::RetirementOperator,
                &keys.operator_b,
            ),
        ])
        .unwrap()
    }

    fn manifest() -> ExecutionManifest {
        ExecutionManifest {
            schema_version: 1,
            manifest_id: "manifest-1".into(),
            issuer_id: "manifest-authority".into(),
            authority_epoch: 3,
            provider_id: "provider-1".into(),
            model_id: "model-1".into(),
            model_revision: "revision-1".into(),
            model_digest: "1".repeat(64),
            tokenizer_id: "tokenizer-1".into(),
            tokenizer_version: "version-1".into(),
            tokenizer_digest: "2".repeat(64),
            template_id: "template-1".into(),
            template_digest: "3".repeat(64),
            runtime_abi: "runtime.v1".into(),
            runtime_digest: "4".repeat(64),
            adapter_abi: "adapter.v1".into(),
            adapter_digest: "5".repeat(64),
            payload_digest: "6".repeat(64),
            policy_digest: "7".repeat(64),
        }
    }

    fn signed_bundle(keys: &Keys) -> SignedExecutionAuthorityBundle {
        let manifest = manifest();
        let manifest_digest = digest_domain(
            b"hepta.inference-control.manifest.v1\0",
            &serde_json::to_vec(&manifest).unwrap(),
        )
        .unwrap();
        let bundle = ExecutionAuthorityBundle {
            schema_version: 1,
            request_id: "request-1".into(),
            principal_id: "principal-1".into(),
            manifest,
            quota_lease: QuotaLease {
                schema_version: 1,
                lease_id: "quota-1".into(),
                authority_id: "quota-authority".into(),
                authority_epoch: 3,
                request_id: "request-1".into(),
                principal_id: "principal-1".into(),
                manifest_digest: manifest_digest.clone(),
                maximum_input_tokens: 100,
                maximum_output_tokens: 200,
                maximum_cost_microunits: 50_000,
                valid_from_unix_ms: NOW - 10,
                valid_until_unix_ms: NOW + 1_000,
            },
            resource_lease: ResourceLease {
                schema_version: 1,
                lease_id: "resource-1".into(),
                authority_id: "resource-authority".into(),
                authority_epoch: 3,
                request_id: "request-1".into(),
                worker_id: "worker-1".into(),
                worker_generation: 4,
                manifest_digest,
                cpu_millis: 1_000,
                memory_bytes: 1024 * 1024,
                accelerator_count: 1,
                accelerator_profile_digest: "8".repeat(64),
                valid_from_unix_ms: NOW - 10,
                valid_until_unix_ms: NOW + 1_000,
            },
            output_policy: OutputDataPolicy {
                schema_version: 1,
                policy_id: "policy-1".into(),
                authority_id: "data-authority".into(),
                authority_epoch: 3,
                classification: OutputClassification::Internal,
                storage_mode: OutputStorageMode::DigestOnly,
                maximum_retention_ms: 2_000,
                delete_after_unix_ms: NOW + 1_000,
                encryption_key_id: None,
                encrypted_store_namespace: None,
            },
        };
        let message = bundle.signing_bytes().unwrap();
        let signature = |key_id: &str, signer_id: &str, key: &SigningKey| ControlSignature {
            key_id: key_id.into(),
            signer_id: signer_id.into(),
            signature: key.sign(&message).to_bytes().to_vec(),
        };
        SignedExecutionAuthorityBundle {
            bundle,
            signatures: vec![
                signature("manifest-key", "manifest-authority", &keys.manifest),
                signature("quota-key", "quota-authority", &keys.quota),
                signature("resource-key", "resource-authority", &keys.resource),
                signature("data-key", "data-authority", &keys.data),
            ],
        }
    }

    #[test]
    fn four_independent_authorities_bind_one_exact_execution() {
        let keys = keys();
        let trust = trust(&keys);
        let signed = signed_bundle(&keys);
        let plan = verify_execution_plan(NOW, &trust, &signed).unwrap();
        assert_eq!(plan.request_id(), "request-1");
        assert_eq!(plan.manifest().model_digest, "1".repeat(64));
        assert_eq!(plan.authenticated_keys().len(), 4);

        let mut drifted = signed;
        drifted.bundle.manifest.tokenizer_digest = "9".repeat(64);
        assert_eq!(
            verify_execution_plan(NOW, &trust, &drifted),
            Err(ContractError::BindingMismatch)
        );
    }

    #[test]
    fn key_rotation_window_and_revocation_are_enforced() {
        let keys = keys();
        let mut trust_keys = trust(&keys);
        let signed = signed_bundle(&keys);
        assert!(verify_execution_plan(NOW, &trust_keys, &signed).is_ok());
        trust_keys
            .keys
            .get_mut("quota-key")
            .unwrap()
            .revoked_at_authority_epoch = Some(3);
        assert_eq!(
            verify_execution_plan(NOW, &trust_keys, &signed),
            Err(ContractError::InvalidTrust)
        );
    }

    #[test]
    fn signed_reconciliation_is_exact_and_rotation_bound() {
        let keys = keys();
        let trust = trust(&keys);
        let plan = verify_execution_plan(NOW, &trust, &signed_bundle(&keys)).unwrap();
        let receipt = ReconciliationReceipt {
            schema_version: 1,
            issuer_id: "provider-reconciler".into(),
            authority_epoch: 3,
            request_id: plan.request_id().into(),
            principal_id: plan.principal_id().into(),
            execution_binding_digest: plan.execution_binding_digest().into(),
            dispatch_digest: "a".repeat(64),
            thread_id: "thread-1".into(),
            turn_id: "turn-1".into(),
            provider_id: plan.manifest().provider_id.clone(),
            model_digest: plan.manifest().model_digest.clone(),
            terminal_sequence: 7,
            terminal_status: ReconciledTerminalStatus::Completed,
            output_digest: Some("b".repeat(64)),
            encrypted_output_reference: None,
            observed_output_tokens: Some(19),
            usage_microunits: Some(42),
            issued_at_unix_ms: NOW - 1,
            expires_at_unix_ms: NOW + 100,
        };
        let signed = SignedReconciliationReceipt {
            signature: ControlSignature {
                key_id: "receipt-key".into(),
                signer_id: "provider-reconciler".into(),
                signature: keys
                    .receipt
                    .sign(&receipt.signing_bytes().unwrap())
                    .to_bytes()
                    .to_vec(),
            },
            receipt,
        };
        let verified = verify_reconciliation_receipt(NOW, &trust, &plan, &signed).unwrap();
        assert_eq!(verified.receipt().terminal_sequence, 7);

        assert_eq!(verified.assert_valid_at(NOW), Ok(()));
        assert_eq!(
            verified.assert_valid_at(NOW - 2),
            Err(ContractError::NotYetValid)
        );
        assert_eq!(
            verified.assert_valid_at(NOW + 100),
            Err(ContractError::Expired)
        );

        let mut drifted = signed;
        drifted.receipt.turn_id = "turn-2".into();
        assert_eq!(
            verify_reconciliation_receipt(NOW, &trust, &plan, &drifted),
            Err(ContractError::InvalidSignature)
        );
    }

    #[test]
    fn retirement_requires_two_distinct_operators() {
        let keys = keys();
        let trust = trust(&keys);
        let plan = verify_execution_plan(NOW, &trust, &signed_bundle(&keys)).unwrap();
        let retirement = IndeterminateRetirement {
            schema_version: 1,
            authority_epoch: 3,
            request_id: plan.request_id().into(),
            principal_id: plan.principal_id().into(),
            execution_binding_digest: plan.execution_binding_digest().into(),
            dispatch_digest: "a".repeat(64),
            record_revision: 5,
            reason_code: "provider_unrecoverable".into(),
            reason: "provider has no independently recoverable terminal record".into(),
            issued_at_unix_ms: NOW - 1,
            expires_at_unix_ms: NOW + 100,
        };
        let message = retirement.signing_bytes().unwrap();
        let approval = |key_id: &str, signer_id: &str, key: &SigningKey| ControlSignature {
            key_id: key_id.into(),
            signer_id: signer_id.into(),
            signature: key.sign(&message).to_bytes().to_vec(),
        };
        let signed = SignedIndeterminateRetirement {
            retirement,
            approvals: vec![
                approval("operator-key-a", "operator-a", &keys.operator_a),
                approval("operator-key-b", "operator-b", &keys.operator_b),
            ],
        };
        let verified = verify_indeterminate_retirement(NOW, &trust, &plan, &signed).unwrap();
        assert_eq!(
            verified.operator_ids(),
            &["operator-a".to_string(), "operator-b".to_string()]
        );

        assert_eq!(
            verified.key_fingerprints(),
            &[
                digest_domain(
                    b"hepta.inference-control.retirement-verifying-key.v1\0",
                    &keys.operator_a.verifying_key().to_bytes()
                )
                .unwrap(),
                digest_domain(
                    b"hepta.inference-control.retirement-verifying-key.v1\0",
                    &keys.operator_b.verifying_key().to_bytes()
                )
                .unwrap(),
            ]
        );
        assert_ne!(
            verified.key_fingerprints()[0],
            verified.key_fingerprints()[1]
        );

        assert_eq!(verified.assert_valid_at(NOW), Ok(()));
        assert_eq!(
            verified.assert_valid_at(NOW - 2),
            Err(ContractError::NotYetValid)
        );
        assert_eq!(
            verified.assert_valid_at(NOW + 100),
            Err(ContractError::Expired)
        );

        let mut one_person = signed;
        one_person.approvals[1] = one_person.approvals[0].clone();
        assert_eq!(
            verify_indeterminate_retirement(NOW, &trust, &plan, &one_person),
            Err(ContractError::SignatureQuorum)
        );
    }

    #[test]
    fn four_authority_aliases_cannot_reuse_one_execution_signing_key() {
        let mut keys = keys();
        keys.quota = keys.manifest.clone();
        keys.resource = keys.manifest.clone();
        keys.data = keys.manifest.clone();
        let trust = trust(&keys);
        let signed = signed_bundle(&keys);
        assert_eq!(
            verify_execution_plan(NOW, &trust, &signed),
            Err(ContractError::SignatureQuorum)
        );
    }

    #[test]
    fn distinct_operator_aliases_cannot_reuse_one_retirement_key() {
        let mut keys = keys();
        keys.operator_b = keys.operator_a.clone();
        let trust = trust(&keys);
        let plan = verify_execution_plan(NOW, &trust, &signed_bundle(&keys)).unwrap();
        let retirement = IndeterminateRetirement {
            schema_version: 1,
            authority_epoch: 3,
            request_id: plan.request_id().into(),
            principal_id: plan.principal_id().into(),
            execution_binding_digest: plan.execution_binding_digest().into(),
            dispatch_digest: "a".repeat(64),
            record_revision: 5,
            reason_code: "provider_unrecoverable".into(),
            reason: "provider has no independently recoverable terminal record".into(),
            issued_at_unix_ms: NOW - 1,
            expires_at_unix_ms: NOW + 100,
        };
        let signature = keys
            .operator_a
            .sign(&retirement.signing_bytes().unwrap())
            .to_bytes()
            .to_vec();
        let signed = SignedIndeterminateRetirement {
            retirement,
            approvals: vec![
                ControlSignature {
                    key_id: "operator-key-a".into(),
                    signer_id: "operator-a".into(),
                    signature: signature.clone(),
                },
                ControlSignature {
                    key_id: "operator-key-b".into(),
                    signer_id: "operator-b".into(),
                    signature,
                },
            ],
        };
        assert_eq!(
            verify_indeterminate_retirement(NOW, &trust, &plan, &signed),
            Err(ContractError::SignatureQuorum)
        );
    }

    #[test]
    fn confidential_output_requires_external_encryption_metadata() {
        let policy = OutputDataPolicy {
            schema_version: 1,
            policy_id: "policy-1".into(),
            authority_id: "data-authority".into(),
            authority_epoch: 3,
            classification: OutputClassification::Confidential,
            storage_mode: OutputStorageMode::ExternalEncrypted,
            maximum_retention_ms: 2_000,
            delete_after_unix_ms: NOW + 1_000,
            encryption_key_id: Some("key-1".into()),
            encrypted_store_namespace: Some("vault-1".into()),
        };
        assert_eq!(
            ProtectedOutput::digest_only(NOW, &policy, b"secret"),
            Err(ContractError::InvalidDataPolicy)
        );
        let protected = ProtectedOutput::external_encrypted(
            NOW,
            &policy,
            b"secret",
            "vault://vault-1/object-1".into(),
            "c".repeat(64),
        )
        .unwrap();
        assert!(!protected.journal_marker().unwrap().contains("secret"));
        assert_eq!(protected.encryption_key_id.as_deref(), Some("key-1"));

        assert_eq!(protected.assert_matches_policy(NOW, &policy), Ok(()));
        assert_eq!(
            protected.assert_matches_policy(NOW + 1_000, &policy),
            Err(ContractError::InvalidDataPolicy)
        );
        let mut missing_reference = protected.clone();
        missing_reference.encrypted_reference = None;
        let mut missing_ciphertext = protected.clone();
        missing_ciphertext.ciphertext_digest = None;
        let mut missing_key = protected.clone();
        missing_key.encryption_key_id = None;
        let mut wrong_key = protected.clone();
        wrong_key.encryption_key_id = Some("other-key".into());
        let mut wrong_expiry = protected;
        wrong_expiry.delete_after_unix_ms += 1;
        for drifted in [
            missing_reference,
            missing_ciphertext,
            missing_key,
            wrong_key,
            wrong_expiry,
        ] {
            assert_eq!(
                drifted.assert_matches_policy(NOW, &policy),
                Err(ContractError::InvalidDataPolicy)
            );
        }
    }
    #[test]
    fn deserialized_protected_metadata_is_checked_before_marker_hashing() {
        let valid = serde_json::json!({
            "output_digest": "a".repeat(64),
            "classification": "confidential",
            "storage_mode": "external_encrypted",
            "delete_after_unix_ms": 1,
            "encrypted_reference": "vault://namespace/object",
            "ciphertext_digest": "b".repeat(64),
            "encryption_key_id": "key-1"
        });
        // Expired historical metadata remains structurally valid. Replay must
        // retain its reference until separately authenticated deletion evidence.
        let expired: ProtectedOutput = serde_json::from_value(valid.clone()).unwrap();
        assert!(expired.journal_marker().is_ok());
        for (field, value) in [
            ("output_digest", serde_json::json!("0".repeat(64))),
            ("delete_after_unix_ms", serde_json::json!(0)),
            ("encrypted_reference", serde_json::Value::Null),
            (
                "encrypted_reference",
                serde_json::json!("vault://bad\nreference"),
            ),
            (
                "encrypted_reference",
                serde_json::json!("r".repeat(MAX_REFERENCE_BYTES + 1)),
            ),
            ("ciphertext_digest", serde_json::Value::Null),
            ("ciphertext_digest", serde_json::json!("0".repeat(64))),
            ("encryption_key_id", serde_json::Value::Null),
            ("encryption_key_id", serde_json::json!("")),
            (
                "encryption_key_id",
                serde_json::json!("k".repeat(MAX_ID_BYTES + 1)),
            ),
            ("encryption_key_id", serde_json::json!("invalid key")),
            ("storage_mode", serde_json::json!("digest_only")),
        ] {
            let mut malformed = valid.clone();
            malformed[field] = value;
            let decoded: ProtectedOutput = serde_json::from_value(malformed).unwrap();
            assert!(
                decoded.journal_marker().is_err(),
                "accepted malformed {field}"
            );
        }
        let mut digest_only = valid;
        digest_only["storage_mode"] = serde_json::json!("digest_only");
        for field in [
            "encrypted_reference",
            "ciphertext_digest",
            "encryption_key_id",
        ] {
            digest_only[field] = serde_json::Value::Null;
        }
        let confidential: ProtectedOutput = serde_json::from_value(digest_only.clone()).unwrap();
        assert!(confidential.journal_marker().is_err());
        digest_only["classification"] = serde_json::json!("internal");
        let valid_digest_only: ProtectedOutput = serde_json::from_value(digest_only).unwrap();
        assert!(valid_digest_only.journal_marker().is_ok());
    }
}
