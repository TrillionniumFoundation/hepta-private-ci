//! Authenticated, bounded projection of an original Dataset into native Q24.
//! Freeze the combined projection before signing Dataset, then materialize the
//! batch, bind SGD(batch) into the row rule, and finally freeze the Root scope.
//! This reader grants no source, signing, training or publication authority.

use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::dataset_freeze_signing_payload_v2;
use codex_hepta_learning_ledger::freeze_dataset_from_ledger;
#[cfg(target_os = "linux")]
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellDecisionReceiptV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
#[cfg(target_os = "linux")]
use codex_hepta_types::StableId;

use super::CellQ24TrainingBatchV1;
use super::CellQ24TrainingSampleV1;
use super::codec;
#[cfg(target_os = "linux")]
use crate::AgentdIdentity;
use crate::CircuitTaskSourcePublicationV1;
#[cfg(target_os = "linux")]
use crate::CircuitTaskSourceReadbackV1;
#[cfg(target_os = "linux")]
use crate::PublishedCircuitCellOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24DatasetErrorV1 {
    #[error("original Q24 Dataset binding: {0}")]
    Binding(&'static str),
    #[error("original Q24 Dataset ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original Q24 Dataset authentication: {0}")]
    Authentication(#[from] SignedEvidenceError),
}

type Error = CellQ24DatasetErrorV1;

/// A new combined policy, never a replacement for the inherited inclusion rule.
/// V1 includes every selected decision in ledger order exactly once, requires
/// one uncorrected Terminal outcome, rejects missing/censored/extra facts and
/// accepts only HQ24I001 inputs. Q32 targets divide by 256 toward zero, without
/// imputation or clipping; the raw target must already lie in [-8, 8].
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellQ24DatasetProjectionV1 {
    pub inherited_inclusion_policy: Digest32,
    pub unit_profile_digest: Digest32,
    pub baseline_bundle: Digest32,
    pub input_width: u16,
}

impl CellQ24DatasetProjectionV1 {
    pub fn inclusion_policy_digest(&self) -> Result<Digest32, Error> {
        if self.inherited_inclusion_policy.is_zero()
            || self.unit_profile_digest.is_zero()
            || self.baseline_bundle.is_zero()
            || !(1..=64).contains(&self.input_width)
        {
            return Err(Error::Binding("projection profile"));
        }
        Ok(Digest32::of_parts(&[
            b"hepta.cell.q24.dataset-projection.v1\0HQ24I001;all-decisions-in-sequence;one-terminal;no-corrections;no-imputation;no-clipping;Q32-div256-toward-zero;raw-bound-eight;rows256;ledger4096;record=run;run-snapshot=HQ24-run-start-v1;artifact-set=historical-only;model=original-cell-bundle;policy=source-output;candidate-set=ledger-sorted;policy-order=source-output;support=source-publication;deterministic-propensity-one",
            self.inherited_inclusion_policy.as_array(),
            self.unit_profile_digest.as_array(),
            self.baseline_bundle.as_array(),
            &self.input_width.to_le_bytes(),
        ]))
    }
}

/// Versioned hash of the full original RunStartSnapshot for this projection.
/// Existing ledgers using another snapshot convention require their own
/// explicitly frozen projection; a Cell request hash is not substituted.
pub fn cell_q24_dataset_run_snapshot_digest_v1(
    publication: &CircuitTaskSourcePublicationV1,
) -> Digest32 {
    let snapshot = &publication.original_record().snapshot;
    Digest32::of_parts(&[
        b"hepta.cell.q24.dataset-run-start-snapshot.v1\0",
        &(snapshot.run_id.as_str().len() as u64).to_le_bytes(),
        snapshot.run_id.as_str().as_bytes(),
        snapshot.objective_digest.as_array(),
        snapshot.hard_constraint_digest.as_array(),
        snapshot.preference_state_digest.as_array(),
        snapshot.model_tuple_digest.as_array(),
        snapshot.prompt_registry_digest.as_array(),
        snapshot.artifact_set_digest.as_array(),
        &snapshot.authority_epoch.to_le_bytes(),
        &snapshot.generation.to_le_bytes(),
        snapshot.fence_digest.as_array(),
    ])
}

trait OriginalTask: Send + Sync {
    fn read(&self) -> Result<CircuitTaskSourcePublicationV1, Error>;
}

#[cfg(target_os = "linux")]
struct TaskSource<W: AnchorWitnessStore> {
    source: CircuitTaskSourceReadbackV1<W>,
    identity: AgentdIdentity,
    run_id: StableId,
}

#[cfg(target_os = "linux")]
impl<W: AnchorWitnessStore + Send> OriginalTask for TaskSource<W> {
    fn read(&self) -> Result<CircuitTaskSourcePublicationV1, Error> {
        self.source
            .read_run_publication(&self.identity, &self.run_id)
            .map_err(|_| Error::Binding("original task source withdrawn or unavailable"))
    }
}

/// Captured only from the original committed Cell and its sealed task source.
/// Cloning retains the very same live source reader; no caller vectors enter.
#[derive(Clone)]
pub struct CellQ24DatasetTaskV1 {
    source: Arc<dyn OriginalTask>,
    publication: CircuitTaskSourcePublicationV1,
    decision: CellDecisionReceiptV1,
}

impl CellQ24DatasetTaskV1 {
    /// The original published Cell capability is currently installed on Linux.
    #[cfg(target_os = "linux")]
    pub fn capture(
        source: CircuitTaskSourceReadbackV1<impl AnchorWitnessStore + Send + 'static>,
        cell: &PublishedCircuitCellOwnerV1<impl AnchorWitnessStore>,
        identity: AgentdIdentity,
        run_id: StableId,
    ) -> Result<Self, Error> {
        let source = Arc::new(TaskSource {
            source,
            identity,
            run_id,
        });
        let publication = source.read()?;
        let decision = cell
            .committed(&publication)
            .map_err(|_| Error::Binding("original committed task decision"))?;
        if source.read()? != publication {
            return Err(Error::Binding("task source changed while capturing"));
        }
        Ok(Self {
            source,
            publication,
            decision,
        })
    }

    fn require_current(&self) -> Result<(), Error> {
        // Historical execution expiry and an advanced model CURRENT do not
        // revoke completed experience. The original source's live withdrawal
        // witness and the current signed Dataset authorization govern reuse.
        if self.source.read()? != self.publication {
            return Err(Error::Binding("original task publication changed"));
        }
        Ok(())
    }
}

pub(super) struct OriginalDataset {
    ledger: Arc<Mutex<LedgerWriter>>,
    frozen: LedgerSnapshot,
    receipt: DatasetSnapshotReceiptV3,
    evidence: SignedLearningEvidenceV1,
    projection: CellQ24DatasetProjectionV1,
    tasks: Vec<CellQ24DatasetTaskV1>,
}

impl CellQ24TrainingBatchV1 {
    /// The host supplies original owners and their existing signed freeze.
    /// HQ24T002 retains their private read capability, including across Clone.
    /// The legacy new() constructor continues to emit only HQ24T001.
    pub fn from_original_dataset(
        ledger: Arc<Mutex<LedgerWriter>>,
        frozen: LedgerSnapshot,
        receipt: DatasetSnapshotReceiptV3,
        evidence: SignedLearningEvidenceV1,
        projection: CellQ24DatasetProjectionV1,
        tasks: Vec<CellQ24DatasetTaskV1>,
    ) -> Result<Self, Error> {
        let source = Arc::new(OriginalDataset {
            ledger,
            frozen,
            receipt,
            evidence,
            projection,
            tasks,
        });
        let mut batch = source.materialize()?;
        batch.source = Some(source);
        Ok(batch)
    }
}

impl OriginalDataset {
    pub(super) fn require_baseline(&self, baseline: Digest32) -> Result<(), Error> {
        if baseline != self.projection.baseline_bundle {
            return Err(Error::Binding("original projection baseline"));
        }
        Ok(())
    }

    pub(super) fn require_batch(&self, expected: &CellQ24TrainingBatchV1) -> Result<(), Error> {
        let current = self.materialize()?;
        if current.encoded != expected.encoded || current.digest != expected.digest {
            return Err(Error::Binding("original materialization changed"));
        }
        Ok(())
    }

    fn materialize(&self) -> Result<CellQ24TrainingBatchV1, Error> {
        let profile = self.projection.inclusion_policy_digest()?;
        if !(1..=256).contains(&self.tasks.len())
            || self.frozen.records().len() > 4096
            || self.receipt.snapshot.source_record_digests.len() > 512
            || self.receipt.inclusion_policy_digest != profile
            || self.receipt.snapshot.pending_outcomes != 0
            || self.receipt.snapshot.censored_outcomes != 0
        {
            return Err(Error::Binding("bounded complete Dataset and projection"));
        }
        let observed_at = now()?;
        let ledger = self
            .ledger
            .lock()
            .map_err(|_| Error::Binding("ledger lock"))?;
        let frontier = ledger.witness_frontier()?;
        if frontier.anchor.sequence > 4096 {
            return Err(Error::Binding("bounded original ledger"));
        }
        let current = ledger.snapshot()?;
        if current.records().len() as u64 != frontier.anchor.sequence
            || current.head_digest != frontier.anchor.chain_digest
            || !current.records().starts_with(self.frozen.records())
        {
            return Err(Error::Binding("original frozen ledger prefix"));
        }
        let plan = DatasetFreezePlanV2 {
            snapshot_id: self.receipt.snapshot.snapshot_id.clone(),
            objective_digest: self.receipt.snapshot.objective_digest,
            inclusion_policy_digest: profile,
        };
        let payload = dataset_freeze_signing_payload_v2(&self.frozen, &plan)?;
        let verified = ledger.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.evidence,
            &payload,
            observed_at,
        )?;
        if freeze_dataset_from_ledger(
            &self.frozen,
            plan,
            verified.principal().clone(),
            observed_at,
        )? != self.receipt
        {
            return Err(Error::Binding("authenticated original Dataset freeze"));
        }
        let records = ledger.read_dataset_records(&self.receipt, observed_at)?;
        let selected: Vec<_> = records.iter().map(|r| r.event_digest).collect();
        let mut decisions = Vec::new();
        let mut outcomes = BTreeMap::new();
        for record in records {
            match &record.event {
                LedgerEvent::AuthenticatedDecisionV2(value) => decisions.push((record, value)),
                LedgerEvent::AuthenticatedOutcomeV2(value) => {
                    if outcomes
                        .insert(&value.episode_id, (record, value))
                        .is_some()
                    {
                        return Err(Error::Binding("ambiguous outcome per decision"));
                    }
                }
                _ => return Err(Error::Binding("unsupported Dataset event")),
            }
        }
        if decisions.len() != self.tasks.len() || outcomes.len() != decisions.len() {
            return Err(Error::Binding("one source and outcome per decision"));
        }
        let mut tasks = BTreeMap::new();
        for task in &self.tasks {
            task.require_current()?;
            if tasks
                .insert(&task.publication.input().scope.run_id, task)
                .is_some()
            {
                return Err(Error::Binding("duplicate original task"));
            }
        }
        let mut samples = Vec::with_capacity(decisions.len());
        let mut transcript = profile.as_array().to_vec();
        for (record, decision) in decisions {
            let task = tasks
                .remove(&decision.record_id)
                .ok_or(Error::Binding("original decision run"))?;
            let (outcome_record, outcome) = outcomes
                .remove(&decision.episode_id)
                .ok_or(Error::Binding("original Terminal outcome"))?;
            let publication = &task.publication;
            let original = &task.decision;
            // The ledger canonicalizes candidate IDs; the source output still
            // binds the original policy order and its exact one-hot weights.
            let mut original_candidates = original
                .policy
                .iter()
                .map(|entry| entry.candidate_id.clone())
                .collect::<Vec<_>>();
            original_candidates.sort();
            if decision.run_snapshot_digest != cell_q24_dataset_run_snapshot_digest_v1(publication)
                || decision.objective_digest != publication.input().objective_digest
                || decision.objective_digest != self.receipt.snapshot.objective_digest
                || decision.policy_digest != Digest32::of_bytes(publication.output())
                || decision.support_digest != publication.publication_digest()
                || outcome.support_digest != publication.publication_digest()
                || publication.bundle_digest() != self.projection.baseline_bundle
                || decision.selected_candidate_id != original.selected_candidate
                || decision.selected_propensity != ProbabilityQ32::ONE
                || original.policy.iter().any(|p| {
                    p.probability_ppm
                        != if p.candidate_id == original.selected_candidate {
                            1_000_000
                        } else {
                            0
                        }
                })
                || !original
                    .policy
                    .iter()
                    .any(|p| p.candidate_id == original.selected_candidate && p.allowed)
                || decision.candidate_ids != original_candidates
                || outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
                || outcome.correction_predecessor.is_some()
                || outcome.unit_profile_digest != self.projection.unit_profile_digest
                || outcome_record.sequence <= record.sequence
            {
                return Err(Error::Binding(
                    "exact task, model, decision, unit and outcome",
                ));
            }
            let raw = outcome.value.ok_or(Error::Binding("missing target"))?.raw();
            if !(-(8_i64 << 32)..=(8_i64 << 32)).contains(&raw) {
                return Err(Error::Binding("target range before conversion"));
            }
            let input = codec::input(
                &publication.input().observation,
                usize::from(self.projection.input_width),
            )
            .map_err(|_| Error::Binding("original HQ24I001 input"))?;
            samples.push(CellQ24TrainingSampleV1 {
                input,
                target: raw / 256,
            });
            for digest in [
                record.event_digest,
                outcome_record.event_digest,
                publication.publication_digest(),
            ] {
                transcript.extend_from_slice(digest.as_array());
            }
        }
        let mut batch = CellQ24TrainingBatchV1::new(self.receipt.snapshot.dataset_digest, samples)
            .map_err(|_| Error::Binding("bounded native samples"))?;
        batch.encoded[..8].copy_from_slice(b"HQ24T002");
        batch.encoded.extend_from_slice(profile.as_array());
        batch
            .encoded
            .extend_from_slice(Digest32::of_bytes(&transcript).as_array());
        batch.digest = Digest32::of_bytes(&batch.encoded);
        // Re-enter both original owners after projection. The process mutex
        // does not replace their independent currentness/witness contracts.
        for task in &self.tasks {
            task.require_current()?;
        }
        if ledger.witness_frontier()? != frontier
            || ledger.snapshot()? != current
            || ledger
                .read_dataset_records(&self.receipt, now()?)?
                .iter()
                .map(|r| r.event_digest)
                .collect::<Vec<_>>()
                != selected
        {
            return Err(Error::Binding("original ledger changed during projection"));
        }
        ledger.verifier().verify(
            LearningEvidenceRoleV1::Evaluator,
            &self.evidence,
            &payload,
            now()?,
        )?;
        Ok(batch)
    }
}

fn now() -> Result<u64, Error> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Binding("system clock"))?
        .as_secs())
}
