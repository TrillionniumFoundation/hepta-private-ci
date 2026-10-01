//! A deliberately narrow local Cell baseline trained from the actual ledger.
//!
//! This constant-state terminal-value profile is not Laya, a general Bellman
//! solver, causal policy improvement, or deployment selection. Targets and
//! action labels are derived from authenticated current owner events, never
//! supplied by the trainer under arbitrary nonzero evidence digests.
//!
//! The V1 receipt must come from the host-controlled owner's freeze operation.
//! V3 receipts carry digest integrity, not the signed freeze attestation; the
//! current owner API cannot authenticate an arbitrary historical freeze head
//! or inclusion policy. Active source checks therefore do not replace trusted
//! receipt provenance at that boundary. The signed-owner V2 entry point derives
//! its receipt directly from the exact evaluator-attested current owner freeze.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error;
use std::fmt;

use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::StrictLearnedOperatorError;
use crate::TabularOperatorArtifactV1;
use crate::TabularOperatorPlanV1;
use crate::TabularOperatorSampleV1;
use crate::fit_tabular_operator_strict_v2;

const MAX_SOURCE_RECORDS: usize = 4096;

#[derive(Clone, Debug)]
pub struct TerminalCellProfileV1 {
    pub artifact_id: StableId,
    pub producer_id: StableId,
    pub generation: Generation,
    pub sensor_id: StableId,
    pub objective_digest: Digest32,
    pub run_snapshot_digest: Digest32,
    pub unit_profile_digest: Digest32,
    pub action_ids: Vec<StableId>,
    pub minimum_samples_per_action: usize,
}

#[derive(Clone, Debug)]
pub struct FrozenTerminalCellV1 {
    plan: TabularOperatorPlanV1,
    dataset: DatasetSnapshotReceiptV3,
    trust_digest: Digest32,
    admitted_at: u64,
    signed_freeze: Option<SignedTerminalFreezeV2>,
}

#[derive(Clone, Debug)]
struct SignedTerminalFreezeV2 {
    evidence: SignedLearningEvidenceV1,
    payload: Vec<u8>,
}

impl FrozenTerminalCellV1 {
    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        &self.dataset
    }
    pub fn sample_count(&self) -> usize {
        self.plan.samples.len()
    }
}

#[derive(Debug)]
pub enum TerminalCellError {
    Ledger(ProductionLedgerError),
    Unsupported(&'static str),
    Fit(StrictLearnedOperatorError),
}
impl fmt::Display for TerminalCellError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}
impl Error for TerminalCellError {}
impl From<ProductionLedgerError> for TerminalCellError {
    fn from(value: ProductionLedgerError) -> Self {
        Self::Ledger(value)
    }
}

pub fn freeze_terminal_cell_from_owner_v1(
    owner: &LedgerWriter,
    dataset: &DatasetSnapshotReceiptV3,
    mut profile: TerminalCellProfileV1,
    now: u64,
) -> Result<FrozenTerminalCellV1, TerminalCellError> {
    if dataset.snapshot.objective_digest != profile.objective_digest
        || profile.objective_digest.is_zero()
        || profile.run_snapshot_digest.is_zero()
        || profile.unit_profile_digest.is_zero()
        || profile.minimum_samples_per_action == 0
        || profile.minimum_samples_per_action > MAX_SOURCE_RECORDS
        || profile.action_ids.is_empty()
        || profile.action_ids.len() > 128
        || dataset.snapshot.source_record_digests.len() > MAX_SOURCE_RECORDS
    {
        return Err(TerminalCellError::Unsupported("profile/dataset bounds"));
    }
    let verifier = owner.verifier();
    if dataset.producer.scope_digest != verifier.scope_digest()
        || dataset.producer.authority_epoch != verifier.authority_epoch()
        || dataset.snapshot.objective_digest != verifier.objective_digest()
    {
        return Err(TerminalCellError::Unsupported("dataset owner context"));
    }
    if dataset.snapshot.pending_outcomes != 0
        || dataset.snapshot.censored_outcomes != 0
        || dataset.snapshot.outcome_watermark > now
    {
        return Err(TerminalCellError::Unsupported("terminal dataset frontier"));
    }
    let frontier = owner.witness_frontier()?.anchor;
    if dataset.snapshot.eligible_frontier > frontier.sequence
        || (dataset.snapshot.eligible_frontier == frontier.sequence
            && dataset.snapshot.ledger_head_digest != frontier.chain_digest)
    {
        return Err(TerminalCellError::Unsupported("dataset owner frontier"));
    }
    profile.action_ids.sort();
    if profile.action_ids.windows(2).any(|pair| pair[0] == pair[1]) {
        return Err(TerminalCellError::Unsupported("duplicate action"));
    }
    let frozen: BTreeSet<_> = dataset
        .snapshot
        .source_record_digests
        .iter()
        .copied()
        .collect();
    let mut found = BTreeSet::new();
    let mut decisions = BTreeMap::new();
    let mut outcomes = BTreeMap::new();
    for record in owner.read_dataset_records(dataset, now)? {
        if !frozen.contains(&record.event_digest) {
            continue;
        }
        if record.sequence.get() > dataset.snapshot.eligible_frontier
            || (record.sequence.get() == dataset.snapshot.eligible_frontier
                && record.chain_digest != dataset.snapshot.ledger_head_digest)
        {
            return Err(TerminalCellError::Unsupported(
                "source outside dataset frontier",
            ));
        }
        found.insert(record.event_digest);
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                let mut actions = value.candidate_ids.clone();
                actions.sort();
                if value.objective_digest != profile.objective_digest
                    || value.run_snapshot_digest != profile.run_snapshot_digest
                    || actions != profile.action_ids
                {
                    return Err(TerminalCellError::Unsupported(
                        "heterogeneous state/objective/action set",
                    ));
                }
                if decisions
                    .insert(value.episode_id.clone(), value.clone())
                    .is_some()
                {
                    return Err(TerminalCellError::Unsupported("duplicate episode decision"));
                }
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if value.terminality != AuthenticatedOutcomeTerminality::Terminal
                    || value.value.is_none()
                    || value.unit_profile_digest != profile.unit_profile_digest
                    || value.finalized_at.is_none()
                    || value.finalized_at.is_some_and(|at| at > now)
                    || value.latest_observable_at > dataset.snapshot.outcome_watermark
                {
                    return Err(TerminalCellError::Unsupported(
                        "nonterminal or different-unit target",
                    ));
                }
                if outcomes
                    .insert(
                        value.episode_id.clone(),
                        (value.clone(), record.event_digest),
                    )
                    .is_some()
                {
                    return Err(TerminalCellError::Unsupported(
                        "multiple active outcome heads",
                    ));
                }
            }
            // The frozen owner provenance may include additional causal facts.
            // They stay bound by the exact dataset but do not invent targets.
            _ => {}
        }
    }
    if found != frozen || decisions.is_empty() || decisions.len() != outcomes.len() {
        return Err(TerminalCellError::Unsupported("incomplete owner evidence"));
    }
    let mut samples = Vec::with_capacity(outcomes.len());
    for (episode, (outcome, evidence_digest)) in outcomes {
        let decision = decisions
            .get(&episode)
            .ok_or(TerminalCellError::Unsupported("orphan outcome"))?;
        samples.push(TabularOperatorSampleV1 {
            sample_id: outcome.record_id,
            sensor_id: profile.sensor_id.clone(),
            action_id: decision.selected_candidate_id.clone(),
            target: outcome
                .value
                .ok_or(TerminalCellError::Unsupported("missing target"))?,
            evidence_digest,
        });
    }
    let mut bytes = b"hepta.terminal-cell.profile.v1\0".to_vec();
    bytes.extend_from_slice(profile.run_snapshot_digest.as_array());
    bytes.extend_from_slice(profile.unit_profile_digest.as_array());
    bytes.extend_from_slice(&(profile.minimum_samples_per_action as u64).to_be_bytes());
    for id in std::iter::once(&profile.sensor_id).chain(profile.action_ids.iter()) {
        bytes.extend_from_slice(&(id.as_str().len() as u64).to_be_bytes());
        bytes.extend_from_slice(id.as_str().as_bytes());
    }
    let profile_digest = Digest32::of_bytes(&bytes);
    let plan = TabularOperatorPlanV1 {
        artifact_id: profile.artifact_id,
        producer_id: profile.producer_id,
        generation: profile.generation,
        objective_digest: profile.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        sensor_core_digest: profile.run_snapshot_digest,
        training_profile_digest: profile_digest,
        minimum_samples_per_cell: profile.minimum_samples_per_action,
        sensor_ids: vec![profile.sensor_id],
        action_ids: profile.action_ids,
        samples,
    };
    Ok(FrozenTerminalCellV1 {
        plan,
        dataset: dataset.clone(),
        trust_digest: verifier.trust_digest(),
        admitted_at: now,
        signed_freeze: None,
    })
}

/// Authenticate an evaluator's exact freeze request and derive the complete
/// dataset through its owner before constructing the opaque terminal plan.
/// Unlike the compatibility V1 receipt boundary, this entry point never accepts
/// caller-supplied source membership, metadata or an asserted receipt producer.
pub fn freeze_terminal_cell_from_signed_owner_v2(
    owner: &LedgerWriter,
    plan: DatasetFreezePlanV2,
    evidence: &SignedLearningEvidenceV1,
    profile: TerminalCellProfileV1,
    now: u64,
) -> Result<FrozenTerminalCellV1, TerminalCellError> {
    // Retain the exact canonical attested bytes. Re-deriving them from a later
    // head during fitting would silently substitute a different frozen cut.
    let payload = dataset_freeze_signing_payload_v2(&owner.snapshot()?, &plan)?;
    let dataset = owner.freeze_dataset(plan, evidence, now)?;
    let mut frozen = freeze_terminal_cell_from_owner_v1(owner, &dataset, profile, now)?;
    frozen.signed_freeze = Some(SignedTerminalFreezeV2 {
        evidence: evidence.clone(),
        payload,
    });
    Ok(frozen)
}

pub fn fit_terminal_cell_from_owner_v1(
    owner: &LedgerWriter,
    frozen: FrozenTerminalCellV1,
    now: u64,
) -> Result<TabularOperatorArtifactV1, TerminalCellError> {
    // Correction, withdrawal or changed trust between freeze and fitting
    // rejects the candidate rather than quietly training on a stale dataset.
    if frozen.trust_digest != owner.verifier().trust_digest() {
        return Err(TerminalCellError::Unsupported(
            "owner trust changed since freeze",
        ));
    }
    if now < frozen.admitted_at {
        return Err(TerminalCellError::Unsupported("terminal dataset frontier"));
    }
    if let Some(attestation) = &frozen.signed_freeze {
        // An immutable trust digest can contain a scheduled revocation, and
        // evidence may expire before the producer credential. Recheck both at
        // the final fit boundary even when no trust rotation has occurred.
        owner
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &attestation.evidence,
                &attestation.payload,
                now,
            )
            .map_err(ProductionLedgerError::from)?;
    }
    owner.revalidate_dataset_snapshot(&frozen.dataset, now)?;
    fit_tabular_operator_strict_v2(frozen.plan).map_err(TerminalCellError::Fit)
}
