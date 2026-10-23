//! Shared qualification seam for every typed cell role.
//!
//! This module deliberately does not add a runtime, a store, or a promotion
//! path.  A role owner implements [`RoleQualificationOwnerV1`] using its
//! existing runtime and persistence owner.  The harness then joins the
//! owner's artifact/reload receipt, one normal step receipt, one fault
//! receipt, and the existing role-specific metric receipt into a replayable
//! evidence boundary.  Target-host and observer facts remain external inputs;
//! this type never manufactures them or marks a role production qualified.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::role_gates::CellRoleGateErrorV1;
use crate::role_gates::CellRoleMetricProfileV1;
use crate::role_gates::CellRoleMetricReceiptV1;

pub const ROLE_QUALIFICATION_HARNESS_SCHEMA_V1: &str = "hepta.cell-role.qualification-harness.v1";

/// Provenance of a qualification input.  `TargetHostMeasurement` is an
/// origin label only; an independent host/observer verifier must still
/// authenticate the corresponding receipt before production admission.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleQualificationEvidenceOriginV1 {
    LocalSimulation,
    RepositoryQualification,
    TargetHostMeasurement,
}

impl RoleQualificationEvidenceOriginV1 {
    pub(crate) const fn tag(self) -> u8 {
        match self {
            Self::LocalSimulation => 0,
            Self::RepositoryQualification => 1,
            Self::TargetHostMeasurement => 2,
        }
    }
}

/// Artifact and reload facts supplied by the existing artifact owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleQualificationArtifactReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub definition_digest: Digest32,
    pub artifact_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
    pub origin: RoleQualificationEvidenceOriginV1,
    pub authority: AuthorityPosture,
}

impl RoleQualificationArtifactReceiptV1 {
    pub fn validate_against(
        &self,
        definition: &CellDefinitionV2,
    ) -> Result<(), RoleQualificationErrorV1> {
        let expected_definition = definition
            .content_digest()
            .map_err(RoleQualificationErrorV1::Definition)?;
        if self.cell_id != definition.cell_id
            || self.generation != definition.generation
            || self.role != definition.role
            || self.definition_digest != expected_definition
        {
            return Err(RoleQualificationErrorV1::Binding("artifact definition"));
        }
        require_id(&self.cell_id, "cell")?;
        for (label, digest) in [
            ("definition", self.definition_digest),
            ("artifact", self.artifact_digest),
            ("CAS receipt", self.cas_receipt_digest),
            ("registry receipt", self.registry_receipt_digest),
            ("state checkpoint", self.state_checkpoint_digest),
            ("reload receipt", self.reload_receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(RoleQualificationErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_parts(
            b"hepta.cell-role.qualification.artifact-receipt.v1",
            &[
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.role.tag()],
                self.definition_digest.as_array(),
                self.artifact_digest.as_array(),
                self.cas_receipt_digest.as_array(),
                self.registry_receipt_digest.as_array(),
                self.state_checkpoint_digest.as_array(),
                self.reload_receipt_digest.as_array(),
                &[self.origin.tag()],
            ],
        )
    }
}

/// A bounded fault/recovery observation from the role's real state owner.
/// The booleans report what the owner observed; they do not grant an
/// activation decision.  In particular, a local simulation cannot become a
/// target-host witness merely by changing `origin`.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleQualificationFaultKindV1 {
    ArtifactReload,
    CheckpointRestart,
    PowerLossRecovery,
    Rollback,
    StaleGeneration,
    RouteFence,
}

impl RoleQualificationFaultKindV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::ArtifactReload => 0,
            Self::CheckpointRestart => 1,
            Self::PowerLossRecovery => 2,
            Self::Rollback => 3,
            Self::StaleGeneration => 4,
            Self::RouteFence => 5,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleQualificationFaultReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub kind: RoleQualificationFaultKindV1,
    pub recovery_receipt_digest: Digest32,
    pub rollback_receipt_digest: Digest32,
    pub tombstone_receipt_digest: Digest32,
    pub no_resurrection_witness_digest: Digest32,
    pub recovered: bool,
    pub rollback_verified: bool,
    pub no_resurrection_verified: bool,
    pub origin: RoleQualificationEvidenceOriginV1,
    pub authority: AuthorityPosture,
}

impl RoleQualificationFaultReceiptV1 {
    pub fn validate_against(
        &self,
        definition: &CellDefinitionV2,
    ) -> Result<(), RoleQualificationErrorV1> {
        if self.cell_id != definition.cell_id
            || self.generation != definition.generation
            || self.role != definition.role
        {
            return Err(RoleQualificationErrorV1::Binding("fault definition"));
        }
        require_id(&self.cell_id, "cell")?;
        for (label, digest) in [
            ("recovery receipt", self.recovery_receipt_digest),
            ("rollback receipt", self.rollback_receipt_digest),
            ("tombstone receipt", self.tombstone_receipt_digest),
            (
                "no-resurrection witness",
                self.no_resurrection_witness_digest,
            ),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(RoleQualificationErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_parts(
            b"hepta.cell-role.qualification.fault-receipt.v1",
            &[
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.role.tag(), self.kind.tag()],
                self.recovery_receipt_digest.as_array(),
                self.rollback_receipt_digest.as_array(),
                self.tombstone_receipt_digest.as_array(),
                self.no_resurrection_witness_digest.as_array(),
                &[u8::from(self.recovered)],
                &[u8::from(self.rollback_verified)],
                &[u8::from(self.no_resurrection_verified)],
                &[self.origin.tag()],
            ],
        )
    }
}

/// Disposition emitted by an evaluator that is independent from the owner
/// which produced the candidate.  A disposition is evidence, not a promotion
/// command; the durable ledger and policy owner still decide retention.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleIndependentEvaluatorDispositionV1 {
    Retain,
    Quarantine,
    Reject,
    InsufficientEvidence,
}

impl RoleIndependentEvaluatorDispositionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::Retain => 0,
            Self::Quarantine => 1,
            Self::Reject => 2,
            Self::InsufficientEvidence => 3,
        }
    }
}

/// Typed evaluator evidence for one harness run.  This is deliberately
/// separate from the role metric receipt: a metric producer may be the role's
/// proposer, while this receipt must be issued by a different evaluator.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleIndependentEvaluatorReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub evaluator_id: StableId,
    pub proposer_id: StableId,
    /// Digest of the artifact/step/metric/fault evidence bundle, before this
    /// evaluator receipt is attached.  This avoids a self-referential digest.
    pub evaluated_receipt_digest: Digest32,
    pub disposition: RoleIndependentEvaluatorDispositionV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RoleIndependentEvaluatorReceiptV1 {
    pub fn validate_against(
        &self,
        definition: &CellDefinitionV2,
        expected_evaluated_receipt_digest: Digest32,
    ) -> Result<(), RoleQualificationErrorV1> {
        if self.cell_id != definition.cell_id
            || self.generation != definition.generation
            || self.role != definition.role
        {
            return Err(RoleQualificationErrorV1::Binding("evaluator definition"));
        }
        require_id(&self.cell_id, "cell")?;
        require_id(&self.evaluator_id, "evaluator")?;
        require_id(&self.proposer_id, "proposer")?;
        if self.evaluator_id == self.proposer_id {
            return Err(RoleQualificationErrorV1::EvaluatorIsProposer);
        }
        require_digest(expected_evaluated_receipt_digest, "evaluated receipt")?;
        if self.evaluated_receipt_digest != expected_evaluated_receipt_digest {
            return Err(RoleQualificationErrorV1::Binding("evaluated receipt"));
        }
        require_digest(self.evidence_digest, "evaluator evidence")?;
        if self.authority.grants_any() {
            return Err(RoleQualificationErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_parts(
            b"hepta.cell-role.qualification.independent-evaluator.v1",
            &[
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.role.tag()],
                self.evaluator_id.as_str().as_bytes(),
                self.proposer_id.as_str().as_bytes(),
                self.evaluated_receipt_digest.as_array(),
                &[self.disposition.tag()],
                self.evidence_digest.as_array(),
            ],
        )
    }
}

/// Errors an owner can return while the harness asks it to reload, step, or
/// exercise a bounded fault.  The harness intentionally keeps this small so
/// an owner can map its existing runtime/store error without introducing a
/// second runtime abstraction.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleQualificationOwnerErrorV1 {
    ArtifactUnavailable,
    StateUnavailable,
    FaultUnavailable,
}

impl fmt::Display for RoleQualificationOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RoleQualificationOwnerErrorV1 {}

/// Existing runtime/persistence owners implement this interface.  It is a
/// qualification seam, not an execution engine: the owner remains responsible
/// for actual artifact storage, checkpointing, routing, and target-host
/// observation.
pub trait RoleQualificationOwnerV1 {
    fn definition(&self) -> &CellDefinitionV2;

    fn reload_artifact(
        &mut self,
    ) -> Result<RoleQualificationArtifactReceiptV1, RoleQualificationOwnerErrorV1>;

    fn step(
        &mut self,
        input_frontier_digest: Digest32,
    ) -> Result<CellStepReceiptV1, RoleQualificationOwnerErrorV1>;

    fn exercise_fault(
        &mut self,
        kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationFaultReceiptV1, RoleQualificationOwnerErrorV1>;
}

/// Replayable join of role owner, artifact/reload, step, metric, fault, and
/// evaluator evidence.  This receipt has no `accepted`, `retained`, or
/// `production_qualified` field.  Independent signed admission remains the
/// responsibility of the learning-ledger/evaluator owner.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleQualificationReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub definition_digest: Digest32,
    pub artifact_receipt_digest: Digest32,
    pub step_receipt_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub fault_receipt_digest: Digest32,
    pub evaluator_receipt_digest: Digest32,
    pub origin: RoleQualificationEvidenceOriginV1,
    pub authority: AuthorityPosture,
}

impl RoleQualificationReceiptV1 {
    pub fn validate(&self) -> Result<(), RoleQualificationErrorV1> {
        require_id(&self.cell_id, "cell")?;
        for (label, digest) in [
            ("definition", self.definition_digest),
            ("artifact receipt", self.artifact_receipt_digest),
            ("step receipt", self.step_receipt_digest),
            ("metric receipt", self.metric_receipt_digest),
            ("fault receipt", self.fault_receipt_digest),
            ("evaluator receipt", self.evaluator_receipt_digest),
        ] {
            require_digest(digest, label)?;
        }
        if self.authority.grants_any() {
            return Err(RoleQualificationErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        digest_parts(
            b"hepta.cell-role.qualification.receipt.v1",
            &[
                self.cell_id.as_str().as_bytes(),
                &self.generation.get().to_be_bytes(),
                &[self.role.tag()],
                self.definition_digest.as_array(),
                self.artifact_receipt_digest.as_array(),
                self.step_receipt_digest.as_array(),
                self.metric_receipt_digest.as_array(),
                self.fault_receipt_digest.as_array(),
                self.evaluator_receipt_digest.as_array(),
                &[self.origin.tag()],
            ],
        )
    }
}

/// Parameterized qualification harness shared by all role owners.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleQualificationHarnessV1 {
    pub definition: CellDefinitionV2,
    pub metric_profile: CellRoleMetricProfileV1,
}

impl RoleQualificationHarnessV1 {
    pub fn new(
        definition: CellDefinitionV2,
        metric_profile: CellRoleMetricProfileV1,
    ) -> Result<Self, RoleQualificationErrorV1> {
        definition
            .validate()
            .map_err(RoleQualificationErrorV1::Definition)?;
        metric_profile
            .validate()
            .map_err(RoleQualificationErrorV1::Metric)?;
        if definition.role != metric_profile.role {
            return Err(RoleQualificationErrorV1::RoleMismatch {
                expected: definition.role,
                actual: metric_profile.role,
            });
        }
        Ok(Self {
            definition,
            metric_profile,
        })
    }

    /// Ask the existing owner to reload, execute one bounded step, and
    /// exercise one fault scenario, then bind the results to the frozen
    /// profile/baseline and an external evaluator receipt.
    pub fn qualify<O: RoleQualificationOwnerV1>(
        &self,
        owner: &mut O,
        input_frontier_digest: Digest32,
        metric_receipt: &CellRoleMetricReceiptV1,
        fault_kind: RoleQualificationFaultKindV1,
        evaluator_receipt_digest: Digest32,
    ) -> Result<RoleQualificationReceiptV1, RoleQualificationErrorV1> {
        require_digest(input_frontier_digest, "input frontier")?;
        require_digest(evaluator_receipt_digest, "evaluator receipt")?;

        let components =
            self.collect_components(owner, input_frontier_digest, metric_receipt, fault_kind)?;
        let expected_definition_digest = components.definition_digest;

        let receipt = RoleQualificationReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            definition_digest: expected_definition_digest,
            artifact_receipt_digest: components.artifact.content_digest(),
            step_receipt_digest: components
                .step
                .content_digest()
                .map_err(RoleQualificationErrorV1::Contract)?,
            metric_receipt_digest: components.metric_receipt_digest,
            fault_receipt_digest: components.fault.content_digest(),
            evaluator_receipt_digest,
            origin: components.artifact.origin,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate()?;
        Ok(receipt)
    }

    /// Qualification path with a typed independent evaluator receipt.  The
    /// evaluator signs/records the digest of all owner evidence before its
    /// own receipt is attached, preventing circular self-approval.
    pub fn qualify_with_independent_evaluator<O: RoleQualificationOwnerV1>(
        &self,
        owner: &mut O,
        input_frontier_digest: Digest32,
        metric_receipt: &CellRoleMetricReceiptV1,
        fault_kind: RoleQualificationFaultKindV1,
        evaluator: &RoleIndependentEvaluatorReceiptV1,
    ) -> Result<RoleQualificationReceiptV1, RoleQualificationErrorV1> {
        let components =
            self.collect_components(owner, input_frontier_digest, metric_receipt, fault_kind)?;
        let evidence_digest = components.evidence_digest();
        evaluator.validate_against(&self.definition, evidence_digest)?;
        if evaluator.proposer_id != metric_receipt.proposer_id {
            return Err(RoleQualificationErrorV1::Binding("evaluator proposer"));
        }
        let definition_digest = components.definition_digest;
        let receipt = RoleQualificationReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            definition_digest,
            artifact_receipt_digest: components.artifact.content_digest(),
            step_receipt_digest: components
                .step
                .content_digest()
                .map_err(RoleQualificationErrorV1::Contract)?,
            metric_receipt_digest: components.metric_receipt_digest,
            fault_receipt_digest: components.fault.content_digest(),
            evaluator_receipt_digest: evaluator.content_digest(),
            origin: components.artifact.origin,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate()?;
        Ok(receipt)
    }

    /// Compute the exact pre-evaluator evidence digest that an independent
    /// evaluator must bind.  Owners can call this after collecting their
    /// durable artifact, step, metric, and fault receipts; the evaluator then
    /// submits a typed [`RoleIndependentEvaluatorReceiptV1`] carrying it.
    pub fn evidence_bundle_digest(
        &self,
        artifact: &RoleQualificationArtifactReceiptV1,
        step: &CellStepReceiptV1,
        metric_receipt: &CellRoleMetricReceiptV1,
        fault: &RoleQualificationFaultReceiptV1,
    ) -> Result<Digest32, RoleQualificationErrorV1> {
        artifact.validate_against(&self.definition)?;
        step.validate()
            .map_err(RoleQualificationErrorV1::Contract)?;
        if step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.role != self.definition.role
        {
            return Err(RoleQualificationErrorV1::Binding("step receipt"));
        }
        metric_receipt
            .validate_structure_against(&self.metric_profile)
            .map_err(RoleQualificationErrorV1::Metric)?;
        if metric_receipt.cell_id != self.definition.cell_id
            || metric_receipt.generation != self.definition.generation
            || metric_receipt.role != self.definition.role
        {
            return Err(RoleQualificationErrorV1::Binding("metric receipt"));
        }
        fault.validate_against(&self.definition)?;
        let components = RoleQualificationComponentsV1 {
            definition_digest: self
                .definition
                .content_digest()
                .map_err(RoleQualificationErrorV1::Definition)?,
            artifact: artifact.clone(),
            step: step.clone(),
            metric_receipt_digest: metric_receipt
                .content_digest(&self.metric_profile)
                .map_err(RoleQualificationErrorV1::Metric)?,
            fault: fault.clone(),
        };
        Ok(components.evidence_digest())
    }

    fn collect_components<O: RoleQualificationOwnerV1>(
        &self,
        owner: &mut O,
        input_frontier_digest: Digest32,
        metric_receipt: &CellRoleMetricReceiptV1,
        fault_kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationComponentsV1, RoleQualificationErrorV1> {
        require_digest(input_frontier_digest, "input frontier")?;
        let owner_definition = owner.definition();
        let owner_definition_digest = owner_definition
            .content_digest()
            .map_err(RoleQualificationErrorV1::Definition)?;
        let expected_definition_digest = self
            .definition
            .content_digest()
            .map_err(RoleQualificationErrorV1::Definition)?;
        if owner_definition_digest != expected_definition_digest {
            return Err(RoleQualificationErrorV1::Binding("owner definition"));
        }
        let artifact = owner
            .reload_artifact()
            .map_err(RoleQualificationErrorV1::Owner)?;
        artifact.validate_against(&self.definition)?;
        let step = owner
            .step(input_frontier_digest)
            .map_err(RoleQualificationErrorV1::Owner)?;
        step.validate()
            .map_err(RoleQualificationErrorV1::Contract)?;
        if step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.role != self.definition.role
            || step.input_frontier_digest != input_frontier_digest
        {
            return Err(RoleQualificationErrorV1::Binding("step receipt"));
        }
        metric_receipt
            .validate_structure_against(&self.metric_profile)
            .map_err(RoleQualificationErrorV1::Metric)?;
        if metric_receipt.cell_id != self.definition.cell_id
            || metric_receipt.generation != self.definition.generation
            || metric_receipt.role != self.definition.role
        {
            return Err(RoleQualificationErrorV1::Binding("metric receipt"));
        }
        let fault = owner
            .exercise_fault(fault_kind)
            .map_err(RoleQualificationErrorV1::Owner)?;
        fault.validate_against(&self.definition)?;
        Ok(RoleQualificationComponentsV1 {
            definition_digest: expected_definition_digest,
            artifact,
            step,
            metric_receipt_digest: metric_receipt
                .content_digest(&self.metric_profile)
                .map_err(RoleQualificationErrorV1::Metric)?,
            fault,
        })
    }
}

struct RoleQualificationComponentsV1 {
    definition_digest: Digest32,
    artifact: RoleQualificationArtifactReceiptV1,
    step: CellStepReceiptV1,
    metric_receipt_digest: Digest32,
    fault: RoleQualificationFaultReceiptV1,
}

impl RoleQualificationComponentsV1 {
    fn evidence_digest(&self) -> Digest32 {
        digest_parts(
            b"hepta.cell-role.qualification.evidence-bundle.v1",
            &[
                self.definition_digest.as_array(),
                self.artifact.content_digest().as_array(),
                self.step
                    .content_digest()
                    .unwrap_or(Digest32::ZERO)
                    .as_array(),
                self.metric_receipt_digest.as_array(),
                self.fault.content_digest().as_array(),
            ],
        )
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RoleQualificationErrorV1 {
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    AuthorityGrant,
    Binding(&'static str),
    RoleMismatch {
        expected: CellRoleV1,
        actual: CellRoleV1,
    },
    Definition(CellRoleContractErrorV1),
    Contract(CellRoleContractErrorV1),
    Metric(CellRoleGateErrorV1),
    Owner(RoleQualificationOwnerErrorV1),
    EvaluatorIsProposer,
}

impl fmt::Display for RoleQualificationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RoleQualificationErrorV1 {}

fn require_id(id: &StableId, label: &'static str) -> Result<(), RoleQualificationErrorV1> {
    if id.as_str().is_empty() {
        Err(RoleQualificationErrorV1::EmptyId(label))
    } else {
        Ok(())
    }
}

fn require_digest(digest: Digest32, label: &'static str) -> Result<(), RoleQualificationErrorV1> {
    if digest.is_zero() {
        Err(RoleQualificationErrorV1::EmptyDigest(label))
    } else {
        Ok(())
    }
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Digest32 {
    let mut bytes = domain.to_vec();
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u64).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::role_gates::CellRoleMetricKindV1;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellStepStatusV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::of_bytes(&[seed])
    }

    fn definition() -> CellDefinitionV2 {
        let role = CellRoleV1::MemoryRead;
        let capability = CellCapabilityProfileV1 {
            role,
            observation_schema_digest: digest(1),
            output_schema_digest: digest(2),
            state_schema_digest: digest(3),
            input_port_digest: digest(4),
            output_port_digest: digest(5),
            termination_port_digest: digest(6),
            owner_module: id("hepta.memory.read.owner"),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::InferenceOnly,
            fallback_role: None,
            objective_digest: digest(7),
            resource_budget_digest: digest(8),
            evaluation_profile_digest: digest(9),
            authority: AuthorityPosture::DENY_ALL,
        };
        CellDefinitionV2 {
            cell_id: id("cell.memory-read.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role,
            capability_profile: capability,
            parameter_bundle_digest: digest(12),
            state_schema_digest: digest(3),
            port_abi_digest: digest(13),
            owner_module: id("hepta.memory.read.owner"),
            objective_digest: digest(7),
            fallback_role: None,
            evidence_owner: id("learning.eval.memory-read"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn profile() -> CellRoleMetricProfileV1 {
        CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::MemoryRead,
            digest(20),
            digest(21),
            digest(22),
            digest(23),
        )
    }

    fn metric_receipt(definition: &CellDefinitionV2) -> CellRoleMetricReceiptV1 {
        let profile = profile();
        let metrics = CellRoleMetricKindV1::standard_for_role(CellRoleV1::MemoryRead)
            .iter()
            .map(|kind| crate::role_gates::CellRoleMetricV1 {
                kind: *kind,
                unit: kind.unit(),
                value: 1,
                sample_count: 1,
                observation_digest: digest(kind.tag()),
            })
            .collect();
        CellRoleMetricReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            role: definition.role,
            proposer_id: id("memory-read.proposer"),
            evaluator_id: id("learning.eval.memory-read"),
            profile_digest: profile.content_digest().expect("profile digest"),
            baseline_digest: digest(21),
            evaluation_window_digest: digest(23),
            metrics,
            evidence_digest: digest(24),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    struct FixtureOwner {
        definition: CellDefinitionV2,
    }

    impl RoleQualificationOwnerV1 for FixtureOwner {
        fn definition(&self) -> &CellDefinitionV2 {
            &self.definition
        }

        fn reload_artifact(
            &mut self,
        ) -> Result<RoleQualificationArtifactReceiptV1, RoleQualificationOwnerErrorV1> {
            Ok(RoleQualificationArtifactReceiptV1 {
                cell_id: self.definition.cell_id.clone(),
                generation: self.definition.generation,
                role: self.definition.role,
                definition_digest: self.definition.content_digest().expect("definition"),
                artifact_digest: digest(30),
                cas_receipt_digest: digest(31),
                registry_receipt_digest: digest(32),
                state_checkpoint_digest: digest(33),
                reload_receipt_digest: digest(34),
                origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
                authority: AuthorityPosture::DENY_ALL,
            })
        }

        fn step(
            &mut self,
            input_frontier_digest: Digest32,
        ) -> Result<CellStepReceiptV1, RoleQualificationOwnerErrorV1> {
            Ok(CellStepReceiptV1 {
                cell_id: self.definition.cell_id.clone(),
                generation: self.definition.generation,
                scope_digest: self.definition.scope_digest,
                role: self.definition.role,
                capability_digest: self.definition.capability_digest().expect("capability"),
                input_frontier_digest,
                state_predecessor_digest: digest(35),
                state_successor_digest: digest(36),
                output_digest: digest(37),
                uncertainty_ppm: 1,
                ood_ppm: 2,
                resource_receipt_digest: digest(38),
                evidence_digest: digest(39),
                status: CellStepStatusV1::Accepted,
                authority: AuthorityPosture::DENY_ALL,
            })
        }

        fn exercise_fault(
            &mut self,
            kind: RoleQualificationFaultKindV1,
        ) -> Result<RoleQualificationFaultReceiptV1, RoleQualificationOwnerErrorV1> {
            Ok(RoleQualificationFaultReceiptV1 {
                cell_id: self.definition.cell_id.clone(),
                generation: self.definition.generation,
                role: self.definition.role,
                kind,
                recovery_receipt_digest: digest(40),
                rollback_receipt_digest: digest(41),
                tombstone_receipt_digest: digest(42),
                no_resurrection_witness_digest: digest(43),
                recovered: true,
                rollback_verified: true,
                no_resurrection_verified: true,
                origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
                authority: AuthorityPosture::DENY_ALL,
            })
        }
    }

    #[test]
    fn harness_joins_owner_artifact_step_metrics_fault_and_evaluator() {
        let definition = definition();
        let harness =
            RoleQualificationHarnessV1::new(definition.clone(), profile()).expect("harness");
        let mut owner = FixtureOwner { definition };
        let receipt = harness
            .qualify(
                &mut owner,
                digest(50),
                &metric_receipt(&harness.definition),
                RoleQualificationFaultKindV1::CheckpointRestart,
                digest(51),
            )
            .expect("qualification receipt");
        assert_eq!(receipt.role, CellRoleV1::MemoryRead);
        assert_eq!(
            receipt.origin,
            RoleQualificationEvidenceOriginV1::RepositoryQualification
        );
        assert!(receipt.validate().is_ok());
        assert!(!receipt.content_digest().is_zero());
    }

    #[test]
    fn harness_rejects_owner_definition_mismatch() {
        let definition = definition();
        let harness =
            RoleQualificationHarnessV1::new(definition.clone(), profile()).expect("harness");
        let mut owner = FixtureOwner {
            definition: {
                let mut value = definition;
                value.generation = Generation::new(2).expect("generation");
                value
            },
        };
        let result = harness.qualify(
            &mut owner,
            digest(50),
            &metric_receipt(&harness.definition),
            RoleQualificationFaultKindV1::ArtifactReload,
            digest(51),
        );
        assert_eq!(
            result,
            Err(RoleQualificationErrorV1::Binding("owner definition"))
        );
    }

    #[test]
    fn target_host_origin_does_not_create_acceptance_flag() {
        let definition = definition();
        let mut owner = FixtureOwner { definition };
        let artifact = owner.reload_artifact().expect("artifact");
        assert_eq!(
            artifact.origin,
            RoleQualificationEvidenceOriginV1::RepositoryQualification
        );
        assert!(!artifact.content_digest().is_zero());
        // The receipt shape intentionally has no production/retention bit.
        let fields = format!("{:?}", artifact);
        assert!(!fields.contains("production_qualified"));
    }

    #[test]
    fn typed_independent_evaluator_path_binds_pre_evaluator_evidence() {
        let definition = definition();
        let harness =
            RoleQualificationHarnessV1::new(definition.clone(), profile()).expect("harness");
        let mut evidence_owner = FixtureOwner {
            definition: definition.clone(),
        };
        let input = digest(50);
        let artifact = evidence_owner.reload_artifact().expect("artifact");
        let step = evidence_owner.step(input).expect("step");
        let metric = metric_receipt(&definition);
        let fault = evidence_owner
            .exercise_fault(RoleQualificationFaultKindV1::Rollback)
            .expect("fault");
        let evaluated_receipt_digest = harness
            .evidence_bundle_digest(&artifact, &step, &metric, &fault)
            .expect("evidence digest");
        let evaluator = RoleIndependentEvaluatorReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            role: definition.role,
            evaluator_id: id("independent.observer"),
            proposer_id: id("memory-read.proposer"),
            evaluated_receipt_digest,
            disposition: RoleIndependentEvaluatorDispositionV1::InsufficientEvidence,
            evidence_digest: digest(52),
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut owner = FixtureOwner { definition };
        let receipt = harness
            .qualify_with_independent_evaluator(
                &mut owner,
                input,
                &metric,
                RoleQualificationFaultKindV1::Rollback,
                &evaluator,
            )
            .expect("typed evaluation");
        assert_eq!(receipt.evaluator_receipt_digest, evaluator.content_digest());
    }

    #[test]
    fn typed_independent_evaluator_rejects_self_evaluation() {
        let definition = definition();
        let harness =
            RoleQualificationHarnessV1::new(definition.clone(), profile()).expect("harness");
        let mut evidence_owner = FixtureOwner {
            definition: definition.clone(),
        };
        let input = digest(50);
        let artifact = evidence_owner.reload_artifact().expect("artifact");
        let step = evidence_owner.step(input).expect("step");
        let metric = metric_receipt(&definition);
        let fault = evidence_owner
            .exercise_fault(RoleQualificationFaultKindV1::Rollback)
            .expect("fault");
        let evaluator = RoleIndependentEvaluatorReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            role: definition.role,
            evaluator_id: id("memory-read.proposer"),
            proposer_id: id("memory-read.proposer"),
            evaluated_receipt_digest: harness
                .evidence_bundle_digest(&artifact, &step, &metric, &fault)
                .expect("evidence digest"),
            disposition: RoleIndependentEvaluatorDispositionV1::Retain,
            evidence_digest: digest(53),
            authority: AuthorityPosture::DENY_ALL,
        };
        let mut owner = FixtureOwner { definition };
        let result = harness.qualify_with_independent_evaluator(
            &mut owner,
            input,
            &metric,
            RoleQualificationFaultKindV1::Rollback,
            &evaluator,
        );
        assert_eq!(result, Err(RoleQualificationErrorV1::EvaluatorIsProposer));
    }
}
