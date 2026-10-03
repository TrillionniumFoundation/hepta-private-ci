//! Original complete dataset receipt transfer; this codec grants no authority.
use crate::DatasetSnapshotReceiptV3;
use crate::DatasetSnapshotV2;
use crate::PrincipalWire;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;
type ReviewResult<T> = Result<T, Box<dyn std::error::Error>>;
#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReviewDatasetWireV1 {
    pub snapshot_id: String,
    pub ledger_head_digest: String,
    pub objective_digest: String,
    pub eligible_frontier: u64,
    pub outcome_watermark: u64,
    pub source_record_digests: Vec<String>,
    pub pending_outcomes: u32,
    pub censored_outcomes: u32,
    pub dataset_digest: String,
    pub authority_grants_any: bool,
    pub producer: PrincipalWire,
    pub correction_cut_digest: String,
    pub revocation_cut_digest: String,
    pub inclusion_policy_digest: String,
}
impl ReviewDatasetWireV1 {
    pub fn from_native(v: &DatasetSnapshotReceiptV3) -> Self {
        Self {
            snapshot_id: v.snapshot.snapshot_id.to_string(),
            ledger_head_digest: v.snapshot.ledger_head_digest.to_string(),
            objective_digest: v.snapshot.objective_digest.to_string(),
            eligible_frontier: v.snapshot.eligible_frontier,
            outcome_watermark: v.snapshot.outcome_watermark,
            source_record_digests: v
                .snapshot
                .source_record_digests
                .iter()
                .map(ToString::to_string)
                .collect(),
            pending_outcomes: v.snapshot.pending_outcomes,
            censored_outcomes: v.snapshot.censored_outcomes,
            dataset_digest: v.snapshot.dataset_digest.to_string(),
            authority_grants_any: false,
            producer: PrincipalWire::from_principal(&v.producer),
            correction_cut_digest: v.correction_cut_digest.to_string(),
            revocation_cut_digest: v.revocation_cut_digest.to_string(),
            inclusion_policy_digest: v.inclusion_policy_digest.to_string(),
        }
    }
    pub fn native(&self) -> ReviewResult<DatasetSnapshotReceiptV3> {
        if self.authority_grants_any || self.source_record_digests.len() > 4096 {
            return Err("review dataset authority/bound".into());
        }
        Ok(DatasetSnapshotReceiptV3 {
            snapshot: DatasetSnapshotV2 {
                snapshot_id: StableId::new(self.snapshot_id.clone())?,
                ledger_head_digest: self.ledger_head_digest.parse()?,
                objective_digest: self.objective_digest.parse()?,
                eligible_frontier: self.eligible_frontier,
                outcome_watermark: self.outcome_watermark,
                source_record_digests: self
                    .source_record_digests
                    .iter()
                    .map(|s| s.parse())
                    .collect::<Result<Vec<_>, _>>()?,
                pending_outcomes: self.pending_outcomes,
                censored_outcomes: self.censored_outcomes,
                dataset_digest: self.dataset_digest.parse()?,
                authority: AuthorityPosture::DENY_ALL,
            },
            producer: self.producer.principal()?,
            correction_cut_digest: self.correction_cut_digest.parse()?,
            revocation_cut_digest: self.revocation_cut_digest.parse()?,
            inclusion_policy_digest: self.inclusion_policy_digest.parse()?,
        })
    }
}
