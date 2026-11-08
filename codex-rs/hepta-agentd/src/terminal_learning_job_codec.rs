//! Protected result data, not deserialized permissions. Restore obtains a new
//! opaque Replay use from Memory; the native owner then revalidates the Ledger.

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_bellman_operator::LoadedTabularOperatorV1;
use codex_hepta_bellman_operator::TabularPayloadPinV1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::DatasetSnapshotV2;
use codex_hepta_learning_ledger::verify_dataset_snapshot_receipt_v3;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::AgentdSharedReplayHostV1;
use crate::SharedTerminalCandidateV1;
use crate::TerminalLearningErrorV1 as Error;
use crate::TerminalLearningReceiptV1;
use crate::TerminalLearningRequestV1;
use crate::TerminalLearningSourceLineageV1;

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct SavedReceipt {
    operation_id: String,
    payload: String,
    payload_digest: String,
    artifact_digest: String,
    sensor_core_digest: String,
    training_profile_digest: String,
    dataset: SavedDataset,
    source_owner: String,
    source_policy: String,
    source_revision: u64,
    source_support: String,
    training_samples: u32,
    elapsed_microseconds: u64,
    evidence_trust_digest: String,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SavedDataset {
    snapshot_id: String,
    ledger_head_digest: String,
    objective_digest: String,
    eligible_frontier: u64,
    outcome_watermark: u64,
    records: Vec<String>,
    pending_outcomes: u32,
    censored_outcomes: u32,
    dataset_digest: String,
    principal_id: String,
    credential_chain_digest: String,
    signing_key_digest: String,
    scope_digest: String,
    authority_epoch: u64,
    authenticated_at: u64,
    expires_at: u64,
    correction_cut_digest: String,
    revocation_cut_digest: String,
    inclusion_policy_digest: String,
}

impl SavedReceipt {
    pub(super) fn capture(receipt: &TerminalLearningReceiptV1) -> Result<Self, Error> {
        let candidate = &receipt.candidate;
        if receipt.authority != AuthorityPosture::DENY_ALL
            || receipt.payload.len() > 16 * 1024
            || candidate.dataset().snapshot.source_record_digests.len() > 256
            || receipt.source_records as usize
                != candidate.dataset().snapshot.source_record_digests.len()
            || receipt.training_samples as usize != candidate.training_samples()
            || candidate.payload_digest() != Digest32::of_bytes(&receipt.payload)
        {
            return Err(Error::Conflict);
        }
        let artifact = candidate.artifact();
        let dataset = candidate.dataset();
        let snapshot = &dataset.snapshot;
        let producer = &dataset.producer;
        Ok(Self {
            operation_id: receipt.operation_id.to_string(),
            payload: STANDARD_NO_PAD.encode(&receipt.payload),
            payload_digest: candidate.payload_digest().to_string(),
            artifact_digest: artifact.artifact_digest.to_string(),
            sensor_core_digest: artifact.sensor_core_digest.to_string(),
            training_profile_digest: artifact.training_profile_digest.to_string(),
            dataset: SavedDataset {
                snapshot_id: snapshot.snapshot_id.to_string(),
                ledger_head_digest: snapshot.ledger_head_digest.to_string(),
                objective_digest: snapshot.objective_digest.to_string(),
                eligible_frontier: snapshot.eligible_frontier,
                outcome_watermark: snapshot.outcome_watermark,
                records: snapshot
                    .source_record_digests
                    .iter()
                    .map(ToString::to_string)
                    .collect(),
                pending_outcomes: snapshot.pending_outcomes,
                censored_outcomes: snapshot.censored_outcomes,
                dataset_digest: snapshot.dataset_digest.to_string(),
                principal_id: producer.principal_id.to_string(),
                credential_chain_digest: producer.credential_chain_digest.to_string(),
                signing_key_digest: producer.signing_key_digest.to_string(),
                scope_digest: producer.scope_digest.to_string(),
                authority_epoch: producer.authority_epoch,
                authenticated_at: producer.authenticated_at,
                expires_at: producer.expires_at,
                correction_cut_digest: dataset.correction_cut_digest.to_string(),
                revocation_cut_digest: dataset.revocation_cut_digest.to_string(),
                inclusion_policy_digest: dataset.inclusion_policy_digest.to_string(),
            },
            source_owner: receipt.source.owner_id.to_string(),
            source_policy: receipt.source.policy_id.as_str().into(),
            source_revision: receipt.source.policy_revision,
            source_support: receipt.source.support_digest.to_string(),
            training_samples: receipt.training_samples,
            elapsed_microseconds: receipt.elapsed_microseconds,
            evidence_trust_digest: receipt.evidence_trust_digest.to_string(),
        })
    }

    pub(super) async fn restore(
        &self,
        replay: &AgentdSharedReplayHostV1,
        request: &TerminalLearningRequestV1,
        binding: Digest32,
        now: u64,
    ) -> Result<TerminalLearningReceiptV1, Error> {
        if self.operation_id != request.operation_id.as_str()
            || self.payload.len() > (16_usize * 1024).div_ceil(3) * 4
            || self.dataset.records.len() > request.budget.maximum_dataset_records as usize
        {
            return Err(Error::Conflict);
        }
        let payload = STANDARD_NO_PAD
            .decode(&self.payload)
            .map_err(|_| Error::InvalidRequest)?;
        if payload.len() as u64 > request.budget.maximum_artifact_bytes
            || STANDARD_NO_PAD.encode(&payload) != self.payload
        {
            return Err(Error::Conflict);
        }
        let dataset = self.dataset.restore()?;
        verify_dataset_snapshot_receipt_v3(&dataset, now).map_err(owner_error)?;
        if dataset.snapshot.dataset_digest != request.expected_dataset_digest {
            return Err(Error::Conflict);
        }
        let pin = TabularPayloadPinV1 {
            payload_digest: digest(&self.payload_digest)?,
            artifact_digest: digest(&self.artifact_digest)?,
            objective_digest: request.profile.objective_digest,
            dataset_digest: request.expected_dataset_digest,
            sensor_core_digest: digest(&self.sensor_core_digest)?,
            training_profile_digest: digest(&self.training_profile_digest)?,
            generation: request.profile.generation,
        };
        let loaded =
            LoadedTabularOperatorV1::from_pinned_payload(&payload, &pin).map_err(owner_error)?;
        let artifact = loaded.artifact();
        if artifact.artifact_id != request.profile.artifact_id
            || artifact.producer_id != request.profile.producer_id
            || artifact
                .cells
                .iter()
                .map(|cell| u64::from(cell.sample_count))
                .sum::<u64>()
                != u64::from(self.training_samples)
        {
            return Err(Error::Conflict);
        }
        // Only Memory can create this private use. Data in the CAS is never
        // promoted to a grant, even when its stored lineage is well formed.
        let source = replay
            .training_source(&request.source_policy_id)
            .await
            .map_err(owner_error)?;
        if source.owner_id().to_string() != self.source_owner
            || source.policy_id().as_str() != self.source_policy
            || source.policy_revision() != self.source_revision
            || source.source_support_digest().as_str() != self.source_support
            || digest(&self.source_support)? != request.expected_source_support_digest
        {
            return Err(Error::Conflict);
        }
        let lineage = TerminalLearningSourceLineageV1 {
            owner_id: source.owner_id().clone(),
            policy_id: source.policy_id().clone(),
            policy_revision: source.policy_revision(),
            support_digest: digest(&self.source_support)?,
        };
        let source_records = dataset.snapshot.source_record_digests.len() as u32;
        let candidate = SharedTerminalCandidateV1::from_recovered(
            artifact.clone(),
            dataset,
            source,
            &payload,
            self.training_samples as usize,
        );
        Ok(TerminalLearningReceiptV1 {
            operation_id: request.operation_id.clone(),
            job_digest: binding,
            candidate,
            payload,
            source: lineage,
            source_records,
            training_samples: self.training_samples,
            elapsed_microseconds: self.elapsed_microseconds,
            evidence_trust_digest: digest(&self.evidence_trust_digest)?,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

impl SavedDataset {
    fn restore(&self) -> Result<DatasetSnapshotReceiptV3, Error> {
        Ok(DatasetSnapshotReceiptV3 {
            snapshot: DatasetSnapshotV2 {
                snapshot_id: StableId::new(&self.snapshot_id).map_err(owner_error)?,
                ledger_head_digest: digest(&self.ledger_head_digest)?,
                objective_digest: digest(&self.objective_digest)?,
                eligible_frontier: self.eligible_frontier,
                outcome_watermark: self.outcome_watermark,
                source_record_digests: self
                    .records
                    .iter()
                    .map(|record| digest(record))
                    .collect::<Result<_, _>>()?,
                pending_outcomes: self.pending_outcomes,
                censored_outcomes: self.censored_outcomes,
                dataset_digest: digest(&self.dataset_digest)?,
                authority: AuthorityPosture::DENY_ALL,
            },
            producer: AuthenticatedPrincipalV1 {
                principal_id: StableId::new(&self.principal_id).map_err(owner_error)?,
                credential_chain_digest: digest(&self.credential_chain_digest)?,
                signing_key_digest: digest(&self.signing_key_digest)?,
                scope_digest: digest(&self.scope_digest)?,
                authority_epoch: self.authority_epoch,
                authenticated_at: self.authenticated_at,
                expires_at: self.expires_at,
            },
            correction_cut_digest: digest(&self.correction_cut_digest)?,
            revocation_cut_digest: digest(&self.revocation_cut_digest)?,
            inclusion_policy_digest: digest(&self.inclusion_policy_digest)?,
        })
    }
}

fn digest(value: &str) -> Result<Digest32, Error> {
    value.parse().map_err(|_| Error::InvalidRequest)
}
fn owner_error(error: impl std::fmt::Display) -> Error {
    Error::Owner(error.to_string())
}
