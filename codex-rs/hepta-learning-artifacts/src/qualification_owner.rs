//! Qualification owner backed by the real CAS and checkpoint owners.
//!
//! The role qualification harness is intentionally a small interface.  This
//! module supplies the missing production-side bridge for learned roles: an
//! artifact reload reads the CAS file and verifies its signed write receipt,
//! a step is produced by a caller-owned role runtime and committed through
//! the durable state owner, and recovery faults operate on that same state
//! owner.  The bridge never turns a repository run into a target-host witness.

use std::error::Error;
use std::fmt;
use std::fs::File;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

use codex_hepta_cell_roles::RoleQualificationArtifactReceiptV1;
use codex_hepta_cell_roles::RoleQualificationEvidenceOriginV1;
use codex_hepta_cell_roles::RoleQualificationFaultKindV1;
use codex_hepta_cell_roles::RoleQualificationFaultReceiptV1;
use codex_hepta_cell_roles::RoleQualificationOwnerErrorV1;
use codex_hepta_cell_roles::RoleQualificationOwnerV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactCasOwnerV1;
use crate::ArtifactRegistry;
use crate::ArtifactWriteReceiptV1;
use crate::DurableLearnedRoleOwnerErrorV1;
use crate::DurableLearnedRoleOwnerV1;
use crate::StateCommitReceiptV1;
use crate::StateTombstoneReceiptV1;
use crate::TypedRoleArtifactReceiptV1;
use crate::TypedRoleArtifactV1;
use crate::TypedRoleOwnerErrorV1;
use crate::is_generic_learned_role;

pub const PRODUCTION_ROLE_QUALIFICATION_OWNER_SCHEMA_V1: &str =
    "hepta.learning-artifacts.production-role-qualification-owner.v1";

/// A role runtime supplies one already validated typed step and the exact
/// bytes that the state owner must commit for that step.  The runtime remains
/// outside this crate: this trait is what prevents the qualification bridge
/// from fabricating an output or a state digest from an input digest alone.
pub trait RoleQualificationStepExecutorV1 {
    fn execute_step(
        &mut self,
        definition: &CellDefinitionV2,
        input_frontier_digest: Digest32,
        predecessor_state_digest: Digest32,
    ) -> Result<RoleQualificationExecutionV1, RoleQualificationExecutorErrorV1>;
}

/// Result returned by [`RoleQualificationStepExecutorV1`].
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RoleQualificationExecutionV1 {
    pub step: CellStepReceiptV1,
    pub state_bytes: Vec<u8>,
}

/// Bounded error surface for a runtime supplied to the qualification owner.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoleQualificationExecutorErrorV1 {
    Unavailable,
    Binding(&'static str),
}

impl fmt::Display for RoleQualificationExecutorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for RoleQualificationExecutorErrorV1 {}

/// Errors produced while wiring the real artifact/state owners to the
/// harness.  The trait implementation below intentionally maps these errors
/// to the harness' bounded owner errors, while callers that construct the
/// owner still get a useful binding reason.
#[derive(Debug)]
pub enum ProductionRoleQualificationOwnerErrorV1 {
    Definition(CellRoleContractErrorV1),
    Artifact(crate::ProductionOwnerError),
    State(DurableLearnedRoleOwnerErrorV1),
    Durable(crate::DurableStateError),
    TypedRole(TypedRoleOwnerErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    Binding(&'static str),
    InvalidRelativePath,
    Executor(RoleQualificationExecutorErrorV1),
}

impl fmt::Display for ProductionRoleQualificationOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for ProductionRoleQualificationOwnerErrorV1 {}

impl From<crate::ProductionOwnerError> for ProductionRoleQualificationOwnerErrorV1 {
    fn from(value: crate::ProductionOwnerError) -> Self {
        Self::Artifact(value)
    }
}

impl From<DurableLearnedRoleOwnerErrorV1> for ProductionRoleQualificationOwnerErrorV1 {
    fn from(value: DurableLearnedRoleOwnerErrorV1) -> Self {
        Self::State(value)
    }
}

impl From<crate::DurableStateError> for ProductionRoleQualificationOwnerErrorV1 {
    fn from(value: crate::DurableStateError) -> Self {
        Self::Durable(value)
    }
}

impl From<TypedRoleOwnerErrorV1> for ProductionRoleQualificationOwnerErrorV1 {
    fn from(value: TypedRoleOwnerErrorV1) -> Self {
        Self::TypedRole(value)
    }
}

/// A learned-role qualification owner that executes against immutable CAS
/// bytes and the durable checkpoint owner.  `E` is the actual role runtime;
/// this owner only fences its output and persists the resulting state.
#[derive(Clone, Debug)]
pub struct ProductionRoleQualificationOwnerV1<E> {
    definition: CellDefinitionV2,
    artifact: TypedRoleArtifactV1,
    artifact_receipt: TypedRoleArtifactReceiptV1,
    artifact_owner: ArtifactCasOwnerV1,
    artifact_write: ArtifactWriteReceiptV1,
    registry: ArtifactRegistry,
    artifact_root: PathBuf,
    artifact_relative: PathBuf,
    state_owner: DurableLearnedRoleOwnerV1,
    state_path: PathBuf,
    current_state: StateCommitReceiptV1,
    initial_state: StateCommitReceiptV1,
    executor: E,
    reload_sequence: u64,
    host_evidence_digest: Option<Digest32>,
    observer_evidence_digest: Option<Digest32>,
}

impl<E> ProductionRoleQualificationOwnerV1<E>
where
    E: RoleQualificationStepExecutorV1,
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        definition: CellDefinitionV2,
        artifact: TypedRoleArtifactV1,
        artifact_receipt: TypedRoleArtifactReceiptV1,
        artifact_owner: ArtifactCasOwnerV1,
        artifact_write: ArtifactWriteReceiptV1,
        registry: ArtifactRegistry,
        artifact_root: impl AsRef<Path>,
        artifact_relative: impl AsRef<Path>,
        state_owner: DurableLearnedRoleOwnerV1,
        state_path: impl AsRef<Path>,
        initial_state: StateCommitReceiptV1,
        executor: E,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<Self, ProductionRoleQualificationOwnerErrorV1> {
        definition
            .validate()
            .map_err(ProductionRoleQualificationOwnerErrorV1::Definition)?;
        if !is_generic_learned_role(definition.role) {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "generic learned role",
            ));
        }
        artifact.validate()?;
        artifact_receipt.validate_against(&artifact)?;
        if artifact.definition != definition
            || artifact_receipt.definition_digest
                != definition
                    .content_digest()
                    .map_err(ProductionRoleQualificationOwnerErrorV1::Definition)?
        {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "artifact definition",
            ));
        }
        if artifact_write.artifact_id != artifact.parameter_manifest.artifact_id
            || artifact_write.artifact_digest != artifact.parameter_manifest.child_bundle_digest
            || artifact_write.encoded_size_bytes != artifact.parameter_manifest.encoded_size_bytes
            || artifact_write.artifact_digest.is_zero()
        {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "artifact write",
            ));
        }
        if state_owner.definition() != &definition {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "state definition",
            ));
        }
        if initial_state.cell_id != definition.cell_id
            || initial_state.generation != definition.generation
            || initial_state.state_schema_digest != definition.state_schema_digest
            || initial_state.state_digest.is_zero()
            || initial_state.authority.grants_any()
        {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "initial state",
            ));
        }
        state_owner.reload(&initial_state)?;
        if host_evidence_digest.is_some_and(Digest32::is_zero)
            || observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(ProductionRoleQualificationOwnerErrorV1::EmptyDigest(
                "host/observer evidence",
            ));
        }
        let artifact_relative = artifact_relative.as_ref().to_path_buf();
        validate_relative_path(&artifact_relative)?;
        let artifact_root = artifact_root.as_ref().to_path_buf();
        let state_path = state_path.as_ref().to_path_buf();
        ensure_state_snapshot(&state_owner, &state_path)?;
        Ok(Self {
            definition,
            artifact,
            artifact_receipt,
            artifact_owner,
            artifact_write,
            registry,
            artifact_root,
            artifact_relative,
            state_owner,
            state_path,
            current_state: initial_state.clone(),
            initial_state,
            executor,
            reload_sequence: 0,
            host_evidence_digest,
            observer_evidence_digest,
        })
    }

    #[must_use]
    pub fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    #[must_use]
    pub fn artifact(&self) -> &TypedRoleArtifactV1 {
        &self.artifact
    }

    #[must_use]
    pub fn artifact_receipt(&self) -> &TypedRoleArtifactReceiptV1 {
        &self.artifact_receipt
    }

    #[must_use]
    pub fn current_state(&self) -> &StateCommitReceiptV1 {
        &self.current_state
    }

    /// Persist the current state owner snapshot.  The caller can use the
    /// returned digest as the external restart witness.
    pub fn persist_state(&self) -> Result<Digest32, ProductionRoleQualificationOwnerErrorV1> {
        Ok(self.state_owner.persist(&self.state_path)?)
    }

    /// Tombstone this role through the real checkpoint owner.  A tombstone is
    /// a state-owner fact; it is not a route activation or a target-host
    /// witness.
    pub fn tombstone(
        &mut self,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, ProductionRoleQualificationOwnerErrorV1> {
        if reason_digest.is_zero() {
            return Err(ProductionRoleQualificationOwnerErrorV1::EmptyDigest(
                "tombstone reason",
            ));
        }
        Ok(self
            .state_owner
            .tombstone_persisted(&self.state_path, reason_digest)?)
    }

    fn operation_id(
        &self,
        domain: &str,
        digest: Digest32,
    ) -> Result<StableId, ProductionRoleQualificationOwnerErrorV1> {
        StableId::new(format!(
            "{domain}.{}.{}.{}",
            self.definition.cell_id,
            self.definition.generation.get(),
            digest
        ))
        .map_err(|_| ProductionRoleQualificationOwnerErrorV1::EmptyId("operation"))
    }

    fn not_exercised_digest(&self, domain: &[u8], recovery: Digest32) -> Digest32 {
        Digest32::of_parts(&[
            PRODUCTION_ROLE_QUALIFICATION_OWNER_SCHEMA_V1.as_bytes(),
            domain,
            self.definition.cell_id.as_str().as_bytes(),
            recovery.as_array(),
        ])
    }

    fn reload_artifact_strict(
        &mut self,
    ) -> Result<RoleQualificationArtifactReceiptV1, ProductionRoleQualificationOwnerErrorV1> {
        let path = self.artifact_root.join(&self.artifact_relative);
        let file = File::open(path).map_err(|_| {
            ProductionRoleQualificationOwnerErrorV1::Artifact(
                crate::ProductionOwnerError::ArtifactUnavailable(
                    self.artifact.parameter_manifest.artifact_id.clone(),
                ),
            )
        })?;
        self.reload_sequence = self.reload_sequence.checked_add(1).ok_or(
            ProductionRoleQualificationOwnerErrorV1::Binding("reload sequence"),
        )?;
        let operation = self.operation_id(
            "role-qualification.reload",
            Digest32::of_parts(&[
                self.artifact_write.artifact_digest.as_array(),
                &self.reload_sequence.to_be_bytes(),
            ]),
        );
        let (bytes, load) = self.artifact_owner.load_candidate(
            operation?,
            file,
            &self.registry,
            &self.artifact_write.artifact_id,
            &self.artifact_write,
            &self.artifact_relative,
            self.host_evidence_digest,
            self.observer_evidence_digest,
        )?;
        if load.registry_head_digest != self.artifact_write.registry_head_digest
            || load.payload_digest != self.artifact_write.artifact_digest
            || bytes.len() as u64 != self.artifact_write.encoded_size_bytes
        {
            return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                "CAS/registry head",
            ));
        }
        let state_bytes = self.state_owner.reload(&self.current_state)?;
        let reload_digest = Digest32::of_parts(&[
            b"hepta.role-qualification.state-reload.v1",
            self.current_state.content_digest().as_array(),
            Digest32::of_bytes(&state_bytes).as_array(),
            load.content_digest().as_array(),
        ]);
        let definition_digest = self
            .definition
            .content_digest()
            .map_err(ProductionRoleQualificationOwnerErrorV1::Definition)?;
        let receipt = RoleQualificationArtifactReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            definition_digest,
            artifact_digest: load.payload_digest,
            cas_receipt_digest: load.content_digest(),
            registry_receipt_digest: load.registry_head_digest,
            state_checkpoint_digest: self.current_state.content_digest(),
            reload_receipt_digest: reload_digest,
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate_against(&self.definition).map_err(|_| {
            ProductionRoleQualificationOwnerErrorV1::Binding("qualification artifact receipt")
        })?;
        Ok(receipt)
    }

    fn exercise_fault_strict(
        &mut self,
        kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationFaultReceiptV1, ProductionRoleQualificationOwnerErrorV1> {
        let (recovery, recovered) = match kind {
            RoleQualificationFaultKindV1::ArtifactReload => {
                let receipt = self.reload_artifact_strict()?;
                (receipt.content_digest(), true)
            }
            RoleQualificationFaultKindV1::CheckpointRestart => {
                let bytes = self.state_owner.reload(&self.current_state)?;
                (
                    Digest32::of_parts(&[
                        b"hepta.role-qualification.checkpoint-restart.v1",
                        self.current_state.content_digest().as_array(),
                        Digest32::of_bytes(&bytes).as_array(),
                    ]),
                    true,
                )
            }
            RoleQualificationFaultKindV1::Rollback => {
                let bytes = self
                    .state_owner
                    .rollback_persisted(&self.state_path, &self.initial_state)?;
                self.current_state = self.initial_state.clone();
                (
                    Digest32::of_parts(&[
                        b"hepta.role-qualification.rollback-recovery.v1",
                        self.current_state.content_digest().as_array(),
                        Digest32::of_bytes(&bytes).as_array(),
                    ]),
                    true,
                )
            }
            RoleQualificationFaultKindV1::PowerLossRecovery
            | RoleQualificationFaultKindV1::StaleGeneration
            | RoleQualificationFaultKindV1::RouteFence => {
                // These observations require a target-host lifecycle owner or
                // a CNS/router owner.  Returning unavailable is intentional:
                // this bridge must never relabel a repository restart as
                // physical power-loss or route-fence evidence.
                return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                    "fault requires external lifecycle owner",
                ));
            }
        };
        let rollback = if kind == RoleQualificationFaultKindV1::Rollback {
            Digest32::of_parts(&[
                b"hepta.role-qualification.rollback.v1",
                recovery.as_array(),
                self.current_state.content_digest().as_array(),
            ])
        } else {
            self.not_exercised_digest(b"rollback-not-exercised", recovery)
        };
        let tombstone = self.not_exercised_digest(b"tombstone-not-exercised", recovery);
        let no_resurrection = self.not_exercised_digest(b"no-resurrection-not-exercised", recovery);
        let receipt = RoleQualificationFaultReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            kind,
            recovery_receipt_digest: recovery,
            rollback_receipt_digest: rollback,
            tombstone_receipt_digest: tombstone,
            no_resurrection_witness_digest: no_resurrection,
            recovered,
            rollback_verified: kind == RoleQualificationFaultKindV1::Rollback,
            no_resurrection_verified: false,
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate_against(&self.definition).map_err(|_| {
            ProductionRoleQualificationOwnerErrorV1::Binding("qualification fault receipt")
        })?;
        Ok(receipt)
    }
}

impl<E> RoleQualificationOwnerV1 for ProductionRoleQualificationOwnerV1<E>
where
    E: RoleQualificationStepExecutorV1,
{
    fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    fn reload_artifact(
        &mut self,
    ) -> Result<RoleQualificationArtifactReceiptV1, RoleQualificationOwnerErrorV1> {
        self.reload_artifact_strict()
            .map_err(|_| RoleQualificationOwnerErrorV1::ArtifactUnavailable)
    }

    fn step(
        &mut self,
        input_frontier_digest: Digest32,
    ) -> Result<CellStepReceiptV1, RoleQualificationOwnerErrorV1> {
        if input_frontier_digest.is_zero() {
            return Err(RoleQualificationOwnerErrorV1::StateUnavailable);
        }
        let execution = self
            .executor
            .execute_step(
                &self.definition,
                input_frontier_digest,
                self.current_state.state_digest,
            )
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        let step = execution.step;
        step.validate()
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        if step.role != self.definition.role
            || step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.scope_digest != self.definition.scope_digest
            || step.capability_digest
                != self
                    .definition
                    .capability_digest()
                    .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?
            || step.input_frontier_digest != input_frontier_digest
            || step.state_predecessor_digest != self.current_state.state_digest
            || Digest32::of_bytes(&execution.state_bytes) != step.state_successor_digest
            || execution.state_bytes.is_empty()
        {
            return Err(RoleQualificationOwnerErrorV1::StateUnavailable);
        }
        let operation = self
            .operation_id(
                "role-qualification.step",
                Digest32::of_parts(&[
                    input_frontier_digest.as_array(),
                    self.current_state.state_digest.as_array(),
                ]),
            )
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        let receipt = self
            .state_owner
            .commit_step_persisted(
                &self.state_path,
                operation,
                &step,
                execution.state_bytes,
                self.host_evidence_digest,
                self.observer_evidence_digest,
            )
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        self.current_state = receipt;
        Ok(step)
    }

    fn exercise_fault(
        &mut self,
        kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationFaultReceiptV1, RoleQualificationOwnerErrorV1> {
        self.exercise_fault_strict(kind)
            .map_err(|_| RoleQualificationOwnerErrorV1::FaultUnavailable)
    }
}

fn validate_relative_path(path: &Path) -> Result<(), ProductionRoleQualificationOwnerErrorV1> {
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(ProductionRoleQualificationOwnerErrorV1::InvalidRelativePath);
    }
    Ok(())
}

fn ensure_state_snapshot(
    owner: &DurableLearnedRoleOwnerV1,
    path: &Path,
) -> Result<(), ProductionRoleQualificationOwnerErrorV1> {
    match crate::DurableStateOwnerV1::snapshot_digest(path)? {
        Some(_) => {
            let persisted = crate::DurableStateOwnerV1::load(path)?;
            if persisted != owner.snapshot() {
                return Err(ProductionRoleQualificationOwnerErrorV1::Binding(
                    "state snapshot owner binding",
                ));
            }
        }
        None => {
            owner.persist(path)?;
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "qualification_owner_tests.rs"]
mod tests;
