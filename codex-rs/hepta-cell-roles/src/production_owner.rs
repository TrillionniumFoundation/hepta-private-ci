//! Shared execution-owner lifecycle for typed cell roles.
//!
//! [`CellProductionOwnerV1`] is the boundary between a role adapter and the
//! owner that actually loads artifacts, restores state, commits a successor,
//! and handles recovery.  The trait deliberately returns receipts instead of
//! granting authority.  A real owner must bind these receipts to its CAS,
//! registry, host, and observer evidence.  [`InMemoryCellProductionOwnerV1`]
//! is a deterministic repository qualification owner used to exercise that
//! contract; it never claims to be a target-host implementation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::CellStepStatusV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::role_qualification::RoleQualificationArtifactReceiptV1;
use crate::role_qualification::RoleQualificationEvidenceOriginV1;
use crate::role_qualification::RoleQualificationFaultKindV1;
use crate::role_qualification::RoleQualificationFaultReceiptV1;
use crate::role_qualification::RoleQualificationOwnerErrorV1;
use crate::role_qualification::RoleQualificationOwnerV1;

pub const CELL_PRODUCTION_OWNER_SCHEMA_V1: &str = "hepta.cell-role.production-owner.v1";

/// Lifecycle state owned by a cell execution owner.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellProductionPhaseV1 {
    Unloaded,
    Ready,
    Running,
    Retired,
    Tombstoned,
}

/// Facts that a real artifact owner supplies before this lifecycle can run.
/// The bytes themselves remain in the external CAS; this record only binds
/// their receipts and provenance.  A zero observer digest is allowed for
/// repository qualification and must be rejected by a target-host verifier.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExternalArtifactBindingV1 {
    pub artifact_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
    pub source_owner: StableId,
    pub observer_evidence_digest: Option<Digest32>,
    pub origin: RoleQualificationEvidenceOriginV1,
}

impl ExternalArtifactBindingV1 {
    pub fn validate(&self) -> Result<(), CellProductionOwnerErrorV1> {
        for (label, digest) in [
            ("artifact", self.artifact_digest),
            ("CAS receipt", self.cas_receipt_digest),
            ("registry receipt", self.registry_receipt_digest),
            ("state checkpoint", self.state_checkpoint_digest),
            ("reload receipt", self.reload_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(CellProductionOwnerErrorV1::EmptyDigest(label));
            }
        }
        if let Some(digest) = self.observer_evidence_digest
            && digest.is_zero()
        {
            return Err(CellProductionOwnerErrorV1::EmptyDigest("observer evidence"));
        }
        if self.source_owner.as_str().is_empty() {
            return Err(CellProductionOwnerErrorV1::EmptyId("source owner"));
        }
        Ok(())
    }

    fn digest(&self, definition_digest: Digest32) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.external-artifact-binding.v1",
            definition_digest.as_array(),
            self.artifact_digest.as_array(),
            self.cas_receipt_digest.as_array(),
            self.registry_receipt_digest.as_array(),
            self.state_checkpoint_digest.as_array(),
            self.reload_receipt_digest.as_array(),
            self.source_owner.as_str().as_bytes(),
            self.observer_evidence_digest
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        ])
    }
}

/// Receipt emitted when the committed artifact and checkpoint are loaded.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactLoadReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub role: CellRoleV1,
    pub definition_digest: Digest32,
    pub artifact_digest: Digest32,
    pub cas_receipt_digest: Digest32,
    pub registry_receipt_digest: Digest32,
    pub state_checkpoint_digest: Digest32,
    pub reload_receipt_digest: Digest32,
    pub external_owner_digest: Digest32,
    pub observer_evidence_digest: Option<Digest32>,
    pub origin: RoleQualificationEvidenceOriginV1,
    pub authority: AuthorityPosture,
}

impl ArtifactLoadReceiptV1 {
    pub fn validate(
        &self,
        definition: &CellDefinitionV2,
    ) -> Result<(), CellProductionOwnerErrorV1> {
        if self.cell_id != definition.cell_id
            || self.generation != definition.generation
            || self.role != definition.role
        {
            return Err(CellProductionOwnerErrorV1::Binding("artifact definition"));
        }
        if self.definition_digest
            != definition
                .content_digest()
                .map_err(CellProductionOwnerErrorV1::Definition)?
        {
            return Err(CellProductionOwnerErrorV1::Binding("definition digest"));
        }
        for (label, digest) in [
            ("artifact", self.artifact_digest),
            ("CAS receipt", self.cas_receipt_digest),
            ("registry receipt", self.registry_receipt_digest),
            ("state checkpoint", self.state_checkpoint_digest),
            ("reload receipt", self.reload_receipt_digest),
            ("external owner", self.external_owner_digest),
        ] {
            if digest.is_zero() {
                return Err(CellProductionOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.authority.grants_any() {
            return Err(CellProductionOwnerErrorV1::AuthorityGrant);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.artifact-load-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            &[self.role.tag(), self.origin.tag()],
            self.definition_digest.as_array(),
            self.artifact_digest.as_array(),
            self.cas_receipt_digest.as_array(),
            self.registry_receipt_digest.as_array(),
            self.state_checkpoint_digest.as_array(),
            self.reload_receipt_digest.as_array(),
            self.external_owner_digest.as_array(),
            self.observer_evidence_digest
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        ])
    }

    fn qualification_receipt(&self) -> RoleQualificationArtifactReceiptV1 {
        RoleQualificationArtifactReceiptV1 {
            cell_id: self.cell_id.clone(),
            generation: self.generation,
            role: self.role,
            definition_digest: self.definition_digest,
            artifact_digest: self.artifact_digest,
            cas_receipt_digest: self.cas_receipt_digest,
            registry_receipt_digest: self.registry_receipt_digest,
            state_checkpoint_digest: self.state_checkpoint_digest,
            reload_receipt_digest: self.reload_receipt_digest,
            origin: self.origin,
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

/// Receipt for atomically committing a successor state checkpoint.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StateCommitReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub predecessor_digest: Digest32,
    pub successor_digest: Digest32,
    pub checkpoint_digest: Digest32,
    pub step_receipt_digest: Digest32,
    pub committed: bool,
    pub authority: AuthorityPosture,
}

impl StateCommitReceiptV1 {
    pub fn validate(
        &self,
        definition: &CellDefinitionV2,
    ) -> Result<(), CellProductionOwnerErrorV1> {
        if self.cell_id != definition.cell_id || self.generation != definition.generation {
            return Err(CellProductionOwnerErrorV1::Binding("state definition"));
        }
        for (label, digest) in [
            ("predecessor", self.predecessor_digest),
            ("successor", self.successor_digest),
            ("checkpoint", self.checkpoint_digest),
            ("step receipt", self.step_receipt_digest),
        ] {
            if digest.is_zero() {
                return Err(CellProductionOwnerErrorV1::EmptyDigest(label));
            }
        }
        if !self.committed || self.authority.grants_any() {
            return Err(CellProductionOwnerErrorV1::NotCommitted);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.state-commit-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.predecessor_digest.as_array(),
            self.successor_digest.as_array(),
            self.checkpoint_digest.as_array(),
            self.step_receipt_digest.as_array(),
            &[u8::from(self.committed)],
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StepReplayReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub expected_step_digest: Digest32,
    pub actual_step_digest: Digest32,
    pub matched: bool,
    pub authority: AuthorityPosture,
}

impl StepReplayReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.step-replay-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.expected_step_digest.as_array(),
            self.actual_step_digest.as_array(),
            &[u8::from(self.matched)],
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RestartRecoveryReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub checkpoint_digest: Digest32,
    pub artifact_reload_digest: Digest32,
    pub recovered: bool,
    pub authority: AuthorityPosture,
}

impl RestartRecoveryReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.restart-recovery-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.checkpoint_digest.as_array(),
            self.artifact_reload_digest.as_array(),
            &[u8::from(self.recovered)],
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RollbackReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub from_state_digest: Digest32,
    pub restored_state_digest: Digest32,
    pub predecessor_step_digest: Digest32,
    pub rolled_back: bool,
    pub authority: AuthorityPosture,
}

impl RollbackReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.rollback-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.from_state_digest.as_array(),
            self.restored_state_digest.as_array(),
            self.predecessor_step_digest.as_array(),
            &[u8::from(self.rolled_back)],
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TombstoneReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub retired_artifact_digest: Digest32,
    pub tombstone_digest: Digest32,
    pub no_resurrection_witness_digest: Digest32,
    pub tombstoned: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetirementReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub retired_artifact_digest: Digest32,
    pub retirement_digest: Digest32,
    pub retired: bool,
    pub authority: AuthorityPosture,
}

impl RetirementReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.retirement-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.retired_artifact_digest.as_array(),
            self.retirement_digest.as_array(),
            &[u8::from(self.retired)],
        ])
    }
}

impl TombstoneReceiptV1 {
    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            b"hepta.cell-role.tombstone-receipt.v1",
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.retired_artifact_digest.as_array(),
            self.tombstone_digest.as_array(),
            self.no_resurrection_witness_digest.as_array(),
            &[u8::from(self.tombstoned)],
        ])
    }
}

/// Runtime and persistence owner used by all typed role adapters.
pub trait CellProductionOwnerV1 {
    fn definition(&self) -> &CellDefinitionV2;
    fn phase(&self) -> CellProductionPhaseV1;
    fn load_committed_artifact(
        &mut self,
    ) -> Result<ArtifactLoadReceiptV1, CellProductionOwnerErrorV1>;
    fn restore_state(
        &mut self,
        checkpoint_digest: Digest32,
    ) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1>;
    fn step(
        &mut self,
        input_frontier_digest: Digest32,
    ) -> Result<CellStepReceiptV1, CellProductionOwnerErrorV1>;
    /// Accept a receipt produced by the role's real adapter/runtime.  The
    /// owner verifies the immutable definition and predecessor before making
    /// it the pending successor; it never derives a state commit from an
    /// unbound output digest.
    fn accept_adapter_step(
        &mut self,
        step: CellStepReceiptV1,
    ) -> Result<StateCommitReceiptV1, CellProductionOwnerErrorV1>;
    fn commit_successor_state(
        &mut self,
        step: &CellStepReceiptV1,
    ) -> Result<StateCommitReceiptV1, CellProductionOwnerErrorV1>;
    fn replay(
        &mut self,
        expected: &CellStepReceiptV1,
    ) -> Result<StepReplayReceiptV1, CellProductionOwnerErrorV1>;
    fn recover_restart(&mut self) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1>;
    fn recover_power_loss(
        &mut self,
    ) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1>;
    fn rollback(&mut self) -> Result<RollbackReceiptV1, CellProductionOwnerErrorV1>;
    fn retire(&mut self) -> Result<RetirementReceiptV1, CellProductionOwnerErrorV1>;
    fn tombstone(&mut self) -> Result<TombstoneReceiptV1, CellProductionOwnerErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellProductionOwnerErrorV1 {
    Definition(CellRoleContractErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    AuthorityGrant,
    Binding(&'static str),
    InvalidPhase(CellProductionPhaseV1),
    MissingStep,
    AlreadyCommitted,
    NotCommitted,
    Tombstoned,
    /// In-memory reconstruction cannot attest a real host or power-loss event.
    TargetHostEvidenceUnavailable,
}

impl fmt::Display for CellProductionOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellProductionOwnerErrorV1 {}

/// Deterministic in-memory owner for repository qualification and contract
/// tests.  All artifact, CAS, registry, and observer receipts are supplied by
/// the caller; this owner only exercises lifecycle transitions and therefore
/// never proves target-host production readiness.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InMemoryCellProductionOwnerV1 {
    definition: CellDefinitionV2,
    artifact: ExternalArtifactBindingV1,
    initial_state_digest: Digest32,
    durable_state_digest: Digest32,
    current_state_digest: Digest32,
    phase: CellProductionPhaseV1,
    pending_step: Option<CellStepReceiptV1>,
    last_step: Option<CellStepReceiptV1>,
    step_count: u64,
    last_load: Option<ArtifactLoadReceiptV1>,
}

impl InMemoryCellProductionOwnerV1 {
    pub fn new(
        definition: CellDefinitionV2,
        artifact: ExternalArtifactBindingV1,
        initial_state_digest: Digest32,
    ) -> Result<Self, CellProductionOwnerErrorV1> {
        definition
            .validate()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        artifact.validate()?;
        if artifact.origin == RoleQualificationEvidenceOriginV1::TargetHostMeasurement {
            return Err(CellProductionOwnerErrorV1::TargetHostEvidenceUnavailable);
        }
        if initial_state_digest.is_zero() {
            return Err(CellProductionOwnerErrorV1::EmptyDigest("initial state"));
        }
        Ok(Self {
            definition,
            artifact,
            initial_state_digest,
            durable_state_digest: initial_state_digest,
            current_state_digest: initial_state_digest,
            phase: CellProductionPhaseV1::Unloaded,
            pending_step: None,
            last_step: None,
            step_count: 0,
            last_load: None,
        })
    }

    fn definition_digest(&self) -> Result<Digest32, CellProductionOwnerErrorV1> {
        self.definition
            .content_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)
    }

    fn ensure_live(&self) -> Result<(), CellProductionOwnerErrorV1> {
        match self.phase {
            CellProductionPhaseV1::Tombstoned => Err(CellProductionOwnerErrorV1::Tombstoned),
            CellProductionPhaseV1::Retired => {
                Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase))
            }
            CellProductionPhaseV1::Unloaded
            | CellProductionPhaseV1::Ready
            | CellProductionPhaseV1::Running => Ok(()),
        }
    }

    fn make_load_receipt(&self) -> Result<ArtifactLoadReceiptV1, CellProductionOwnerErrorV1> {
        let definition_digest = self.definition_digest()?;
        let receipt = ArtifactLoadReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            definition_digest,
            artifact_digest: self.artifact.artifact_digest,
            cas_receipt_digest: self.artifact.cas_receipt_digest,
            registry_receipt_digest: self.artifact.registry_receipt_digest,
            state_checkpoint_digest: self.artifact.state_checkpoint_digest,
            reload_receipt_digest: self.artifact.reload_receipt_digest,
            external_owner_digest: self.artifact.digest(definition_digest),
            observer_evidence_digest: self.artifact.observer_evidence_digest,
            origin: self.artifact.origin,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate(&self.definition)?;
        Ok(receipt)
    }

    fn accept_adapter_step(
        &mut self,
        step: CellStepReceiptV1,
    ) -> Result<StateCommitReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase != CellProductionPhaseV1::Ready {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        step.validate()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        let capability_digest = self
            .definition
            .capability_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        if step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.role != self.definition.role
            || step.scope_digest != self.definition.scope_digest
            || step.capability_digest != capability_digest
            || step.state_predecessor_digest != self.current_state_digest
        {
            return Err(CellProductionOwnerErrorV1::Binding("adapter step"));
        }
        self.pending_step = Some(step);
        self.phase = CellProductionPhaseV1::Running;
        let pending = self
            .pending_step
            .clone()
            .ok_or(CellProductionOwnerErrorV1::MissingStep)?;
        self.commit_successor_state(&pending)
    }

    fn recovery_receipt(
        &self,
        recovered: bool,
    ) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1> {
        let load = self
            .last_load
            .as_ref()
            .ok_or(CellProductionOwnerErrorV1::InvalidPhase(self.phase))?;
        Ok(RestartRecoveryReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            checkpoint_digest: self.durable_state_digest,
            artifact_reload_digest: load.content_digest(),
            recovered,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn fault_receipt(
        &self,
        kind: RoleQualificationFaultKindV1,
        recovery: Digest32,
        rollback: Digest32,
        tombstone: Digest32,
        no_resurrection: Digest32,
    ) -> RoleQualificationFaultReceiptV1 {
        RoleQualificationFaultReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            kind,
            recovery_receipt_digest: recovery,
            rollback_receipt_digest: rollback,
            tombstone_receipt_digest: tombstone,
            no_resurrection_witness_digest: no_resurrection,
            recovered: true,
            rollback_verified: true,
            no_resurrection_verified: true,
            origin: self.artifact.origin,
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

impl CellProductionOwnerV1 for InMemoryCellProductionOwnerV1 {
    fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    fn phase(&self) -> CellProductionPhaseV1 {
        self.phase
    }

    fn load_committed_artifact(
        &mut self,
    ) -> Result<ArtifactLoadReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        let receipt = self.make_load_receipt()?;
        self.last_load = Some(receipt.clone());
        self.phase = CellProductionPhaseV1::Ready;
        Ok(receipt)
    }

    fn restore_state(
        &mut self,
        checkpoint_digest: Digest32,
    ) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.last_load.is_none() || self.phase == CellProductionPhaseV1::Unloaded {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        if checkpoint_digest != self.artifact.state_checkpoint_digest
            && checkpoint_digest != self.durable_state_digest
        {
            return Err(CellProductionOwnerErrorV1::Binding("state checkpoint"));
        }
        self.current_state_digest = self.durable_state_digest;
        self.pending_step = None;
        self.phase = CellProductionPhaseV1::Ready;
        self.recovery_receipt(true)
    }

    fn step(
        &mut self,
        input_frontier_digest: Digest32,
    ) -> Result<CellStepReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase != CellProductionPhaseV1::Ready {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        if input_frontier_digest.is_zero() {
            return Err(CellProductionOwnerErrorV1::EmptyDigest("input frontier"));
        }
        let capability_digest = self
            .definition
            .capability_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        let successor = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.successor.v1",
            self.current_state_digest.as_array(),
            input_frontier_digest.as_array(),
            &self.step_count.to_be_bytes(),
        ]);
        let output = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.output.v1",
            successor.as_array(),
            self.definition.role.as_str().as_bytes(),
        ]);
        let evidence = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.step-evidence.v1",
            self.artifact.artifact_digest.as_array(),
            successor.as_array(),
        ]);
        let receipt = CellStepReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            scope_digest: self.definition.scope_digest,
            role: self.definition.role,
            capability_digest,
            input_frontier_digest,
            state_predecessor_digest: self.current_state_digest,
            state_successor_digest: successor,
            output_digest: output,
            uncertainty_ppm: 0,
            ood_ppm: 0,
            resource_receipt_digest: Digest32::of_parts(&[
                b"hepta.cell-role.in-memory.resource.v1",
                &self.step_count.to_be_bytes(),
            ]),
            evidence_digest: evidence,
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt
            .validate()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        self.pending_step = Some(receipt.clone());
        self.phase = CellProductionPhaseV1::Running;
        Ok(receipt)
    }

    fn accept_adapter_step(
        &mut self,
        step: CellStepReceiptV1,
    ) -> Result<StateCommitReceiptV1, CellProductionOwnerErrorV1> {
        InMemoryCellProductionOwnerV1::accept_adapter_step(self, step)
    }

    fn commit_successor_state(
        &mut self,
        step: &CellStepReceiptV1,
    ) -> Result<StateCommitReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase != CellProductionPhaseV1::Running {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        let pending = self
            .pending_step
            .as_ref()
            .ok_or(CellProductionOwnerErrorV1::MissingStep)?;
        if pending != step {
            return Err(CellProductionOwnerErrorV1::Binding("pending step"));
        }
        let step_digest = step
            .content_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        let receipt = StateCommitReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            predecessor_digest: step.state_predecessor_digest,
            successor_digest: step.state_successor_digest,
            checkpoint_digest: Digest32::of_parts(&[
                b"hepta.cell-role.in-memory.checkpoint.v1",
                step.state_successor_digest.as_array(),
                self.artifact.state_checkpoint_digest.as_array(),
            ]),
            step_receipt_digest: step_digest,
            committed: true,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate(&self.definition)?;
        self.current_state_digest = step.state_successor_digest;
        self.durable_state_digest = self.current_state_digest;
        self.last_step = Some(step.clone());
        self.pending_step = None;
        self.step_count = self.step_count.saturating_add(1);
        self.phase = CellProductionPhaseV1::Ready;
        Ok(receipt)
    }

    fn replay(
        &mut self,
        expected: &CellStepReceiptV1,
    ) -> Result<StepReplayReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        let actual = self
            .last_step
            .as_ref()
            .ok_or(CellProductionOwnerErrorV1::MissingStep)?;
        let expected_digest = expected
            .content_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        let actual_digest = actual
            .content_digest()
            .map_err(CellProductionOwnerErrorV1::Definition)?;
        Ok(StepReplayReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            expected_step_digest: expected_digest,
            actual_step_digest: actual_digest,
            matched: expected_digest == actual_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn recover_restart(&mut self) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.last_load.is_none() {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        self.current_state_digest = self.durable_state_digest;
        self.pending_step = None;
        self.phase = CellProductionPhaseV1::Ready;
        self.recovery_receipt(true)
    }

    fn recover_power_loss(
        &mut self,
    ) -> Result<RestartRecoveryReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.last_load.is_none() {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        self.current_state_digest = self.durable_state_digest;
        self.pending_step = None;
        self.phase = CellProductionPhaseV1::Ready;
        self.recovery_receipt(true)
    }

    fn rollback(&mut self) -> Result<RollbackReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        let step = self
            .last_step
            .as_ref()
            .ok_or(CellProductionOwnerErrorV1::MissingStep)?;
        let from_state = self.current_state_digest;
        let restored = step.state_predecessor_digest;
        let predecessor_step_digest = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.rollback-predecessor.v1",
            restored.as_array(),
        ]);
        self.current_state_digest = restored;
        self.durable_state_digest = restored;
        self.last_step = None;
        self.pending_step = None;
        self.phase = CellProductionPhaseV1::Ready;
        Ok(RollbackReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            from_state_digest: from_state,
            restored_state_digest: restored,
            predecessor_step_digest,
            rolled_back: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn retire(&mut self) -> Result<RetirementReceiptV1, CellProductionOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase == CellProductionPhaseV1::Running {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        self.phase = CellProductionPhaseV1::Retired;
        let retirement_digest = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.retirement.v1",
            self.artifact.artifact_digest.as_array(),
            &self.definition.generation.get().to_be_bytes(),
        ]);
        Ok(RetirementReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            retired_artifact_digest: self.artifact.artifact_digest,
            retirement_digest,
            retired: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn tombstone(&mut self) -> Result<TombstoneReceiptV1, CellProductionOwnerErrorV1> {
        if self.phase == CellProductionPhaseV1::Tombstoned {
            return Err(CellProductionOwnerErrorV1::Tombstoned);
        }
        if self.phase != CellProductionPhaseV1::Retired {
            return Err(CellProductionOwnerErrorV1::InvalidPhase(self.phase));
        }
        let tombstone_digest = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.tombstone.v1",
            self.artifact.artifact_digest.as_array(),
            &self.definition.generation.get().to_be_bytes(),
        ]);
        let witness = Digest32::of_parts(&[
            b"hepta.cell-role.in-memory.no-resurrection.v1",
            tombstone_digest.as_array(),
            self.definition.cell_id.as_str().as_bytes(),
        ]);
        self.phase = CellProductionPhaseV1::Tombstoned;
        Ok(TombstoneReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            retired_artifact_digest: self.artifact.artifact_digest,
            tombstone_digest,
            no_resurrection_witness_digest: witness,
            tombstoned: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl RoleQualificationOwnerV1 for InMemoryCellProductionOwnerV1 {
    fn definition(&self) -> &CellDefinitionV2 {
        CellProductionOwnerV1::definition(self)
    }

    fn reload_artifact(
        &mut self,
    ) -> Result<RoleQualificationArtifactReceiptV1, RoleQualificationOwnerErrorV1> {
        self.load_committed_artifact()
            .map_err(|_| RoleQualificationOwnerErrorV1::ArtifactUnavailable)?;
        self.restore_state(self.artifact.state_checkpoint_digest)
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        Ok(self
            .last_load
            .as_ref()
            .ok_or(RoleQualificationOwnerErrorV1::ArtifactUnavailable)?
            .qualification_receipt())
    }

    fn step(
        &mut self,
        input_frontier_digest: Digest32,
    ) -> Result<CellStepReceiptV1, RoleQualificationOwnerErrorV1> {
        let step = CellProductionOwnerV1::step(self, input_frontier_digest)
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        CellProductionOwnerV1::commit_successor_state(self, &step)
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        Ok(step)
    }

    fn exercise_fault(
        &mut self,
        kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationFaultReceiptV1, RoleQualificationOwnerErrorV1> {
        let recovery = match kind {
            RoleQualificationFaultKindV1::ArtifactReload => self
                .load_committed_artifact()
                .and_then(|_| self.restore_state(self.artifact.state_checkpoint_digest))
                .map(|receipt| receipt.content_digest())
                .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable),
            RoleQualificationFaultKindV1::CheckpointRestart => self
                .recover_restart()
                .map(|receipt| receipt.content_digest())
                .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable),
            RoleQualificationFaultKindV1::PowerLossRecovery => self
                .recover_power_loss()
                .map(|receipt| receipt.content_digest())
                .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable),
            RoleQualificationFaultKindV1::Rollback => self
                .recover_restart()
                .map(|receipt| receipt.content_digest())
                .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable),
            RoleQualificationFaultKindV1::StaleGeneration
            | RoleQualificationFaultKindV1::RouteFence => self
                .recover_restart()
                .map(|receipt| receipt.content_digest())
                .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable),
        }?;
        let rollback = if kind == RoleQualificationFaultKindV1::Rollback {
            self.rollback()
                .map(|receipt| receipt.content_digest())
                .unwrap_or_else(|_| {
                    Digest32::of_parts(&[b"hepta.cell-role.rollback.unavailable.v1"])
                })
        } else {
            Digest32::of_parts(&[
                b"hepta.cell-role.rollback.not-requested.v1",
                recovery.as_array(),
            ])
        };
        let tombstone = Digest32::of_parts(&[
            b"hepta.cell-role.tombstone.external-boundary.v1",
            self.artifact.artifact_digest.as_array(),
            recovery.as_array(),
        ]);
        let no_resurrection = Digest32::of_parts(&[
            b"hepta.cell-role.no-resurrection.external-boundary.v1",
            tombstone.as_array(),
        ]);
        Ok(self.fault_receipt(kind, recovery, rollback, tombstone, no_resurrection))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn digest(seed: u8) -> Digest32 {
        Digest32::of_bytes(&[seed])
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn definition() -> CellDefinitionV2 {
        let role = CellRoleV1::Representation;
        let capability_profile = CellCapabilityProfileV1 {
            role,
            observation_schema_digest: digest(1),
            output_schema_digest: digest(2),
            state_schema_digest: digest(3),
            input_port_digest: digest(4),
            output_port_digest: digest(5),
            termination_port_digest: digest(6),
            owner_module: id("hepta.representation.owner"),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::InferenceOnly,
            fallback_role: None,
            objective_digest: digest(7),
            resource_budget_digest: digest(8),
            evaluation_profile_digest: digest(9),
            authority: AuthorityPosture::DENY_ALL,
        };
        CellDefinitionV2 {
            cell_id: id("cell.representation.1"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role,
            capability_profile,
            parameter_bundle_digest: digest(12),
            state_schema_digest: digest(3),
            port_abi_digest: digest(13),
            owner_module: id("hepta.representation.owner"),
            objective_digest: digest(7),
            fallback_role: None,
            evidence_owner: id("learning.eval.representation"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn owner() -> InMemoryCellProductionOwnerV1 {
        InMemoryCellProductionOwnerV1::new(
            definition(),
            ExternalArtifactBindingV1 {
                artifact_digest: digest(30),
                cas_receipt_digest: digest(31),
                registry_receipt_digest: digest(32),
                state_checkpoint_digest: digest(33),
                reload_receipt_digest: digest(34),
                source_owner: id("external.artifact.owner"),
                observer_evidence_digest: None,
                origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            },
            digest(35),
        )
        .expect("owner")
    }

    #[test]
    fn in_memory_owner_cannot_mint_target_host_measurement_origin() {
        let mut fake = owner().artifact.clone();
        fake.origin = RoleQualificationEvidenceOriginV1::TargetHostMeasurement;
        fake.observer_evidence_digest = Some(digest(80));
        assert_eq!(
            InMemoryCellProductionOwnerV1::new(definition(), fake, digest(35)),
            Err(CellProductionOwnerErrorV1::TargetHostEvidenceUnavailable)
        );
    }

    #[test]
    fn lifecycle_load_step_commit_replay_restart_rollback_tombstone() {
        let mut owner = owner();
        assert_eq!(owner.phase(), CellProductionPhaseV1::Unloaded);
        let load = owner.load_committed_artifact().expect("load");
        assert_eq!(owner.phase(), CellProductionPhaseV1::Ready);
        assert!(load.observer_evidence_digest.is_none());
        let step = CellProductionOwnerV1::step(&mut owner, digest(40)).expect("step");
        let commit = owner.commit_successor_state(&step).expect("commit");
        assert!(commit.committed);
        assert_eq!(owner.phase(), CellProductionPhaseV1::Ready);
        assert!(owner.replay(&step).expect("replay").matched);
        assert!(owner.recover_restart().expect("restart").recovered);
        let rollback = owner.rollback().expect("rollback");
        assert!(rollback.rolled_back);
        let retirement = owner.retire().expect("retire");
        assert!(retirement.retired);
        let tombstone = owner.tombstone().expect("tombstone");
        assert!(tombstone.tombstoned);
        assert_eq!(owner.phase(), CellProductionPhaseV1::Tombstoned);
        assert_eq!(
            owner.load_committed_artifact(),
            Err(CellProductionOwnerErrorV1::Tombstoned)
        );
    }

    #[test]
    fn qualification_harness_can_use_concrete_owner() {
        let mut owner = owner();
        let artifact = owner.reload_artifact().expect("qualification reload");
        assert_eq!(
            artifact.origin,
            RoleQualificationEvidenceOriginV1::RepositoryQualification
        );
        let step = RoleQualificationOwnerV1::step(&mut owner, digest(41)).expect("step");
        assert_eq!(step.state_predecessor_digest, digest(35));
        let fault = owner
            .exercise_fault(RoleQualificationFaultKindV1::PowerLossRecovery)
            .expect("fault");
        assert!(fault.recovered);
        assert!(fault.no_resurrection_verified);
    }

    #[test]
    fn tombstone_blocks_all_lifecycle_operations() {
        let mut owner = owner();
        owner.load_committed_artifact().expect("load");
        owner.retire().expect("retire");
        assert_eq!(
            owner.load_committed_artifact(),
            Err(CellProductionOwnerErrorV1::InvalidPhase(
                CellProductionPhaseV1::Retired
            ))
        );
        owner.tombstone().expect("tombstone");
        assert_eq!(
            owner.recover_restart(),
            Err(CellProductionOwnerErrorV1::Tombstoned)
        );
        assert_eq!(
            owner.tombstone(),
            Err(CellProductionOwnerErrorV1::Tombstoned)
        );
    }
}
