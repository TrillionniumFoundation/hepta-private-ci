//! Formal production-side seam for a `MemoryRead` artifact.
//!
//! The experimental MemoryCell labs may use their own bundle encoding.  This
//! module deliberately does not pretend to load that encoding or to own a
//! cognitive store.  Instead it binds an externally materialized payload to
//! the shared `CellDefinitionV2`, the cell-specific parameter manifest and the
//! existing retrieval role adapter.  Every operation produces a deterministic
//! receipt that can be replayed from the same immutable inputs.

use std::error::Error;
use std::fmt;

use codex_hepta_cell_roles::CellAdapterContextV1;
use codex_hepta_cell_roles::CellRoleAdapterErrorV1;
use codex_hepta_cell_roles::CellRoleGateErrorV1;
use codex_hepta_cell_roles::CellRoleMetricProfileV1;
use codex_hepta_cell_roles::CellRoleMetricReceiptV1;
use codex_hepta_cell_roles::CellRoleStepV1;
use codex_hepta_cell_roles::MemoryReadAdapterV1;
use codex_hepta_cell_roles::MemoryReadResultV1;
use codex_hepta_memory_retrieval::RetrievalReceipt;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::ArtifactRegistry;
use crate::CellArtifactOwnerErrorV1;
use crate::CellParameterBundleManifestV1;
use crate::DurableStateError;
use crate::DurableStateOwnerV1;
use crate::StateCheckpointOwnerV1;
use crate::StateCheckpointSnapshotV1;
use crate::StateCommitReceiptV1;
use crate::StateTombstoneReceiptV1;

pub const MEMORY_READ_ARTIFACT_SCHEMA_V1: &str = "hepta.memory-read.artifact.v1";
pub const MEMORY_READ_STEP_SCHEMA_V1: &str = "hepta.memory-read.step.v1";
pub const MEMORY_READ_EVALUATION_SCHEMA_V1: &str = "hepta.memory-read.evaluation.v1";
pub const DURABLE_MEMORY_READ_STATE_OWNER_SCHEMA_V1: &str =
    "hepta.memory-read.durable-state-owner.v1";

/// An immutable binding between a formal cell definition and a materialized
/// parameter bundle.  `experimental_bundle_digest` is only provenance for a
/// lab-produced bundle; it is not treated as a production qualification.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadArtifactV1 {
    pub definition: CellDefinitionV2,
    pub parameter_manifest: CellParameterBundleManifestV1,
    pub experimental_bundle_digest: Digest32,
    pub artifact_digest: Digest32,
}

impl MemoryReadArtifactV1 {
    pub fn validate(&self) -> Result<(), MemoryReadOwnerErrorV1> {
        self.definition.validate()?;
        if self.definition.role != CellRoleV1::MemoryRead {
            return Err(MemoryReadOwnerErrorV1::RoleMismatch);
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
            || self.experimental_bundle_digest.is_zero()
        {
            return Err(MemoryReadOwnerErrorV1::ArtifactBinding);
        }
        if self.artifact_digest != self.content_digest()? {
            return Err(MemoryReadOwnerErrorV1::ArtifactDigestMismatch);
        }
        Ok(())
    }

    pub fn definition_digest(&self) -> Result<Digest32, MemoryReadOwnerErrorV1> {
        Ok(self.definition.content_digest()?)
    }

    pub fn content_digest(&self) -> Result<Digest32, MemoryReadOwnerErrorV1> {
        let definition = self
            .definition
            .content_digest()
            .map_err(MemoryReadOwnerErrorV1::Contract)?;
        let manifest = self.parameter_manifest.content_digest();
        let mut bytes = Vec::with_capacity(32 * 3 + MEMORY_READ_ARTIFACT_SCHEMA_V1.len());
        bytes.extend_from_slice(MEMORY_READ_ARTIFACT_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(definition.as_array());
        bytes.extend_from_slice(manifest.as_array());
        bytes.extend_from_slice(self.experimental_bundle_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Receipt for artifact ownership/provenance.  It is a publication-side
/// binding and does not grant activation or route authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadArtifactReceiptV1 {
    pub artifact_digest: Digest32,
    pub definition_digest: Digest32,
    pub parameter_manifest_digest: Digest32,
    pub experimental_bundle_digest: Digest32,
    pub owner_id: StableId,
    pub receipt_digest: Digest32,
}

impl MemoryReadArtifactReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &MemoryReadArtifactV1,
    ) -> Result<(), MemoryReadOwnerErrorV1> {
        artifact.validate()?;
        if self.artifact_digest != artifact.artifact_digest
            || self.definition_digest != artifact.definition_digest()?
            || self.parameter_manifest_digest != artifact.parameter_manifest.manifest_digest
            || self.experimental_bundle_digest != artifact.experimental_bundle_digest
            || self.owner_id.as_str().is_empty()
            || self.receipt_digest != self.content_digest()
        {
            return Err(MemoryReadOwnerErrorV1::ReceiptBinding);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 4 + self.owner_id.as_str().len());
        bytes.extend_from_slice(MEMORY_READ_ARTIFACT_SCHEMA_V1.as_bytes());
        for digest in [
            self.artifact_digest,
            self.definition_digest,
            self.parameter_manifest_digest,
            self.experimental_bundle_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        append_id(&mut bytes, &self.owner_id);
        Digest32::of_bytes(&bytes)
    }
}

/// A projection-only execution receipt for one memory lookup.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadStepReceiptV1 {
    pub artifact_digest: Digest32,
    pub query_digest: Digest32,
    pub retrieval_receipt_digest: Digest32,
    pub cell_step_receipt: CellStepReceiptV1,
    pub replay_digest: Digest32,
}

impl MemoryReadStepReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &MemoryReadArtifactV1,
    ) -> Result<(), MemoryReadOwnerErrorV1> {
        artifact.validate()?;
        if self.artifact_digest != artifact.artifact_digest
            || self.query_digest.is_zero()
            || self.retrieval_receipt_digest.is_zero()
            || self.cell_step_receipt.role != CellRoleV1::MemoryRead
            || self.cell_step_receipt.cell_id != artifact.definition.cell_id
            || self.cell_step_receipt.generation != artifact.definition.generation
            || self.cell_step_receipt.scope_digest != artifact.definition.scope_digest
            || self.replay_digest != self.content_digest()
        {
            return Err(MemoryReadOwnerErrorV1::StepBinding);
        }
        self.cell_step_receipt.validate()?;
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 4 + 32);
        bytes.extend_from_slice(MEMORY_READ_STEP_SCHEMA_V1.as_bytes());
        bytes.extend_from_slice(self.artifact_digest.as_array());
        bytes.extend_from_slice(self.query_digest.as_array());
        bytes.extend_from_slice(self.retrieval_receipt_digest.as_array());
        bytes.extend_from_slice(
            self.cell_step_receipt
                .content_digest()
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        );
        Digest32::of_bytes(&bytes)
    }
}

/// Result of one formal owner execution.  The role-specific result remains
/// available beside the replayable production-side receipt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadExecutionV1 {
    pub result: MemoryReadResultV1,
    pub role_step: CellRoleStepV1<MemoryReadResultV1>,
    pub receipt: MemoryReadStepReceiptV1,
}

/// Minimal evaluation binding.  The metric receipt performs the complete
/// structural role-profile check; this record joins it to the exact artifact.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadEvaluationReceiptV1 {
    pub artifact_digest: Digest32,
    pub cell_id: StableId,
    pub generation: Generation,
    pub profile_digest: Digest32,
    pub metric_receipt_digest: Digest32,
    pub baseline_digest: Digest32,
    pub future_window_digest: Digest32,
    pub evaluator_id: StableId,
    pub evidence_digest: Digest32,
    pub receipt_digest: Digest32,
}

impl MemoryReadEvaluationReceiptV1 {
    pub fn validate_against(
        &self,
        artifact: &MemoryReadArtifactV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<(), MemoryReadOwnerErrorV1> {
        artifact.validate()?;
        metrics.validate_structure_against(profile)?;
        if profile.role != CellRoleV1::MemoryRead
            || self.artifact_digest != artifact.artifact_digest
            || self.cell_id != artifact.definition.cell_id
            || self.generation != artifact.definition.generation
            || self.profile_digest != profile.content_digest()?
            || self.metric_receipt_digest != metrics.content_digest(profile)?
            || self.baseline_digest != profile.no_change_baseline_digest
            || self.future_window_digest != profile.future_window_digest
            || self.evaluator_id != metrics.evaluator_id
            || self.evidence_digest.is_zero()
            || self.receipt_digest != self.content_digest()
        {
            return Err(MemoryReadOwnerErrorV1::EvaluationBinding);
        }
        Ok(())
    }

    #[must_use]
    pub fn content_digest(&self) -> Digest32 {
        let mut bytes = Vec::with_capacity(32 * 7 + self.cell_id.as_str().len());
        bytes.extend_from_slice(MEMORY_READ_EVALUATION_SCHEMA_V1.as_bytes());
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
        append_id(&mut bytes, &self.cell_id);
        append_id(&mut bytes, &self.evaluator_id);
        Digest32::of_bytes(&bytes)
    }
}

/// Production-side owner facade. It validates external materialization and
/// delegates retrieval semantics to the existing role adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadArtifactOwnerV1 {
    pub owner_id: StableId,
}

impl MemoryReadArtifactOwnerV1 {
    pub fn new(owner_id: StableId) -> Result<Self, MemoryReadOwnerErrorV1> {
        if owner_id.as_str().is_empty() {
            return Err(MemoryReadOwnerErrorV1::EmptyId("owner"));
        }
        Ok(Self { owner_id })
    }

    pub fn bind(
        &self,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        experimental_bundle_digest: Digest32,
    ) -> Result<(MemoryReadArtifactV1, MemoryReadArtifactReceiptV1), MemoryReadOwnerErrorV1> {
        let mut artifact = MemoryReadArtifactV1 {
            definition,
            parameter_manifest,
            experimental_bundle_digest,
            artifact_digest: Digest32::ZERO,
        };
        artifact.artifact_digest = artifact.content_digest()?;
        artifact.validate()?;
        let mut receipt = MemoryReadArtifactReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            definition_digest: artifact.definition_digest()?,
            parameter_manifest_digest: artifact.parameter_manifest.manifest_digest,
            experimental_bundle_digest,
            owner_id: self.owner_id.clone(),
            receipt_digest: Digest32::ZERO,
        };
        receipt.receipt_digest = receipt.content_digest();
        receipt.validate_against(&artifact)?;
        Ok((artifact, receipt))
    }

    /// Bind only after the generic durable registry contains the exact typed
    /// parameter manifest projection. This prevents an unregistered digest
    /// from being treated as a production MemoryRead artifact.
    pub fn bind_registered(
        &self,
        registry: &ArtifactRegistry,
        definition: CellDefinitionV2,
        parameter_manifest: CellParameterBundleManifestV1,
        experimental_bundle_digest: Digest32,
    ) -> Result<(MemoryReadArtifactV1, MemoryReadArtifactReceiptV1), MemoryReadOwnerErrorV1> {
        parameter_manifest.validate()?;
        let projected = parameter_manifest.as_registry_manifest();
        if registry.manifest(&parameter_manifest.artifact_id) != Some(&projected)
            || !registry.is_eligible(&parameter_manifest.artifact_id)
        {
            return Err(MemoryReadOwnerErrorV1::RegistryBinding);
        }
        self.bind(definition, parameter_manifest, experimental_bundle_digest)
    }

    pub fn execute(
        &self,
        artifact: &MemoryReadArtifactV1,
        context: &CellAdapterContextV1,
        query_digest: Digest32,
        retrieval: &RetrievalReceipt,
    ) -> Result<MemoryReadExecutionV1, MemoryReadOwnerErrorV1> {
        artifact.validate()?;
        if query_digest.is_zero() {
            return Err(MemoryReadOwnerErrorV1::EmptyDigest("query"));
        }
        let capability_digest = artifact.definition.capability_digest()?;
        if context.cell_id != artifact.definition.cell_id
            || context.generation != artifact.definition.generation
            || context.scope_digest != artifact.definition.scope_digest
            || context.capability_digest != capability_digest
        {
            return Err(MemoryReadOwnerErrorV1::ContextBinding);
        }
        let role_step = MemoryReadAdapterV1::adapt(context, retrieval)?;
        let mut receipt = MemoryReadStepReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            query_digest,
            retrieval_receipt_digest: retrieval.receipt_digest,
            cell_step_receipt: role_step.receipt.clone(),
            replay_digest: Digest32::ZERO,
        };
        receipt.replay_digest = receipt.content_digest();
        receipt.validate_against(artifact)?;
        Ok(MemoryReadExecutionV1 {
            result: role_step.result.clone(),
            role_step,
            receipt,
        })
    }

    /// Recompute one step from immutable inputs and compare the resulting
    /// receipt byte-for-byte with the persisted witness. A mismatch is
    /// fail-closed and does not mutate artifact or route state.
    pub fn replay(
        &self,
        artifact: &MemoryReadArtifactV1,
        context: &CellAdapterContextV1,
        query_digest: Digest32,
        retrieval: &RetrievalReceipt,
        expected: &MemoryReadStepReceiptV1,
    ) -> Result<(), MemoryReadOwnerErrorV1> {
        expected.validate_against(artifact)?;
        let actual = self.execute(artifact, context, query_digest, retrieval)?;
        if actual.receipt != *expected {
            return Err(MemoryReadOwnerErrorV1::ReplayMismatch);
        }
        Ok(())
    }
}

/// Durable state owner for one MemoryRead cell.
///
/// Retrieval itself remains owned by `MemoryReadArtifactOwnerV1` and the
/// cognitive store. This owner supplies the missing lifecycle half: the
/// adapter's state successor is checked against the exact bytes committed to
/// the signed checkpoint owner, then the history can be persisted, reopened,
/// rolled back, and tombstoned after a process restart.
#[derive(Clone, Debug)]
pub struct DurableMemoryReadStateOwnerV1 {
    definition: CellDefinitionV2,
    owner_id: StableId,
    state: StateCheckpointOwnerV1,
}

#[derive(Debug)]
pub enum DurableMemoryReadStateOwnerErrorV1 {
    Contract(CellRoleContractErrorV1),
    State(crate::ProductionOwnerError),
    Durable(DurableStateError),
    EmptyId(&'static str),
    RoleMismatch,
    Binding(&'static str),
}

impl fmt::Display for DurableMemoryReadStateOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for DurableMemoryReadStateOwnerErrorV1 {}

impl From<CellRoleContractErrorV1> for DurableMemoryReadStateOwnerErrorV1 {
    fn from(value: CellRoleContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

impl From<crate::ProductionOwnerError> for DurableMemoryReadStateOwnerErrorV1 {
    fn from(value: crate::ProductionOwnerError) -> Self {
        Self::State(value)
    }
}

impl From<DurableStateError> for DurableMemoryReadStateOwnerErrorV1 {
    fn from(value: DurableStateError) -> Self {
        Self::Durable(value)
    }
}

impl DurableMemoryReadStateOwnerV1 {
    pub fn new(
        definition: CellDefinitionV2,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<Self, DurableMemoryReadStateOwnerErrorV1> {
        definition.validate()?;
        if definition.role != CellRoleV1::MemoryRead {
            return Err(DurableMemoryReadStateOwnerErrorV1::RoleMismatch);
        }
        if owner_id.as_str().is_empty() {
            return Err(DurableMemoryReadStateOwnerErrorV1::EmptyId("owner"));
        }
        Ok(Self {
            definition,
            owner_id: owner_id.clone(),
            state: StateCheckpointOwnerV1::new(owner_id, signing_key)?,
        })
    }

    #[must_use]
    pub fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    #[must_use]
    pub fn owner_id(&self) -> &StableId {
        &self.owner_id
    }

    pub fn seed_initial_state(
        &mut self,
        operation_id: StableId,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        if state_bytes.is_empty() {
            return Err(DurableMemoryReadStateOwnerErrorV1::Binding("initial state"));
        }
        Ok(self.state.commit(
            operation_id,
            self.definition.cell_id.clone(),
            self.definition.generation,
            self.definition.state_schema_digest,
            Digest32::ZERO,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?)
    }

    pub fn seed_initial_state_persisted(
        &mut self,
        path: impl AsRef<std::path::Path>,
        operation_id: StableId,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.seed_initial_state(
            operation_id,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn commit_execution(
        &mut self,
        operation_id: StableId,
        execution: &MemoryReadExecutionV1,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        self.validate_step(&execution.role_step.receipt, &state_bytes)?;
        Ok(self.state.commit(
            operation_id,
            self.definition.cell_id.clone(),
            self.definition.generation,
            self.definition.state_schema_digest,
            execution.role_step.receipt.state_predecessor_digest,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?)
    }

    pub fn commit_execution_persisted(
        &mut self,
        path: impl AsRef<std::path::Path>,
        operation_id: StableId,
        execution: &MemoryReadExecutionV1,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.commit_execution(
            operation_id,
            execution,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn reload(
        &self,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableMemoryReadStateOwnerErrorV1> {
        self.validate_receipt(receipt)?;
        Ok(self.state.reload(&self.definition.cell_id, receipt)?)
    }

    pub fn persist(
        &self,
        path: impl AsRef<std::path::Path>,
    ) -> Result<Digest32, DurableMemoryReadStateOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist(path, &self.state.snapshot())?)
    }

    pub fn persist_if_digest(
        &self,
        path: impl AsRef<std::path::Path>,
        expected_digest: Option<Digest32>,
    ) -> Result<Digest32, DurableMemoryReadStateOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist_if_digest(
            path,
            &self.state.snapshot(),
            expected_digest,
        )?)
    }

    pub fn reopen(
        path: impl AsRef<std::path::Path>,
        definition: CellDefinitionV2,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<Self, DurableMemoryReadStateOwnerErrorV1> {
        let snapshot = DurableStateOwnerV1::load(path.as_ref())?;
        if !snapshot
            .active_heads
            .iter()
            .any(|(cell_id, _)| *cell_id == definition.cell_id)
        {
            return Err(DurableMemoryReadStateOwnerErrorV1::Binding(
                "active state head",
            ));
        }
        let state = DurableStateOwnerV1::reopen(path, owner_id.clone(), signing_key.clone())?;
        let owner = Self::new(definition, owner_id, signing_key)?;
        Ok(Self { state, ..owner })
    }

    pub fn snapshot(&self) -> StateCheckpointSnapshotV1 {
        self.state.snapshot()
    }

    pub fn rollback(
        &mut self,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableMemoryReadStateOwnerErrorV1> {
        self.validate_receipt(receipt)?;
        Ok(self.state.rollback(&self.definition.cell_id, receipt)?)
    }

    pub fn rollback_persisted(
        &mut self,
        path: impl AsRef<std::path::Path>,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableMemoryReadStateOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let bytes = candidate.rollback(receipt)?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(bytes)
    }

    pub fn tombstone(
        &mut self,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        Ok(self.state.tombstone(
            self.definition.cell_id.clone(),
            self.definition.generation,
            reason_digest,
        )?)
    }

    pub fn tombstone_persisted(
        &mut self,
        path: impl AsRef<std::path::Path>,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, DurableMemoryReadStateOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.tombstone(reason_digest)?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    fn validate_receipt(
        &self,
        receipt: &StateCommitReceiptV1,
    ) -> Result<(), DurableMemoryReadStateOwnerErrorV1> {
        if receipt.cell_id != self.definition.cell_id
            || receipt.generation != self.definition.generation
            || receipt.state_schema_digest != self.definition.state_schema_digest
        {
            return Err(DurableMemoryReadStateOwnerErrorV1::Binding("state receipt"));
        }
        Ok(())
    }

    fn validate_step(
        &self,
        step: &CellStepReceiptV1,
        state_bytes: &[u8],
    ) -> Result<(), DurableMemoryReadStateOwnerErrorV1> {
        step.validate()
            .map_err(|_| DurableMemoryReadStateOwnerErrorV1::Binding("step contract"))?;
        if step.role != CellRoleV1::MemoryRead
            || step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.scope_digest != self.definition.scope_digest
            || step.capability_digest
                != self
                    .definition
                    .capability_digest()
                    .map_err(|_| DurableMemoryReadStateOwnerErrorV1::Binding("capability"))?
            || Digest32::of_bytes(state_bytes) != step.state_successor_digest
        {
            return Err(DurableMemoryReadStateOwnerErrorV1::Binding("typed step"));
        }
        if state_bytes.is_empty() || step.authority.grants_any() {
            return Err(DurableMemoryReadStateOwnerErrorV1::Binding(
                "state authority",
            ));
        }
        Ok(())
    }
}

/// Evaluation owner seam. It records evidence but deliberately does not
/// decide retention, activation or promotion.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryReadEvaluationOwnerV1 {
    pub evaluator_id: StableId,
}

impl MemoryReadEvaluationOwnerV1 {
    pub fn new(evaluator_id: StableId) -> Result<Self, MemoryReadOwnerErrorV1> {
        if evaluator_id.as_str().is_empty() {
            return Err(MemoryReadOwnerErrorV1::EmptyId("evaluator"));
        }
        Ok(Self { evaluator_id })
    }

    pub fn record(
        &self,
        artifact: &MemoryReadArtifactV1,
        profile: &CellRoleMetricProfileV1,
        metrics: &CellRoleMetricReceiptV1,
    ) -> Result<MemoryReadEvaluationReceiptV1, MemoryReadOwnerErrorV1> {
        artifact.validate()?;
        metrics.validate_structure_against(profile)?;
        if metrics.role != CellRoleV1::MemoryRead || metrics.evaluator_id != self.evaluator_id {
            return Err(MemoryReadOwnerErrorV1::EvaluationBinding);
        }
        if metrics.cell_id != artifact.definition.cell_id
            || metrics.generation != artifact.definition.generation
        {
            return Err(MemoryReadOwnerErrorV1::EvaluationBinding);
        }
        let profile_digest = profile.content_digest()?;
        let metric_receipt_digest = metrics.content_digest(profile)?;
        let mut receipt = MemoryReadEvaluationReceiptV1 {
            artifact_digest: artifact.artifact_digest,
            cell_id: artifact.definition.cell_id.clone(),
            generation: artifact.definition.generation,
            profile_digest,
            metric_receipt_digest,
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum MemoryReadOwnerErrorV1 {
    Contract(CellRoleContractErrorV1),
    Adapter(CellRoleAdapterErrorV1),
    Metric(CellRoleGateErrorV1),
    Artifact(CellArtifactOwnerErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    RoleMismatch,
    ArtifactBinding,
    ArtifactDigestMismatch,
    ReceiptBinding,
    StepBinding,
    ContextBinding,
    RegistryBinding,
    ReplayMismatch,
    EvaluationBinding,
}

impl fmt::Display for MemoryReadOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for MemoryReadOwnerErrorV1 {}

impl From<CellRoleContractErrorV1> for MemoryReadOwnerErrorV1 {
    fn from(value: CellRoleContractErrorV1) -> Self {
        Self::Contract(value)
    }
}

impl From<CellRoleAdapterErrorV1> for MemoryReadOwnerErrorV1 {
    fn from(value: CellRoleAdapterErrorV1) -> Self {
        Self::Adapter(value)
    }
}

impl From<CellRoleGateErrorV1> for MemoryReadOwnerErrorV1 {
    fn from(value: CellRoleGateErrorV1) -> Self {
        Self::Metric(value)
    }
}

impl From<CellArtifactOwnerErrorV1> for MemoryReadOwnerErrorV1 {
    fn from(value: CellArtifactOwnerErrorV1) -> Self {
        Self::Artifact(value)
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
    use crate::ArtifactEvent;
    use crate::ArtifactKind;
    use crate::ArtifactManifest;
    use crate::ArtifactRegistry;
    use codex_hepta_cell_roles::CellRoleMetricKindV1;
    use codex_hepta_cell_roles::CellRoleMetricV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellUpdateModeV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }

    fn definition() -> CellDefinitionV2 {
        let profile = CellCapabilityProfileV1 {
            role: CellRoleV1::MemoryRead,
            observation_schema_digest: digest(1),
            output_schema_digest: digest(2),
            state_schema_digest: digest(3),
            input_port_digest: digest(4),
            output_port_digest: digest(5),
            termination_port_digest: digest(6),
            owner_module: id("hepta-memory-retrieval::retrieve"),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::OutcomeProposal,
            fallback_role: Some(CellRoleV1::Representation),
            objective_digest: digest(7),
            resource_budget_digest: digest(8),
            evaluation_profile_digest: digest(9),
            authority: AuthorityPosture::DENY_ALL,
        };
        CellDefinitionV2 {
            cell_id: id("cell.memory-read.1"),
            generation: Generation::new(2).expect("generation"),
            scope_digest: digest(10),
            lineage_digest: digest(11),
            role: CellRoleV1::MemoryRead,
            state_schema_digest: profile.state_schema_digest,
            parameter_bundle_digest: digest(12),
            port_abi_digest: digest(13),
            owner_module: profile.owner_module.clone(),
            objective_digest: profile.objective_digest,
            fallback_role: profile.fallback_role,
            evidence_owner: id("observer.memory-read"),
            capability_profile: profile,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn manifest(definition: &CellDefinitionV2) -> CellParameterBundleManifestV1 {
        let mut value = CellParameterBundleManifestV1 {
            artifact_id: id("cell.memory-read.1"),
            cell_id: definition.cell_id.clone(),
            parent_artifact_id: id("cell.memory-read.parent"),
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
            producer_id: id("producer.memory-read"),
            encoded_size_bytes: 128,
            manifest_digest: Digest32::ZERO,
        };
        value.manifest_digest = value.content_digest();
        value
    }

    fn context(definition: &CellDefinitionV2) -> CellAdapterContextV1 {
        CellAdapterContextV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: CellRoleV1::MemoryRead,
            capability_digest: definition.capability_digest().expect("capability"),
            input_frontier_digest: digest(31),
            state_predecessor_digest: digest(32),
            resource_receipt_digest: digest(33),
            evidence_digest: digest(34),
        }
    }

    fn retrieval() -> RetrievalReceipt {
        RetrievalReceipt {
            query_id: id("query:1"),
            snapshot_digest: digest(40),
            results: Vec::new(),
            omitted_count: 0,
            receipt_digest: digest(41),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn artifact() -> (MemoryReadArtifactV1, MemoryReadArtifactReceiptV1) {
        MemoryReadArtifactOwnerV1::new(id("owner.memory-read"))
            .expect("owner")
            .bind(definition(), manifest(&definition()), digest(50))
            .expect("artifact")
    }

    #[test]
    fn artifact_binds_definition_manifest_and_lab_provenance() {
        let (artifact, receipt) = artifact();
        artifact.validate().expect("valid artifact");
        receipt.validate_against(&artifact).expect("valid receipt");
        assert_eq!(artifact.definition.role, CellRoleV1::MemoryRead);
        assert!(!artifact.artifact_digest.is_zero());
    }

    #[test]
    fn registered_binding_requires_exact_registry_projection() {
        let definition = definition();
        let parameter_manifest = manifest(&definition);
        let parent_id = parameter_manifest.parent_artifact_id.clone();
        let parent = ArtifactManifest {
            artifact_id: parent_id,
            kind: ArtifactKind::Parameters,
            generation: Generation::new(1).expect("generation"),
            predecessor_id: None,
            content_digest: parameter_manifest.parent_bundle_digest,
            objective_digest: parameter_manifest.objective_digest,
            support_digest: definition.lineage_digest,
            producer_id: id("producer.memory-read-parent"),
            compatibility_digest: parameter_manifest.compatibility_digest,
            encoded_size_bytes: 128,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.memory-read-parent"),
                manifest: parent,
            })
            .expect("parent");
        registry
            .append(ArtifactEvent::Register {
                event_id: id("event.memory-read-child"),
                manifest: parameter_manifest.as_registry_manifest(),
            })
            .expect("child");
        let owner = MemoryReadArtifactOwnerV1::new(id("owner.memory-read")).expect("owner");
        let (bound, _) = owner
            .bind_registered(&registry, definition, parameter_manifest, digest(51))
            .expect("registered artifact");
        assert!(registry.is_eligible(&bound.definition.cell_id));
    }

    #[test]
    fn execution_is_replayable_and_role_authority_free() {
        let (artifact, _) = artifact();
        let owner = MemoryReadArtifactOwnerV1::new(id("owner.memory-read")).expect("owner");
        let execution = owner
            .execute(
                &artifact,
                &context(&artifact.definition),
                digest(60),
                &retrieval(),
            )
            .expect("execution");
        execution
            .receipt
            .validate_against(&artifact)
            .expect("receipt");
        assert_eq!(
            execution.role_step.receipt.authority,
            AuthorityPosture::DENY_ALL
        );
        assert_eq!(execution.result.result_count, 0);
        assert_eq!(
            execution.receipt.replay_digest,
            execution.receipt.content_digest()
        );
        owner
            .replay(
                &artifact,
                &context(&artifact.definition),
                digest(60),
                &retrieval(),
                &execution.receipt,
            )
            .expect("deterministic replay");
    }

    #[test]
    fn durable_state_owner_reopens_rolls_back_and_tombstones_memory_read() {
        let definition = definition();
        let (artifact, _) = artifact();
        let key = SigningKey::from_bytes(&[61; 32]);
        let owner_id = id("owner.memory-read.state");
        let mut state_owner =
            DurableMemoryReadStateOwnerV1::new(definition.clone(), owner_id.clone(), key.clone())
                .expect("state owner");
        let initial = state_owner
            .seed_initial_state(
                id("memory-read.state.initial"),
                b"initial-state".to_vec(),
                None,
                None,
            )
            .expect("initial state");
        let mut execution_context = context(&definition);
        execution_context.state_predecessor_digest = initial.state_digest;
        let execution = MemoryReadArtifactOwnerV1::new(id("owner.memory-read"))
            .expect("artifact owner")
            .execute(&artifact, &execution_context, digest(60), &retrieval())
            .expect("execution");
        assert_eq!(
            execution.role_step.receipt.state_successor_digest,
            initial.state_digest
        );
        let directory =
            std::env::temp_dir().join(format!("hepta-memory-read-state-{}", std::process::id()));
        std::fs::create_dir_all(&directory).expect("directory");
        let path = directory.join("state.snapshot");
        let successor = state_owner
            .commit_execution_persisted(
                &path,
                id("memory-read.state.successor"),
                &execution,
                b"initial-state".to_vec(),
                None,
                None,
            )
            .expect("successor");
        let mut reopened = DurableMemoryReadStateOwnerV1::reopen(&path, definition, owner_id, key)
            .expect("reopen");
        assert_eq!(
            reopened.reload(&successor).expect("reload"),
            b"initial-state"
        );
        reopened
            .rollback_persisted(&path, &initial)
            .expect("rollback");
        reopened
            .tombstone_persisted(&path, digest(62))
            .expect("tombstone");
        std::fs::remove_dir_all(directory).expect("cleanup");
    }

    #[test]
    fn evaluation_joins_profile_and_rejects_self_evaluation() {
        let (artifact, _) = artifact();
        let profile = CellRoleMetricProfileV1::standard_for_role(
            CellRoleV1::MemoryRead,
            digest(70),
            digest(71),
            digest(72),
            digest(73),
        );
        let metrics = CellRoleMetricReceiptV1 {
            cell_id: artifact.definition.cell_id.clone(),
            generation: artifact.definition.generation,
            role: CellRoleV1::MemoryRead,
            proposer_id: id("proposal.memory-read"),
            evaluator_id: id("observer.memory-read"),
            profile_digest: profile.content_digest().expect("profile"),
            baseline_digest: profile.no_change_baseline_digest,
            evaluation_window_digest: profile.future_window_digest,
            metrics: CellRoleMetricKindV1::standard_for_role(CellRoleV1::MemoryRead)
                .iter()
                .enumerate()
                .map(|(index, kind)| CellRoleMetricV1 {
                    kind: *kind,
                    unit: kind.unit(),
                    value: 900_000,
                    sample_count: 10,
                    observation_digest: digest(80 + index as u8),
                })
                .collect(),
            evidence_digest: digest(90),
            authority: AuthorityPosture::DENY_ALL,
        };
        let owner = MemoryReadEvaluationOwnerV1::new(id("observer.memory-read")).expect("owner");
        let receipt = owner
            .record(&artifact, &profile, &metrics)
            .expect("evaluation");
        receipt
            .validate_against(&artifact, &profile, &metrics)
            .expect("replay");
        assert_eq!(receipt.baseline_digest, digest(71));
        assert!(receipt.receipt_digest != Digest32::ZERO);

        let mut self_evaluation = metrics;
        self_evaluation.evaluator_id = self_evaluation.proposer_id.clone();
        assert!(owner.record(&artifact, &profile, &self_evaluation).is_err());
    }
}
