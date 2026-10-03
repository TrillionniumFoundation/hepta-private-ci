//! A separately authenticated, bounded dataset purpose over the SAME full ledger.
//! Windows select complete episodes by their original decision sequence. They
//! never truncate history, discard a late outcome, or grant execution authority.
use super::*;
use crate::ReviewDatasetWireV1;

#[path = "production_dataset_window_current_v3.rs"]
mod current;
pub use current::authenticate_ledger_snapshot_prefix_v3;
pub use current::verify_dataset_window_snapshot_against_current_ledger_v3;

pub const MAX_DATASET_WINDOW_SOURCE_RECORDS_V3: u32 = 4096;
pub const MAX_DATASET_WINDOW_ENCODED_BYTES_V3: u32 = 65_536;

/// The Root caller must pin the whole policy source, not just its digest field.
/// The independent Evaluator signs every field plus the full derived ledger cut.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWindowFreezePlanV3 {
    pub snapshot_id: StableId,
    pub objective_digest: Digest32,
    pub inclusion_policy_digest: Digest32,
    pub decision_sequence_start: u64,
    pub decision_sequence_end: u64,
    pub maximum_episodes: u32,
    pub maximum_source_records: u32,
    /// Bound the original complete receipt codec. Transport must separately
    /// bound its whole envelope, including the full signing payload.
    pub maximum_encoded_bytes: u32,
}
/// Complete transport of the original window policy. Parsing grants no
/// authority and does not validate a policy against a ledger frontier.
#[derive(Clone, Debug, serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DatasetWindowFreezePlanWireV3 {
    pub snapshot_id: String,
    pub objective_digest: String,
    pub inclusion_policy_digest: String,
    pub decision_sequence_start: u64,
    pub decision_sequence_end: u64,
    pub maximum_episodes: u32,
    pub maximum_source_records: u32,
    pub maximum_encoded_bytes: u32,
}
impl DatasetWindowFreezePlanWireV3 {
    pub fn from_native(plan: &DatasetWindowFreezePlanV3) -> Self {
        Self {
            snapshot_id: plan.snapshot_id.to_string(),
            objective_digest: plan.objective_digest.to_string(),
            inclusion_policy_digest: plan.inclusion_policy_digest.to_string(),
            decision_sequence_start: plan.decision_sequence_start,
            decision_sequence_end: plan.decision_sequence_end,
            maximum_episodes: plan.maximum_episodes,
            maximum_source_records: plan.maximum_source_records,
            maximum_encoded_bytes: plan.maximum_encoded_bytes,
        }
    }
    pub fn native(&self) -> Result<DatasetWindowFreezePlanV3, Box<dyn StdError>> {
        Ok(DatasetWindowFreezePlanV3 {
            snapshot_id: StableId::new(self.snapshot_id.clone())?,
            objective_digest: self.objective_digest.parse()?,
            inclusion_policy_digest: self.inclusion_policy_digest.parse()?,
            decision_sequence_start: self.decision_sequence_start,
            decision_sequence_end: self.decision_sequence_end,
            maximum_episodes: self.maximum_episodes,
            maximum_source_records: self.maximum_source_records,
            maximum_encoded_bytes: self.maximum_encoded_bytes,
        })
    }
}

/// Full policy binding beside the unchanged original receipt. This integrity
/// digest is not authenticated issuance; the original Evaluator signature is.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DatasetWindowSnapshotReceiptV3 {
    pub window_policy_digest: Digest32,
    pub receipt: DatasetSnapshotReceiptV3,
}
impl DatasetWindowFreezePlanV3 {
    pub fn policy_digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.canonical_policy_bytes())
    }
    fn canonical_policy_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.learning-ledger.dataset-window-policy.v3".to_vec();
        push_id(&mut bytes, &self.snapshot_id);
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(self.inclusion_policy_digest.as_array());
        bytes.extend_from_slice(&self.decision_sequence_start.to_be_bytes());
        bytes.extend_from_slice(&self.decision_sequence_end.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_episodes.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_source_records.to_be_bytes());
        bytes.extend_from_slice(&self.maximum_encoded_bytes.to_be_bytes());
        bytes
    }
    fn validate(&self, frontier: u64) -> Result<(), ProductionLedgerError> {
        if self.objective_digest.is_zero()
            || self.inclusion_policy_digest.is_zero()
            || self.decision_sequence_start == 0
            || self.decision_sequence_end < self.decision_sequence_start
            || self.decision_sequence_end > frontier
            || self.maximum_episodes == 0
            || self.maximum_episodes > MAX_DATASET_WINDOW_SOURCE_RECORDS_V3
            || self.maximum_source_records == 0
            || self.maximum_source_records > MAX_DATASET_WINDOW_SOURCE_RECORDS_V3
            || self.maximum_encoded_bytes == 0
            || self.maximum_encoded_bytes > MAX_DATASET_WINDOW_ENCODED_BYTES_V3
        {
            return Err(ProductionLedgerError::Binding("dataset window policy"));
        }
        Ok(())
    }
}

fn derive_window(
    snapshot: &LedgerSnapshot,
    plan: &DatasetWindowFreezePlanV3,
) -> Result<DerivedDataset, ProductionLedgerError> {
    let frontier = snapshot.records().last().map_or(0, |r| r.sequence.get());
    plan.validate(frontier)?;
    if snapshot.head_digest.is_zero() {
        return Err(ProductionLedgerError::Binding("empty ledger"));
    }
    // Replay the complete source before selection. Later corrections,
    // revocations and unlearning remain authoritative outside the interval.
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let active = ledger.active_records();
    let episodes = active
        .iter()
        .filter_map(|record| match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(decision)
                if decision.objective_digest == plan.objective_digest
                    && (plan.decision_sequence_start..=plan.decision_sequence_end)
                        .contains(&record.sequence.get()) =>
            {
                Some(decision.episode_id.clone())
            }
            _ => None,
        })
        .collect::<BTreeSet<_>>();
    if episodes.is_empty() {
        return Err(ProductionLedgerError::AuthenticatedDecisionRequired);
    }
    if episodes.len() > plan.maximum_episodes as usize {
        return Err(ProductionLedgerError::Binding(
            "dataset window episode capacity",
        ));
    }
    let derived = derive_dataset_for_episodes(snapshot, &active, &episodes)?;
    if derived.source_record_digests.len() > plan.maximum_source_records as usize {
        return Err(ProductionLedgerError::Binding(
            "dataset window source capacity",
        ));
    }
    Ok(derived)
}

fn receipt_from_derived(
    snapshot: &LedgerSnapshot,
    plan: &DatasetWindowFreezePlanV3,
    derived: DerivedDataset,
    producer: AuthenticatedPrincipalV1,
    now: u64,
) -> Result<DatasetWindowSnapshotReceiptV3, ProductionLedgerError> {
    producer
        .validate(now)
        .map_err(ProductionLedgerError::Causal)?;
    let receipt = freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: plan.snapshot_id.clone(),
            producer,
            ledger_head_digest: snapshot.head_digest,
            objective_digest: plan.objective_digest,
            eligible_frontier: derived.eligible_frontier,
            outcome_watermark: derived.outcome_watermark,
            correction_cut_digest: derived.correction_cut_digest,
            revocation_cut_digest: derived.revocation_cut_digest,
            inclusion_policy_digest: plan.inclusion_policy_digest,
            source_record_digests: derived.source_record_digests,
            pending_outcomes: derived.pending_outcomes,
            censored_outcomes: derived.censored_outcomes,
        },
        now,
    )?;
    let result = DatasetWindowSnapshotReceiptV3 {
        window_policy_digest: plan.policy_digest(),
        receipt,
    };
    let encoded = serde_json::to_vec(&DatasetWindowSnapshotWireV3::from_native(&result))
        .map_err(|_| ProductionLedgerError::Binding("dataset window receipt encoding"))?;
    if encoded.len() > plan.maximum_encoded_bytes as usize {
        return Err(ProductionLedgerError::Binding(
            "dataset window encoded capacity",
        ));
    }
    Ok(result)
}

/// Derive current metadata through the original receipt codec. This pure helper
/// does not authenticate signed issuance; the product writer below does.
pub fn freeze_dataset_window_from_ledger_v3(
    snapshot: &LedgerSnapshot,
    plan: DatasetWindowFreezePlanV3,
    producer: AuthenticatedPrincipalV1,
    now: u64,
) -> Result<DatasetWindowSnapshotReceiptV3, ProductionLedgerError> {
    let derived = derive_window(snapshot, &plan)?;
    receipt_from_derived(snapshot, &plan, derived, producer, now)
}

/// Separate V3 purpose: every policy field, current full head, complete episode
/// closure and historical cuts are bound. The original V2 signing bytes stay
/// unchanged, and a V2 signature cannot authorize a window.
pub fn dataset_window_freeze_signing_payload_v3(
    snapshot: &LedgerSnapshot,
    plan: &DatasetWindowFreezePlanV3,
) -> Result<Vec<u8>, ProductionLedgerError> {
    let derived = derive_window(snapshot, plan)?;
    let mut bytes = b"hepta.learning-ledger.dataset-window-freeze-plan.v3".to_vec();
    bytes.extend_from_slice(&plan.canonical_policy_bytes());
    bytes.extend_from_slice(plan.policy_digest().as_array());
    bytes.extend_from_slice(snapshot.head_digest.as_array());
    bytes.extend_from_slice(&derived.eligible_frontier.to_be_bytes());
    bytes.extend_from_slice(&derived.outcome_watermark.to_be_bytes());
    bytes.extend_from_slice(derived.correction_cut_digest.as_array());
    bytes.extend_from_slice(derived.revocation_cut_digest.as_array());
    bytes.extend_from_slice(&(derived.source_record_digests.len() as u64).to_be_bytes());
    for digest in derived.source_record_digests {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

/// Match the whole explicit policy against the SAME complete canonical source.
/// This validates current metadata, not peer custody or signature issuance.
pub fn verify_dataset_window_snapshot_against_ledger_v3(
    receipt: &DatasetWindowSnapshotReceiptV3,
    plan: &DatasetWindowFreezePlanV3,
    snapshot: &LedgerSnapshot,
    now: u64,
) -> Result<(), ProductionLedgerError> {
    verify_dataset_snapshot_receipt_v3(&receipt.receipt, now)?;
    let expected = freeze_dataset_window_from_ledger_v3(
        snapshot,
        plan.clone(),
        receipt.receipt.producer.clone(),
        now,
    )?;
    if receipt != &expected {
        return Err(ProductionLedgerError::Binding(
            "dataset window complete ledger binding",
        ));
    }
    Ok(())
}

impl LedgerWriter {
    /// Original writer, current independent Evaluator and witness; no ledger
    /// event is appended by freezing metadata.
    pub fn freeze_dataset_window_v3(
        &self,
        plan: DatasetWindowFreezePlanV3,
        evidence: &SignedLearningEvidenceV1,
        now: u64,
    ) -> Result<DatasetWindowSnapshotReceiptV3, ProductionLedgerError> {
        if plan.objective_digest != self.trust.verifier().objective_digest() {
            return Err(ProductionLedgerError::Binding("dataset objective"));
        }
        if self.backend.frontier()? != self.witness.frontier()? {
            return Err(ProductionLedgerError::WitnessLag);
        }
        let snapshot = self.backend.snapshot()?;
        let payload = dataset_window_freeze_signing_payload_v3(&snapshot, &plan)?;
        let verified = self.verify_current_evidence(
            LearningEvidenceRoleV1::Evaluator,
            evidence,
            &payload,
            now,
        )?;
        require_role(&verified, LearningEvidenceRoleV1::Evaluator)?;
        freeze_dataset_window_from_ledger_v3(&snapshot, plan, verified.principal().clone(), now)
    }

    pub fn revalidate_dataset_window_v3(
        &self,
        receipt: &DatasetWindowSnapshotReceiptV3,
        plan: &DatasetWindowFreezePlanV3,
        now: u64,
    ) -> Result<(), ProductionLedgerError> {
        self.revalidate_dataset_snapshot(&receipt.receipt, now)?;
        verify_dataset_window_snapshot_against_ledger_v3(
            receipt,
            plan,
            &self.backend.snapshot()?,
            now,
        )
    }
}

/// Thin composition of the original public receipt codec; successful parsing
/// supplies no custody, signature or current-source validation.
#[derive(serde::Deserialize, serde::Serialize)]
#[serde(deny_unknown_fields)]
pub struct DatasetWindowSnapshotWireV3 {
    pub window_policy_digest: String,
    pub receipt: ReviewDatasetWireV1,
}
impl DatasetWindowSnapshotWireV3 {
    pub fn from_native(v: &DatasetWindowSnapshotReceiptV3) -> Self {
        Self {
            window_policy_digest: v.window_policy_digest.to_string(),
            receipt: ReviewDatasetWireV1::from_native(&v.receipt),
        }
    }
    pub fn native(&self) -> Result<DatasetWindowSnapshotReceiptV3, Box<dyn StdError>> {
        let digest: Digest32 = self.window_policy_digest.parse()?;
        if digest.is_zero() {
            return Err("dataset window policy digest".into());
        }
        Ok(DatasetWindowSnapshotReceiptV3 {
            window_policy_digest: digest,
            receipt: self.receipt.native()?,
        })
    }
}
