//! Qualification owner for the specialized MemoryRead lifecycle.
//!
//! MemoryRead cannot use the generic learned-role artifact facade because its
//! retrieval snapshot and opaque bundle have different ownership semantics.
//! This owner joins the existing MemoryRead CAS reload owner and durable state
//! owner to the common role qualification harness without decoding or
//! re-interpreting the #1452 bundle.

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
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ArtifactCasOwnerV1;
use crate::ArtifactRegistry;
use crate::ArtifactWriteReceiptV1;
use crate::DurableMemoryReadStateOwnerErrorV1;
use crate::DurableMemoryReadStateOwnerV1;
use crate::MemoryReadArtifactOwnerV1;
use crate::MemoryReadArtifactReceiptV1;
use crate::MemoryReadArtifactV1;
use crate::MemoryReadBundleOwnerErrorV1;
use crate::MemoryReadExecutionV1;
use crate::StateCommitReceiptV1;
use crate::StateTombstoneReceiptV1;

pub const MEMORY_READ_QUALIFICATION_OWNER_SCHEMA_V1: &str =
    "hepta.learning-artifacts.memory-read-qualification-owner.v1";

/// A MemoryRead runtime supplies a retrieval execution and the exact state
/// bytes that execution committed. The owner below only fences and persists
/// those bytes; it does not create a retrieval result from a query digest.
pub trait MemoryReadQualificationStepExecutorV1 {
    fn execute_step(
        &mut self,
        definition: &CellDefinitionV2,
        input_frontier_digest: Digest32,
        predecessor_state_digest: Digest32,
    ) -> Result<MemoryReadQualificationExecutionV1, MemoryReadQualificationExecutorErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadQualificationExecutionV1 {
    pub execution: MemoryReadExecutionV1,
    pub state_bytes: Vec<u8>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum MemoryReadQualificationExecutorErrorV1 {
    Unavailable,
    Binding(&'static str),
}

impl fmt::Display for MemoryReadQualificationExecutorErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for MemoryReadQualificationExecutorErrorV1 {}

#[derive(Debug)]
pub enum MemoryReadQualificationOwnerErrorV1 {
    Contract(CellRoleContractErrorV1),
    Artifact(MemoryReadBundleOwnerErrorV1),
    State(DurableMemoryReadStateOwnerErrorV1),
    Durable(crate::DurableStateError),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    Binding(&'static str),
    InvalidRelativePath,
    Executor(MemoryReadQualificationExecutorErrorV1),
    Io,
}

impl fmt::Display for MemoryReadQualificationOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for MemoryReadQualificationOwnerErrorV1 {}

impl From<MemoryReadBundleOwnerErrorV1> for MemoryReadQualificationOwnerErrorV1 {
    fn from(value: MemoryReadBundleOwnerErrorV1) -> Self {
        Self::Artifact(value)
    }
}

impl From<DurableMemoryReadStateOwnerErrorV1> for MemoryReadQualificationOwnerErrorV1 {
    fn from(value: DurableMemoryReadStateOwnerErrorV1) -> Self {
        Self::State(value)
    }
}

impl From<CellRoleContractErrorV1> for MemoryReadQualificationOwnerErrorV1 {
    fn from(value: CellRoleContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

impl From<crate::DurableStateError> for MemoryReadQualificationOwnerErrorV1 {
    fn from(value: crate::DurableStateError) -> Self {
        Self::Durable(value)
    }
}

/// Specialized durable qualification owner for one MemoryRead generation.
#[derive(Clone, Debug)]
pub struct MemoryReadQualificationOwnerV1<E> {
    definition: CellDefinitionV2,
    artifact: MemoryReadArtifactV1,
    artifact_owner: MemoryReadArtifactOwnerV1,
    cas_owner: ArtifactCasOwnerV1,
    write_receipt: ArtifactWriteReceiptV1,
    registry: ArtifactRegistry,
    artifact_root: PathBuf,
    artifact_relative: PathBuf,
    state_owner: DurableMemoryReadStateOwnerV1,
    state_path: PathBuf,
    current_state: StateCommitReceiptV1,
    initial_state: StateCommitReceiptV1,
    executor: E,
    reload_sequence: u64,
    host_evidence_digest: Option<Digest32>,
    observer_evidence_digest: Option<Digest32>,
}

impl<E> MemoryReadQualificationOwnerV1<E>
where
    E: MemoryReadQualificationStepExecutorV1,
{
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        definition: CellDefinitionV2,
        artifact: MemoryReadArtifactV1,
        artifact_receipt: MemoryReadArtifactReceiptV1,
        artifact_owner: MemoryReadArtifactOwnerV1,
        cas_owner: ArtifactCasOwnerV1,
        write_receipt: ArtifactWriteReceiptV1,
        registry: ArtifactRegistry,
        artifact_root: impl AsRef<Path>,
        artifact_relative: impl AsRef<Path>,
        state_owner: DurableMemoryReadStateOwnerV1,
        state_path: impl AsRef<Path>,
        initial_state: StateCommitReceiptV1,
        executor: E,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<Self, MemoryReadQualificationOwnerErrorV1> {
        definition.validate()?;
        if definition.role != CellRoleV1::MemoryRead {
            return Err(MemoryReadQualificationOwnerErrorV1::Binding("role"));
        }
        artifact
            .validate()
            .map_err(MemoryReadBundleOwnerErrorV1::from)?;
        artifact_receipt
            .validate_against(&artifact)
            .map_err(MemoryReadBundleOwnerErrorV1::from)?;
        if artifact.definition != definition
            || write_receipt.artifact_id != artifact.parameter_manifest.artifact_id
            || write_receipt.artifact_digest != artifact.parameter_manifest.child_bundle_digest
            || write_receipt.encoded_size_bytes != artifact.parameter_manifest.encoded_size_bytes
            || write_receipt.artifact_digest.is_zero()
        {
            return Err(MemoryReadQualificationOwnerErrorV1::Binding(
                "artifact write",
            ));
        }
        if state_owner.definition() != &definition {
            return Err(MemoryReadQualificationOwnerErrorV1::Binding(
                "state definition",
            ));
        }
        if initial_state.cell_id != definition.cell_id
            || initial_state.generation != definition.generation
            || initial_state.state_schema_digest != definition.state_schema_digest
            || initial_state.state_digest.is_zero()
            || initial_state.authority.grants_any()
        {
            return Err(MemoryReadQualificationOwnerErrorV1::Binding(
                "initial state",
            ));
        }
        state_owner.reload(&initial_state)?;
        if host_evidence_digest.is_some_and(Digest32::is_zero)
            || observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(MemoryReadQualificationOwnerErrorV1::EmptyDigest(
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
            artifact_owner,
            cas_owner,
            write_receipt,
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
    pub fn current_state(&self) -> &StateCommitReceiptV1 {
        &self.current_state
    }

    pub fn persist_state(&self) -> Result<Digest32, MemoryReadQualificationOwnerErrorV1> {
        Ok(self.state_owner.persist(&self.state_path)?)
    }

    pub fn tombstone(
        &mut self,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, MemoryReadQualificationOwnerErrorV1> {
        if reason_digest.is_zero() {
            return Err(MemoryReadQualificationOwnerErrorV1::EmptyDigest(
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
    ) -> Result<StableId, MemoryReadQualificationOwnerErrorV1> {
        StableId::new(format!(
            "{domain}.{}.{}",
            self.definition.generation.get(),
            digest
        ))
        .map_err(|_| MemoryReadQualificationOwnerErrorV1::EmptyId("operation"))
    }

    fn reload_artifact_strict(
        &mut self,
    ) -> Result<RoleQualificationArtifactReceiptV1, MemoryReadQualificationOwnerErrorV1> {
        let path = self.artifact_root.join(&self.artifact_relative);
        let file = File::open(path).map_err(|_| MemoryReadQualificationOwnerErrorV1::Io)?;
        self.reload_sequence = self.reload_sequence.checked_add(1).ok_or(
            MemoryReadQualificationOwnerErrorV1::Binding("reload sequence"),
        )?;
        let operation = self.operation_id(
            "memory-read-qualification.reload",
            Digest32::of_parts(&[
                self.write_receipt.artifact_digest.as_array(),
                &self.reload_sequence.to_be_bytes(),
            ]),
        )?;
        let reload = self.artifact_owner.reload_bundle(
            &self.cas_owner,
            operation,
            file,
            &self.registry,
            self.definition.clone(),
            self.artifact.parameter_manifest.clone(),
            &self.write_receipt,
            &self.artifact_relative,
            self.host_evidence_digest,
            self.observer_evidence_digest,
        )?;
        reload.validate()?;
        let definition_digest = self
            .definition
            .content_digest()
            .map_err(MemoryReadQualificationOwnerErrorV1::Contract)?;
        let reload_digest = Digest32::of_parts(&[
            self.current_state.content_digest().as_array(),
            reload.load_receipt.content_digest().as_array(),
            Digest32::of_bytes(&reload.payload).as_array(),
        ]);
        let receipt = RoleQualificationArtifactReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            definition_digest,
            artifact_digest: reload.load_receipt.payload_digest,
            cas_receipt_digest: reload.load_receipt.content_digest(),
            registry_receipt_digest: reload.load_receipt.registry_head_digest,
            state_checkpoint_digest: self.current_state.content_digest(),
            reload_receipt_digest: reload_digest,
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt
            .validate_against(&self.definition)
            .map_err(|_| MemoryReadQualificationOwnerErrorV1::Binding("artifact receipt"))?;
        Ok(receipt)
    }

    fn not_exercised_digest(&self, domain: &[u8], recovery: Digest32) -> Digest32 {
        Digest32::of_parts(&[
            MEMORY_READ_QUALIFICATION_OWNER_SCHEMA_V1.as_bytes(),
            domain,
            self.definition.cell_id.as_str().as_bytes(),
            recovery.as_array(),
        ])
    }

    fn exercise_fault_strict(
        &mut self,
        kind: RoleQualificationFaultKindV1,
    ) -> Result<RoleQualificationFaultReceiptV1, MemoryReadQualificationOwnerErrorV1> {
        let (recovery, recovered) = match kind {
            RoleQualificationFaultKindV1::ArtifactReload => {
                let receipt = self.reload_artifact_strict()?;
                (receipt.content_digest(), true)
            }
            RoleQualificationFaultKindV1::CheckpointRestart => {
                let bytes = self.state_owner.reload(&self.current_state)?;
                (
                    Digest32::of_parts(&[
                        b"hepta.memory-read-qualification.checkpoint-restart.v1",
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
                        b"hepta.memory-read-qualification.rollback-recovery.v1",
                        self.current_state.content_digest().as_array(),
                        Digest32::of_bytes(&bytes).as_array(),
                    ]),
                    true,
                )
            }
            RoleQualificationFaultKindV1::PowerLossRecovery
            | RoleQualificationFaultKindV1::StaleGeneration
            | RoleQualificationFaultKindV1::RouteFence => {
                return Err(MemoryReadQualificationOwnerErrorV1::Binding(
                    "fault requires external lifecycle owner",
                ));
            }
        };
        let rollback = if kind == RoleQualificationFaultKindV1::Rollback {
            Digest32::of_parts(&[
                b"hepta.memory-read-qualification.rollback.v1",
                recovery.as_array(),
                self.current_state.content_digest().as_array(),
            ])
        } else {
            self.not_exercised_digest(b"rollback-not-exercised", recovery)
        };
        let receipt = RoleQualificationFaultReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            role: self.definition.role,
            kind,
            recovery_receipt_digest: recovery,
            rollback_receipt_digest: rollback,
            tombstone_receipt_digest: self
                .not_exercised_digest(b"tombstone-not-exercised", recovery),
            no_resurrection_witness_digest: self
                .not_exercised_digest(b"no-resurrection-not-exercised", recovery),
            recovered,
            rollback_verified: kind == RoleQualificationFaultKindV1::Rollback,
            no_resurrection_verified: false,
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt
            .validate_against(&self.definition)
            .map_err(|_| MemoryReadQualificationOwnerErrorV1::Binding("fault receipt"))?;
        Ok(receipt)
    }
}

impl<E> RoleQualificationOwnerV1 for MemoryReadQualificationOwnerV1<E>
where
    E: MemoryReadQualificationStepExecutorV1,
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
        let step = execution.execution.role_step.receipt.clone();
        step.validate()
            .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        if step.role != CellRoleV1::MemoryRead
            || step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.scope_digest != self.definition.scope_digest
            || step.input_frontier_digest != input_frontier_digest
            || step.state_predecessor_digest != self.current_state.state_digest
            || Digest32::of_bytes(&execution.state_bytes) != step.state_successor_digest
            || execution.state_bytes.is_empty()
        {
            return Err(RoleQualificationOwnerErrorV1::StateUnavailable);
        }
        let operation = StableId::new(format!(
            "memory-read-qualification.step.{}.{}",
            self.definition.generation.get(),
            input_frontier_digest
        ))
        .map_err(|_| RoleQualificationOwnerErrorV1::StateUnavailable)?;
        let receipt = self
            .state_owner
            .commit_execution_persisted(
                &self.state_path,
                operation,
                &execution.execution,
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

fn validate_relative_path(path: &Path) -> Result<(), MemoryReadQualificationOwnerErrorV1> {
    if path.is_absolute()
        || path.components().any(|component| {
            matches!(
                component,
                Component::ParentDir | Component::RootDir | Component::Prefix(_)
            )
        })
    {
        return Err(MemoryReadQualificationOwnerErrorV1::InvalidRelativePath);
    }
    Ok(())
}

fn ensure_state_snapshot(
    owner: &DurableMemoryReadStateOwnerV1,
    path: &Path,
) -> Result<(), MemoryReadQualificationOwnerErrorV1> {
    match crate::DurableStateOwnerV1::snapshot_digest(path)? {
        Some(_) => {
            let persisted = crate::DurableStateOwnerV1::load(path)?;
            if persisted != owner.snapshot() {
                return Err(MemoryReadQualificationOwnerErrorV1::Binding(
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
#[path = "memory_read_qualification_tests.rs"]
mod tests;
