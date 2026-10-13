//! Generic artifact, reload, execution and evaluation owner for learned roles.
//!
//! This module is intentionally a thin owner around the existing runtime and
//! role adapters.  It does not create a second runtime, a second store, or an
//! activation path.  A caller supplies the already materialized parameter
//! manifest, checkpoint/reload receipts and the typed role step produced by
//! the existing owner.  The owner binds those facts to one replayable record
//! for Representation, Predictor, Value, Decision or Evaluator roles.
//!
//! `MemoryRead` has a dedicated owner because its retrieval snapshot and
//! provenance have additional semantics.  `Plasticity` remains an update
//! proposal owner and is deliberately not admitted by this generic facade.

use std::error::Error;
use std::fmt;

use codex_hepta_cell_roles::CellRoleGateErrorV1;
use codex_hepta_cell_roles::CellRoleMetricProfileV1;
use codex_hepta_cell_roles::CellRoleMetricReceiptV1;
use codex_hepta_cell_roles::CellRoleStepV1;
use codex_hepta_cell_roles::RoleMetricAcceptancePolicyV1;
use codex_hepta_cell_roles::RoleMetricDecisionReceiptV1;
use codex_hepta_cell_roles::RoleMetricPolicyErrorV1;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::VerifyingKey;

use crate::ArtifactLoadReceiptV1;
use crate::ArtifactRegistry;
use crate::ArtifactWriteReceiptV1;
use crate::CellArtifactOwnerErrorV1;
use crate::CellParameterBundleManifestV1;
use crate::StateCommitReceiptV1;

pub const TYPED_ROLE_ARTIFACT_SCHEMA_V1: &str = "hepta.typed-role.artifact.v1";
pub const TYPED_ROLE_STEP_SCHEMA_V1: &str = "hepta.typed-role.step.v1";
pub const TYPED_ROLE_EVALUATION_SCHEMA_V1: &str = "hepta.typed-role.evaluation.v1";

/// External owner facts that accompany a typed artifact.  Keeping these
/// receipts in one value object prevents callers from accidentally omitting
/// a CAS, registry, checkpoint or reload witness.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TypedRoleArtifactEvidenceV1 {
    pub provenance_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
}

impl TypedRoleArtifactEvidenceV1 {
    fn validate(&self) -> Result<(), TypedRoleOwnerErrorV1> {
        for (label, digest) in [
            ("provenance", self.provenance_digest),
            ("CAS receipt", self.cas_receipt_digest),
            ("registry receipt", self.registry_receipt_digest),
            ("state checkpoint", self.state_checkpoint_digest),
            ("reload receipt", self.reload_receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        Ok(())
    }
}

/// Roles whose model/state owner can use the generic facade.  MemoryRead has
/// a specialized retrieval owner and Plasticity has a candidate/update owner.
#[must_use]
pub const fn is_generic_learned_role(role: CellRoleV1) -> bool {
    matches!(
        role,
        CellRoleV1::Representation
            | CellRoleV1::Predictor
            | CellRoleV1::Value
            | CellRoleV1::Decision
            | CellRoleV1::Evaluator
    )
}

/// Immutable binding between a formal role definition and its externally
/// materialized parameter/state facts.  The payload itself remains owned by
/// the CAS; this object only binds its digest to the durable manifest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleArtifactV1 {
    pub definition: CellDefinitionV2,
    pub parameter_manifest: CellParameterBundleManifestV1,
    pub provenance_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
    pub artifact_digest: Digest32,
}

impl TypedRoleArtifactV1 {
    pub fn validate(&self) -> Result<(), TypedRoleOwnerErrorV1> {
        self.definition.validate()?;
        if !is_generic_learned_role(self.definition.role) {
            return Err(TypedRoleOwnerErrorV1::UnsupportedRole(self.definition.role));
        }
        self.parameter_manifest.validate()?;
        if self.parameter_manifest.cell_id != self.definition.cell_id
            || self.parameter_manifest.generation != self.definition.generation
            || self.parameter_manifest.scope_digest != self.definition.scope_digest
            || self.parameter_manifest.lineage_digest != self.definition.lineage_digest
            || self.parameter_manifest.objective_digest != self.definition.objective_digest
            || self.parameter_manifest.child_bundle_digest
                != self.definition.parameter_bundle_digest
            || self.parameter_manifest.definition_digest != self.definition_digest()?
        {
            return Err(TypedRoleOwnerErrorV1::ArtifactBinding);
        }
        TypedRoleArtifactEvidenceV1 {
            provenance_digest: self.provenance_digest,
            cas_receipt_digest: self.cas_receipt_digest,
            registry_receipt_digest: self.registry_receipt_digest,
            state_checkpoint_digest: self.state_checkpoint_digest,
            reload_receipt_digest: self.reload_receipt_digest,
        }
        .validate()?;
        if self.artifact_digest != self.content_digest()? {
            return Err(TypedRoleOwnerErrorV1::ArtifactDigestMismatch);
        }
        Ok(())
    }

    pub fn definition_digest(&self) -> Result<Digest32, TypedRoleOwnerErrorV1> {
        self.definition
            .content_digest()
            .map_err(TypedRoleOwnerErrorV1::Contract)
    }

    pub fn content_digest(&self) -> Result<Digest32, TypedRoleOwnerErrorV1> {
        let definition = self.definition_digest()?;
        let mut bytes = Vec::with_capacity(32 * 7 + TYPED_ROLE_ARTIFACT_SCHEMA_V1.len());
        bytes.extend_from_slice(TYPED_ROLE_ARTIFACT_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(definition.as_array());
        bytes.extend_from_slice(self.parameter_manifest.manifest_digest.as_array());
        bytes.extend_from_slice(self.provenance_digest.as_array());
        bytes.extend_from_slice(self.cas_receipt_digest.as_array());
        bytes.extend_from_slice(self.registry_receipt_digest.as_array());
        bytes.extend_from_slice(self.state_checkpoint_digest.as_array());
        bytes.extend_from_slice(self.reload_receipt_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Publication/reload receipt.  It records that a real owner supplied the
/// manifest, checkpoint and reload witness; it does not grant activation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleArtifactReceiptV1 {
    pub artifact_digest: Digest32,
    pub definition_digest: Digest32,
    pub parameter_manifest_digest: Digest32,
    pub provenance_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
    pub owner_id: StableId,
    pub receipt_digest: Digest32,
}

impl TypedRoleArtifactReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &TypedRoleArtifactV1,
    ) -> Result<(), TypedRoleOwnerErrorV1> {
        artifact.validate()?;
        if self.artifact_digest != artifact.artifact_digest
            || self.definition_digest != artifact.definition_digest()?
            || self.parameter_manifest_digest != artifact.parameter_manifest.manifest_digest
            || self.provenance_digest != artifact.provenance_digest
            || self.cas_receipt_digest != artifact.cas_receipt_digest
            || self.registry_receipt_digest != artifact.registry_receipt_digest
            || self.state_checkpoint_digest != artifact.state_checkpoint_digest
            || self.reload_receipt_digest != artifact.reload_receipt_digest
            || self.owner_id.as_str().is_empty()
            || self.receipt_digest != self.content_digest()
        {
            return Err(TypedRoleOwnerErrorV1::ReceiptBinding);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 8 + self.owner_id.as_str().len());
        bytes.extend_from_slice(TYPED_ROLE_ARTIFACT_SCHEMA_V1.as_bytes());
        for digest in [
            self.artifact_digest,
            self.definition_digest,
            self.parameter_manifest_digest,
            self.provenance_digest,
            self.cas_receipt_digest,
            self.registry_receipt_digest,
            self.state_checkpoint_digest,
            self.reload_receipt_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        append_id(&mut bytes, &self.owner_id);
        Digest32::of_bytes(&bytes)
    }
}

/// A generic role-step receipt.  The role adapter remains the source of the
/// typed result; this wrapper binds it to the immutable artifact and records
/// a deterministic replay digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleStepReceiptV1 {
    pub artifact_digest: Digest32,
    pub cell_step_receipt: CellStepReceiptV1,
    pub replay_digest: Digest32,
}

impl TypedRoleStepReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &TypedRoleArtifactV1,
    ) -> Result<(), TypedRoleOwnerErrorV1> {
        artifact.validate()?;
        let step = &self.cell_step_receipt;
        if self.artifact_digest != artifact.artifact_digest
            || !is_generic_learned_role(step.role)
            || step.role != artifact.definition.role
            || step.cell_id != artifact.definition.cell_id
            || step.generation != artifact.definition.generation
            || step.scope_digest != artifact.definition.scope_digest
            || step.capability_digest != artifact.definition.capability_digest()?
            || self.replay_digest != self.content_digest()
        {
            return Err(TypedRoleOwnerErrorV1::StepBinding);
        }
        step.validate()?;
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 3 + TYPED_ROLE_STEP_SCHEMA_V1.len());
        bytes.extend_from_slice(TYPED_ROLE_STEP_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(self.artifact_digest.as_array());
        bytes.extend_from_slice(
            self.cell_step_receipt
                .content_digest()
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        );
        Digest32::of_bytes(&bytes)
    }
}

/// Generic role evaluation receipt.  It deliberately carries no retain,
/// promote or production-qualified bit.  Those decisions remain with the
/// independent evaluator and durable learning ledger.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleEvaluationReceiptV1 {
    pub artifact_digest: Digest32,
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub profile_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub baseline_digest: Digest32,
    pub future_window_digest: Digest32,
    pub evaluator_id: StableId,
    pub evidence_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl TypedRoleEvaluationReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &TypedRoleArtifactV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<(), TypedRoleOwnerErrorV1> {
        artifact.validate()?;
        metrics.validate_structure_against(profile)?;
        if !is_generic_learned_role(profile.role)
            || self.artifact_digest != artifact.artifact_digest
            || self.cell_id != artifact.definition.cell_id
            || self.generation != artifact.definition.generation
            || self.role != artifact.definition.role
            || self.role != profile.role
            || self.profile_digest != profile.content_digest()?
            || self.metric_receipt_digest != metrics.content_digest(profile)?
            || self.baseline_digest != profile.no_change_baseline_digest
            || self.future_window_digest != profile.future_window_digest
            || self.evaluator_id != metrics.evaluator_id
            || self.evidence_digest != metrics.evidence_digest
            || self.evidence_digest.is_zero()
            || self.receipt_digest != self.content_digest()
        {
            return Err(TypedRoleOwnerErrorV1::EvaluationBinding);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 7 + self.cell_id.as_str().len());
        bytes.extend_from_slice(TYPED_ROLE_EVALUATION_SCHEMA_V1.as_bytes());
        for digest in [
            self.artifact_digest,
            self.profile_digest,
            self.metric_receipt_digest,
            self.baseline_digest,
            self.future_window_digest,
            self.evidence_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.push(self.role.tag());
        append_id(&mut bytes, &self.cell_id);
        append_id(&mut bytes, &self.evaluator_id);
        Digest32::of_bytes(&bytes)
    }
}

/// Reusable owner facade for Representation/Predictor/Value/Decision/Evaluator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleArtifactOwnerV1 {
    pub owner_id: StableId,
}

impl TypedRoleArtifactOwnerV1 {
    pub fn new(owner_id: StableId) -> Result<Self, TypedRoleOwnerErrorV1> {
        if owner_id.as_str().is_empty() {
            return Err(TypedRoleOwnerErrorV1::EmptyId("owner"));
        }
        Ok(Self { owner_id })
    }

    pub fn bind(
        &self,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        evidence: TypedRoleArtifactEvidenceV1,
    ) -> Result<(TypedRoleArtifactV1, TypedRoleArtifactReceiptV1), TypedRoleOwnerErrorV1> {
        evidence.validate()?;
        let mut artifact = TypedRoleArtifactV1 {
            definition,
            parameter_manifest,
            provenance_digest: evidence.provenance_digest,
            cas_receipt_digest: evidence.cas_receipt_digest,
            registry_receipt_digest: evidence.registry_receipt_digest,
            state_checkpoint_digest: evidence.state_checkpoint_digest,
            reload_receipt_digest: evidence.reload_receipt_digest,
            artifact_digest: Digest32::ZERO,
        };
        artifact.artifact_digest = artifact.content_digest()?;
        artifact.validate()?;
        let mut receipt = TypedRoleArtifactReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            definition_digest: artifact.definition_digest()?,
            parameter_manifest_digest: artifact.parameter_manifest.manifest_digest,
            provenance_digest: evidence.provenance_digest,
            cas_receipt_digest: evidence.cas_receipt_digest,
            registry_receipt_digest: evidence.registry_receipt_digest,
            state_checkpoint_digest: evidence.state_checkpoint_digest,
            reload_receipt_digest: evidence.reload_receipt_digest,
            owner_id: self.owner_id.clone(),
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate_against(&artifact)?;
        Ok((artifact, receipt))
    }

    /// Require an exact durable-registry projection before accepting the
    /// typed artifact as production-side input.
    pub fn bind_registered(
        &self,
        registry: &ArtifactRegistry,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        evidence: TypedRoleArtifactEvidenceV1,
    ) -> Result<(TypedRoleArtifactV1, TypedRoleArtifactReceiptV1), TypedRoleOwnerErrorV1> {
        parameter_manifest.validate()?;
        if registry.manifest(&parameter_manifest.artifact_id)
            != Some(&parameter_manifest.as_registry_manifest())
            || !registry.is_eligible(&parameter_manifest.artifact_id)
        {
            return Err(TypedRoleOwnerErrorV1::RegistryBinding);
        }
        self.bind(definition, parameter_manifest, evidence)
    }

    /// Bind a learned-role artifact from the signed CAS/load/state owners.
    /// This is the production path: the generic facade cannot be satisfied by
    /// manually supplying five unrelated digests.  The host and independent
    /// observer evidence gates are applied before the role artifact is
    /// admitted to the registry projection.
    #[allow(clippy::too_many_arguments)]
    pub fn bind_production(
        &self,
        registry: &ArtifactRegistry,
        key: &VerifyingKey,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        write: &ArtifactWriteReceiptV1,
        load: &ArtifactLoadReceiptV1,
        state: &StateCommitReceiptV1,
    ) -> Result<(TypedRoleArtifactV1, TypedRoleArtifactReceiptV1), TypedRoleOwnerErrorV1> {
        write
            .verify_production(key)
            .map_err(|_| TypedRoleOwnerErrorV1::ArtifactBinding)?;
        load.verify_production(key)
            .map_err(|_| TypedRoleOwnerErrorV1::ArtifactBinding)?;
        state
            .verify_production(key)
            .map_err(|_| TypedRoleOwnerErrorV1::ArtifactBinding)?;
        if write.artifact_id != parameter_manifest.artifact_id
            || write.artifact_digest != load.artifact_digest
            || write.artifact_digest != parameter_manifest.child_bundle_digest
            || load.artifact_id != parameter_manifest.artifact_id
            || load.registry_head_digest != write.registry_head_digest
            || state.cell_id != definition.cell_id
            || state.generation != definition.generation
            || state.state_schema_digest != definition.state_schema_digest
        {
            return Err(TypedRoleOwnerErrorV1::ArtifactBinding);
        }
        let evidence = TypedRoleArtifactEvidenceV1 {
            provenance_digest: Digest32::of_parts(&[
                b"hepta.typed-role.production-provenance.v1",
                write.content_digest().as_array(),
                load.content_digest().as_array(),
                state.content_digest().as_array(),
            ]),
            cas_receipt_digest: write.content_digest(),
            registry_receipt_digest: load.registry_head_digest,
            state_checkpoint_digest: state.content_digest(),
            reload_receipt_digest: load.content_digest(),
        };
        self.bind_registered(registry, definition, parameter_manifest, evidence)
    }

    /// Join a role adapter's immutable step to the artifact owner.  The
    /// runtime and adapter remain external; this method only creates the
    /// durable boundary receipt.
    pub fn record_step(
        &self,
        artifact: &TypedRoleArtifactV1,
        step: &CellStepReceiptV1,
    ) -> Result<TypedRoleStepReceiptV1, TypedRoleOwnerErrorV1> {
        artifact.validate()?;
        step.validate()?;
        if !is_generic_learned_role(step.role)
            || step.role != artifact.definition.role
            || step.cell_id != artifact.definition.cell_id
            || step.generation != artifact.definition.generation
            || step.scope_digest != artifact.definition.scope_digest
            || step.capability_digest != artifact.definition.capability_digest()?
        {
            return Err(TypedRoleOwnerErrorV1::StepBinding);
        }
        let mut receipt = TypedRoleStepReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            cell_step_receipt: step.clone(),
            replay_digest: Digest32::ZERO,
        };
        receipt.replay_digest = receipt.content_digest();
        receipt.validate_against(artifact)?;
        Ok(receipt)
    }

    /// Accept a step directly from any existing typed role adapter.  The
    /// generic result is intentionally ignored by this persistence owner: the
    /// role adapter remains responsible for its typed value, while this owner
    /// binds the immutable receipt to artifact/state evidence.
    pub fn record_adapter_step<T>(
        &self,
        artifact: &TypedRoleArtifactV1,
        step: &CellRoleStepV1<T>,
    ) -> Result<TypedRoleStepReceiptV1, TypedRoleOwnerErrorV1> {
        self.record_step(artifact, &step.receipt)
    }

    /// Re-run the existing adapter/runtime and compare its new immutable step
    /// with the prior owner receipt.  No state or route mutation occurs here.
    pub fn replay_step(
        &self,
        artifact: &TypedRoleArtifactV1,
        expected: &TypedRoleStepReceiptV1,
        actual_step: &CellStepReceiptV1,
    ) -> Result<(), TypedRoleOwnerErrorV1> {
        expected.validate_against(artifact)?;
        let actual = self.record_step(artifact, actual_step)?;
        if actual != *expected {
            return Err(TypedRoleOwnerErrorV1::ReplayMismatch);
        }
        Ok(())
    }

    /// Replay helper for callers that have re-run an existing typed adapter.
    pub fn replay_adapter_step<T>(
        &self,
        artifact: &TypedRoleArtifactV1,
        expected: &TypedRoleStepReceiptV1,
        actual_step: &CellRoleStepV1<T>,
    ) -> Result<(), TypedRoleOwnerErrorV1> {
        self.replay_step(artifact, expected, &actual_step.receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TypedRoleEvaluationOwnerV1 {
    pub evaluator_id: StableId,
}

impl TypedRoleEvaluationOwnerV1 {
    pub fn new(evaluator_id: StableId) -> Result<Self, TypedRoleOwnerErrorV1> {
        if evaluator_id.as_str().is_empty() {
            return Err(TypedRoleOwnerErrorV1::EmptyId("evaluator"));
        }
        Ok(Self { evaluator_id })
    }

    pub fn record(
        &self,
        artifact: &TypedRoleArtifactV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<TypedRoleEvaluationReceiptV1, TypedRoleOwnerErrorV1> {
        artifact.validate()?;
        metrics.validate_structure_against(profile)?;
        if metrics.role != artifact.definition.role
            || metrics.cell_id != artifact.definition.cell_id
            || metrics.generation != artifact.definition.generation
            || metrics.evaluator_id != self.evaluator_id
        {
            return Err(TypedRoleOwnerErrorV1::EvaluationBinding);
        }
        let mut receipt = TypedRoleEvaluationReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            cell_id: artifact.definition.cell_id.clone(),
            generation: artifact.definition.generation,
            role: artifact.definition.role,
            profile_digest: profile.content_digest()?,
            metric_receipt_digest: metrics.content_digest(profile)?,
            baseline_digest: profile.no_change_baseline_digest,
            future_window_digest: profile.future_window_digest,
            evaluator_id: self.evaluator_id.clone(),
            evidence_digest: metrics.evidence_digest,
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate_against(artifact, profile, metrics)?;
        Ok(receipt)
    }

    /// Execute the frozen role policy as an independent evaluator and return
    /// both the artifact-bound evaluation receipt and the authority-free
    /// threshold decision.  Retain/quarantine/activation remains outside
    /// this owner.
    pub fn evaluate_policy(
        &self,
        artifact: &TypedRoleArtifactV1,
        profile: &CellRoleMetricProfileV1,
        policy: &RoleMetricAcceptancePolicyV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<(TypedRoleEvaluationReceiptV1, RoleMetricDecisionReceiptV1), TypedRoleOwnerErrorV1>
    {
        let evaluation = self.record(artifact, profile, metrics)?;
        let decision = policy
            .evaluate(profile, metrics)
            .map_err(TypedRoleOwnerErrorV1::Policy)?;
        Ok((evaluation, decision))
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum TypedRoleOwnerErrorV1 {
    Contract(CellRoleContractErrorV1),
    Metric(CellRoleGateErrorV1),
    Policy(RoleMetricPolicyErrorV1),
    Artifact(CellArtifactOwnerErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    UnsupportedRole(CellRoleV1),
    ArtifactBinding,
    ArtifactDigestMismatch,
    ReceiptBinding,
    StepBinding,
    RegistryBinding,
    ReplayMismatch,
    EvaluationBinding,
}

impl fmt::Display for TypedRoleOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for TypedRoleOwnerErrorV1 {}

impl From<CellRoleContractErrorV1> for TypedRoleOwnerErrorV1 {
    fn from(value: CellRoleContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

impl From<CellRoleGateErrorV1> for TypedRoleOwnerErrorV1 {
    fn from(value: CellRoleGateErrorV1) -> Self {
        Self::Metric(value)
    }
}

impl From<RoleMetricPolicyErrorV1> for TypedRoleOwnerErrorV1 {
    fn from(value: RoleMetricPolicyErrorV1) -> Self {
        Self::Policy(value)
    }
}

impl From<CellArtifactOwnerErrorV1> for TypedRoleOwnerErrorV1 {
    fn from(value: CellArtifactOwnerErrorV1) -> Self {
        Self::Artifact(value)
    }
}

fn require_digest(value: Digest32, label: &'static str) -> Result<(), TypedRoleOwnerErrorV1> {
    if value.is_zero() {
        Err(TypedRoleOwnerErrorV1::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn append_id(bytes: &mut Vec<u8>, id: &StableId) {
    let value = id.as_str().as_bytes();
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value);
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::ArtifactCasOwnerV1;
    use crate::ArtifactEvent;
    use crate::ArtifactKind;
    use crate::ArtifactManifest;
    use crate::ArtifactRegistry;
    use crate::StateCheckpointOwnerV1;
    use codex_hepta_cell_roles::CellRoleMetricKindV1;
    use codex_hepta_cell_roles::CellRoleMetricV1;
    use codex_hepta_cell_roles::RoleMetricDecisionDispositionV1;
    use codex_hepta_cell_roles::RoleMetricDirectionV1;
    use codex_hepta_cell_roles::RoleMetricThresholdV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::CellStepStatusV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn definition(role: CellRoleV1) -> CellDefinitionV2 {
        let owner = id("hepta.role::owner");
        let fallback_role = if role == CellRoleV1::Representation {
            Some(CellRoleV1::MemoryRead)
        } else {
            Some(CellRoleV1::Representation)
        };
        let profile = CellCapabilityProfileV1 {
            role,
            observation_schema_digest: digest(1),
            output_schema_digest: digest(2),
            state_schema_digest: digest(3),
            input_port_digest: digest(4),
            output_port_digest: digest(5),
            termination_port_digest: digest(6),
            owner_module: owner.clone(),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::OutcomeProposal,
            fallback_role,
            objective_digest: digest(7),
            resource_budget_digest: digest(8),
            evaluation_profile_digest: digest(9),
            authority: AuthorityPosture::DENY_ALL,
        };
        CellDefinitionV2 {
            cell_id: id("cell.typed-role.1"),
            generation: Generation::new(2).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role,
            state_schema_digest: profile.state_schema_digest,
            parameter_bundle_digest: digest(12),
            port_abi_digest: digest(13),
            owner_module: owner,
            objective_digest: profile.objective_digest,
            fallback_role: profile.fallback_role,
            evidence_owner: id("observer.typed-role"),
            capability_profile: profile,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn manifest(definition: &CellDefinitionV2) -> CellParameterBundleManifestV1 {
        let mut value = CellParameterBundleManifestV1 {
            artifact_id: definition.cell_id.clone(),
            cell_id: definition.cell_id.clone(),
            parent_artifact_id: id("cell.typed-role.parent"),
            generation: definition.generation,
            parent_bundle_digest: digest(20),
            child_bundle_digest: definition.parameter_bundle_digest,
            scope_digest: definition.scope_digest,
            definition_digest: definition.content_digest().expect("definition"),
            lineage_digest: definition.lineage_digest,
            objective_digest: definition.objective_digest,
            compatibility_digest: digest(21),
            inheritance_digest: digest(22),
            split_digest: digest(23),
            producer_id: id("producer.typed-role"),
            encoded_size_bytes: 128,
            manifest_digest: Digest32::ZERO,
        };
        value.manifest_digest = value.content_digest();
        value
    }

    fn step(definition: &CellDefinitionV2) -> CellStepReceiptV1 {
        CellStepReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: definition.role,
            capability_digest: definition.capability_digest().expect("capability"),
            input_frontier_digest: digest(31),
            state_predecessor_digest: digest(32),
            state_successor_digest: digest(33),
            output_digest: digest(34),
            uncertainty_ppm: 10,
            ood_ppm: 20,
            resource_receipt_digest: digest(35),
            evidence_digest: digest(36),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn evidence() -> TypedRoleArtifactEvidenceV1 {
        TypedRoleArtifactEvidenceV1 {
            provenance_digest: digest(40),
            cas_receipt_digest: digest(41),
            registry_receipt_digest: digest(42),
            state_checkpoint_digest: digest(43),
            reload_receipt_digest: digest(44),
        }
    }

    fn artifact(role: CellRoleV1) -> (TypedRoleArtifactV1, TypedRoleArtifactReceiptV1) {
        let definition = definition(role);
        TypedRoleArtifactOwnerV1::new(id("owner.typed-role"))
            .expect("owner")
            .bind(definition.clone(), manifest(&definition), evidence())
            .expect("artifact")
    }

    #[test]
    fn artifact_rejects_dedicated_or_control_roles() {
        for role in [
            CellRoleV1::MemoryRead,
            CellRoleV1::Plasticity,
            CellRoleV1::Router,
        ] {
            let definition = definition(role);
            let result = TypedRoleArtifactOwnerV1::new(id("owner.typed-role"))
                .expect("owner")
                .bind(definition.clone(), manifest(&definition), evidence());
            assert!(matches!(
                result,
                Err(TypedRoleOwnerErrorV1::UnsupportedRole(actual)) if actual == role
            ));
        }
    }

    #[test]
    fn artifact_owner_accepts_every_generic_learned_role() {
        for role in [
            CellRoleV1::Representation,
            CellRoleV1::Predictor,
            CellRoleV1::Value,
            CellRoleV1::Decision,
            CellRoleV1::Evaluator,
        ] {
            let (artifact, receipt) = artifact(role);
            artifact.validate().expect("artifact");
            receipt.validate_against(&artifact).expect("receipt");
            let owner = TypedRoleArtifactOwnerV1::new(id("owner.typed-role")).expect("owner");
            let adapter_step = CellRoleStepV1 {
                result: (),
                receipt: step(&artifact.definition),
            };
            let step = owner
                .record_adapter_step(&artifact, &adapter_step)
                .expect("step");
            owner
                .replay_adapter_step(&artifact, &step, &adapter_step)
                .expect("replay");
        }
    }

    #[test]
    fn registered_artifact_step_and_replay_are_deterministic() {
        let role = CellRoleV1::Predictor;
        let definition = definition(role);
        let parameter_manifest = manifest(&definition);
        let parent = ArtifactManifest {
            artifact_id: parameter_manifest.parent_artifact_id.clone(),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: parameter_manifest.parent_bundle_digest,
            objective_digest: parameter_manifest.objective_digest,
            support_digest: parameter_manifest.lineage_digest,
            producer_id: id("producer.typed-role-parent"),
            compatibility_digest: parameter_manifest.compatibility_digest,
            encoded_size_bytes: 128,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.typed-role-parent"),
                manifest: parent,
            })
            .expect("parent");
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.typed-role-child"),
                manifest: parameter_manifest.as_registry_manifest(),
            })
            .expect("child");
        let owner = TypedRoleArtifactOwnerV1::new(id("owner.typed-role")).expect("owner");
        let (artifact, receipt) = owner
            .bind_registered(
                &registry,
                definition.clone(),
                parameter_manifest,
                evidence(),
            )
            .expect("registered artifact");
        receipt.validate_against(&artifact).expect("receipt");
        let step = step(&definition);
        let execution = owner.record_step(&artifact, &step).expect("step");
        execution.validate_against(&artifact).expect("step receipt");
        owner
            .replay_step(&artifact, &execution, &step)
            .expect("replay");
        let mut changed = step;
        changed.output_digest = digest(99);
        assert_eq!(
            owner.replay_step(&artifact, &execution, &changed),
            Err(TypedRoleOwnerErrorV1::ReplayMismatch)
        );
    }

    #[test]
    fn production_artifact_state_lifecycle_binds_as_one_role_owner_input() {
        let key = ed25519_dalek::SigningKey::from_bytes(&[91; 32]);
        let mut definition = definition(CellRoleV1::Representation);
        let payload = b"representation-parameters-v1";
        definition.parameter_bundle_digest = Digest32::of_bytes(payload);
        let mut parameter_manifest = manifest(&definition);
        parameter_manifest.child_bundle_digest = definition.parameter_bundle_digest;
        parameter_manifest.encoded_size_bytes = payload.len() as u64;
        parameter_manifest.manifest_digest = parameter_manifest.content_digest();

        let parent = ArtifactManifest {
            artifact_id: parameter_manifest.parent_artifact_id.clone(),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: parameter_manifest.parent_bundle_digest,
            objective_digest: parameter_manifest.objective_digest,
            support_digest: parameter_manifest.lineage_digest,
            producer_id: id("producer.typed-role-parent"),
            compatibility_digest: parameter_manifest.compatibility_digest,
            encoded_size_bytes: 1,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.production-parent"),
                manifest: parent,
            })
            .expect("parent");
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.production-child"),
                manifest: parameter_manifest.as_registry_manifest(),
            })
            .expect("child");

        let root = std::env::temp_dir().join(format!(
            "hepta-typed-role-production-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        std::fs::create_dir(&root).expect("root");
        let cas = ArtifactCasOwnerV1::new(id("cas.typed-role"), key.clone()).expect("cas");
        let host = Some(Digest32::of_bytes(b"real-host-evidence"));
        let observer = Some(Digest32::of_bytes(b"independent-observer-evidence"));
        let write = cas
            .write_candidate(
                id("operation.production-write"),
                &root,
                "representation.bin",
                &registry,
                &parameter_manifest.artifact_id,
                payload,
                host,
                observer,
            )
            .expect("write");
        let file = std::fs::File::open(root.join("representation.bin")).expect("payload");
        let (_bytes, load) = cas
            .load_candidate(
                id("operation.production-load"),
                file,
                &registry,
                &parameter_manifest.artifact_id,
                &write,
                "representation.bin",
                host,
                observer,
            )
            .expect("load");
        let mut state_owner =
            StateCheckpointOwnerV1::new(id("state.typed-role"), key.clone()).expect("state");
        let state = state_owner
            .commit(
                id("operation.production-state"),
                definition.cell_id.clone(),
                definition.generation,
                definition.state_schema_digest,
                Digest32::ZERO,
                b"initial-role-state".to_vec(),
                host,
                observer,
            )
            .expect("state commit");
        let owner =
            TypedRoleArtifactOwnerV1::new(id("owner.typed-role.production")).expect("owner");
        let (artifact, receipt) = owner
            .bind_production(
                &registry,
                &key.verifying_key(),
                definition,
                parameter_manifest,
                &write,
                &load,
                &state,
            )
            .expect("production binding");
        artifact.validate().expect("artifact");
        receipt.validate_against(&artifact).expect("receipt");
        std::fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn evaluation_binds_role_baseline_future_window_and_independent_evaluator() {
        let role = CellRoleV1::Value;
        let (artifact, _) = artifact(role);
        let profile = CellRoleMetricProfileV1::standard_for_role(
            role,
            digest(50),
            digest(51),
            digest(52),
            digest(53),
        );
        let metrics = CellRoleMetricReceiptV1 {
            cell_id: artifact.definition.cell_id.clone(),
            generation: artifact.definition.generation,
            role,
            proposer_id: id("proposal.typed-role"),
            evaluator_id: id("observer.typed-role"),
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics: CellRoleMetricKindV1::standard_for_role(role)
                .iter()
                .enumerate()
                .map(|(index, kind)| CellRoleMetricV1 {
                    kind: *kind,
                    unit: kind.unit(),
                    value: if kind.permits_negative() { -1 } else { 1 },
                    sample_count: 10,
                    observation_digest: digest(60 + index as u8),
                })
                .collect(),
            evidence_digest: digest(70),
            authority: AuthorityPosture::DENY_ALL,
        };
        let evaluator =
            TypedRoleEvaluationOwnerV1::new(id("observer.typed-role")).expect("evaluator");
        let receipt = evaluator
            .record(&artifact, &profile, &metrics)
            .expect("evaluation");
        receipt
            .validate_against(&artifact, &profile, &metrics)
            .expect("evaluation replay");
        let policy = RoleMetricAcceptancePolicyV1::new(
            &profile,
            profile
                .required_metrics
                .iter()
                .map(|kind| RoleMetricThresholdV1 {
                    kind: *kind,
                    direction: RoleMetricDirectionV1::AtMost,
                    threshold_value: 1_000_000,
                    tolerance: 0,
                    minimum_sample_count: 1,
                })
                .collect(),
        )
        .expect("policy");
        let (evaluation, decision) = evaluator
            .evaluate_policy(&artifact, &profile, &policy, &metrics)
            .expect("policy evaluation");
        assert_eq!(decision.disposition, RoleMetricDecisionDispositionV1::Pass);
        evaluation
            .validate_against(&artifact, &profile, &metrics)
            .expect("evaluation remains bound");
        let mut self_evaluation = metrics;
        self_evaluation.evaluator_id = self_evaluation.proposer_id.clone();
        assert!(
            evaluator
                .record(&artifact, &profile, &self_evaluation)
                .is_err()
        );
    }
}
