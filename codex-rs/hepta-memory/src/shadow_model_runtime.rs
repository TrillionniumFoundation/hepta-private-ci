//! Shadow-only compatibility seam for the E21/E22 model contracts.
//!
//! The current Rust [`crate::ModelReceipt`] is an attempt-chain receipt.  The
//! E21/S3a/E22 qualification schemas additionally describe a complete
//! `RunStartSnapshot` and, in their wire views, fields such as `run_id`,
//! `backend`, `device`, `invoked`, `outcome`, `head_digest`, and
//! `artifact_manifest_digest`.  Those are not interchangeable fields.  In
//! particular, an `artifact_sha256` must never be guessed to be a head or an
//! artifact-manifest digest.
//!
//! This module therefore binds the existing receipt to an explicit, local
//! snapshot without pretending to emit the E21/E22 wire objects.  Callers
//! must provide every snapshot digest explicitly.  The seam is useful for
//! deterministic shadow qualification and for finding stale/cross-run data;
//! it does not acquire a lease, invoke a model, install an artifact, or grant
//! runtime/effect authority.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::ModelReceipt;
use crate::ModelReceiptError;
use crate::framing::frame_part;

/// Version of this local compatibility envelope.
pub const SHADOW_MODEL_RUNTIME_SCHEMA_VERSION: u32 = 1;
/// Namespace fence: values in this module are qualification data only.
pub const SHADOW_MODEL_RUNTIME_NAMESPACE: &str = "local_qualification_only";
/// The current Rust receipt cannot satisfy the E21/E22 wire schemas by
/// itself.  Keep this list machine-readable for receipt/report generators.
pub const MODEL_RECEIPT_SCHEMA_GAPS: &[&str] = &[
    "run_id/receipt_id are not represented by the current attempt-chain receipt",
    "backend/device/invoked/outcome are not measured by the current receipt",
    "head_digest/tokenizer_digest/compiled_artifact_digest/operator_digest/sbom_digest require explicit future bindings",
    "artifact_manifest_digest is distinct from artifact_sha256 and must not be inferred",
    "E21/E22 wire objects are not emitted or registered by this compatibility seam",
];

/// A complete fence shape shared by E21, S3a, and the local H4/H7 identity
/// contracts.  This is a value copied from an already-owned qualification
/// context; constructing it does not acquire or renew a lease.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ShadowRunFence {
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub lease_expires_at: u64,
}

impl ShadowRunFence {
    /// Construct a fence value after checking the non-zero E21 identity
    /// fields.  The expiry is an observation, not a renewal operation.
    pub fn new(
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at: u64,
    ) -> Result<Self, ShadowModelRuntimeError> {
        let fence = Self {
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token: fencing_token.into(),
            lease_expires_at,
        };
        fence.validate()?;
        Ok(fence)
    }

    pub fn validate(&self) -> Result<(), ShadowModelRuntimeError> {
        if self.authority_epoch == 0
            || self.owner_epoch == 0
            || self.generation == 0
            || self.lease_expires_at == 0
        {
            return Err(ShadowModelRuntimeError::Invalid(
                "run fence epochs, generation, and expiry must be non-zero".to_string(),
            ));
        }
        validate_identifier(&self.fencing_token, "fencing token")
    }

    /// Return a deterministic digest of the complete fence tuple.
    ///
    /// A fencing token by itself is not sufficient to identify the snapshot
    /// that it protects: authority/owner epochs, generation, and the
    /// observed expiry are part of the local qualification boundary too.
    /// This digest is a pure value operation; it does not acquire, renew, or
    /// otherwise mutate a lease.
    pub fn digest(&self) -> Result<Sha256Digest, ShadowModelRuntimeError> {
        self.validate()?;
        let payload = ShadowRunFenceDigest {
            authority_epoch: self.authority_epoch,
            owner_epoch: self.owner_epoch,
            generation: self.generation,
            fencing_token: &self.fencing_token,
            lease_expires_at: self.lease_expires_at,
        };
        let bytes = serde_json::to_vec(&payload)
            .map_err(|error| ShadowModelRuntimeError::Serialization(error.to_string()))?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:shadow-run-fence:v1");
        frame_part(&mut hasher, &bytes);
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

#[derive(Serialize)]
struct ShadowRunFenceDigest<'a> {
    authority_epoch: u64,
    owner_epoch: u64,
    generation: u64,
    fencing_token: &'a str,
    lease_expires_at: u64,
}

/// Bounded resource values carried by a snapshot.  These are budgets, not
/// measurements or an admission grant.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ShadowResourceBudget {
    pub timeout_ms: u64,
    pub rss_kib: u64,
    pub energy_mj: u64,
}

impl ShadowResourceBudget {
    pub fn new(
        timeout_ms: u64,
        rss_kib: u64,
        energy_mj: u64,
    ) -> Result<Self, ShadowModelRuntimeError> {
        let budget = Self {
            timeout_ms,
            rss_kib,
            energy_mj,
        };
        budget.validate()?;
        Ok(budget)
    }

    pub fn validate(&self) -> Result<(), ShadowModelRuntimeError> {
        if self.timeout_ms == 0 || self.rss_kib == 0 || self.energy_mj == 0 {
            return Err(ShadowModelRuntimeError::Invalid(
                "resource budgets must be non-zero".to_string(),
            ));
        }
        Ok(())
    }
}

/// Privacy profile names accepted by the E21 contract.  There is no remote
/// or unrestricted profile in this module.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ShadowPrivacyProfile {
    #[serde(rename = "guard_deterministic")]
    GuardDeterministic,
    #[serde(rename = "privacy_local")]
    PrivacyLocal,
    #[serde(rename = "proposal_local")]
    ProposalLocal,
}

/// Execution scope carried only as a qualification annotation.  Both values
/// are non-effect scopes; no external-effect variant exists by construction.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub enum ShadowExecutionScope {
    #[serde(rename = "none")]
    None,
    #[serde(rename = "sandbox_activity")]
    SandboxActivity,
}

/// Input for constructing one immutable local snapshot.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunStartSnapshotInput {
    pub snapshot_id: String,
    pub run_id: String,
    pub definition_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub capability_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub initial_state_digest: Sha256Digest,
    pub graph_digest: Sha256Digest,
    pub model_registry_digest: Sha256Digest,
    pub model_digest: Sha256Digest,
    pub head_digest: Sha256Digest,
    pub calibration_digest: Sha256Digest,
    pub artifact_manifest_digest: Sha256Digest,
    pub logical_clock: u64,
    pub rng_seed: u64,
    pub fence: ShadowRunFence,
    pub privacy_profile: ShadowPrivacyProfile,
    pub resource_budget: ShadowResourceBudget,
    pub revision: u64,
    pub execution_scope: ShadowExecutionScope,
}

/// Superset identity envelope for the E21/E22 snapshot fields.
///
/// This is intentionally *not* declared as the E21 or E22 wire type: the
/// historical schemas have different required fields and different exact
/// constants.  Use it to validate the shared intersection, then create an
/// explicitly versioned wire projection in the owning qualification lane.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunStartSnapshot {
    pub schema_version: u32,
    pub namespace: String,
    pub snapshot_id: String,
    pub run_id: String,
    pub definition_digest: Sha256Digest,
    pub policy_digest: Sha256Digest,
    pub capability_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub initial_state_digest: Sha256Digest,
    pub graph_digest: Sha256Digest,
    pub model_registry_digest: Sha256Digest,
    pub model_digest: Sha256Digest,
    pub head_digest: Sha256Digest,
    pub calibration_digest: Sha256Digest,
    pub artifact_manifest_digest: Sha256Digest,
    pub logical_clock: u64,
    pub rng_seed: u64,
    pub fence: ShadowRunFence,
    pub privacy_profile: ShadowPrivacyProfile,
    pub resource_budget: ShadowResourceBudget,
    pub revision: u64,
    pub execution_scope: ShadowExecutionScope,
    pub runtime_authority: bool,
    pub snapshot_digest: Sha256Digest,
}

impl RunStartSnapshot {
    /// Build and validate a local snapshot.  This is a pure digest operation;
    /// it does not consult or mutate the lease/outbox store.
    pub fn qualification(input: RunStartSnapshotInput) -> Result<Self, ShadowModelRuntimeError> {
        let mut snapshot = Self {
            schema_version: SHADOW_MODEL_RUNTIME_SCHEMA_VERSION,
            namespace: SHADOW_MODEL_RUNTIME_NAMESPACE.to_string(),
            snapshot_id: input.snapshot_id,
            run_id: input.run_id,
            definition_digest: input.definition_digest,
            policy_digest: input.policy_digest,
            capability_digest: input.capability_digest,
            input_digest: input.input_digest,
            initial_state_digest: input.initial_state_digest,
            graph_digest: input.graph_digest,
            model_registry_digest: input.model_registry_digest,
            model_digest: input.model_digest,
            head_digest: input.head_digest,
            calibration_digest: input.calibration_digest,
            artifact_manifest_digest: input.artifact_manifest_digest,
            logical_clock: input.logical_clock,
            rng_seed: input.rng_seed,
            fence: input.fence,
            privacy_profile: input.privacy_profile,
            resource_budget: input.resource_budget,
            revision: input.revision,
            execution_scope: input.execution_scope,
            runtime_authority: false,
            snapshot_digest: Sha256Digest::for_bytes(b"uncomputed"),
        };
        snapshot.snapshot_digest = snapshot.compute_digest()?;
        snapshot.validate()?;
        Ok(snapshot)
    }

    pub fn validate(&self) -> Result<(), ShadowModelRuntimeError> {
        if self.schema_version != SHADOW_MODEL_RUNTIME_SCHEMA_VERSION
            || self.namespace != SHADOW_MODEL_RUNTIME_NAMESPACE
        {
            return Err(ShadowModelRuntimeError::SchemaMismatch);
        }
        validate_identifier(&self.snapshot_id, "snapshot id")?;
        validate_identifier(&self.run_id, "run id")?;
        for (digest, label) in [
            (&self.definition_digest, "definition digest"),
            (&self.policy_digest, "policy digest"),
            (&self.capability_digest, "capability digest"),
            (&self.input_digest, "input digest"),
            (&self.initial_state_digest, "initial state digest"),
            (&self.graph_digest, "graph digest"),
            (&self.model_registry_digest, "model registry digest"),
            (&self.model_digest, "model digest"),
            (&self.head_digest, "head digest"),
            (&self.calibration_digest, "calibration digest"),
            (&self.artifact_manifest_digest, "artifact manifest digest"),
            (&self.snapshot_digest, "snapshot digest"),
        ] {
            validate_digest(digest, label)?;
        }
        self.fence.validate()?;
        self.resource_budget.validate()?;
        if self.runtime_authority {
            return Err(ShadowModelRuntimeError::AuthorityBoundary);
        }
        if self.snapshot_digest != self.compute_digest()? {
            return Err(ShadowModelRuntimeError::DigestMismatch("snapshot"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, ShadowModelRuntimeError> {
        self.validate()?;
        Ok(self.snapshot_digest.clone())
    }

    pub fn is_shadow_only(&self) -> bool {
        self.namespace == SHADOW_MODEL_RUNTIME_NAMESPACE && !self.runtime_authority
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ShadowModelRuntimeError> {
        let payload = RunStartSnapshotDigest {
            schema_version: self.schema_version,
            namespace: &self.namespace,
            snapshot_id: &self.snapshot_id,
            run_id: &self.run_id,
            definition_digest: &self.definition_digest,
            policy_digest: &self.policy_digest,
            capability_digest: &self.capability_digest,
            input_digest: &self.input_digest,
            initial_state_digest: &self.initial_state_digest,
            graph_digest: &self.graph_digest,
            model_registry_digest: &self.model_registry_digest,
            model_digest: &self.model_digest,
            head_digest: &self.head_digest,
            calibration_digest: &self.calibration_digest,
            artifact_manifest_digest: &self.artifact_manifest_digest,
            logical_clock: self.logical_clock,
            rng_seed: self.rng_seed,
            fence: &self.fence,
            privacy_profile: self.privacy_profile,
            resource_budget: &self.resource_budget,
            revision: self.revision,
            execution_scope: self.execution_scope,
            runtime_authority: self.runtime_authority,
        };
        let bytes = serde_json::to_vec(&payload)
            .map_err(|error| ShadowModelRuntimeError::Serialization(error.to_string()))?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:shadow-run-start-snapshot:v1");
        frame_part(&mut hasher, &bytes);
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

#[derive(Serialize)]
struct RunStartSnapshotDigest<'a> {
    schema_version: u32,
    namespace: &'a str,
    snapshot_id: &'a str,
    run_id: &'a str,
    definition_digest: &'a Sha256Digest,
    policy_digest: &'a Sha256Digest,
    capability_digest: &'a Sha256Digest,
    input_digest: &'a Sha256Digest,
    initial_state_digest: &'a Sha256Digest,
    graph_digest: &'a Sha256Digest,
    model_registry_digest: &'a Sha256Digest,
    model_digest: &'a Sha256Digest,
    head_digest: &'a Sha256Digest,
    calibration_digest: &'a Sha256Digest,
    artifact_manifest_digest: &'a Sha256Digest,
    logical_clock: u64,
    rng_seed: u64,
    fence: &'a ShadowRunFence,
    privacy_profile: ShadowPrivacyProfile,
    resource_budget: &'a ShadowResourceBudget,
    revision: u64,
    execution_scope: ShadowExecutionScope,
    runtime_authority: bool,
}

/// A validated binding between the current Rust attempt-chain receipt and a
/// complete local snapshot.  Missing E21/E22 fields remain explicit gaps;
/// this type never synthesizes them.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ShadowModelRuntimeBinding {
    pub snapshot: RunStartSnapshot,
    pub model_receipt: ModelReceipt,
    pub binding_digest: Sha256Digest,
}

impl ShadowModelRuntimeBinding {
    pub fn bind(
        snapshot: RunStartSnapshot,
        model_receipt: ModelReceipt,
    ) -> Result<Self, ShadowModelRuntimeError> {
        let mut binding = Self {
            snapshot,
            model_receipt,
            binding_digest: Sha256Digest::for_bytes(b"uncomputed"),
        };
        binding.binding_digest = binding.compute_digest()?;
        binding.validate()?;
        Ok(binding)
    }

    pub fn validate(&self) -> Result<(), ShadowModelRuntimeError> {
        self.snapshot.validate()?;
        self.model_receipt.validate()?;
        if !self.model_receipt.is_shadow_only() {
            return Err(ShadowModelRuntimeError::AuthorityBoundary);
        }
        if self.model_receipt.snapshot_digest != self.snapshot.snapshot_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch("snapshot digest"));
        }
        if self.model_receipt.graph_digest != self.snapshot.graph_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch("graph digest"));
        }
        if self.model_receipt.input_digest != self.snapshot.input_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch("input digest"));
        }
        if self.model_receipt.policy_digest != self.snapshot.policy_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch("policy digest"));
        }
        if self.model_receipt.model_sha256 != self.snapshot.model_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch("model digest"));
        }
        if self.model_receipt.calibration_digest != self.snapshot.calibration_digest {
            return Err(ShadowModelRuntimeError::BindingMismatch(
                "calibration digest",
            ));
        }
        if self.model_receipt.fence_sha256 != self.snapshot.fence.digest()? {
            return Err(ShadowModelRuntimeError::BindingMismatch("fence digest"));
        }
        if self.binding_digest != self.compute_digest()? {
            return Err(ShadowModelRuntimeError::DigestMismatch("binding"));
        }
        Ok(())
    }

    pub fn digest(&self) -> Result<Sha256Digest, ShadowModelRuntimeError> {
        self.validate()?;
        Ok(self.binding_digest.clone())
    }

    pub fn is_shadow_only(&self) -> bool {
        self.snapshot.is_shadow_only() && self.model_receipt.is_shadow_only()
    }

    /// Return the fields that still need an owning E21/E22 wire adapter.
    /// Keeping this method explicit prevents a caller from silently treating
    /// the local attempt receipt as a complete model execution receipt.
    pub const fn schema_gaps() -> &'static [&'static str] {
        MODEL_RECEIPT_SCHEMA_GAPS
    }

    fn compute_digest(&self) -> Result<Sha256Digest, ShadowModelRuntimeError> {
        let payload = serde_json::to_vec(&(&self.snapshot, &self.model_receipt))
            .map_err(|error| ShadowModelRuntimeError::Serialization(error.to_string()))?;
        let mut hasher = Sha256::new();
        frame_part(&mut hasher, b"hepta:shadow-model-runtime-binding:v1");
        frame_part(&mut hasher, &payload);
        Ok(Sha256Digest::from_sha256_output(hasher.finalize()))
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Error)]
pub enum ShadowModelRuntimeError {
    #[error("invalid shadow model runtime value: {0}")]
    Invalid(String),
    #[error("shadow model runtime schema or namespace mismatch")]
    SchemaMismatch,
    #[error("shadow model runtime value crosses the authority boundary")]
    AuthorityBoundary,
    #[error("shadow model runtime digest mismatch for {0}")]
    DigestMismatch(&'static str),
    #[error("shadow model runtime binding mismatch for {0}")]
    BindingMismatch(&'static str),
    #[error(transparent)]
    ModelReceipt(#[from] ModelReceiptError),
    #[error("shadow model runtime serialization failed: {0}")]
    Serialization(String),
}

fn validate_digest(
    digest: &Sha256Digest,
    label: &'static str,
) -> Result<(), ShadowModelRuntimeError> {
    Sha256Digest::parse(digest.as_str().to_string())
        .map(|_| ())
        .map_err(|_| ShadowModelRuntimeError::DigestMismatch(label))
}

fn validate_identifier(value: &str, label: &'static str) -> Result<(), ShadowModelRuntimeError> {
    if value.trim().is_empty()
        || value.len() > 256
        || value.as_bytes().contains(&0)
        || value.chars().any(char::is_control)
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'/' | b'@' | b'-')
        })
    {
        return Err(ShadowModelRuntimeError::Invalid(format!(
            "{label} contains an invalid identifier"
        )));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &str) -> Sha256Digest {
        Sha256Digest::for_bytes(label.as_bytes())
    }

    fn fence() -> ShadowRunFence {
        ShadowRunFence::new(3, 4, 5, "fence-5", 9_999).expect("fence")
    }

    fn snapshot_input(label: &str) -> RunStartSnapshotInput {
        RunStartSnapshotInput {
            snapshot_id: format!("snapshot-{label}"),
            run_id: format!("run-{label}"),
            definition_digest: digest(&format!("{label}:definition")),
            policy_digest: digest(&format!("{label}:policy")),
            capability_digest: digest(&format!("{label}:capability")),
            input_digest: digest(&format!("{label}:input")),
            initial_state_digest: digest(&format!("{label}:state")),
            graph_digest: digest(&format!("{label}:graph")),
            model_registry_digest: digest(&format!("{label}:registry")),
            model_digest: digest(&format!("{label}:model")),
            head_digest: digest(&format!("{label}:head")),
            calibration_digest: digest(&format!("{label}:calibration")),
            artifact_manifest_digest: digest(&format!("{label}:manifest")),
            logical_clock: 7,
            rng_seed: 11,
            fence: fence(),
            privacy_profile: ShadowPrivacyProfile::PrivacyLocal,
            resource_budget: ShadowResourceBudget::new(100, 512, 1_000).expect("budget"),
            revision: 1,
            execution_scope: ShadowExecutionScope::SandboxActivity,
        }
    }

    fn model_receipt_with(
        snapshot: &RunStartSnapshot,
        input_digest: Sha256Digest,
        fence_sha256: Sha256Digest,
    ) -> ModelReceipt {
        ModelReceipt::qualification(
            "attempt-1",
            1,
            None,
            None,
            crate::ModelReceiptBindings {
                input_digest,
                output_digest: digest("output"),
                artifact_sha256: snapshot.artifact_manifest_digest.clone(),
                model_sha256: snapshot.model_digest.clone(),
                policy_digest: snapshot.policy_digest.clone(),
                graph_digest: snapshot.graph_digest.clone(),
                calibration_digest: snapshot.calibration_digest.clone(),
                evidence_digest: digest("evidence"),
                snapshot_digest: snapshot.snapshot_digest.clone(),
                causal_parent_sha256: None,
                fence_sha256,
            },
        )
        .expect("model receipt")
    }

    fn model_receipt(snapshot: &RunStartSnapshot) -> ModelReceipt {
        model_receipt_with(
            snapshot,
            snapshot.input_digest.clone(),
            snapshot.fence.digest().expect("fence digest"),
        )
    }

    #[test]
    fn snapshot_and_receipt_bind_deterministically() {
        let snapshot = RunStartSnapshot::qualification(snapshot_input("one")).expect("snapshot");
        let receipt = model_receipt(&snapshot);
        let binding = ShadowModelRuntimeBinding::bind(snapshot.clone(), receipt).expect("binding");
        assert!(binding.is_shadow_only());
        assert_eq!(binding.digest().expect("digest"), binding.binding_digest);
        let encoded = serde_json::to_vec(&binding).expect("encode");
        let decoded: ShadowModelRuntimeBinding = serde_json::from_slice(&encoded).expect("decode");
        assert_eq!(decoded, binding);
        assert_eq!(
            snapshot,
            RunStartSnapshot::qualification(snapshot_input("one")).expect("same")
        );
    }

    #[test]
    fn snapshot_digest_tampering_is_rejected() {
        let snapshot = RunStartSnapshot::qualification(snapshot_input("tamper")).expect("snapshot");
        let mut tampered = snapshot;
        tampered.graph_digest = digest("other-graph");
        assert_eq!(
            tampered.validate(),
            Err(ShadowModelRuntimeError::DigestMismatch("snapshot"))
        );
    }

    #[test]
    fn cross_snapshot_receipt_is_rejected() {
        let first = RunStartSnapshot::qualification(snapshot_input("first")).expect("first");
        let second = RunStartSnapshot::qualification(snapshot_input("second")).expect("second");
        let receipt = model_receipt(&first);
        assert_eq!(
            ShadowModelRuntimeBinding::bind(second, receipt),
            Err(ShadowModelRuntimeError::BindingMismatch("snapshot digest"))
        );
    }

    #[test]
    fn model_and_policy_cross_bindings_are_rejected() {
        let snapshot =
            RunStartSnapshot::qualification(snapshot_input("binding")).expect("snapshot");
        let mut receipt = model_receipt(&snapshot);
        receipt.model_sha256 = digest("other-model");
        assert_eq!(
            ShadowModelRuntimeBinding::bind(snapshot.clone(), receipt),
            Err(ShadowModelRuntimeError::ModelReceipt(
                ModelReceiptError::DigestMismatch("receipt")
            ))
        );

        let mut receipt = model_receipt(&snapshot);
        receipt.policy_digest = digest("other-policy");
        assert_eq!(
            ShadowModelRuntimeBinding::bind(snapshot, receipt),
            Err(ShadowModelRuntimeError::ModelReceipt(
                ModelReceiptError::DigestMismatch("receipt")
            ))
        );
    }

    #[test]
    fn model_receipt_input_and_fence_are_exactly_bound() {
        let snapshot =
            RunStartSnapshot::qualification(snapshot_input("exact-binding")).expect("snapshot");

        let input_tampered = model_receipt_with(
            &snapshot,
            digest("other-input"),
            snapshot.fence.digest().expect("fence digest"),
        );
        assert_eq!(
            ShadowModelRuntimeBinding::bind(snapshot.clone(), input_tampered),
            Err(ShadowModelRuntimeError::BindingMismatch("input digest"))
        );

        let fence_tampered = model_receipt_with(
            &snapshot,
            snapshot.input_digest.clone(),
            digest("other-fence"),
        );
        assert_eq!(
            ShadowModelRuntimeBinding::bind(snapshot, fence_tampered),
            Err(ShadowModelRuntimeError::BindingMismatch("fence digest"))
        );
    }

    #[test]
    fn fence_digest_changes_with_each_identity_field() {
        let original = fence();
        let original_digest = original.digest().expect("digest");

        for (authority_epoch, owner_epoch, generation, token, expiry) in [
            (4, 4, 5, "fence-5", 9_999),
            (3, 5, 5, "fence-5", 9_999),
            (3, 4, 6, "fence-5", 9_999),
            (3, 4, 5, "fence-6", 9_999),
            (3, 4, 5, "fence-5", 10_000),
        ] {
            let changed =
                ShadowRunFence::new(authority_epoch, owner_epoch, generation, token, expiry)
                    .expect("changed fence");
            assert_ne!(changed.digest().expect("changed digest"), original_digest);
        }
    }

    #[test]
    fn authority_and_fence_fail_closed() {
        let snapshot =
            RunStartSnapshot::qualification(snapshot_input("authority")).expect("snapshot");
        let mut authority = snapshot;
        authority.runtime_authority = true;
        assert_eq!(
            authority.validate(),
            Err(ShadowModelRuntimeError::AuthorityBoundary)
        );
        assert_eq!(
            ShadowRunFence::new(0, 1, 1, "fence", 10),
            Err(ShadowModelRuntimeError::Invalid(
                "run fence epochs, generation, and expiry must be non-zero".to_string()
            ))
        );
    }

    #[test]
    fn schema_gaps_remain_explicit_and_unknown_fields_reject() {
        assert!(
            ShadowModelRuntimeBinding::schema_gaps()
                .iter()
                .any(|gap| gap.contains("artifact_manifest_digest"))
        );
        let snapshot =
            RunStartSnapshot::qualification(snapshot_input("unknown")).expect("snapshot");
        let mut json = serde_json::to_value(&snapshot).expect("json");
        json["production_writer"] = serde_json::json!(true);
        assert!(serde_json::from_value::<RunStartSnapshot>(json).is_err());
    }
}
