//! Durable learned-role state owner.
//!
//! This owner is shared by Representation, Predictor, Value, Decision and
//! Evaluator. It persists the bytes produced by a role runtime through the
//! signed `StateCheckpointOwnerV1`; it does not invoke a model, choose an
//! artifact, activate a route, or manufacture host/observer evidence.

use std::error::Error;
use std::fmt;
use std::path::Path;

use codex_hepta_cell_roles::CellRoleStepV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::CellStepReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::DurableStateError;
use crate::DurableStateOwnerV1;
use crate::ProductionOwnerError;
use crate::StateCheckpointOwnerV1;
use crate::StateCheckpointSnapshotV1;
use crate::StateCommitReceiptV1;
use crate::StateTombstoneReceiptV1;
use crate::is_generic_learned_role;

pub const DURABLE_LEARNED_ROLE_OWNER_SCHEMA_V1: &str = "hepta.learned-role.durable-owner.v1";

#[derive(Debug)]
pub enum DurableLearnedRoleOwnerErrorV1 {
    Definition,
    RoleNotLearned(CellRoleV1),
    Binding(&'static str),
    State(ProductionOwnerError),
    Durable(DurableStateError),
}

impl fmt::Display for DurableLearnedRoleOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for DurableLearnedRoleOwnerErrorV1 {}

impl From<ProductionOwnerError> for DurableLearnedRoleOwnerErrorV1 {
    fn from(value: ProductionOwnerError) -> Self {
        Self::State(value)
    }
}

impl From<DurableStateError> for DurableLearnedRoleOwnerErrorV1 {
    fn from(value: DurableStateError) -> Self {
        Self::Durable(value)
    }
}

/// State owner for one immutable learned-role definition.
#[derive(Clone, Debug)]
pub struct DurableLearnedRoleOwnerV1 {
    definition: CellDefinitionV2,
    owner_id: StableId,
    state: StateCheckpointOwnerV1,
}

impl DurableLearnedRoleOwnerV1 {
    pub fn new(
        definition: CellDefinitionV2,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<Self, DurableLearnedRoleOwnerErrorV1> {
        definition
            .validate()
            .map_err(|_| DurableLearnedRoleOwnerErrorV1::Definition)?;
        if !is_generic_learned_role(definition.role) {
            return Err(DurableLearnedRoleOwnerErrorV1::RoleNotLearned(
                definition.role,
            ));
        }
        let state = StateCheckpointOwnerV1::new(owner_id.clone(), signing_key)?;
        Ok(Self {
            definition,
            owner_id,
            state,
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

    /// Commit state bytes corresponding to an adapter step. The digest in the
    /// typed step must equal the exact bytes handed to the state owner.
    pub fn commit_step(
        &mut self,
        operation_id: StableId,
        step: &CellStepReceiptV1,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        self.validate_step(step, &state_bytes)?;
        Ok(self.state.commit(
            operation_id,
            self.definition.cell_id.clone(),
            self.definition.generation,
            self.definition.state_schema_digest,
            step.state_predecessor_digest,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?)
    }

    pub fn commit_adapter_step<T>(
        &mut self,
        operation_id: StableId,
        step: &CellRoleStepV1<T>,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        self.commit_step(
            operation_id,
            &step.receipt,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )
    }

    /// Commit and persist as one owner operation. The candidate owner is
    /// written first; the live in-memory head is replaced only after the
    /// durable snapshot succeeds, so a failed filesystem operation cannot
    /// leave the caller with an acknowledged but unpersisted state.
    pub fn commit_step_persisted(
        &mut self,
        path: impl AsRef<Path>,
        operation_id: StableId,
        step: &CellStepReceiptV1,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.commit_step(
            operation_id,
            step,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn commit_adapter_step_persisted<T>(
        &mut self,
        path: impl AsRef<Path>,
        operation_id: StableId,
        step: &CellRoleStepV1<T>,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        self.commit_step_persisted(
            path,
            operation_id,
            &step.receipt,
            state_bytes,
            host_evidence_digest,
            observer_evidence_digest,
        )
    }

    /// Persist the predecessor checkpoint required by the first typed step.
    /// The initial state is explicit; the owner never treats a missing
    /// predecessor as a valid successor transition.
    pub fn seed_initial_state(
        &mut self,
        operation_id: StableId,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        if state_bytes.is_empty() {
            return Err(DurableLearnedRoleOwnerErrorV1::Binding("initial state"));
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
        path: impl AsRef<Path>,
        operation_id: StableId,
        state_bytes: Vec<u8>,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<StateCommitReceiptV1, DurableLearnedRoleOwnerErrorV1> {
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

    pub fn reload(
        &self,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableLearnedRoleOwnerErrorV1> {
        if receipt.cell_id != self.definition.cell_id
            || receipt.generation != self.definition.generation
            || receipt.state_schema_digest != self.definition.state_schema_digest
        {
            return Err(DurableLearnedRoleOwnerErrorV1::Binding("state receipt"));
        }
        Ok(self.state.reload(&self.definition.cell_id, receipt)?)
    }

    pub fn persist(
        &self,
        path: impl AsRef<Path>,
    ) -> Result<Digest32, DurableLearnedRoleOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist(path, &self.state.snapshot())?)
    }

    pub fn persist_if_digest(
        &self,
        path: impl AsRef<Path>,
        expected_digest: Option<Digest32>,
    ) -> Result<Digest32, DurableLearnedRoleOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist_if_digest(
            path,
            &self.state.snapshot(),
            expected_digest,
        )?)
    }

    pub fn reopen(
        path: impl AsRef<Path>,
        definition: CellDefinitionV2,
        owner_id: StableId,
        signing_key: SigningKey,
    ) -> Result<Self, DurableLearnedRoleOwnerErrorV1> {
        let owner = Self::new(definition, owner_id.clone(), signing_key.clone())?;
        let state = DurableStateOwnerV1::reopen(path, owner_id, signing_key)?;
        Ok(Self { state, ..owner })
    }

    #[must_use]
    pub fn snapshot(&self) -> StateCheckpointSnapshotV1 {
        self.state.snapshot()
    }

    pub fn rollback(
        &mut self,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableLearnedRoleOwnerErrorV1> {
        if receipt.cell_id != self.definition.cell_id {
            return Err(DurableLearnedRoleOwnerErrorV1::Binding("rollback cell"));
        }
        Ok(self.state.rollback(&self.definition.cell_id, receipt)?)
    }

    pub fn rollback_persisted(
        &mut self,
        path: impl AsRef<Path>,
        receipt: &StateCommitReceiptV1,
    ) -> Result<Vec<u8>, DurableLearnedRoleOwnerErrorV1> {
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
    ) -> Result<StateTombstoneReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        Ok(self.state.tombstone(
            self.definition.cell_id.clone(),
            self.definition.generation,
            reason_digest,
        )?)
    }

    pub fn tombstone_persisted(
        &mut self,
        path: impl AsRef<Path>,
        reason_digest: Digest32,
    ) -> Result<StateTombstoneReceiptV1, DurableLearnedRoleOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.tombstone(reason_digest)?;
        candidate.persist_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    fn validate_step(
        &self,
        step: &CellStepReceiptV1,
        state_bytes: &[u8],
    ) -> Result<(), DurableLearnedRoleOwnerErrorV1> {
        step.validate()
            .map_err(|_| DurableLearnedRoleOwnerErrorV1::Binding("step contract"))?;
        if step.role != self.definition.role
            || step.cell_id != self.definition.cell_id
            || step.generation != self.definition.generation
            || step.scope_digest != self.definition.scope_digest
            || step.capability_digest
                != self
                    .definition
                    .capability_digest()
                    .map_err(|_| DurableLearnedRoleOwnerErrorV1::Binding("capability"))?
            || Digest32::of_bytes(state_bytes) != step.state_successor_digest
        {
            return Err(DurableLearnedRoleOwnerErrorV1::Binding("typed step"));
        }
        if state_bytes.is_empty() || step.authority != AuthorityPosture::DENY_ALL {
            return Err(DurableLearnedRoleOwnerErrorV1::Binding("state authority"));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::CellStepStatusV1;
    use codex_hepta_types::CellUpdateModeV1;
    use codex_hepta_types::Generation;

    fn d(seed: u8) -> Digest32 {
        Digest32::from_array([seed; 32])
    }
    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn definition() -> CellDefinitionV2 {
        let role = CellRoleV1::Representation;
        let capability_profile = CellCapabilityProfileV1 {
            role,
            observation_schema_digest: d(1),
            output_schema_digest: d(2),
            state_schema_digest: d(3),
            input_port_digest: d(4),
            output_port_digest: d(5),
            termination_port_digest: d(6),
            owner_module: id("hepta.rep.owner"),
            persistence_class: CellPersistenceClassV1::Checkpointed,
            update_mode: CellUpdateModeV1::InferenceOnly,
            fallback_role: None,
            objective_digest: d(7),
            resource_budget_digest: d(8),
            evaluation_profile_digest: d(9),
            authority: AuthorityPosture::DENY_ALL,
        };
        CellDefinitionV2 {
            cell_id: id("cell.rep.durable"),
            generation: Generation::new(1).expect("gen"),
            scope_digest: d(10),
            lineage_digest: d(11),
            role,
            capability_profile,
            parameter_bundle_digest: d(12),
            state_schema_digest: d(3),
            port_abi_digest: d(13),
            owner_module: id("hepta.rep.owner"),
            objective_digest: d(7),
            fallback_role: None,
            evidence_owner: id("learning.eval.rep"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn state_owner_commits_reloads_persists_and_reopens() {
        let key = SigningKey::from_bytes(&[7; 32]);
        let definition = definition();
        let mut owner =
            DurableLearnedRoleOwnerV1::new(definition.clone(), id("owner.rep"), key.clone())
                .expect("owner");
        let state = b"representation-state-v1".to_vec();
        let genesis = owner
            .seed_initial_state(id("op.rep.genesis"), b"genesis-state".to_vec(), None, None)
            .expect("genesis");
        let step = CellStepReceiptV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: definition.role,
            capability_digest: definition.capability_digest().expect("cap"),
            input_frontier_digest: d(20),
            state_predecessor_digest: genesis.state_digest,
            state_successor_digest: Digest32::of_bytes(&state),
            output_digest: d(22),
            uncertainty_ppm: 1,
            ood_ppm: 2,
            resource_receipt_digest: d(23),
            evidence_digest: d(24),
            status: CellStepStatusV1::Accepted,
            authority: AuthorityPosture::DENY_ALL,
        };
        let receipt = owner
            .commit_step(id("op.rep"), &step, state.clone(), None, None)
            .expect("commit");
        assert_eq!(owner.reload(&receipt).expect("reload"), state);
        let path = std::env::temp_dir().join(format!("hepta-role-state-{}", std::process::id()));
        let _ = std::fs::remove_file(&path);
        owner.persist(&path).expect("persist");
        let reopened =
            DurableLearnedRoleOwnerV1::reopen(path.clone(), definition, id("owner.rep"), key)
                .expect("reopen");
        assert_eq!(
            reopened.reload(&receipt).expect("reloaded"),
            b"representation-state-v1"
        );
        let _ = std::fs::remove_file(path);
    }
}
