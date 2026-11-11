//! Original signed ledger Dataset -> sealed ordinary Circuit inputs -> Q24 rows.
//! This narrow profile reads no excluded-episode labels. The exclusion list is
//! not a scientific preregistration, hidden holdout or independent B guarantee.
//! The original Dataset must contain exactly this training partition; mixing
//! excluded or unrelated episodes is rejected, not filtered after the signature.
//! A row target is the observed terminal value under the frozen source policy.
//! It is not a counterfactual action value, advantage or evidence of policy gain.
//! No signer, label, source owner, trainer, selected version or authority is created.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerWitnessFrontier;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AgentdIdentity;
use crate::CellQ24TrainingBatchV1;
use crate::CellQ24TrainingErrorV1;
use crate::CellQ24TrainingSampleV1;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::cell_composed_q24::codec;
use crate::circuit_learning_run_id_v1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24DatasetErrorV1 {
    #[error("original Q24 Dataset binding: {0}")]
    Binding(&'static str),
    #[error("original Q24 Dataset ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original Q24 Dataset source: {0}")]
    Source(#[from] CircuitTaskErrorV1),
    #[error("original Q24 Dataset batch: {0}")]
    Batch(#[from] CellQ24TrainingErrorV1),
}
type Error = OriginalCellQ24DatasetErrorV1;

/// Fixed before signing the Dataset freeze. IDs are strictly sorted and disjoint;
/// rows follow original Decision sequence, never hash order or target quality.
/// The original Observer must sign the exact source publication as its Outcome
/// support. Older support profiles are rejected, never silently reinterpreted.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24DatasetEpisodeV1 {
    pub episode_id: StableId,
    /// Exact original signed Decision fields; their existing digest profiles
    /// are preserved. They are not recomputed from a different RunStart type.
    pub run_snapshot_digest: Digest32,
    pub decision_support_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24DatasetProfileV1 {
    /// Learning principal asserted by the original Evaluator's signed freeze.
    /// This is an explicit association with the source's opaque principal_digest,
    /// never an identity inferred by hashing or decoding that digest.
    pub principal_id: StableId,
    pub agent_id: AgentId,
    pub cell_id: StableId,
    pub principal_digest: Digest32,
    pub ledger_binding: Digest32,
    pub evidence_trust_digest: Digest32,
    pub objective_digest: Digest32,
    pub selected_bundle: Digest32,
    pub outcome_unit_profile: Digest32,
    pub input_width: u16,
    pub training_episodes: Vec<CellQ24DatasetEpisodeV1>,
    pub excluded_episodes: Vec<StableId>,
}

impl CellQ24DatasetProfileV1 {
    pub fn digest(&self) -> Result<Digest32, Error> {
        if !(1..=64).contains(&self.input_width)
            || !(1..=64).contains(&self.training_episodes.len())
            || self.excluded_episodes.len() > 64
            || self
                .training_episodes
                .windows(2)
                .any(|pair| pair[0].episode_id >= pair[1].episode_id)
            || self
                .excluded_episodes
                .windows(2)
                .any(|pair| pair[0] >= pair[1])
            || self.training_episodes.iter().any(|row| {
                row.run_snapshot_digest.is_zero()
                    || row.decision_support_digest.is_zero()
                    || self
                        .excluded_episodes
                        .binary_search(&row.episode_id)
                        .is_ok()
            })
        {
            return Err(Error::Binding(
                "bounded canonical training/excluded partition",
            ));
        }
        let mut bytes = b"hepta.agentd.original-q24-dataset.v1\0HQ24I001;terminal-Q32/256-toward-zero;reject-outside-eight;original-decision-order;no-missing-label-imputation".to_vec();
        push_text(&mut bytes, self.principal_id.as_str());
        push_text(&mut bytes, self.agent_id.as_str());
        push_text(&mut bytes, self.cell_id.as_str());
        for digest in [
            self.principal_digest,
            self.ledger_binding,
            self.evidence_trust_digest,
            self.objective_digest,
            self.selected_bundle,
            self.outcome_unit_profile,
        ] {
            if digest.is_zero() {
                return Err(Error::Binding("nonzero frozen identity"));
            }
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.input_width.to_be_bytes());
        bytes.extend_from_slice(&(self.training_episodes.len() as u16).to_be_bytes());
        for row in &self.training_episodes {
            push_text(&mut bytes, row.episode_id.as_str());
            bytes.extend_from_slice(row.run_snapshot_digest.as_array());
            bytes.extend_from_slice(row.decision_support_digest.as_array());
        }
        bytes.extend_from_slice(&(self.excluded_episodes.len() as u16).to_be_bytes());
        for id in &self.excluded_episodes {
            push_text(&mut bytes, id.as_str());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Sealed result of actual ledger/source reads. Retain this object with the
/// original training job and revalidate before claim and after fit/readback.
/// A raw batch is computation material; it is never source or adoption authority.
pub struct OriginalCellQ24DatasetV1 {
    profile: CellQ24DatasetProfileV1,
    dataset: DatasetSnapshotReceiptV3,
    evidence: SignedLearningEvidenceV1,
    freeze_payload: Vec<u8>,
    batch: CellQ24TrainingBatchV1,
    publications: Vec<CircuitTaskSourcePublicationV1>,
}

impl OriginalCellQ24DatasetV1 {
    pub fn freeze<W: AnchorWitnessStore>(
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<W>,
        identity: &AgentdIdentity,
        profile: CellQ24DatasetProfileV1,
        plan: DatasetFreezePlanV2,
        evidence: SignedLearningEvidenceV1,
    ) -> Result<Self, Error> {
        let before = current_ledger(ledger, identity, &profile)?;
        if plan.objective_digest != profile.objective_digest
            || plan.inclusion_policy_digest != profile.digest()?
        {
            return Err(Error::Binding("original signed extraction profile"));
        }
        let freeze_payload = dataset_freeze_signing_payload_v2(&ledger.snapshot()?, &plan)?;
        let dataset = LedgerWriter::freeze_dataset(ledger, plan, &evidence, now()?)?;
        let (batch, publications) = collect(ledger, source, identity, &profile, &dataset)?;
        if current_ledger(ledger, identity, &profile)? != before {
            return Err(Error::Binding("original ledger frontier changed"));
        }
        let material = Self {
            profile,
            dataset,
            evidence,
            freeze_payload,
            batch,
            publications,
        };
        material.revalidate(ledger, source, identity)?;
        Ok(material)
    }

    pub fn profile(&self) -> &CellQ24DatasetProfileV1 {
        &self.profile
    }
    pub fn dataset(&self) -> &DatasetSnapshotReceiptV3 {
        &self.dataset
    }
    pub fn batch(&self) -> &CellQ24TrainingBatchV1 {
        &self.batch
    }

    /// This narrow profile includes the triggering task in its training partition.
    /// Match its existing run and completion identity; never infer a trigger from
    /// a shared objective or accept another task's completed-receipt claim.
    pub(crate) fn require_request_source(
        &self,
        run_id: &StableId,
        completed_task_receipt: Digest32,
    ) -> Result<(), Error> {
        if !self.publications.iter().any(|publication| {
            &publication.input().scope.run_id == run_id
                && publication
                    .history_digest()
                    .as_str()
                    .parse::<Digest32>()
                    .ok()
                    == Some(completed_task_receipt)
        }) {
            return Err(Error::Binding("original triggering task and completion"));
        }
        Ok(())
    }

    /// Re-read every original source and current active ledger record. A revoked,
    /// corrected, missing or changed source is an error; it is never NoUpdate.
    /// This observes successive owner cuts, not an atomic cross-owner snapshot.
    pub fn revalidate<W: AnchorWitnessStore>(
        &self,
        ledger: &LedgerWriter,
        source: &CircuitTaskSourceReadbackV1<W>,
        identity: &AgentdIdentity,
    ) -> Result<(), Error> {
        let before = current_ledger(ledger, identity, &self.profile)?;
        let signed = ledger
            .verifier()
            .verify(
                LearningEvidenceRoleV1::Evaluator,
                &self.evidence,
                &self.freeze_payload,
                now()?,
            )
            .map_err(|_| Error::Binding("current original Dataset freeze signature"))?;
        if signed.principal() != &self.dataset.producer {
            return Err(Error::Binding("original Dataset producer"));
        }
        let (batch, publications) =
            collect(ledger, source, identity, &self.profile, &self.dataset)?;
        if batch.encoded() != self.batch.encoded()
            || publications != self.publications
            || current_ledger(ledger, identity, &self.profile)? != before
        {
            return Err(Error::Binding("original Dataset material changed"));
        }
        Ok(())
    }
}

fn collect<W: AnchorWitnessStore>(
    ledger: &LedgerWriter,
    source: &CircuitTaskSourceReadbackV1<W>,
    identity: &AgentdIdentity,
    profile: &CellQ24DatasetProfileV1,
    dataset: &DatasetSnapshotReceiptV3,
) -> Result<(CellQ24TrainingBatchV1, Vec<CircuitTaskSourcePublicationV1>), Error> {
    if dataset.snapshot.objective_digest != profile.objective_digest
        || dataset.inclusion_policy_digest != profile.digest()?
        || dataset.snapshot.pending_outcomes != 0
        || dataset.snapshot.censored_outcomes != 0
    {
        return Err(Error::Binding("complete terminal training Dataset"));
    }
    let records = LedgerWriter::read_dataset_records(ledger, dataset, now()?)?;
    let training: BTreeMap<_, _> = profile
        .training_episodes
        .iter()
        .map(|row| (row.episode_id.clone(), row))
        .collect();
    let mut decisions = Vec::new();
    let mut outcomes = BTreeMap::new();
    let mut seen = BTreeSet::new();
    for record in records {
        match &record.event {
            LedgerEvent::AuthenticatedDecisionV2(value) => {
                if !training.contains_key(&value.episode_id)
                    || !seen.insert(value.episode_id.clone())
                {
                    return Err(Error::Binding("unexpected or duplicate training Decision"));
                }
                decisions.push(value);
            }
            LedgerEvent::AuthenticatedOutcomeV2(value) => {
                if !training.contains_key(&value.episode_id)
                    || outcomes.insert(value.episode_id.clone(), value).is_some()
                {
                    return Err(Error::Binding("unexpected or duplicate training Outcome"));
                }
            }
            // Credits remain in the signed Dataset identity; this profile never
            // substitutes a credit allocation for the original terminal outcome.
            LedgerEvent::CreditBatchV2(value) if training.contains_key(&value.episode_id) => {}
            _ => return Err(Error::Binding("unsupported Dataset record profile")),
        }
    }
    if decisions.len() != training.len() || outcomes.len() != training.len() {
        return Err(Error::Binding(
            "missing original training Decision or Outcome",
        ));
    }
    let mut samples = Vec::with_capacity(decisions.len());
    let mut publications = Vec::with_capacity(decisions.len());
    for decision in decisions {
        let run = circuit_learning_run_id_v1(ledger, &identity.agent_id, &decision.episode_id)
            .map_err(|_| Error::Binding("original episode execution identity"))?;
        if decision.record_id != run
            || decision.objective_digest != profile.objective_digest
            || decision.policy_digest != profile.selected_bundle
            || decision.run_snapshot_digest != training[&decision.episode_id].run_snapshot_digest
            || decision.support_digest != training[&decision.episode_id].decision_support_digest
        {
            return Err(Error::Binding("original Decision run/objective/model"));
        }
        let published = source.read_run_publication(identity, &run)?;
        let input = published.input();
        if input.scope.agent_id.as_str() != profile.agent_id.as_str()
            || input.scope.cell_id != profile.cell_id
            || input.scope.principal_digest != profile.principal_digest
            || input.scope.run_id != run
            || input.objective_digest != profile.objective_digest
            || published.original_record().snapshot.run_id != run
            || published.original_record().snapshot.objective_digest != profile.objective_digest
            || published.bundle_digest() != profile.selected_bundle
        {
            return Err(Error::Binding(
                "original sealed source scope/model/snapshot",
            ));
        }
        require_selection(
            &published,
            &decision.selected_candidate_id,
            &decision.candidate_ids,
        )?;
        let outcome = outcomes[&decision.episode_id];
        if outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
            || outcome.observed_at.is_none()
            || outcome.finalized_at.is_none()
            || outcome.censoring_reason.is_some()
            || outcome.unit_profile_digest != profile.outcome_unit_profile
            || outcome.support_digest != published.publication_digest()
        {
            return Err(Error::Binding("original terminal Outcome support/unit"));
        }
        let raw = outcome
            .value
            .ok_or(Error::Binding("missing terminal label"))?
            .raw();
        let target = target_q24(raw)?;
        let input = codec::input(&input.observation, usize::from(profile.input_width))
            .map_err(|_| Error::Binding("original HQ24I001 input"))?;
        samples.push(CellQ24TrainingSampleV1 { input, target });
        publications.push(published);
    }
    Ok((
        CellQ24TrainingBatchV1::new(dataset.snapshot.dataset_digest, samples)?,
        publications,
    ))
}

fn current_ledger(
    ledger: &LedgerWriter,
    identity: &AgentdIdentity,
    profile: &CellQ24DatasetProfileV1,
) -> Result<LedgerWitnessFrontier, Error> {
    profile.digest()?;
    if identity.agent_id != profile.agent_id
        || ledger.binding_digest() != profile.ledger_binding
        || ledger.verifier().trust_digest() != profile.evidence_trust_digest
        || ledger.verifier().objective_digest() != profile.objective_digest
    {
        return Err(Error::Binding("original ledger/agent/trust/objective"));
    }
    let witness = ledger.witness_frontier()?;
    if witness.anchor.sequence > 4096 {
        return Err(Error::Binding("ledger materialization bound"));
    }
    let snapshot = ledger.snapshot()?;
    if snapshot.records().last().map_or(0, |r| r.sequence.get()) != witness.anchor.sequence
        || snapshot.head_digest != witness.anchor.chain_digest
    {
        return Err(Error::Binding("unacknowledged original ledger frontier"));
    }
    if let Some(checkpoint) = ledger.segmented_checkpoint()?
        && (witness.segment != Some(checkpoint.segment) || witness.sealed != checkpoint.sealed)
    {
        return Err(Error::Binding("unacknowledged original ledger segment"));
    }
    Ok(witness)
}

fn require_selection(
    published: &CircuitTaskSourcePublicationV1,
    selected: &StableId,
    candidates: &[StableId],
) -> Result<(), Error> {
    let bytes = published.output();
    let prefix = b"hepta.circuit.cell-policy-output.v1\0";
    let offset = prefix.len() + 64;
    let length = bytes
        .get(offset..offset + 4)
        .and_then(|v| <[u8; 4]>::try_from(v).ok())
        .map(u32::from_be_bytes)
        .ok_or(Error::Binding("original policy output"))? as usize;
    let allowed: BTreeSet<_> = published
        .input()
        .candidates
        .iter()
        .filter(|mask| mask.allowed)
        .map(|mask| mask.candidate_id.clone())
        .collect();
    let declared: BTreeSet<_> = candidates.iter().cloned().collect();
    if !bytes.starts_with(prefix)
        || bytes.get(prefix.len()..prefix.len() + 32)
            != Some(published.input().scope.digest().as_array())
        || bytes.get(prefix.len() + 32..offset) != Some(published.bundle_digest().as_array())
        || length != selected.as_str().len()
        || bytes.get(offset + 4..offset + 4 + selected.as_str().len())
            != Some(selected.as_str().as_bytes())
        || allowed != declared
        || declared.len() != candidates.len()
        || !allowed.contains(selected)
    {
        return Err(Error::Binding("original Cell selected candidate set"));
    }
    Ok(())
}

fn target_q24(raw: i64) -> Result<i64, Error> {
    if !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&raw) {
        return Err(Error::Binding("terminal Q32 label outside eight"));
    }
    Ok(raw / 256)
}
fn push_text(bytes: &mut Vec<u8>, text: &str) {
    bytes.extend_from_slice(&(text.len() as u32).to_be_bytes());
    bytes.extend_from_slice(text.as_bytes());
}
fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|v| v.as_secs())
        .map_err(|_| Error::Binding("original Dataset clock"))
}

#[cfg(all(test, unix))]
#[path = "cell_q24_dataset_support_tests.rs"]
pub(crate) mod test_support;

#[cfg(all(test, unix))]
#[path = "cell_q24_dataset_tests.rs"]
mod tests;
