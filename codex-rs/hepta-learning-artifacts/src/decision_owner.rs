//! Concrete DecisionCell owner over the existing artifact/CAS and state owners.
//!
//! This module is the first role-specific owner that drives the calibrated
//! intuition kernel through a durable artifact/checkpoint boundary.  It does
//! not emulate a decision with a digest: `execute` calls
//! `decide_calibrated_v3`, then projects that receipt through
//! `DecisionAdapterV1`.  CAS bytes and state bytes are still owned by the
//! existing `ArtifactCasOwnerV1` and `StateCheckpointOwnerV1` instances.
//!
//! Host and observer evidence are accepted as external receipts.  Supplying
//! repository or simulation evidence does not turn this owner into a
//! target-host production witness; the existing signed receipt verifiers and
//! target-host verifier remain the admission boundary.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::path::Path;

use codex_hepta_cell_roles::CellAdapterContextV1;
use codex_hepta_cell_roles::CellRoleStepV1;
use codex_hepta_cell_roles::DecisionAdapterErrorV1;
use codex_hepta_cell_roles::DecisionAdapterV1;
use codex_hepta_cell_roles::DecisionAuthenticationBindingV1;
use codex_hepta_cell_roles::DecisionExecutionBindingV1;
use codex_hepta_cell_roles::DecisionPolicyBindingV1;
use codex_hepta_cell_roles::DecisionResultV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedError;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleContractErrorV1;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::ArtifactCasOwnerV1;
use crate::ArtifactRegistry;
use crate::ArtifactWriteReceiptV1;
use crate::DurableStateOwnerV1;
use crate::ProductionOwnerError;
use crate::StateCheckpointOwnerV1;
use crate::StateCommitReceiptV1;
use codex_hepta_cell_roles::RoleQualificationEvidenceOriginV1;

pub const DECISION_CELL_OWNER_SCHEMA_V1: &str = "hepta.learning-artifacts.decision-cell-owner.v1";
const DECISION_POLICY_PAYLOAD_SCHEMA_V1: &[u8] = b"hepta.decision.policy-artifact-payload.v1";
const DECISION_STATE_PAYLOAD_SCHEMA_V1: &[u8] = b"hepta.decision.state-payload.v1";

/// Canonical payload convention for a Decision policy artifact.  A real
/// artifact publisher writes exactly these bytes (and records the resulting
/// digest in the registry); the owner then checks the loaded CAS payload
/// against the profile it is about to execute.
pub fn decision_policy_artifact_payload_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Vec<u8>, DecisionCellOwnerErrorV1> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)?;
    let mut payload = DECISION_POLICY_PAYLOAD_SCHEMA_V1.to_vec();
    payload.extend_from_slice(profile_digest.as_array());
    Ok(payload)
}

/// Canonical checkpoint payload for the owner state.  The bytes are committed
/// through `StateCheckpointOwnerV1`; a successor digest is therefore backed by
/// a real state receipt rather than being copied from the predecessor.
fn decision_state_payload_v1(
    predecessor: Digest32,
    intuition_receipt: Digest32,
    decision_id: &StableId,
    sequence: u64,
) -> Vec<u8> {
    let mut payload = DECISION_STATE_PAYLOAD_SCHEMA_V1.to_vec();
    payload.extend_from_slice(predecessor.as_array());
    payload.extend_from_slice(intuition_receipt.as_array());
    payload.extend_from_slice(decision_id.as_str().as_bytes());
    payload.extend_from_slice(&sequence.to_be_bytes());
    payload
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum DecisionCellPhaseV1 {
    Unloaded,
    Ready,
    Running,
    Retired,
    Tombstoned,
}

/// External artifact facts required to load a Decision policy.  The write
/// receipt is verified by `ArtifactCasOwnerV1`; this type additionally binds
/// its payload digest to the canonical policy profile.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionPolicyArtifactBindingV1 {
    pub artifact_id: StableId,
    pub expected_write: ArtifactWriteReceiptV1,
    pub state_checkpoint_digest: Digest32,
    pub source_owner: StableId,
    pub origin: RoleQualificationEvidenceOriginV1,
}

impl DecisionPolicyArtifactBindingV1 {
    fn validate(&self) -> Result<(), DecisionCellOwnerErrorV1> {
        if self.artifact_id.as_str().is_empty() || self.source_owner.as_str().is_empty() {
            return Err(DecisionCellOwnerErrorV1::EmptyId("artifact owner binding"));
        }
        if self.state_checkpoint_digest.is_zero() {
            return Err(DecisionCellOwnerErrorV1::EmptyDigest("state checkpoint"));
        }
        if self.expected_write.artifact_id != self.artifact_id {
            return Err(DecisionCellOwnerErrorV1::Binding("artifact id"));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionArtifactLoadReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub definition_digest: Digest32,
    pub profile_digest: Digest32,
    pub artifact_load_digest: Digest32,
    pub cas_load_receipt_digest: Digest32,
    pub registry_head_digest: Digest32,
    pub observer_evidence_digest: Option<Digest32>,
    pub origin: RoleQualificationEvidenceOriginV1,
    pub authority: AuthorityPosture,
}

impl DecisionArtifactLoadReceiptV1 {
    pub fn validate(&self) -> Result<(), DecisionCellOwnerErrorV1> {
        if self.cell_id.as_str().is_empty() {
            return Err(DecisionCellOwnerErrorV1::EmptyId("cell"));
        }
        for (label, digest) in [
            ("definition", self.definition_digest),
            ("profile", self.profile_digest),
            ("artifact load", self.artifact_load_digest),
            ("CAS load", self.cas_load_receipt_digest),
            ("registry head", self.registry_head_digest),
        ] {
            if digest.is_zero() {
                return Err(DecisionCellOwnerErrorV1::EmptyDigest(label));
            }
        }
        if self.observer_evidence_digest.is_some_and(Digest32::is_zero)
            || self.authority.grants_any()
        {
            return Err(DecisionCellOwnerErrorV1::InvalidReceipt);
        }
        Ok(())
    }

    pub fn content_digest(&self) -> Digest32 {
        Digest32::of_parts(&[
            DECISION_CELL_OWNER_SCHEMA_V1.as_bytes(),
            self.cell_id.as_str().as_bytes(),
            &self.generation.get().to_be_bytes(),
            self.definition_digest.as_array(),
            self.profile_digest.as_array(),
            self.artifact_load_digest.as_array(),
            self.cas_load_receipt_digest.as_array(),
            self.registry_head_digest.as_array(),
            self.observer_evidence_digest
                .unwrap_or(Digest32::ZERO)
                .as_array(),
        ])
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionStateRecoveryReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub restored_state_digest: Digest32,
    pub checkpoint_receipt_digest: Digest32,
    pub recovered: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionRollbackReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub from_state_digest: Digest32,
    pub restored_state_digest: Digest32,
    pub predecessor_receipt_digest: Digest32,
    pub rolled_back: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionTombstoneReceiptV1 {
    pub cell_id: StableId,
    pub generation: Generation,
    pub state_tombstone_digest: Digest32,
    pub no_resurrection_witness_digest: Digest32,
    pub tombstoned: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct PendingDecisionV1 {
    context: CellAdapterContextV1,
    request: CalibratedDecisionRequestV1,
    binding: DecisionExecutionBindingV1,
    intuition: CalibratedIntuitionReceiptV1,
    step: CellRoleStepV1<DecisionResultV1>,
    state_payload: Vec<u8>,
    operation_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecisionCellOwnerErrorV1 {
    Adapter(DecisionAdapterErrorV1),
    Calibrated(CalibratedError),
    Artifact(ProductionOwnerError),
    Durable(String),
    Policy(QualifiedCalibratedError),
    Definition(CellRoleContractErrorV1),
    EmptyId(&'static str),
    EmptyDigest(&'static str),
    Binding(&'static str),
    InvalidPhase(DecisionCellPhaseV1),
    InvalidReceipt,
    MissingStep,
    Tombstoned,
    ReplayMismatch,
}

impl fmt::Display for DecisionCellOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for DecisionCellOwnerErrorV1 {}

impl From<DecisionAdapterErrorV1> for DecisionCellOwnerErrorV1 {
    fn from(error: DecisionAdapterErrorV1) -> Self {
        Self::Adapter(error)
    }
}

impl From<ProductionOwnerError> for DecisionCellOwnerErrorV1 {
    fn from(error: ProductionOwnerError) -> Self {
        Self::Artifact(error)
    }
}

impl From<crate::DurableStateError> for DecisionCellOwnerErrorV1 {
    fn from(error: crate::DurableStateError) -> Self {
        Self::Durable(error.to_string())
    }
}

impl From<QualifiedCalibratedError> for DecisionCellOwnerErrorV1 {
    fn from(error: QualifiedCalibratedError) -> Self {
        Self::Policy(error)
    }
}

impl From<CalibratedError> for DecisionCellOwnerErrorV1 {
    fn from(error: CalibratedError) -> Self {
        Self::Calibrated(error)
    }
}

/// Decision owner that combines the real intuition kernel with external CAS
/// and checkpoint owners.  The owner is still process-local; restart/reload
/// uses the supplied durable owner snapshots and therefore leaves target-host
/// attestation outside this crate.
#[derive(Clone, Debug)]
pub struct DecisionCellOwnerV1 {
    definition: CellDefinitionV2,
    profile: CanonicalPolicyProfileV1,
    artifact: DecisionPolicyArtifactBindingV1,
    artifact_owner: ArtifactCasOwnerV1,
    state_owner: StateCheckpointOwnerV1,
    state_schema_digest: Digest32,
    current_state: StateCommitReceiptV1,
    initial_state: StateCommitReceiptV1,
    loaded: Option<DecisionArtifactLoadReceiptV1>,
    pending: Option<PendingDecisionV1>,
    last: Option<PendingDecisionV1>,
    phase: DecisionCellPhaseV1,
    host_evidence_digest: Option<Digest32>,
    observer_evidence_digest: Option<Digest32>,
}

impl DecisionCellOwnerV1 {
    pub fn new(
        definition: CellDefinitionV2,
        profile: CanonicalPolicyProfileV1,
        artifact: DecisionPolicyArtifactBindingV1,
        artifact_owner: ArtifactCasOwnerV1,
        state_owner: StateCheckpointOwnerV1,
        initial_state: StateCommitReceiptV1,
    ) -> Result<Self, DecisionCellOwnerErrorV1> {
        definition
            .validate()
            .map_err(DecisionCellOwnerErrorV1::Definition)?;
        if definition.role != CellRoleV1::Decision
            || definition.owner_module.as_str() != DecisionAdapterV1::OWNER_MODULE
        {
            return Err(DecisionCellOwnerErrorV1::Binding("decision owner"));
        }
        artifact.validate()?;
        let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
        let payload = decision_policy_artifact_payload_v1(&profile)?;
        if artifact.expected_write.artifact_digest != Digest32::of_bytes(&payload)
            || definition.parameter_bundle_digest != profile_digest
        {
            return Err(DecisionCellOwnerErrorV1::Binding("policy artifact"));
        }
        if initial_state.cell_id != definition.cell_id
            || initial_state.generation != definition.generation
            || initial_state.state_schema_digest != definition.state_schema_digest
            || artifact.state_checkpoint_digest != initial_state.content_digest()
        {
            return Err(DecisionCellOwnerErrorV1::Binding("initial state"));
        }
        if initial_state.state_digest.is_zero() || initial_state.authority.grants_any() {
            return Err(DecisionCellOwnerErrorV1::InvalidReceipt);
        }
        state_owner.reload(&definition.cell_id, &initial_state)?;
        Ok(Self {
            definition,
            profile,
            artifact,
            artifact_owner,
            state_owner,
            state_schema_digest: initial_state.state_schema_digest,
            current_state: initial_state.clone(),
            initial_state,
            loaded: None,
            pending: None,
            last: None,
            phase: DecisionCellPhaseV1::Unloaded,
            host_evidence_digest: None,
            observer_evidence_digest: None,
        })
    }

    /// Reconstruct the owner after a clean process restart from the signed
    /// state snapshot. The caller still supplies the immutable definition,
    /// policy artifact binding and initial checkpoint identity, so a snapshot
    /// from another cell or generation cannot be adopted accidentally.
    #[allow(clippy::too_many_arguments)]
    pub fn reopen_from_state_snapshot(
        path: impl AsRef<Path>,
        owner_id: StableId,
        signing_key: SigningKey,
        definition: CellDefinitionV2,
        profile: CanonicalPolicyProfileV1,
        artifact: DecisionPolicyArtifactBindingV1,
        artifact_owner: ArtifactCasOwnerV1,
        initial_state: StateCommitReceiptV1,
    ) -> Result<Self, DecisionCellOwnerErrorV1> {
        let snapshot = DurableStateOwnerV1::load(path.as_ref())?;
        let state_owner = DurableStateOwnerV1::reopen(path, owner_id, signing_key)?;
        let active_head = snapshot
            .active_heads
            .iter()
            .find(|(cell_id, _)| *cell_id == definition.cell_id)
            .map(|(_, digest)| *digest)
            .ok_or(DecisionCellOwnerErrorV1::Binding("active state head"))?;
        let current_state = snapshot
            .entries
            .iter()
            .find(|(receipt, _)| {
                receipt.cell_id == definition.cell_id && receipt.state_digest == active_head
            })
            .map(|(receipt, _)| receipt.clone())
            .ok_or(DecisionCellOwnerErrorV1::Binding("active state receipt"))?;
        if current_state.generation != definition.generation
            || current_state.state_schema_digest != definition.state_schema_digest
        {
            return Err(DecisionCellOwnerErrorV1::Binding("active state identity"));
        }
        state_owner.reload(&definition.cell_id, &current_state)?;
        let mut owner = Self::new(
            definition,
            profile,
            artifact,
            artifact_owner,
            state_owner,
            initial_state,
        )?;
        owner.current_state = current_state;
        if snapshot
            .tombstones
            .iter()
            .any(|receipt| receipt.cell_id == owner.definition.cell_id)
        {
            owner.phase = DecisionCellPhaseV1::Tombstoned;
        }
        Ok(owner)
    }

    pub fn phase(&self) -> DecisionCellPhaseV1 {
        self.phase
    }

    pub fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    /// Persist the complete append-only state history and active head owned by
    /// this DecisionCell. The policy artifact remains in CAS; this snapshot
    /// is the state half of the restart contract.
    pub fn persist_state(
        &self,
        path: impl AsRef<Path>,
    ) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist(
            path,
            &self.state_owner.snapshot(),
        )?)
    }

    pub fn persist_state_if_digest(
        &self,
        path: impl AsRef<Path>,
        expected_digest: Option<Digest32>,
    ) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        Ok(DurableStateOwnerV1::persist_if_digest(
            path,
            &self.state_owner.snapshot(),
            expected_digest,
        )?)
    }

    pub fn set_host_observer_evidence(
        &mut self,
        host_evidence_digest: Option<Digest32>,
        observer_evidence_digest: Option<Digest32>,
    ) -> Result<(), DecisionCellOwnerErrorV1> {
        if host_evidence_digest.is_some_and(Digest32::is_zero)
            || observer_evidence_digest.is_some_and(Digest32::is_zero)
        {
            return Err(DecisionCellOwnerErrorV1::EmptyDigest(
                "host/observer evidence",
            ));
        }
        self.host_evidence_digest = host_evidence_digest;
        self.observer_evidence_digest = observer_evidence_digest;
        Ok(())
    }

    pub fn load_committed_artifact(
        &mut self,
        operation_id: StableId,
        file: File,
        registry: &ArtifactRegistry,
        relative: impl AsRef<Path>,
    ) -> Result<DecisionArtifactLoadReceiptV1, DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        let payload = decision_policy_artifact_payload_v1(&self.profile)?;
        let (bytes, cas_receipt) = self.artifact_owner.load_candidate(
            operation_id,
            file,
            registry,
            &self.artifact.artifact_id,
            &self.artifact.expected_write,
            relative,
            self.host_evidence_digest,
            self.observer_evidence_digest,
        )?;
        if bytes != payload
            || cas_receipt.payload_digest != self.artifact.expected_write.artifact_digest
        {
            return Err(DecisionCellOwnerErrorV1::Binding("policy payload"));
        }
        let definition_digest = self
            .definition
            .content_digest()
            .map_err(DecisionCellOwnerErrorV1::Definition)?;
        let profile_digest = canonical_policy_profile_digest_v1(&self.profile)?;
        let receipt = DecisionArtifactLoadReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            definition_digest,
            profile_digest,
            artifact_load_digest: cas_receipt.content_digest(),
            cas_load_receipt_digest: cas_receipt.receipt_digest,
            registry_head_digest: cas_receipt.registry_head_digest,
            observer_evidence_digest: self.observer_evidence_digest,
            origin: self.artifact.origin,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt.validate()?;
        self.loaded = Some(receipt.clone());
        self.phase = DecisionCellPhaseV1::Ready;
        Ok(receipt)
    }

    pub fn execute(
        &mut self,
        context: &CellAdapterContextV1,
        request: CalibratedDecisionRequestV1,
        authentication: Option<DecisionAuthenticationBindingV1>,
        uncertainty_ppm: u32,
        ood_ppm: u32,
    ) -> Result<CellRoleStepV1<DecisionResultV1>, DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase != DecisionCellPhaseV1::Ready {
            return Err(DecisionCellOwnerErrorV1::InvalidPhase(self.phase));
        }
        self.validate_context(context)?;
        if request.state_digest != self.current_state.state_digest {
            return Err(DecisionCellOwnerErrorV1::Binding("request state"));
        }
        let profile_digest = canonical_policy_profile_digest_v1(&self.profile)?;
        let intuition = decide_calibrated_v3(request.clone(), &self.profile)?;
        let candidate_set_digest = canonical_candidate_set_digest_v1(&request.candidates)?;
        let candidate_order_digest = canonical_candidate_order_digest_v1(&request.candidates)?;
        let state_payload = decision_state_payload_v1(
            self.current_state.state_digest,
            intuition.receipt_digest,
            &request.decision_id,
            request.sequence,
        );
        let state_successor_digest = Digest32::of_bytes(&state_payload);
        let binding = DecisionExecutionBindingV1 {
            policy: DecisionPolicyBindingV1 {
                policy_digest: request.policy_digest,
                policy_profile_digest: profile_digest,
                candidate_set_digest,
                candidate_order_digest,
                policy_generation: request.policy_generation,
                sequence: request.sequence,
            },
            authentication,
            completeness_receipt_digest: request.completeness.receipt_digest,
            state_successor_digest,
            uncertainty_ppm,
            ood_ppm,
        };
        let step = DecisionAdapterV1::adapt(context, &intuition, &binding)?;
        let operation_id = StableId::new(format!(
            "decision-state.{}.{}",
            request.decision_id, request.sequence
        ))
        .map_err(|_| DecisionCellOwnerErrorV1::EmptyId("state operation"))?;
        let pending = PendingDecisionV1 {
            context: context.clone(),
            request,
            binding,
            intuition,
            step: step.clone(),
            state_payload,
            operation_id,
        };
        self.pending = Some(pending);
        self.phase = DecisionCellPhaseV1::Running;
        Ok(step)
    }

    pub fn commit_successor_state(
        &mut self,
    ) -> Result<StateCommitReceiptV1, DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase != DecisionCellPhaseV1::Running {
            return Err(DecisionCellOwnerErrorV1::InvalidPhase(self.phase));
        }
        let pending = self
            .pending
            .take()
            .ok_or(DecisionCellOwnerErrorV1::MissingStep)?;
        let receipt = self.state_owner.commit(
            pending.operation_id.clone(),
            self.definition.cell_id.clone(),
            self.definition.generation,
            self.state_schema_digest,
            self.current_state.state_digest,
            pending.state_payload.clone(),
            self.host_evidence_digest,
            self.observer_evidence_digest,
        )?;
        if receipt.state_digest != pending.step.receipt.state_successor_digest {
            return Err(DecisionCellOwnerErrorV1::Binding("successor checkpoint"));
        }
        self.current_state = receipt.clone();
        self.last = Some(pending);
        self.phase = DecisionCellPhaseV1::Ready;
        Ok(receipt)
    }

    /// Commit the successor and replace the durable state snapshot before
    /// publishing the new in-memory head. A failed snapshot leaves the live
    /// owner at its predecessor so callers can retry or quarantine it.
    pub fn commit_successor_state_persisted(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<StateCommitReceiptV1, DecisionCellOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.commit_successor_state()?;
        candidate.persist_state_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn replay_last(
        &self,
        expected: &CellRoleStepV1<DecisionResultV1>,
    ) -> Result<(), DecisionCellOwnerErrorV1> {
        let last = self
            .last
            .as_ref()
            .ok_or(DecisionCellOwnerErrorV1::MissingStep)?;
        let intuition = decide_calibrated_v3(last.request.clone(), &self.profile)?;
        let actual = DecisionAdapterV1::adapt(&last.context, &intuition, &last.binding)?;
        if actual != *expected {
            return Err(DecisionCellOwnerErrorV1::ReplayMismatch);
        }
        Ok(())
    }

    pub fn recover_restart(
        &mut self,
    ) -> Result<DecisionStateRecoveryReceiptV1, DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        let loaded = self
            .loaded
            .as_ref()
            .ok_or(DecisionCellOwnerErrorV1::InvalidPhase(self.phase))?;
        self.state_owner
            .reload(&self.definition.cell_id, &self.current_state)?;
        self.pending = None;
        self.phase = DecisionCellPhaseV1::Ready;
        Ok(DecisionStateRecoveryReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            restored_state_digest: self.current_state.state_digest,
            checkpoint_receipt_digest: loaded.artifact_load_digest,
            recovered: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn rollback(&mut self) -> Result<DecisionRollbackReceiptV1, DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        let last = self
            .last
            .as_ref()
            .ok_or(DecisionCellOwnerErrorV1::MissingStep)?;
        let predecessor =
            if last.step.receipt.state_predecessor_digest == self.initial_state.state_digest {
                self.initial_state.clone()
            } else {
                return Err(DecisionCellOwnerErrorV1::Binding("predecessor checkpoint"));
            };
        self.state_owner
            .rollback(&self.definition.cell_id, &predecessor)?;
        let from = self.current_state.state_digest;
        self.current_state = predecessor.clone();
        self.last = None;
        self.phase = DecisionCellPhaseV1::Ready;
        Ok(DecisionRollbackReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            from_state_digest: from,
            restored_state_digest: predecessor.state_digest,
            predecessor_receipt_digest: predecessor.receipt_digest,
            rolled_back: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn rollback_persisted(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<DecisionRollbackReceiptV1, DecisionCellOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.rollback()?;
        candidate.persist_state_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn tombstone(&mut self) -> Result<DecisionTombstoneReceiptV1, DecisionCellOwnerErrorV1> {
        if self.phase == DecisionCellPhaseV1::Tombstoned {
            return Err(DecisionCellOwnerErrorV1::Tombstoned);
        }
        if self.phase != DecisionCellPhaseV1::Retired {
            return Err(DecisionCellOwnerErrorV1::InvalidPhase(self.phase));
        }
        let reason = Digest32::of_parts(&[
            b"hepta.decision.tombstone.reason.v1",
            self.definition.cell_id.as_str().as_bytes(),
            self.current_state.state_digest.as_array(),
        ]);
        let tombstone = self.state_owner.tombstone_with_evidence(
            self.definition.cell_id.clone(),
            self.definition.generation,
            reason,
            self.host_evidence_digest,
            self.observer_evidence_digest,
        )?;
        let witness = Digest32::of_parts(&[
            b"hepta.decision.no-resurrection.v1",
            tombstone.receipt_digest.as_array(),
            self.definition.cell_id.as_str().as_bytes(),
            &self.definition.generation.get().to_be_bytes(),
        ]);
        self.phase = DecisionCellPhaseV1::Tombstoned;
        Ok(DecisionTombstoneReceiptV1 {
            cell_id: self.definition.cell_id.clone(),
            generation: self.definition.generation,
            state_tombstone_digest: tombstone.receipt_digest,
            no_resurrection_witness_digest: witness,
            tombstoned: true,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    pub fn tombstone_persisted(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<DecisionTombstoneReceiptV1, DecisionCellOwnerErrorV1> {
        let expected_snapshot = DurableStateOwnerV1::snapshot_digest(path.as_ref())?;
        let mut candidate = self.clone();
        let receipt = candidate.tombstone()?;
        candidate.persist_state_if_digest(path, expected_snapshot)?;
        *self = candidate;
        Ok(receipt)
    }

    pub fn retire(&mut self) -> Result<(), DecisionCellOwnerErrorV1> {
        self.ensure_live()?;
        if self.phase == DecisionCellPhaseV1::Running {
            return Err(DecisionCellOwnerErrorV1::InvalidPhase(self.phase));
        }
        self.phase = DecisionCellPhaseV1::Retired;
        Ok(())
    }

    fn validate_context(
        &self,
        context: &CellAdapterContextV1,
    ) -> Result<(), DecisionCellOwnerErrorV1> {
        context
            .validate(CellRoleV1::Decision)
            .map_err(|_| DecisionCellOwnerErrorV1::Binding("execution context"))?;
        if context.cell_id != self.definition.cell_id
            || context.generation != self.definition.generation
            || context.scope_digest != self.definition.scope_digest
            || context.state_predecessor_digest != self.current_state.state_digest
        {
            return Err(DecisionCellOwnerErrorV1::Binding("execution context"));
        }
        let capability = self
            .definition
            .capability_digest()
            .map_err(DecisionCellOwnerErrorV1::Definition)?;
        if context.capability_digest != capability {
            return Err(DecisionCellOwnerErrorV1::Binding("capability"));
        }
        Ok(())
    }

    fn ensure_live(&self) -> Result<(), DecisionCellOwnerErrorV1> {
        if self.phase == DecisionCellPhaseV1::Tombstoned {
            Err(DecisionCellOwnerErrorV1::Tombstoned)
        } else {
            Ok(())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intuition::AssignmentModeV1;
    use codex_hepta_intuition::CalibratedActionCandidateV1;
    use codex_hepta_intuition::CalibrationArtifactV1;
    use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
    use codex_hepta_intuition::CanonicalRiskRuleV1;
    use codex_hepta_intuition::LearnedScorerContractV1;
    use codex_hepta_intuition::OodArtifactV1;
    use codex_hepta_intuition::RiskClass;
    use codex_hepta_intuition::canonical_candidate_order_digest_v1;
    use codex_hepta_intuition::canonical_candidate_set_digest_v1;
    use codex_hepta_intuition::canonical_policy_profile_digest_v1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellRoleV1;
    use codex_hepta_types::CellUpdateModeV1;
    use codex_hepta_types::FixedQ32;
    use codex_hepta_types::Generation;
    use codex_hepta_types::ProbabilityQ32;
    use std::fs;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn probability_ppm(ppm: u64) -> ProbabilityQ32 {
        ProbabilityQ32::from_raw(
            ((u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000) as u64,
        )
        .expect("probability")
    }

    fn profile_and_request() -> (CanonicalPolicyProfileV1, CalibratedDecisionRequestV1) {
        let policy = digest("decision-policy");
        let objective_class = digest("decision-objective-class");
        let calibration = digest("decision-calibration");
        let ood = digest("decision-ood");
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("candidate:one"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            calibrated_confidence: probability_ppm(900_000),
            ood_score: probability_ppm(100_000),
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest("candidate-support"),
        }];
        let profile = CanonicalPolicyProfileV1 {
            profile_id: id("decision-profile"),
            policy_digest: policy,
            objective_class_digest: objective_class,
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            minimum_confidence: probability_ppm(700_000),
            maximum_ece_ppm: 30_000,
            maximum_ood_false_acceptance_ppm: 2_000,
            maximum_in_domain_score: probability_ppm(500_000),
            risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
            scorer: LearnedScorerContractV1 {
                model_digest: policy,
                feature_schema_digest: digest("features"),
                output_schema_digest: digest("outputs"),
                score_semantics_digest: digest("semantics"),
                scorer_contract_digest: digest("scorer"),
            },
            calibration_dataset_digest: digest("calibration-data"),
            ood_dataset_digest: digest("ood-data"),
            calibration_artifact_digest: calibration,
            ood_artifact_digest: ood,
        };
        let completeness = CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("complete"),
            generator_digest: digest("generator"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest: canonical_candidate_set_digest_v1(&candidates)
                .expect("candidate set"),
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("candidate order"),
            candidate_count: 1,
            omitted_count_bound: 0,
        };
        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision:one"),
            objective_digest: digest("objective"),
            objective_class_digest: objective_class,
            state_digest: digest("initial-state"),
            policy_digest: policy,
            policy_generation: 1,
            sequence: 1,
            minimum_confidence: profile.minimum_confidence,
            maximum_ece_ppm: profile.maximum_ece_ppm,
            maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
            risk_class: RiskClass::Low,
            completeness,
            calibration: CalibrationArtifactV1 {
                artifact_digest: calibration,
                policy_digest: policy,
                objective_class_digest: objective_class,
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                measured_ece_ppm: 10_000,
                subgroup_audit_digest: digest("subgroup"),
            },
            ood: OodArtifactV1 {
                artifact_digest: ood,
                policy_digest: policy,
                detector_digest: digest("detector"),
                support_digest: digest("ood-support"),
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 100,
                maximum_in_domain_score: profile.maximum_in_domain_score,
                measured_false_acceptance_ppm: 1_000,
            },
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        (profile, request)
    }

    fn definition(profile_digest: Digest32) -> CellDefinitionV2 {
        let state_schema = digest("decision-state-schema");
        CellDefinitionV2 {
            cell_id: id("cell.decision.integration"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest("scope"),
            lineage_digest: digest("lineage"),
            role: CellRoleV1::Decision,
            capability_profile: CellCapabilityProfileV1 {
                role: CellRoleV1::Decision,
                observation_schema_digest: digest("observation"),
                output_schema_digest: digest("output"),
                state_schema_digest: state_schema,
                input_port_digest: digest("input-port"),
                output_port_digest: digest("output-port"),
                termination_port_digest: digest("termination-port"),
                owner_module: id("hepta-intuition::decide_calibrated_v3"),
                persistence_class: CellPersistenceClassV1::Durable,
                update_mode: CellUpdateModeV1::InferenceOnly,
                fallback_role: None,
                objective_digest: digest("objective"),
                resource_budget_digest: digest("budget"),
                evaluation_profile_digest: digest("evaluation"),
                authority: AuthorityPosture::DENY_ALL,
            },
            parameter_bundle_digest: profile_digest,
            state_schema_digest: state_schema,
            port_abi_digest: digest("port-abi"),
            owner_module: id("hepta-intuition::decide_calibrated_v3"),
            objective_digest: digest("objective"),
            fallback_role: None,
            evidence_owner: id("hepta.learning.eval"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    // The owner tests in this module intentionally focus on policy/state
    // binding.  CAS publication and signed receipts are exercised by
    // `production_owner` tests; combining both boundaries here is done by
    // integration tests on target hosts where the artifact bytes are real.
    #[test]
    fn policy_payload_is_stable_and_nonempty() {
        assert!(!DECISION_POLICY_PAYLOAD_SCHEMA_V1.is_empty());
        assert!(!DECISION_STATE_PAYLOAD_SCHEMA_V1.is_empty());
    }

    #[test]
    fn cas_execute_persist_reopen_and_tombstone_round_trip() {
        let key = SigningKey::from_bytes(&[41; 32]);
        let host = Some(digest("host-evidence"));
        let observer = Some(digest("observer-evidence"));
        let (profile, mut request) = profile_and_request();
        let profile_digest = canonical_policy_profile_digest_v1(&profile).expect("profile digest");
        let definition = definition(profile_digest);
        let state_owner_id = id("decision.state.owner");
        let mut state_owner =
            StateCheckpointOwnerV1::new(state_owner_id.clone(), key.clone()).expect("state owner");
        let initial_state = state_owner
            .commit(
                id("decision.state.initial"),
                definition.cell_id.clone(),
                definition.generation,
                definition.state_schema_digest,
                Digest32::ZERO,
                digest("initial-state").as_array().to_vec(),
                host,
                observer,
            )
            .expect("initial state");

        let artifact_id = id("artifact.decision.policy");
        let payload = decision_policy_artifact_payload_v1(&profile).expect("policy payload");
        let mut registry = ArtifactRegistry::new();
        registry
            .append(crate::ArtifactEvent::Register {
                event_id: id("artifact.register"),
                manifest: crate::ArtifactManifest {
                    artifact_id: artifact_id.clone(),
                    kind: crate::ArtifactKind::Policy,
                    generation: definition.generation,
                    predecessor_id: None,
                    content_digest: Digest32::of_bytes(&payload),
                    objective_digest: definition.objective_digest,
                    support_digest: digest("artifact-support"),
                    producer_id: id("decision.artifact.owner"),
                    compatibility_digest: definition.port_abi_digest,
                    encoded_size_bytes: payload.len() as u64,
                },
            })
            .expect("register policy");
        let artifact_root = std::env::temp_dir().join(format!(
            "hepta-decision-artifact-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        fs::create_dir(&artifact_root).expect("artifact root");
        let artifact_owner =
            ArtifactCasOwnerV1::new(id("decision.cas.owner"), key.clone()).expect("cas owner");
        let write = artifact_owner
            .write_candidate(
                id("artifact.write"),
                &artifact_root,
                "policy.bin",
                &registry,
                &artifact_id,
                &payload,
                host,
                observer,
            )
            .expect("write policy");
        let artifact = DecisionPolicyArtifactBindingV1 {
            artifact_id,
            expected_write: write,
            state_checkpoint_digest: initial_state.content_digest(),
            source_owner: id("decision.artifact.owner"),
            origin: RoleQualificationEvidenceOriginV1::RepositoryQualification,
        };
        let state_path = artifact_root.join("state.snapshot");
        DurableStateOwnerV1::persist(&state_path, &state_owner.snapshot())
            .expect("persist initial");
        let mut owner = DecisionCellOwnerV1::new(
            definition.clone(),
            profile.clone(),
            artifact.clone(),
            artifact_owner.clone(),
            state_owner,
            initial_state.clone(),
        )
        .expect("decision owner");
        owner
            .load_committed_artifact(
                id("artifact.load"),
                File::open(artifact_root.join("policy.bin")).expect("open policy"),
                &registry,
                "policy.bin",
            )
            .expect("load policy");
        let capability = definition.capability_digest().expect("capability");
        let context = CellAdapterContextV1 {
            cell_id: definition.cell_id.clone(),
            generation: definition.generation,
            scope_digest: definition.scope_digest,
            role: CellRoleV1::Decision,
            capability_digest: capability,
            input_frontier_digest: digest("frontier"),
            state_predecessor_digest: initial_state.state_digest,
            resource_receipt_digest: digest("resource"),
            evidence_digest: digest("evidence"),
        };
        request.state_digest = initial_state.state_digest;
        owner
            .execute(&context, request, None, 1_000, 500)
            .expect("execute");
        let successor = owner
            .commit_successor_state_persisted(&state_path)
            .expect("commit successor");
        assert_ne!(successor.state_digest, initial_state.state_digest);
        let mut reopened = DecisionCellOwnerV1::reopen_from_state_snapshot(
            &state_path,
            state_owner_id,
            key.clone(),
            definition,
            profile,
            artifact,
            artifact_owner,
            initial_state,
        )
        .expect("reopen active successor");
        assert_eq!(reopened.phase(), DecisionCellPhaseV1::Unloaded);
        reopened
            .load_committed_artifact(
                id("artifact.reload"),
                File::open(artifact_root.join("policy.bin")).expect("reopen policy"),
                &registry,
                "policy.bin",
            )
            .expect("reload policy");
        assert_eq!(reopened.phase(), DecisionCellPhaseV1::Ready);
        reopened.retire().expect("retire");
        let tombstone = reopened
            .tombstone_persisted(&state_path)
            .expect("tombstone");
        assert!(tombstone.tombstoned);
        let mut tombstoned = DecisionCellOwnerV1::reopen_from_state_snapshot(
            &state_path,
            id("decision.state.owner"),
            key,
            reopened.definition().clone(),
            reopened.profile.clone(),
            reopened.artifact.clone(),
            reopened.artifact_owner.clone(),
            reopened.initial_state.clone(),
        )
        .expect("reopen tombstone");
        assert_eq!(tombstoned.phase(), DecisionCellPhaseV1::Tombstoned);
        assert!(matches!(
            tombstoned.load_committed_artifact(
                id("artifact.after-tombstone"),
                File::open(artifact_root.join("policy.bin")).expect("policy"),
                &registry,
                "policy.bin",
            ),
            Err(DecisionCellOwnerErrorV1::Tombstoned)
        ));
        fs::remove_dir_all(artifact_root).expect("cleanup");
    }
}
