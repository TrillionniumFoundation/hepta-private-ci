//! Original ordinary-task inputs and authenticated terminal outcomes -> Q24.
//! This restricted profile materializes one source run and retains every active
//! Decision/Outcome/optional Credit source in the original signed Dataset cut.
//! It produces no signature, training claim, independent evaluation or adoption.
//! The v3 inclusion policy pins the Decision to the input's NDU snapshot and
//! exact Source policy/publication. Outcome support remains the Observer's
//! independently signed measurement reference. Legacy freezes need a separate
//! authorization; full-RunStart records are never reinterpreted as NDU.

use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_ledger::AuthenticatedOutcomeTerminality;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LearningEpisodeV1;
use codex_hepta_learning_ledger::LearningProtocolError;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::ProductionLedgerError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::encode_learning_episode_v1;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AgentdIdentity;
use crate::CellQ24PrivateHeadV1;
use crate::CellQ24SgdRuleV1;
use crate::CellQ24SingleHeadTrainingPlanV1;
use crate::CellQ24TrainingBatchV1;
use crate::CellQ24TrainingErrorV1;
use crate::CellQ24TrainingPlanErrorV1;
use crate::CellQ24TrainingSampleV1;
use crate::CircuitTaskErrorV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::LoadedCellQ24ModelV1;
use crate::cell_composed_q24::codec;
use crate::circuit_credit::circuit_learning_run_id_v1;

#[derive(Debug, thiserror::Error)]
pub enum CellQ24DatasetErrorV1 {
    #[error("original Q24 dataset binding: {0}")]
    Binding(&'static str),
    #[error("original TaskSource: {0}")]
    Source(#[from] CircuitTaskErrorV1),
    #[error("original learning ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original episode: {0}")]
    Episode(#[from] LearningProtocolError),
    #[error("learning request: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Q24 input: {0}")]
    Input(#[from] CellGenerationErrorV2),
    #[error("Q24 training material: {0}")]
    Training(#[from] CellQ24TrainingErrorV1),
    #[error("Q24 training plan: {0}")]
    Plan(#[from] CellQ24TrainingPlanErrorV1),
}

/// Caller-declared semantics must be pinned by the original freeze signature.
/// The unit is not inferred from a model response or from the observed reward.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CellQ24DatasetRuleV1 {
    pub head: CellQ24PrivateHeadV1,
    pub unit_profile_digest: Digest32,
}

impl CellQ24DatasetRuleV1 {
    pub fn inclusion_policy_digest(
        &self,
        initial: &LearningIterationSnapshotV1,
    ) -> Result<Digest32, CellQ24DatasetErrorV1> {
        let coordinator = LearningIterationCoordinatorV1::from_snapshot(initial.clone())?;
        if coordinator.next_stage() != Some(LearningIterationStageV1::Experience)
            || self.unit_profile_digest.is_zero()
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "original empty iteration and unit",
            ));
        }
        let (tag, index) = match self.head {
            CellQ24PrivateHeadV1::Drive { index } => (1_u8, index),
            CellQ24PrivateHeadV1::Prediction { index } => (2_u8, index),
        };
        Ok(Digest32::of_parts(&[
            b"hepta.cell.q24.original-dataset.v3\0single-run;HQ24I001;active-authenticated-terminal-outcome;optional-same-outcome-credit-lineage;Q32-exact-divide-256;reject-outside-eight;no-output-label;run-snapshot=source-input-ndu;policy=source-output;decision-support=source-publication;outcome-support=observer-measurement;candidate-set=ledger-sorted;policy-order=source-output;deterministic-propensity-one;observed-at-or-after-ceil-source-admission;finalized-at-or-after-window-end",
            initial.head_digest.as_array(),
            self.unit_profile_digest.as_array(),
            &[tag],
            &index.to_le_bytes(),
        ]))
    }
}

/// Borrow original owners. Construction creates no claim, file or authority.
pub struct CellQ24DatasetReaderV1<'a, W: AnchorWitnessStore> {
    source: &'a CircuitTaskSourceReadbackV1<W>,
    identity: &'a AgentdIdentity,
    ledger: &'a mut LedgerWriter,
}

impl<'a, W: AnchorWitnessStore> CellQ24DatasetReaderV1<'a, W> {
    pub fn new(
        source: &'a CircuitTaskSourceReadbackV1<W>,
        identity: &'a AgentdIdentity,
        ledger: &'a mut LedgerWriter,
    ) -> Self {
        Self {
            source,
            identity,
            ledger,
        }
    }

    /// No source subset or target can be supplied. The original Evaluator
    /// signature must cover the complete current source set and this request's
    /// frozen mapping rule. freeze_dataset is a pure receipt derivation: this
    /// reader neither signs, reserves a snapshot id nor advances either owner.
    /// Production time comes only from the system clock, including a fresh
    /// expiry/signature check after the original owners' physical reads.
    pub fn read_current(
        &mut self,
        initial: &LearningIterationSnapshotV1,
        baseline: &LoadedCellQ24ModelV1,
        rule: CellQ24DatasetRuleV1,
        plan: DatasetFreezePlanV2,
        freeze_evidence: &SignedLearningEvidenceV1,
    ) -> Result<OriginalCellQ24DatasetV1, CellQ24DatasetErrorV1> {
        self.read_current_with_clock(initial, baseline, rule, plan, freeze_evidence, || {
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .map(|elapsed| elapsed.as_secs())
                .map_err(|_| CellQ24DatasetErrorV1::Binding("system clock before Unix epoch"))
        })
    }

    /// Only the concrete original receipt owner calls this after physically
    /// reading an already completed signature journal. The original freeze,
    /// trust and both CURRENTs are still checked at fresh system time. This
    /// creates no claim, receipt or extended signature/deadline.
    pub(crate) fn read_current_for_original_receipt(
        &mut self,
        initial: &LearningIterationSnapshotV1,
        baseline: &LoadedCellQ24ModelV1,
        rule: CellQ24DatasetRuleV1,
        plan: DatasetFreezePlanV2,
        freeze_evidence: &SignedLearningEvidenceV1,
    ) -> Result<OriginalCellQ24DatasetV1, CellQ24DatasetErrorV1> {
        self.read_current_at_clock(
            initial,
            baseline,
            rule,
            plan,
            freeze_evidence,
            false,
            || {
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|elapsed| elapsed.as_secs())
                    .map_err(|_| CellQ24DatasetErrorV1::Binding("system clock before Unix epoch"))
            },
        )
    }

    // Only read_current supplies this clock in product builds. The private
    // seam lets tests model time spent in real owner reads without exposing
    // a caller-controlled time or a public test clock.
    fn read_current_with_clock(
        &mut self,
        initial: &LearningIterationSnapshotV1,
        baseline: &LoadedCellQ24ModelV1,
        rule: CellQ24DatasetRuleV1,
        plan: DatasetFreezePlanV2,
        freeze_evidence: &SignedLearningEvidenceV1,
        clock: impl FnMut() -> Result<u64, CellQ24DatasetErrorV1>,
    ) -> Result<OriginalCellQ24DatasetV1, CellQ24DatasetErrorV1> {
        self.read_current_at_clock(initial, baseline, rule, plan, freeze_evidence, true, clock)
    }

    fn read_current_at_clock(
        &mut self,
        initial: &LearningIterationSnapshotV1,
        baseline: &LoadedCellQ24ModelV1,
        rule: CellQ24DatasetRuleV1,
        plan: DatasetFreezePlanV2,
        freeze_evidence: &SignedLearningEvidenceV1,
        require_work_deadline: bool,
        mut clock: impl FnMut() -> Result<u64, CellQ24DatasetErrorV1>,
    ) -> Result<OriginalCellQ24DatasetV1, CellQ24DatasetErrorV1> {
        let started_at = clock()?;
        let policy = rule.inclusion_policy_digest(initial)?;
        let request = &initial.request;
        let head_index = match rule.head {
            CellQ24PrivateHeadV1::Drive { index } | CellQ24PrivateHeadV1::Prediction { index } => {
                index
            }
        };
        if plan.inclusion_policy_digest != policy
            || plan.objective_digest != request.envelope.objective_digest
            || initial.owners.evidence_trust_digest != self.ledger.verifier().trust_digest()
            || baseline.components() != &request.selected_bundle.components
            || usize::from(head_index) >= baseline.output_width()
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "frozen request, rule, trust or baseline",
            ));
        }
        if require_work_deadline && started_at >= request.envelope.expiry_unix_seconds {
            return Err(CellQ24DatasetErrorV1::Binding("learning request expired"));
        }
        let source = self
            .source
            .read_run_publication(self.identity, &request.source_run_id)?;
        require_source(self.identity, &source, request)?;
        let before = self.ledger.read_current_durable_snapshot()?;
        let receipt = self
            .ledger
            .freeze_dataset(plan.clone(), freeze_evidence, started_at)?;
        if receipt.snapshot.ledger_head_digest != before.head_digest
            || receipt.snapshot.pending_outcomes != 0
            || receipt.snapshot.censored_outcomes != 0
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "terminal original Dataset cut",
            ));
        }
        let records = self.ledger.read_dataset_records(&receipt, started_at)?;
        let mut actual = records
            .iter()
            .map(|record| record.event_digest)
            .collect::<Vec<_>>();
        actual.sort_unstable();
        if actual != receipt.snapshot.source_record_digests {
            return Err(CellQ24DatasetErrorV1::Binding("exact Dataset source set"));
        }
        let (episode_id, target) =
            terminal_target(&records, request, &source, rule.unit_profile_digest)?;
        let original_run =
            circuit_learning_run_id_v1(self.ledger, &self.identity.agent_id, &episode_id).map_err(
                |_| CellQ24DatasetErrorV1::Binding("original execution-before-credit profile"),
            )?;
        if request.source_run_id != original_run {
            return Err(CellQ24DatasetErrorV1::Binding(
                "original ledger-bound execution identity",
            ));
        }
        let episode = LearningEpisodeV1::from_snapshot(&before, &episode_id)?;
        let episode_digest = Digest32::of_bytes(&encode_learning_episode_v1(&episode)?);
        let input = codec::input(&source.input().observation, baseline.input_width())?;
        let batch = CellQ24TrainingBatchV1::new(
            receipt.snapshot.dataset_digest,
            vec![CellQ24TrainingSampleV1 { input, target }],
        )?;
        if batch.rows() > request.budget.maximum_dataset_rows
            || batch.encoded().len() as u64 > request.budget.maximum_dataset_bytes
        {
            return Err(CellQ24DatasetErrorV1::Binding("original Dataset budget"));
        }
        let mut signed_freeze = freeze_evidence.signing_bytes();
        signed_freeze.extend_from_slice(&freeze_evidence.signature);
        let provenance_digest = Digest32::of_parts(&[
            b"hepta.cell.q24.original-dataset-provenance.v1\0",
            initial.head_digest.as_array(),
            self.ledger.binding_digest().as_array(),
            self.ledger.trust_distribution_digest().as_array(),
            source.publication_digest().as_array(),
            before.head_digest.as_array(),
            receipt.snapshot.dataset_digest.as_array(),
            receipt.correction_cut_digest.as_array(),
            receipt.revocation_cut_digest.as_array(),
            episode_digest.as_array(),
            batch.digest().as_array(),
            policy.as_array(),
            Digest32::of_bytes(&signed_freeze).as_array(),
        ]);
        // Both calls reach the original locked data and independent witnesses.
        // A different source, withdrawal, history, or frontier cannot return a
        // previously materialized batch. Neither check repairs suspect bytes.
        if self
            .source
            .read_run_publication(self.identity, &request.source_run_id)?
            != source
            || self.ledger.read_current_durable_snapshot()? != before
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "source changed during materialization",
            ));
        }
        let fresh_now = clock()?;
        if fresh_now < started_at {
            return Err(CellQ24DatasetErrorV1::Binding(
                "system clock moved backwards",
            ));
        }
        if require_work_deadline && fresh_now >= request.envelope.expiry_unix_seconds {
            return Err(CellQ24DatasetErrorV1::Binding(
                "learning request expired during materialization",
            ));
        }
        // read_dataset_records alone does not reverify the original signature.
        // Verify the same signed plan again at fresh wall time; this cannot
        // replace issued_at, renew evidence, or authorize a different cut.
        if self
            .ledger
            .freeze_dataset(plan, freeze_evidence, fresh_now)?
            != receipt
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "signed Dataset changed during materialization",
            ));
        }
        let _ = self.ledger.read_dataset_records(&receipt, fresh_now)?;
        Ok(OriginalCellQ24DatasetV1 {
            initial_head: initial.head_digest,
            completed_task_receipt: request.completed_task_receipt,
            episode_digest,
            provenance_digest,
            head: rule.head,
            receipt,
            batch,
            #[cfg(target_os = "linux")]
            ledger_binding: self.ledger.binding_digest(),
            #[cfg(target_os = "linux")]
            trust_distribution: self.ledger.trust_distribution_digest(),
            #[cfg(target_os = "linux")]
            source_publication: source.publication_digest(),
        })
    }
}

/// Sealed original material. These observations are unsigned; their existing
/// Experience/Dataset owners must independently attest them before Training.
/// One terminal training label is not an independent B/retention evaluation.
/// This material records one successful CURRENT read. Original stage owners
/// must re-read CURRENT before training or publication; retaining this value
/// does not retain source authorization.
pub struct OriginalCellQ24DatasetV1 {
    initial_head: Digest32,
    completed_task_receipt: Digest32,
    episode_digest: Digest32,
    provenance_digest: Digest32,
    head: CellQ24PrivateHeadV1,
    receipt: DatasetSnapshotReceiptV3,
    batch: CellQ24TrainingBatchV1,
    #[cfg(target_os = "linux")]
    ledger_binding: Digest32,
    #[cfg(target_os = "linux")]
    trust_distribution: Digest32,
    #[cfg(target_os = "linux")]
    source_publication: Digest32,
}

impl OriginalCellQ24DatasetV1 {
    pub fn experience_observation(&self) -> LearningIterationObservationV1 {
        LearningIterationObservationV1::Experience {
            episode_digest: self.episode_digest,
            completed_task_receipt: self.completed_task_receipt,
        }
    }

    pub fn dataset_observation(&self) -> LearningIterationObservationV1 {
        LearningIterationObservationV1::Dataset {
            snapshot_digest: self.receipt.snapshot.dataset_digest,
            episode_digest: self.episode_digest,
            withdrawal_frontier: self.receipt.revocation_cut_digest,
            rows: self.batch.rows(),
            bytes: self.batch.encoded().len() as u64,
        }
    }

    pub fn provenance_digest(&self) -> Digest32 {
        self.provenance_digest
    }

    pub fn receipt(&self) -> &DatasetSnapshotReceiptV3 {
        &self.receipt
    }

    pub fn batch(&self) -> &CellQ24TrainingBatchV1 {
        &self.batch
    }

    /// Bind the actual batch and the originally pinned head to an already
    /// attested Dataset cut and separately held scope. This does not create
    /// those attestations or a training job.
    pub fn training_plan(
        &self,
        snapshot: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        baseline: Arc<LoadedCellQ24ModelV1>,
        optimizer: CellQ24SgdRuleV1,
    ) -> Result<CellQ24SingleHeadTrainingPlanV1, CellQ24DatasetErrorV1> {
        let initial =
            LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
        if initial.snapshot().head_digest != self.initial_head
            || snapshot.receipts.len() != 2
            || snapshot.receipts[0].observation != self.experience_observation()
            || snapshot.receipts[1].observation != self.dataset_observation()
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "exact original Dataset observations",
            ));
        }
        Ok(CellQ24SingleHeadTrainingPlanV1::from_dataset_cut(
            snapshot,
            scope,
            baseline,
            self.head,
            optimizer.digest(&self.batch)?,
        )?)
    }
}

fn require_source(
    identity: &AgentdIdentity,
    source: &CircuitTaskSourcePublicationV1,
    request: &LearningIterationRequestV1,
) -> Result<(), CellQ24DatasetErrorV1> {
    let input = source.input();
    let original = source.original_record();
    let selected = request
        .selected_bundle
        .digest()
        .map_err(LearningIterationError::from)?;
    if identity.agent_id.as_str() != request.agent_id.as_str()
        || input.scope.principal_digest.to_string() != request.principal_id.as_str()
        || input.scope.agent_id != request.agent_id
        || input.scope.cell_id != request.cell_id
        || input.scope.run_id != request.source_run_id
        || original.snapshot.run_id != request.source_run_id
        || input.objective_digest != request.envelope.objective_digest
        || original.snapshot.objective_digest != request.envelope.objective_digest
        || source.history_digest().as_str() != request.completed_task_receipt.to_string()
        || source.bundle_digest() != selected
    {
        return Err(CellQ24DatasetErrorV1::Binding(
            "original task identity, receipt and bundle",
        ));
    }
    Ok(())
}

fn terminal_target(
    records: &[&LedgerRecord],
    request: &LearningIterationRequestV1,
    source: &CircuitTaskSourcePublicationV1,
    unit: Digest32,
) -> Result<(StableId, i64), CellQ24DatasetErrorV1> {
    let (decision, outcome, credit) = match records {
        [decision, outcome] => (*decision, *outcome, None),
        [decision, outcome, credit] => (*decision, *outcome, Some(*credit)),
        _ => {
            return Err(CellQ24DatasetErrorV1::Binding(
                "one complete source episode",
            ));
        }
    };
    let (
        LedgerEvent::AuthenticatedDecisionV2(decision),
        LedgerEvent::AuthenticatedOutcomeV2(outcome),
    ) = (&decision.event, &outcome.event)
    else {
        return Err(CellQ24DatasetErrorV1::Binding(
            "authenticated source Decision and Outcome",
        ));
    };
    // The ledger authenticates the records but does not know this Source.
    // Enforce the join here even when the writer did not use the intake API.
    // Outcome support is an independently signed measurement reference, not a
    // second copy of the Decision's Source publication. The immutable ledger
    // joins it through the same episode; the signed freeze pins the full event.
    // Only a derived set is sorted; the original policy bytes remain intact.
    let policy = CircuitTaskSourcePublicationV1::original_policy(source)?;
    let admitted_at = source
        .original_record()
        .admission
        .observed_at_unix_micros
        .div_ceil(1_000_000);
    let mut candidates = policy
        .entries()
        .iter()
        .map(|entry| entry.candidate_id.clone())
        .collect::<Vec<_>>();
    candidates.sort();
    if decision.record_id != request.source_run_id
        || decision.objective_digest != request.envelope.objective_digest
        || decision.run_snapshot_digest != source.input().ndu_snapshot_digest
        || decision.policy_digest != Digest32::of_bytes(source.output())
        || decision.support_digest != source.publication_digest()
        || decision.candidate_ids != candidates
        || decision.selected_candidate_id != *policy.selected()
        || decision.selected_propensity != ProbabilityQ32::ONE
        || outcome.episode_id != decision.episode_id
        || outcome.support_digest.is_zero()
        || outcome.unit_profile_digest != unit
        || outcome.terminality != AuthenticatedOutcomeTerminality::Terminal
        || outcome.observed_at.is_none()
        || admitted_at == 0
        || outcome.observed_at.is_some_and(|at| at < admitted_at)
        || outcome.finalized_at.is_none()
        || outcome
            .finalized_at
            .is_some_and(|at| at < outcome.latest_observable_at)
        || decision.authentication_digest.is_zero()
        || outcome.authentication_digest.is_zero()
        || decision.generator_controller_id == outcome.observer_controller_id
        || decision.generator_signing_key_digest == outcome.observer_signing_key_digest
    {
        return Err(CellQ24DatasetErrorV1::Binding(
            "independent terminal source outcome",
        ));
    }
    let value = outcome
        .value
        .ok_or(CellQ24DatasetErrorV1::Binding("terminal outcome value"))?;
    if let Some(credit) = credit {
        let LedgerEvent::CreditBatchV2(credit) = &credit.event else {
            return Err(CellQ24DatasetErrorV1::Binding(
                "optional original credit lineage",
            ));
        };
        if credit.episode_id != outcome.episode_id
            || credit.outcome_id != outcome.outcome_id
            || credit.terminal_outcome != value
            || credit.authentication_digest.is_zero()
        {
            return Err(CellQ24DatasetErrorV1::Binding(
                "same-outcome credit lineage",
            ));
        }
    }
    let raw = value.raw();
    if raw % 256 != 0 || !(-8 * codec::Q..=8 * codec::Q).contains(&(raw / 256)) {
        return Err(CellQ24DatasetErrorV1::Binding(
            "exact representable Q32 to Q24 target",
        ));
    }
    Ok((decision.episode_id.clone(), raw / 256))
}

#[cfg(test)]
#[path = "cell_q24_dataset_tests.rs"]
mod tests;

#[cfg(target_os = "linux")]
#[path = "cell_q24_dataset_remote.rs"]
mod remote;
#[cfg(target_os = "linux")]
pub(crate) use remote::OriginalCellQ24MaterialWireV1;
