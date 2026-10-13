//! Executing DecisionCell owner over the calibrated intuition kernel.
//!
//! The adapter in `decision.rs` is intentionally projection-only.  This owner
//! supplies the missing execution boundary: it loads one committed policy
//! profile, checks the predecessor state, invokes `decide_calibrated_v3`, and
//! advances an append-only state history.  It never dispatches an effect.

use std::error::Error;
use std::fmt;
use std::fs;
use std::fs::File;
use std::io::Write;
use std::path::Path;

use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedIntuitionReceiptV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::QualifiedCalibratedError;
use codex_hepta_intuition::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::decide_calibrated_v3;
use codex_hepta_types::CellDefinitionV2;
use codex_hepta_types::CellRoleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::CellAdapterContextV1;
use crate::CellRoleStepV1;
use crate::DecisionAdapterErrorV1;
use crate::DecisionAdapterV1;
use crate::DecisionAuthenticationBindingV1;
use crate::DecisionExecutionBindingV1;
use crate::DecisionPolicyBindingV1;
use crate::DecisionResultV1;

pub const DECISION_CELL_OWNER_SCHEMA_V1: &str = "hepta.decision-cell.owner.v1";
const DECISION_CHECKPOINT_MAGIC_V1: &[u8] = b"HEPTA-DECISION-CHECKPOINT-V1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellStateV1 {
    pub current_state_digest: Digest32,
    pub sequence: u64,
    pub history: Vec<Digest32>,
    pub tombstone_digest: Option<Digest32>,
}

impl DecisionCellStateV1 {
    fn new(initial_state_digest: Digest32) -> Result<Self, DecisionCellOwnerErrorV1> {
        if initial_state_digest.is_zero() {
            return Err(DecisionCellOwnerErrorV1::EmptyDigest("initial state"));
        }
        Ok(Self {
            current_state_digest: initial_state_digest,
            sequence: 0,
            history: vec![initial_state_digest],
            tombstone_digest: None,
        })
    }

    fn ensure_live(&self) -> Result<(), DecisionCellOwnerErrorV1> {
        if self.tombstone_digest.is_some() {
            return Err(DecisionCellOwnerErrorV1::Tombstoned);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DecisionCellExecutionV1 {
    pub intuition: CalibratedIntuitionReceiptV1,
    pub role_step: CellRoleStepV1<DecisionResultV1>,
    pub predecessor_state_digest: Digest32,
    pub successor_state_digest: Digest32,
}

pub struct DecisionCellOwnerV1 {
    cell_id: StableId,
    definition: CellDefinitionV2,
    profile: CanonicalPolicyProfileV1,
    profile_digest: Digest32,
    committed_artifact_digest: Digest32,
    state: DecisionCellStateV1,
    last_execution: Option<DecisionCellExecutionV1>,
}

impl fmt::Debug for DecisionCellOwnerV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("DecisionCellOwnerV1")
            .field("cell_id", &self.cell_id)
            .field("profile_digest", &self.profile_digest)
            .field("committed_artifact_digest", &self.committed_artifact_digest)
            .field("state", &self.state)
            .finish_non_exhaustive()
    }
}

impl DecisionCellOwnerV1 {
    pub fn load_committed(
        definition: CellDefinitionV2,
        profile: CanonicalPolicyProfileV1,
        committed_artifact_digest: Digest32,
        initial_state_digest: Digest32,
    ) -> Result<Self, DecisionCellOwnerErrorV1> {
        definition.validate()?;
        if definition.role != CellRoleV1::Decision {
            return Err(DecisionCellOwnerErrorV1::RoleMismatch);
        }
        if definition.owner_module.as_str() != "hepta-intuition::decide_calibrated_v3"
            || committed_artifact_digest.is_zero()
            || definition.parameter_bundle_digest != committed_artifact_digest
        {
            return Err(DecisionCellOwnerErrorV1::ArtifactBinding);
        }
        let profile_digest = canonical_policy_profile_digest_v1(&profile)?;
        Ok(Self {
            cell_id: definition.cell_id.clone(),
            definition,
            profile,
            profile_digest,
            committed_artifact_digest,
            state: DecisionCellStateV1::new(initial_state_digest)?,
            last_execution: None,
        })
    }

    #[must_use]
    pub fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub fn state(&self) -> &DecisionCellStateV1 {
        &self.state
    }

    #[must_use]
    pub fn definition(&self) -> &CellDefinitionV2 {
        &self.definition
    }

    pub fn execute(
        &mut self,
        request: CalibratedDecisionRequestV1,
        context: &CellAdapterContextV1,
        authentication: Option<DecisionAuthenticationBindingV1>,
        uncertainty_ppm: u32,
        ood_ppm: u32,
    ) -> Result<DecisionCellExecutionV1, DecisionCellOwnerErrorV1> {
        self.state.ensure_live()?;
        if request.state_digest != self.state.current_state_digest
            || request.sequence <= self.state.sequence
            || context.cell_id != self.cell_id
            || context.generation != self.definition.generation
            || context.scope_digest != self.definition.scope_digest
            || context.state_predecessor_digest != self.state.current_state_digest
        {
            return Err(DecisionCellOwnerErrorV1::StateBinding);
        }
        if request.policy_digest != self.profile.policy_digest {
            return Err(DecisionCellOwnerErrorV1::PolicyBinding);
        }
        let intuition = decide_calibrated_v3(request.clone(), &self.profile)?;
        let successor = Digest32::of_parts(&[
            DECISION_CELL_OWNER_SCHEMA_V1.as_bytes(),
            self.state.current_state_digest.as_array(),
            intuition.receipt_digest.as_array(),
            &request.sequence.to_be_bytes(),
        ]);
        let policy = DecisionPolicyBindingV1 {
            policy_digest: self.profile.policy_digest,
            policy_profile_digest: self.profile_digest,
            candidate_set_digest: request.completeness.candidate_set_digest,
            candidate_order_digest: request.completeness.canonical_order_digest,
            policy_generation: request.policy_generation,
            sequence: request.sequence,
        };
        let binding = DecisionExecutionBindingV1 {
            policy,
            authentication,
            completeness_receipt_digest: request.completeness.receipt_digest,
            state_successor_digest: successor,
            uncertainty_ppm,
            ood_ppm,
        };
        let role_step = DecisionAdapterV1::adapt(context, &intuition, &binding)?;
        let execution = DecisionCellExecutionV1 {
            intuition,
            role_step,
            predecessor_state_digest: self.state.current_state_digest,
            successor_state_digest: successor,
        };
        self.state.current_state_digest = successor;
        self.state.sequence = request.sequence;
        self.state.history.push(successor);
        self.last_execution = Some(execution.clone());
        Ok(execution)
    }

    pub fn replay_last(&self) -> Result<&DecisionCellExecutionV1, DecisionCellOwnerErrorV1> {
        self.last_execution
            .as_ref()
            .ok_or(DecisionCellOwnerErrorV1::NoExecution)
    }

    pub fn rollback(
        &mut self,
        target_state_digest: Digest32,
    ) -> Result<(), DecisionCellOwnerErrorV1> {
        self.state.ensure_live()?;
        if !self.state.history.contains(&target_state_digest) {
            return Err(DecisionCellOwnerErrorV1::UnknownState);
        }
        self.state.current_state_digest = target_state_digest;
        self.last_execution = None;
        Ok(())
    }

    pub fn tombstone(
        &mut self,
        reason_digest: Digest32,
    ) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        self.state.ensure_live()?;
        if reason_digest.is_zero() {
            return Err(DecisionCellOwnerErrorV1::EmptyDigest("tombstone reason"));
        }
        let tombstone = Digest32::of_parts(&[
            b"hepta.decision-cell.tombstone.v1",
            self.cell_id.as_str().as_bytes(),
            self.state.current_state_digest.as_array(),
            reason_digest.as_array(),
        ]);
        self.state.tombstone_digest = Some(tombstone);
        Ok(tombstone)
    }

    /// Persist the state owned by this DecisionCell after a successful step.
    /// Definition, policy and artifact bytes remain immutable external
    /// artifacts and are identified by their digests in the checkpoint.
    pub fn save_checkpoint(
        &self,
        path: impl AsRef<Path>,
    ) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        let path = path.as_ref();
        reject_checkpoint_path(path)?;
        let payload = self.encode_checkpoint()?;
        let checksum = Digest32::of_parts(&[b"hepta.decision-cell.checkpoint.v1", &payload]);
        let mut bytes = payload;
        bytes.extend_from_slice(checksum.as_array());
        let temp = path.with_extension("decision.checkpoint.tmp");
        reject_checkpoint_path(&temp)?;
        let mut file = File::create(&temp).map_err(|_| DecisionCellOwnerErrorV1::DurableIo)?;
        file.write_all(&bytes)
            .and_then(|_| file.sync_all())
            .map_err(|_| DecisionCellOwnerErrorV1::DurableIo)?;
        drop(file);
        fs::rename(&temp, path).map_err(|_| DecisionCellOwnerErrorV1::DurableIo)?;
        if let Some(parent) = path.parent()
            && let Ok(directory) = File::open(parent)
        {
            let _ = directory.sync_all();
        }
        Ok(checksum)
    }

    /// Restore only state for this already-loaded identity and policy.
    pub fn restore_checkpoint(
        &mut self,
        path: impl AsRef<Path>,
    ) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        self.state.ensure_live()?;
        let path = path.as_ref();
        reject_checkpoint_path(path)?;
        let bytes = fs::read(path).map_err(|_| DecisionCellOwnerErrorV1::DurableIo)?;
        if bytes.len() < DECISION_CHECKPOINT_MAGIC_V1.len() + 32 {
            return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
        }
        let payload_len = bytes.len() - 32;
        let payload = &bytes[..payload_len];
        let expected = Digest32::from_array(
            bytes[payload_len..]
                .try_into()
                .map_err(|_| DecisionCellOwnerErrorV1::InvalidCheckpoint)?,
        );
        let actual = Digest32::of_parts(&[b"hepta.decision-cell.checkpoint.v1", payload]);
        if expected != actual {
            return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
        }
        let restored = decode_checkpoint(payload)?;
        let definition_digest = self
            .definition
            .content_digest()
            .map_err(DecisionCellOwnerErrorV1::from)?;
        if restored.cell_id != self.cell_id
            || restored.generation != self.definition.generation
            || restored.definition_digest != definition_digest
            || restored.profile_digest != self.profile_digest
            || restored.artifact_digest != self.committed_artifact_digest
            || restored.history.is_empty()
            || !restored.history.contains(&restored.current_state_digest)
        {
            return Err(DecisionCellOwnerErrorV1::StateBinding);
        }
        self.state = DecisionCellStateV1 {
            current_state_digest: restored.current_state_digest,
            sequence: restored.sequence,
            history: restored.history,
            tombstone_digest: restored.tombstone_digest,
        };
        self.last_execution = None;
        Ok(expected)
    }

    fn encode_checkpoint(&self) -> Result<Vec<u8>, DecisionCellOwnerErrorV1> {
        if self.state.history.is_empty()
            || !self
                .state
                .history
                .contains(&self.state.current_state_digest)
        {
            return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
        }
        let definition_digest = self
            .definition
            .content_digest()
            .map_err(DecisionCellOwnerErrorV1::from)?;
        let mut bytes = Vec::with_capacity(256);
        bytes.extend_from_slice(DECISION_CHECKPOINT_MAGIC_V1);
        put_id(&mut bytes, &self.cell_id)?;
        bytes.extend_from_slice(&self.definition.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.profile_digest.as_array());
        bytes.extend_from_slice(self.committed_artifact_digest.as_array());
        bytes.extend_from_slice(definition_digest.as_array());
        bytes.extend_from_slice(self.state.current_state_digest.as_array());
        bytes.extend_from_slice(&self.state.sequence.to_be_bytes());
        let history_len = u32::try_from(self.state.history.len())
            .map_err(|_| DecisionCellOwnerErrorV1::InvalidCheckpoint)?;
        bytes.extend_from_slice(&history_len.to_be_bytes());
        for digest in &self.state.history {
            bytes.extend_from_slice(digest.as_array());
        }
        match self.state.tombstone_digest {
            Some(digest) => {
                bytes.push(1);
                bytes.extend_from_slice(digest.as_array());
            }
            None => bytes.push(0),
        }
        Ok(bytes)
    }
}

#[derive(Clone, Debug)]
struct DecodedCheckpointV1 {
    cell_id: StableId,
    generation: codex_hepta_types::Generation,
    profile_digest: Digest32,
    artifact_digest: Digest32,
    definition_digest: Digest32,
    current_state_digest: Digest32,
    sequence: u64,
    history: Vec<Digest32>,
    tombstone_digest: Option<Digest32>,
}

fn reject_checkpoint_path(path: &Path) -> Result<(), DecisionCellOwnerErrorV1> {
    if let Ok(metadata) = fs::symlink_metadata(path)
        && (metadata.file_type().is_symlink() || !metadata.is_file())
    {
        return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
    }
    Ok(())
}

fn put_id(bytes: &mut Vec<u8>, id: &StableId) -> Result<(), DecisionCellOwnerErrorV1> {
    let value = id.as_str().as_bytes();
    if value.len() > u16::MAX as usize {
        return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
    }
    bytes.extend_from_slice(&(value.len() as u16).to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

fn decode_checkpoint(bytes: &[u8]) -> Result<DecodedCheckpointV1, DecisionCellOwnerErrorV1> {
    let mut cursor = DecisionCursor { bytes, position: 0 };
    if cursor.take(DECISION_CHECKPOINT_MAGIC_V1.len())? != DECISION_CHECKPOINT_MAGIC_V1 {
        return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
    }
    let cell_id = cursor.id()?;
    let generation = codex_hepta_types::Generation::new(cursor.u64()?)
        .map_err(|_| DecisionCellOwnerErrorV1::InvalidCheckpoint)?;
    let profile_digest = cursor.digest()?;
    let artifact_digest = cursor.digest()?;
    let definition_digest = cursor.digest()?;
    let current_state_digest = cursor.digest()?;
    let sequence = cursor.u64()?;
    let history_len = cursor.u32()? as usize;
    if history_len == 0 || history_len > 1_000_000 {
        return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
    }
    let mut history = Vec::with_capacity(history_len);
    for _ in 0..history_len {
        history.push(cursor.digest()?);
    }
    let tombstone_digest = if cursor.byte()? == 0 {
        None
    } else {
        Some(cursor.digest()?)
    };
    if !cursor.is_empty()
        || profile_digest.is_zero()
        || artifact_digest.is_zero()
        || definition_digest.is_zero()
        || current_state_digest.is_zero()
    {
        return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
    }
    Ok(DecodedCheckpointV1 {
        cell_id,
        generation,
        profile_digest,
        artifact_digest,
        definition_digest,
        current_state_digest,
        sequence,
        history,
        tombstone_digest,
    })
}

struct DecisionCursor<'a> {
    bytes: &'a [u8],
    position: usize,
}

impl<'a> DecisionCursor<'a> {
    fn take(&mut self, length: usize) -> Result<&'a [u8], DecisionCellOwnerErrorV1> {
        let end = self
            .position
            .checked_add(length)
            .ok_or(DecisionCellOwnerErrorV1::InvalidCheckpoint)?;
        if end > self.bytes.len() {
            return Err(DecisionCellOwnerErrorV1::InvalidCheckpoint);
        }
        let value = &self.bytes[self.position..end];
        self.position = end;
        Ok(value)
    }

    fn byte(&mut self) -> Result<u8, DecisionCellOwnerErrorV1> {
        Ok(self.take(1)?[0])
    }

    fn u32(&mut self) -> Result<u32, DecisionCellOwnerErrorV1> {
        let mut value = [0; 4];
        value.copy_from_slice(self.take(4)?);
        Ok(u32::from_be_bytes(value))
    }

    fn u64(&mut self) -> Result<u64, DecisionCellOwnerErrorV1> {
        let mut value = [0; 8];
        value.copy_from_slice(self.take(8)?);
        Ok(u64::from_be_bytes(value))
    }

    fn digest(&mut self) -> Result<Digest32, DecisionCellOwnerErrorV1> {
        let mut value = [0; 32];
        value.copy_from_slice(self.take(32)?);
        Ok(Digest32::from_array(value))
    }

    fn id(&mut self) -> Result<StableId, DecisionCellOwnerErrorV1> {
        let mut length = [0; 2];
        length.copy_from_slice(self.take(2)?);
        let length = u16::from_be_bytes(length) as usize;
        let value = std::str::from_utf8(self.take(length)?)
            .map_err(|_| DecisionCellOwnerErrorV1::InvalidCheckpoint)?;
        StableId::new(value).map_err(|_| DecisionCellOwnerErrorV1::InvalidCheckpoint)
    }

    fn is_empty(&self) -> bool {
        self.position == self.bytes.len()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DecisionCellOwnerErrorV1 {
    Contract(String),
    Qualified(QualifiedCalibratedError),
    Adapter(DecisionAdapterErrorV1),
    EmptyDigest(&'static str),
    RoleMismatch,
    ArtifactBinding,
    PolicyBinding,
    StateBinding,
    Tombstoned,
    UnknownState,
    NoExecution,
    DurableIo,
    InvalidCheckpoint,
}

impl fmt::Display for DecisionCellOwnerErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for DecisionCellOwnerErrorV1 {}

impl From<QualifiedCalibratedError> for DecisionCellOwnerErrorV1 {
    fn from(value: QualifiedCalibratedError) -> Self {
        Self::Qualified(value)
    }
}

impl From<DecisionAdapterErrorV1> for DecisionCellOwnerErrorV1 {
    fn from(value: DecisionAdapterErrorV1) -> Self {
        Self::Adapter(value)
    }
}

impl From<codex_hepta_types::CellRoleContractErrorV1> for DecisionCellOwnerErrorV1 {
    fn from(value: codex_hepta_types::CellRoleContractErrorV1) -> Self {
        Self::Contract(value.to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_intuition::CanonicalRiskRuleV1;
    use codex_hepta_intuition::LearnedScorerContractV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::CellCapabilityProfileV1;
    use codex_hepta_types::CellPersistenceClassV1;
    use codex_hepta_types::CellUpdateModeV1;
    use codex_hepta_types::Generation;
    use codex_hepta_types::ProbabilityQ32;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("id")
    }

    fn digest(value: u8) -> Digest32 {
        Digest32::of_bytes(&[value])
    }

    fn profile() -> CanonicalPolicyProfileV1 {
        CanonicalPolicyProfileV1 {
            profile_id: id("profile.decision"),
            policy_digest: digest(1),
            objective_class_digest: digest(2),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            minimum_confidence: ProbabilityQ32::from_raw(1).expect("probability"),
            maximum_ece_ppm: 10_000,
            maximum_ood_false_acceptance_ppm: 10_000,
            maximum_in_domain_score: ProbabilityQ32::from_raw(1).expect("probability"),
            risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
            scorer: LearnedScorerContractV1 {
                model_digest: digest(3),
                feature_schema_digest: digest(4),
                output_schema_digest: digest(5),
                score_semantics_digest: digest(6),
                scorer_contract_digest: digest(7),
            },
            calibration_dataset_digest: digest(8),
            ood_dataset_digest: digest(9),
            calibration_artifact_digest: digest(10),
            ood_artifact_digest: digest(11),
        }
    }

    fn definition(parameter_bundle_digest: Digest32) -> CellDefinitionV2 {
        let role = CellRoleV1::Decision;
        let state = digest(13);
        CellDefinitionV2 {
            cell_id: id("cell.decision.owner"),
            generation: Generation::new(1).expect("generation"),
            scope_digest: digest(14),
            lineage_digest: digest(15),
            role,
            capability_profile: CellCapabilityProfileV1 {
                role,
                observation_schema_digest: digest(16),
                output_schema_digest: digest(17),
                state_schema_digest: state,
                input_port_digest: digest(18),
                output_port_digest: digest(19),
                termination_port_digest: digest(20),
                owner_module: id("hepta-intuition::decide_calibrated_v3"),
                persistence_class: CellPersistenceClassV1::Durable,
                update_mode: CellUpdateModeV1::InferenceOnly,
                fallback_role: None,
                objective_digest: digest(21),
                resource_budget_digest: digest(22),
                evaluation_profile_digest: digest(23),
                authority: AuthorityPosture::DENY_ALL,
            },
            parameter_bundle_digest,
            state_schema_digest: state,
            port_abi_digest: digest(24),
            owner_module: id("hepta-intuition::decide_calibrated_v3"),
            objective_digest: digest(21),
            fallback_role: None,
            evidence_owner: id("hepta.learning.eval"),
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    #[test]
    fn checkpoint_round_trip_binds_definition_profile_and_artifact() {
        let profile = profile();
        let artifact = digest(25);
        let mut owner = DecisionCellOwnerV1::load_committed(
            definition(artifact),
            profile.clone(),
            artifact,
            digest(26),
        )
        .expect("owner");
        owner.state.sequence = 4;
        owner.state.current_state_digest = digest(27);
        owner.state.history.push(digest(27));
        let path = std::env::temp_dir().join(format!(
            "hepta-decision-checkpoint-{}-{}.bin",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock")
                .as_nanos()
        ));
        let checksum = owner.save_checkpoint(&path).expect("save");
        let mut restored = DecisionCellOwnerV1::load_committed(
            definition(artifact),
            profile,
            artifact,
            digest(99),
        )
        .expect("restored owner");
        assert_eq!(
            restored.restore_checkpoint(&path).expect("restore"),
            checksum
        );
        assert_eq!(restored.state().current_state_digest, digest(27));
        let mut bytes = std::fs::read(&path).expect("read");
        *bytes.last_mut().expect("bytes") ^= 0x20;
        std::fs::write(&path, bytes).expect("tamper");
        assert_eq!(
            restored.restore_checkpoint(&path),
            Err(DecisionCellOwnerErrorV1::InvalidCheckpoint)
        );
        let _ = std::fs::remove_file(path);
    }
}
