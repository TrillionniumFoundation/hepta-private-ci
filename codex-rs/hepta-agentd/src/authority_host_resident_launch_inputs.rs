//! Bounded Root deployment data for an already completed ordinary A.
//! No task result, trust key set, role endpoint or private signer is decoded.

use std::io;
use std::path::Path;
use std::sync::Arc;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningUpdateScopeV2;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use super::trust::OriginalHostTrust;
use super::trust::digest;
use crate::AgentdRootAuthorityPeer;
use crate::CellQ24DatasetRuleV1;
use crate::CellQ24PrivateHeadV1;
use crate::LoadedCellQ24ModelV1;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationPanelTaskV1;
use crate::OriginalCellQ24MaterialReceiptConfigV1;
use crate::RootResidentCandidateInputsV1;
use crate::RootResidentLearningProfileV3;
use crate::authority_host_config::read_root_json;
use crate::learning_iteration_checkpoint::decode_original_owner_snapshot_v1;
use crate::learning_iteration_checkpoint::encode_original_owner_snapshot_v1;

const PURPOSE: &str = "hepta.host-resident-learning.candidate-deployment.v3";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DeploymentFile {
    schema_version: u32,
    purpose: String,
    initial_snapshot: String,
    scope: Scope,
    head: Head,
    unit_profile_digest: String,
    freeze_plan: FreezePlan,
    freeze_evidence: FreezeEvidence,
    original_freeze_payload: String,
    maximum_signature_lifetime_seconds: u64,
    panel: Panel,
    original_intent: SignedFinalUseGrant,
    original_lease: AuthorityLease,
    consumer: Consumer,
    handoff_timeout_ms: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Scope {
    update_scope: UpdateScope,
    update_rule: String,
    binding: String,
}

#[derive(Clone, Copy, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum UpdateScope {
    Cell,
    Organ,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Head {
    Drive { index: u16 },
    Prediction { index: u16 },
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FreezePlan {
    snapshot_id: String,
    objective_digest: String,
    inclusion_policy_digest: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct FreezeEvidence {
    evidence_id: String,
    principal_id: String,
    role: String,
    trust_digest: String,
    scope_digest: String,
    objective_digest: String,
    authority_epoch: u64,
    issued_at: u64,
    expires_at: u64,
    payload_digest: String,
    signature: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Panel {
    primary: PanelTask,
    retention: Vec<PanelTask>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PanelTask {
    plan_id: String,
    task_digest: String,
    cohort_rule_digest: String,
}

impl PanelTask {
    fn original(self) -> io::Result<OriginalCellEvaluationPanelTaskV1> {
        Ok(OriginalCellEvaluationPanelTaskV1 {
            plan_id: StableId::new(self.plan_id).map_err(io::Error::other)?,
            task_digest: digest(&self.task_digest)?,
            cohort_rule_digest: digest(&self.cohort_rule_digest)?,
        })
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Consumer {
    pub(super) uid: u32,
    pid: u32,
    boot_id: String,
    process_start_ticks: u64,
    timeout_ms: u64,
    lifetime_ms: u64,
}

impl Consumer {
    pub(super) fn into_peer(self) -> (AgentdRootAuthorityPeer, u32, Duration, Duration) {
        (
            AgentdRootAuthorityPeer {
                pid: self.pid,
                boot_id: self.boot_id,
                process_start_ticks: self.process_start_ticks,
            },
            self.uid,
            Duration::from_millis(self.timeout_ms),
            Duration::from_millis(self.lifetime_ms),
        )
    }
}

pub(super) struct OriginalDeployment {
    pub(super) profile: RootResidentLearningProfileV3,
    pub(super) inputs: RootResidentCandidateInputsV1,
    pub(super) consumer: Consumer,
    pub(super) handoff_timeout: Duration,
    pub(super) enrollment_profile: EnrollmentProfile,
}

impl OriginalDeployment {
    pub(super) fn read(
        path: &Path,
        trust: &OriginalHostTrust,
        baseline: Arc<LoadedCellQ24ModelV1>,
    ) -> io::Result<Self> {
        let value: DeploymentFile = read_root_json(path)?;
        if value.schema_version != 3
            || value.purpose != PURPOSE
            || !(1..=30_000).contains(&value.handoff_timeout_ms)
            || value.consumer.uid == 0
            || value.consumer.pid == 0
            || value.consumer.process_start_ticks == 0
            || value.consumer.boot_id.is_empty()
            || !(1..=30_000).contains(&value.consumer.timeout_ms)
            || !(1..=300_000).contains(&value.consumer.lifetime_ms)
            || value.panel.retention.is_empty()
            || value.panel.retention.len() > 16
        {
            return Err(io::Error::other("original resident deployment profile differs"));
        }
        let raw = decode(&value.initial_snapshot, 8_192)?;
        let initial = decode_original_owner_snapshot_v1(&raw).map_err(io::Error::other)?;
        let empty = LearningIterationCoordinatorV1::new(
            initial.request.clone(),
            initial.owners.clone(),
        )
        .map_err(io::Error::other)?;
        if empty.snapshot() != &initial
            || encode_original_owner_snapshot_v1(&initial).map_err(io::Error::other)? != raw
        {
            return Err(io::Error::other("exact original empty stage cut is required"));
        }
        let scope = FrozenLearningScopeV2::freeze(
            &initial.request,
            &initial.owners,
            match value.scope.update_scope {
                UpdateScope::Cell => LearningUpdateScopeV2::Cell,
                UpdateScope::Organ => LearningUpdateScopeV2::Organ,
            },
            digest(&value.scope.update_rule)?,
        )
        .map_err(io::Error::other)?;
        if scope.binding() != digest(&value.scope.binding)? {
            return Err(io::Error::other("original frozen scope binding differs"));
        }
        let protocol = OriginalCellEvaluationPanelRegistrationV1::new(
            value.panel.primary.original()?,
            value
                .panel
                .retention
                .into_iter()
                .map(PanelTask::original)
                .collect::<io::Result<_>>()?,
        )
        .map_err(io::Error::other)?;
        if initial.request.evaluation_profile != protocol.evaluation_profile()
            || baseline.components() != &initial.request.selected_bundle.components
        {
            return Err(io::Error::other("original pre-training panel or loaded baseline differs"));
        }
        let at = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(io::Error::other)?
            .as_secs();
        let freeze = value.freeze_evidence.original()?;
        let payload = decode(&value.original_freeze_payload, 65_536)?;
        trust
            .verifier
            .verify(LearningEvidenceRoleV1::Evaluator, &freeze, &payload, at)
            .map_err(io::Error::other)?;
        let material = OriginalCellQ24MaterialReceiptConfigV1 {
            experience_signer: trust.observer(&initial.owners.experience, at)?,
            dataset_signer: trust.observer(&initial.owners.dataset, at)?,
            initial,
            scope,
            rule: CellQ24DatasetRuleV1 {
                head: match value.head {
                    Head::Drive { index } => CellQ24PrivateHeadV1::Drive { index },
                    Head::Prediction { index } => CellQ24PrivateHeadV1::Prediction { index },
                },
                unit_profile_digest: digest(&value.unit_profile_digest)?,
            },
            freeze_plan: DatasetFreezePlanV2 {
                snapshot_id: StableId::new(value.freeze_plan.snapshot_id)
                    .map_err(io::Error::other)?,
                objective_digest: digest(&value.freeze_plan.objective_digest)?,
                inclusion_policy_digest: digest(&value.freeze_plan.inclusion_policy_digest)?,
            },
            freeze_evidence: freeze,
            verifier: trust.verifier.clone(),
            maximum_signature_lifetime_seconds: value.maximum_signature_lifetime_seconds,
        };
        OriginalCellQ24MaterialReceiptConfigV1::require_original_command_initial(&material)
            .map_err(io::Error::other)?;
        let original_handoff = (
            value.initial_snapshot.clone(),
            value.scope.clone(),
            value.original_intent.clone(),
            value.original_lease.clone(),
        );
        let profile = RootResidentLearningProfileV3::new(
            material.initial.clone(),
            material.scope.clone(),
            &trust.verifier,
            value.original_intent,
            value.original_lease,
        )?;
        let enrollment_profile = EnrollmentProfile::capture(original_handoff, profile.binding());
        Ok(Self {
            profile,
            enrollment_profile,
            inputs: RootResidentCandidateInputsV1 {
                material,
                protocol,
                baseline,
                verifier: trust.verifier.clone(),
            },
            consumer: value.consumer,
            handoff_timeout: Duration::from_millis(value.handoff_timeout_ms),
        })
    }
}

impl FreezeEvidence {
    fn original(self) -> io::Result<SignedLearningEvidenceV1> {
        if self.role != "evaluator" {
            return Err(io::Error::other("fixed original freeze evaluator purpose required"));
        }
        let signature = decode(&self.signature, 64)?
            .try_into()
            .map_err(|_| io::Error::other("complete original freeze signature required"))?;
        Ok(SignedLearningEvidenceV1 {
            evidence_id: StableId::new(self.evidence_id).map_err(io::Error::other)?,
            principal_id: StableId::new(self.principal_id).map_err(io::Error::other)?,
            role: LearningEvidenceRoleV1::Evaluator,
            trust_digest: digest(&self.trust_digest)?,
            scope_digest: digest(&self.scope_digest)?,
            objective_digest: digest(&self.objective_digest)?,
            authority_epoch: self.authority_epoch,
            issued_at: self.issued_at,
            expires_at: self.expires_at,
            payload_digest: digest(&self.payload_digest)?,
            signature,
        })
    }
}

fn decode(value: &str, limit: usize) -> io::Result<Vec<u8>> {
    if value.is_empty() || value.len() > limit.div_ceil(3) * 4 {
        return Err(io::Error::other("original resident input exceeds its codec bound"));
    }
    let bytes = STANDARD_NO_PAD.decode(value).map_err(io::Error::other)?;
    if bytes.len() > limit || STANDARD_NO_PAD.encode(&bytes) != value {
        return Err(io::Error::other("noncanonical original resident input bytes"));
    }
    Ok(bytes)
}

#[path = "authority_host_resident_enrollment_profile.rs"]
mod enrollment_profile;
pub(super) use enrollment_profile::EnrollmentProfile;
