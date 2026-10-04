//! Fixed host composition over the original learning owners. No path, key,
//! writer or journal is opened here. The host retains both exclusive handles.
use std::error::Error;
use std::fmt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_components::learning_artifacts as artifacts;
use codex_hepta_agent_components::learning_ledger as ledger;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

#[derive(Clone, Debug)]
pub struct HostLearningWithdrawalIntentV1 {
    pub ledger_predecessor: Digest32,
    pub lineage: ledger::UnlearningLineageRequestV1,
    pub dataset: ledger::DatasetSnapshotReceiptV3,
    pub evidence: ledger::SignedLearningEvidenceV1,
    pub artifact_predecessor: Digest32,
}

#[derive(Clone, Debug)]
pub struct HostLearningWithdrawalReceiptV1 {
    pub source: ledger::UnlearningLineageReceiptV1,
    pub withdrawal_head: Digest32,
    pub publication: artifacts::ArtifactPublicationReceiptV1,
    /// Actual CURRENT eligibility observations, not model-weight forgetting or
    /// proof that an external delivery was attempted. The driver probes that.
    pub current_ineligible_artifacts: Vec<StableId>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum HostLearningWithdrawalPhaseV1 {
    RejectedBeforeFence,
    WithdrawalFenceUncertain,
    SourceAppendUncertain,
    SourceAcknowledged,
    PublicationUncertain,
    ArtifactAcknowledged,
}

/// Retain the original intent and any publication request. Resolve uncertain
/// effects from the existing ledger witness/checkpoint, never mint a new ID.
#[derive(Debug)]
pub struct HostLearningWithdrawalErrorV1 {
    pub phase: HostLearningWithdrawalPhaseV1,
    pub source_ack: Option<ledger::UnlearningLineageReceiptV1>,
    pub publication_request: Option<Box<artifacts::LearningArtifactPublishRequestV1>>,
    pub state_changes: Vec<artifacts::ArtifactEvent>,
    pub withdrawal_frontier: Option<artifacts::DatasetWithdrawalRegistry>,
    pub publication_ack: Option<artifacts::ArtifactPublicationReceiptV1>,
    pub detail: String,
}
impl fmt::Display for HostLearningWithdrawalErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            formatter,
            "learning withdrawal {:?}: {}",
            self.phase, self.detail
        )
    }
}
impl Error for HostLearningWithdrawalErrorV1 {}

/// Execute a currently signed source withdrawal while borrowing the actual
/// owners. The Root-published delivery fence is durably closed BEFORE the first
/// source append. `publication` supplies a genuine clean candidate and a head
/// signed by the already admitted independent artifact authority; no signer is
/// created here. This function is not exposed through ordinary Agentd RPC.
pub fn withdraw_learning_dataset_v1(
    writer: &mut ledger::LedgerWriter,
    owner: &mut artifacts::LearningArtifactOwnerService,
    intent: &HostLearningWithdrawalIntentV1,
    publication: impl FnOnce(
        &artifacts::LearningArtifactOwnerService,
        &[artifacts::ArtifactEvent],
        u64,
    ) -> Result<artifacts::LearningArtifactPublishRequestV1, String>,
) -> Result<HostLearningWithdrawalReceiptV1, HostLearningWithdrawalErrorV1> {
    withdraw_with_clock(writer, owner, intent, publication, wall_clock_millis)
}

fn withdraw_with_clock(
    writer: &mut ledger::LedgerWriter,
    owner: &mut artifacts::LearningArtifactOwnerService,
    intent: &HostLearningWithdrawalIntentV1,
    publication: impl FnOnce(
        &artifacts::LearningArtifactOwnerService,
        &[artifacts::ArtifactEvent],
        u64,
    ) -> Result<artifacts::LearningArtifactPublishRequestV1, String>,
    mut clock: impl FnMut() -> Result<u64, String>,
) -> Result<HostLearningWithdrawalReceiptV1, HostLearningWithdrawalErrorV1> {
    let mut phase = HostLearningWithdrawalPhaseV1::RejectedBeforeFence;
    let mut source_ack = None;
    let mut publication_request = None;
    let mut state_changes = Vec::new();
    let mut withdrawal_frontier = None;
    let mut publication_ack = None;
    let outcome = (|| -> Result<HostLearningWithdrawalReceiptV1, String> {
        // Root's public frontier cannot be published by an ordinary workload.
        let status = std::fs::read_to_string("/proc/self/status").map_err(|e| e.to_string())?;
        let uid = status
            .lines()
            .find_map(|line| line.strip_prefix("Uid:"))
            .ok_or("missing actual host UID")?;
        if uid.split_whitespace().count() != 4 || uid.split_whitespace().any(|id| id != "0") {
            return Err("learning withdrawal requires the original Root host".to_string());
        }
        let started = clock()?;
        let mut last = started;
        let mut now = || {
            let observed = clock()?;
            if observed < last {
                return Err("withdrawal owner clock regressed".to_string());
            }
            last = observed;
            Ok(observed)
        };
        if owner.registry().head_digest() != intent.artifact_predecessor {
            return Err("withdrawal artifact predecessor changed".to_string());
        }
        let preview = writer
            .preview_unlearning(
                intent.ledger_predecessor,
                &intent.lineage,
                &intent.dataset,
                &intent.evidence,
                started,
            )
            .map_err(|e| e.to_string())?;
        let principal = preview.principal();
        let notice = artifacts::DatasetRevocationRequest {
            operation_id: intent.lineage.lineage_id.clone(),
            dataset_digest: intent.lineage.dataset_digest,
            source_revocation_digest: preview.event_digest(),
            evaluator_id: principal.principal_id.clone(),
        };
        let prepared = owner
            .prepare_dataset_revocation_from_current(&notice, started)
            .map_err(|e| e.to_string())?;
        if !prepared
            .summary()
            .direct_artifacts
            .contains(&intent.lineage.artifact_id)
        {
            return Err("source handoff artifact is not in the authenticated dataset".to_string());
        }
        let changes: Vec<_> = prepared.registry().records()[owner.registry().records().len()..]
            .iter()
            .map(|record| record.event.clone())
            .collect();
        state_changes = changes.clone();
        let targets = prepared.summary().direct_artifacts.clone();
        let mut withdrawals = owner.withdrawal_registry().clone();
        withdrawals
            .append(artifacts::DatasetWithdrawalNoticeV1 {
                notice_id: intent.lineage.lineage_id.clone(),
                dataset_digest: intent.lineage.dataset_digest,
                source_tombstone_digest: preview.event_digest(),
                authority_id: principal.principal_id.clone(),
                credential_chain_digest: principal.credential_chain_digest,
                signing_key_digest: principal.signing_key_digest,
                authority_epoch: principal.authority_epoch,
                issued_at: intent.evidence.issued_at,
            })
            .map_err(|e| e.to_string())?;
        let withdrawal_head = withdrawals.head_digest();
        withdrawal_frontier = Some(withdrawals.clone());
        phase = HostLearningWithdrawalPhaseV1::WithdrawalFenceUncertain;
        owner
            .install_withdrawal_frontier(withdrawals)
            .map_err(|e| e.to_string())?;
        owner
            .publish_root_read_frontier(now()?)
            .map_err(|e| e.to_string())?;

        // A slow fsync cannot preserve expired authority. The original append
        // re-verifies role, scope, distribution, witness and this fresh clock.
        phase = HostLearningWithdrawalPhaseV1::SourceAppendUncertain;
        let source = writer
            .append_unlearning(
                intent.ledger_predecessor,
                intent.lineage.clone(),
                &intent.dataset,
                &intent.evidence,
                now()?,
            )
            .map_err(|e| e.to_string())?;
        source_ack = Some(source.clone());
        phase = HostLearningWithdrawalPhaseV1::SourceAcknowledged;
        if source.append.event_digest != preview.event_digest()
            || source.source_event_digest != preview.source_event_digest()
        {
            return Err("original source ACK differs from authenticated preview".to_string());
        }
        let mut request = publication(owner, &changes, now()?)?;
        publication_request = Some(Box::new(request.clone()));
        if request.expected_registry_predecessor_head != intent.artifact_predecessor {
            return Err("publication did not retain the original predecessor".to_string());
        }
        request.now = now()?;
        publication_request = Some(Box::new(request.clone()));
        phase = HostLearningWithdrawalPhaseV1::PublicationUncertain;
        let receipt = owner
            .publish_with_state_changes_and_clock(request, &changes, &mut || {
                now().map_err(|_| artifacts::LearningArtifactOwnerServiceError::ClockUnavailable)
            })
            .map_err(|e| e.to_string())?;
        publication_ack = Some(receipt.clone());
        phase = HostLearningWithdrawalPhaseV1::ArtifactAcknowledged;
        owner
            .publish_root_read_frontier(now()?)
            .map_err(|e| e.to_string())?;
        let current = owner
            .current_registry_view(now()?)
            .map_err(|e| e.to_string())?;
        if targets.iter().any(|target| current.is_eligible(target)) {
            return Err("acknowledged withdrawal still permits an original artifact".to_string());
        }
        Ok(HostLearningWithdrawalReceiptV1 {
            source,
            withdrawal_head,
            publication: receipt,
            current_ineligible_artifacts: targets,
        })
    })();
    outcome.map_err(|detail| HostLearningWithdrawalErrorV1 {
        phase,
        source_ack,
        publication_request,
        state_changes,
        withdrawal_frontier,
        publication_ack,
        detail,
    })
}

#[cfg(test)]
#[path = "learning_withdrawal_tests.rs"]
mod tests;

fn wall_clock_millis() -> Result<u64, String> {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|e| e.to_string())?
            .as_millis(),
    )
    .map_err(|e| e.to_string())
}
