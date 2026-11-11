//! The ordinary task's original source feeds authenticated Q24 ledger facts.
//! Generator signing has its own witnessed once-only journal. A real business
//! Observer supplies Terminal evidence separately; execution success is no label.

use std::fs::File;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionStoreErrorV1;
use codex_hepta_learning_ledger::*;
use codex_hepta_neuron::FileAnchorWitnessStore;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use ed25519_dalek::SigningKey;

use crate::AgentdIdentity;
use crate::CellQ24DatasetErrorV1;
use crate::CellQ24DatasetFreezePreparationV1;
use crate::CellQ24DatasetTaskV1;
use crate::CellQ24LearningPreparationConfigV1;
use crate::CellQ24LearningPreparationErrorV1;
use crate::CircuitQ24TaskOpenModeV1;
use crate::CircuitTaskSourcePublicationV1;
use crate::CircuitTaskSourceReadbackV1;
use crate::OriginalCellQ24DatasetFreezeOwnerV1;
use crate::OriginalCellQ24DatasetFreezeSigningConfigV1;
use crate::PublishedCircuitCellOwnerV1;
use crate::PublishedCircuitFeatureTaskV1;
use crate::learning_owner_evidence;
use crate::learning_owner_journal::LearningOriginalOwnerErrorV1;
use crate::learning_owner_journal::LearningOwnerJournalV1;

#[path = "cell_q24_task_ledger_binding.rs"]
mod binding;
#[path = "cell_q24_task_ledger_outcome.rs"]
mod outcome;
#[path = "cell_q24_task_outcome_codec.rs"]
mod outcome_codec;
#[path = "cell_q24_task_learning_ready.rs"]
mod readiness;
pub use readiness::OriginalCellQ24TaskLearningReadyV1;
#[cfg(test)]
#[path = "cell_q24_task_ledger_fault_support_tests.rs"]
pub(crate) mod test_faults;

/// Frozen original Generator metadata and business outcome contract. This
/// profile covers the complete finite declared Cell candidate set, without
/// truncation. State, candidates and selection come from the committed Cell.
/// These values grant no signing authority.
#[derive(Clone)]
pub struct OriginalCellQ24TaskLedgerConfigV1 {
    pub episode_id: StableId,
    pub candidate_set_id: StableId,
    pub generator_code_digest: Digest32,
    pub grammar_digest: Digest32,
    pub hard_filter_digest: Digest32,
    pub truncation_digest: Digest32,
    pub generator: TrustedLearningSignerV1,
    pub observer: TrustedLearningSignerV1,
    pub outcome_record_id: StableId,
    pub outcome_id: StableId,
    pub unit_profile_digest: Digest32,
    pub expected_delay_profile_digest: Digest32,
    pub claim_deadline_unix_seconds: u64,
    pub maximum_signature_lifetime_seconds: u64,
}

/// All files, witnesses, trust and keys come from their original enrolled
/// owners. Create and Recover are explicit even if task-source mode differs.
pub struct OriginalCellQ24TaskLedgerInputsV1 {
    pub ledger: Arc<Mutex<LedgerWriter>>,
    pub signature_journal: File,
    pub signature_witness: FileAnchorWitnessStore,
    pub open_mode: CircuitQ24TaskOpenModeV1,
    pub config: OriginalCellQ24TaskLedgerConfigV1,
    pub generator_key: SigningKey,
}

/// The original Evaluator freeze capability is a separate mandatory handoff.
pub struct OriginalCellQ24TaskDatasetFreezeInputsV1 {
    pub journal: File,
    pub witness: FileAnchorWitnessStore,
    pub open_mode: CircuitQ24TaskOpenModeV1,
    pub signing: OriginalCellQ24DatasetFreezeSigningConfigV1,
    pub evaluator_key: SigningKey,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum OriginalCellQ24TaskLedgerStatusV1 {
    AwaitingOutcome { decision: LedgerRecord },
    Complete { decision: LedgerRecord, outcome: LedgerRecord },
}

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TaskLedgerErrorV1 {
    #[error("original Q24 task ledger binding: {0}")]
    Binding(&'static str),
    #[error("task committed; original Terminal outcome is pending")]
    PendingOutcome,
    #[error("original task ledger owner: {0}")]
    Owner(#[from] LearningOriginalOwnerErrorV1),
    #[error("original task ledger: {0}")]
    Ledger(#[from] ProductionLedgerError),
    #[error("original task ledger evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original task ledger outcome: {0}")]
    Outcome(#[from] CausalV2Error),
    #[error("original task Dataset: {0}")]
    Dataset(#[from] CellQ24DatasetErrorV1),
    #[error("original task preparation: {0}")]
    Preparation(#[from] CellQ24LearningPreparationErrorV1),
    #[error("original Dataset freeze owner: {0}")]
    Freeze(#[from] crate::OriginalCellQ24DatasetFreezeErrorV1),
}
type Error = OriginalCellQ24TaskLedgerErrorV1;

#[derive(Clone)]
struct Captured {
    task: CellQ24DatasetTaskV1,
    publication: CircuitTaskSourcePublicationV1,
    decision: ProductionDecisionV2,
}
struct State {
    journal: LearningOwnerJournalV1<FileAnchorWitnessStore>,
    key: SigningKey,
    captured: Option<Captured>,
}

/// Installed only beside the original Q24 runtime. Reconciliation reads the
/// original committed source and never submits work.
pub struct OriginalCellQ24TaskLedgerProducerV1 {
    state: Mutex<State>,
    ledger: Arc<Mutex<LedgerWriter>>,
    source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
    cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
    published: PublishedCircuitFeatureTaskV1,
    identity: AgentdIdentity,
    config: OriginalCellQ24TaskLedgerConfigV1,
    decision_key: ProductEvaluationExecutionKeyV1,
    outcome_key: ProductEvaluationExecutionKeyV1,
    ledger_binding: Digest32,
    trust_digest: Digest32,
}

impl OriginalCellQ24TaskLedgerProducerV1 {
    pub(crate) fn open_original(
        inputs: OriginalCellQ24TaskLedgerInputsV1,
        source: Arc<CircuitTaskSourceReadbackV1<FileAnchorWitnessStore>>,
        cell: PublishedCircuitCellOwnerV1<FileAnchorWitnessStore>,
        published: PublishedCircuitFeatureTaskV1,
        identity: AgentdIdentity,
    ) -> Result<Self, Error> {
        let ledger = inputs.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
        let binding = binding::configuration(&inputs, &ledger, &published, &identity)?;
        let ledger_binding = ledger.binding_digest();
        let trust_digest = ledger.verifier().trust_digest();
        drop(ledger);
        let journal = match inputs.open_mode {
            CircuitQ24TaskOpenModeV1::Create => LearningOwnerJournalV1::create(
                inputs.signature_journal, inputs.signature_witness, binding,
            )?,
            CircuitQ24TaskOpenModeV1::Recover => LearningOwnerJournalV1::recover(
                inputs.signature_journal, inputs.signature_witness, binding,
            )?,
        };
        Ok(Self {
            state: Mutex::new(State { journal, key: inputs.generator_key, captured: None }),
            ledger: inputs.ledger, source, cell, published, identity, config: inputs.config,
            decision_key: execution_key("decision", binding)?,
            outcome_key: execution_key("outcome", binding)?,
            ledger_binding, trust_digest,
        })
    }

    /// Finish original ledger work after task/result ACK loss. A Pending
    /// signing claim never signs again. A witnessed accepted Decision is
    /// historical data; an absent append still requires the original signature
    /// to authorize today's write. No timestamp or signature is renewed.
    pub fn resume_from_original_source(&self) -> Result<OriginalCellQ24TaskLedgerStatusV1, Error> {
        let mut state = self.state.lock().map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        let mut locked = self.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
        let ledger: &mut LedgerWriter = &mut locked;
        self.require_ledger(ledger)?;
        let payload = decision_signing_payload_v2(&captured.decision)?;
        let bytes = match state.journal.read(&self.decision_key) {
            Ok(bytes) => bytes,
            Err(LearningOriginalOwnerErrorV1::Store(ProductEvaluationExecutionStoreErrorV1::Missing)) => {
                let cut = witnessed_snapshot(ledger)?;
                ledger.verifier().require_signer_binding(
                    LearningEvidenceRoleV1::Generator, &self.config.generator, now()?,
                )?;
                if now()? >= self.config.claim_deadline_unix_seconds
                    || cut.records().iter().any(|r| r.event.record_id() == &captured.decision.record_id)
                {
                    return Err(Error::Binding("new original Generator claim"));
                }
                let State { journal, key, .. } = &mut *state;
                journal.commit_once(&self.decision_key, || {
                    self.require_source(&captured).map_err(owner_binding)?;
                    let signed = binding::sign(self, ledger, key, &payload).map_err(owner_binding)?;
                    self.require_source(&captured).map_err(owner_binding)?;
                    binding::encode(cut.head_digest, &payload, &signed)
                })?
            }
            Err(error) => return Err(error.into()),
        };
        let (predecessor, original_payload, signed) = binding::decode(&bytes)?;
        if original_payload != payload || signed.evidence_id != self.decision_key.plan_id {
            return Err(Error::Binding("original Decision signature payload"));
        }
        let expected = binding::decision_event(&captured.decision, &signed, &self.config.generator)?;
        let (snapshot, frontier) = original_snapshot(ledger)?;
        let witnessed = snapshot.records().iter().any(|r| {
            r.event == expected && r.predecessor_chain_digest == predecessor
                && r.sequence.get() <= frontier.anchor.sequence
        });
        self.require_source(&captured)?;
        if !witnessed {
            // This is still an actual append/reconciliation effect. The
            // original LedgerWriter verifies the unchanged signature at now.
            ledger.append_decision(predecessor, captured.decision.clone(), &signed, now()?)?;
        }
        self.require_source(&captured)?;
        self.resume_original_outcome(&mut state, ledger, &captured)?;
        self.status(&mut state, ledger, &captured)
    }

    /// Observation only: no signing, append, witness repair or task retry.
    pub fn readback(&self) -> Result<OriginalCellQ24TaskLedgerStatusV1, Error> {
        let mut state = self.state.lock().map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        let ledger = self.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
        self.status(&mut state, &ledger, &captured)
    }

    /// Historical tasks must be real retained capabilities. This task is added
    /// exactly once; the original materializer checks the complete Dataset.
    pub fn prepare_dataset(
        &self,
        config: CellQ24LearningPreparationConfigV1,
        mut original_history: Vec<CellQ24DatasetTaskV1>,
    ) -> Result<CellQ24DatasetFreezePreparationV1, Error> {
        let mut state = self.state.lock().map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        {
            let ledger = self.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
            if !matches!(self.status(&mut state, &ledger, &captured)?, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
                return Err(Error::PendingOutcome);
            }
        }
        if config.projection.unit_profile_digest != self.config.unit_profile_digest {
            return Err(Error::Binding("original outcome unit projection"));
        }
        original_history.push(captured.task.clone());
        let preparation = CellQ24DatasetFreezePreparationV1::capture(
            config, Arc::clone(&self.ledger), original_history,
        )?;
        self.require_source(&captured)?;
        Ok(preparation)
    }

    /// The original Evaluator journal and HQ24T002 materializer feed Prepared
    /// and the existing scoped Root startup. That startup's registered original
    /// Objective/Circuit recovery enqueues history without dispatching A again.
    /// Recover here requires the same current cut. A retained older cut uses
    /// recover_learning and its original frozen descriptor, initial and scope.
    pub fn prepare_learning(
        &self,
        config: CellQ24LearningPreparationConfigV1,
        original_history: Vec<CellQ24DatasetTaskV1>,
        freeze: OriginalCellQ24TaskDatasetFreezeInputsV1,
    ) -> Result<crate::CellQ24PreparedLearningV1, Error> {
        let preparation = self.prepare_dataset(config, original_history)?;
        let mut owner: OriginalCellQ24DatasetFreezeOwnerV1<FileAnchorWitnessStore> = match freeze.open_mode {
            CircuitQ24TaskOpenModeV1::Create => OriginalCellQ24DatasetFreezeOwnerV1::create(
                freeze.journal, freeze.witness, &preparation, freeze.signing, freeze.evaluator_key,
            )?,
            CircuitQ24TaskOpenModeV1::Recover => OriginalCellQ24DatasetFreezeOwnerV1::recover(
                freeze.journal, freeze.witness, &preparation, freeze.signing, freeze.evaluator_key,
            )?,
        };
        let prepared = preparation.authorize_and_materialize(&mut owner)?;
        if !matches!(self.readback()?, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
            return Err(Error::PendingOutcome);
        }
        prepared.revalidate_source()?;
        Ok(prepared)
    }

    /// Restore an already authorized Dataset at its exact retained cut with
    /// current original owners. No capture, claim, new freeze or signing is
    /// permitted; the saved Evaluator journal must return the same signature.
    pub fn recover_learning(
        &self,
        config: CellQ24LearningPreparationConfigV1,
        mut original_history: Vec<CellQ24DatasetTaskV1>,
        frozen: crate::CellQ24FrozenDatasetV1,
        initial: &codex_hepta_learning_artifacts::LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
        freeze: OriginalCellQ24TaskDatasetFreezeInputsV1,
    ) -> Result<crate::CellQ24PreparedLearningV1, Error> {
        if !matches!(freeze.open_mode, CircuitQ24TaskOpenModeV1::Recover) {
            return Err(Error::Binding("retained Dataset requires explicit Recover"));
        }
        let mut state = self.state.lock().map_err(|_| Error::Binding("producer lock"))?;
        let captured = self.capture(&mut state)?;
        {
            let ledger = self.ledger.lock().map_err(|_| Error::Binding("ledger lock"))?;
            if !matches!(self.status(&mut state, &ledger, &captured)?, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
                return Err(Error::PendingOutcome);
            }
        }
        if config.projection.unit_profile_digest != self.config.unit_profile_digest {
            return Err(Error::Binding("original outcome unit projection"));
        }
        original_history.push(captured.task.clone());
        drop(state);
        let preparation = CellQ24DatasetFreezePreparationV1::recover(
            config.clone(), Arc::clone(&self.ledger), original_history.clone(), frozen.snapshot.clone(),
        )?;
        let mut owner: OriginalCellQ24DatasetFreezeOwnerV1<FileAnchorWitnessStore> = OriginalCellQ24DatasetFreezeOwnerV1::recover(
            freeze.journal, freeze.witness, &preparation, freeze.signing, freeze.evaluator_key,
        )?;
        let authorization = owner.readback(&preparation)?;
        if authorization != frozen.authorization {
            return Err(Error::Binding("original retained Dataset authorization"));
        }
        let prepared = crate::CellQ24PreparedLearningV1::recover(
            config, Arc::clone(&self.ledger), original_history, frozen, initial, scope,
        )?;
        self.require_source(&captured)?;
        if !matches!(self.readback()?, OriginalCellQ24TaskLedgerStatusV1::Complete { .. }) {
            return Err(Error::PendingOutcome);
        }
        prepared.revalidate_source()?;
        Ok(prepared)
    }

    fn capture(&self, state: &mut State) -> Result<Captured, Error> {
        if let Some(captured) = &state.captured {
            self.require_source(captured)?;
            return Ok(captured.clone());
        }
        let run = self.published.source().scope.run_id.clone();
        let publication = self.source.read_run_publication(&self.identity, &run)
            .map_err(|_| Error::Binding("original task is not committed or was withdrawn"))?;
        let cell: &PublishedCircuitCellOwnerV1<FileAnchorWitnessStore> = &self.cell;
        let decision = cell.committed(&publication)
            .map_err(|_| Error::Binding("original committed Cell"))?;
        let task = CellQ24DatasetTaskV1::capture(
            self.source.as_ref().clone(), &self.cell, self.identity.clone(), run,
        )?;
        let captured = Captured {
            decision: binding::decision(&self.config, &self.published, &publication, &decision)?,
            publication, task,
        };
        self.require_source(&captured)?;
        state.captured = Some(captured.clone());
        Ok(captured)
    }

    fn require_source(&self, captured: &Captured) -> Result<(), Error> {
        if self.source.read_run_publication(&self.identity, &captured.decision.record_id)
            .map_err(|_| Error::Binding("original source is unavailable"))? != captured.publication
        {
            return Err(Error::Binding("original source changed or was withdrawn"));
        }
        Ok(())
    }

    fn require_ledger(&self, ledger: &LedgerWriter) -> Result<(), Error> {
        if ledger.binding_digest() != self.ledger_binding
            || ledger.verifier().trust_digest() != self.trust_digest
        {
            return Err(Error::Binding("original ledger or enrolled trust changed"));
        }
        binding::require_original_signers(ledger, &self.config)
    }
}

fn execution_key(kind: &str, binding: Digest32) -> Result<ProductEvaluationExecutionKeyV1, Error> {
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new(format!("q24-task-{kind}:{binding}"))
            .map_err(|_| Error::Binding("original task ledger operation id"))?,
        binding_digest: binding,
    })
}

/// A one-record lag is observation only. Only the original LedgerWriter's
/// exact idempotent replay may repair it; it never counts as witnessed history.
fn original_snapshot(
    ledger: &LedgerWriter,
) -> Result<(LedgerSnapshot, LedgerWitnessFrontier), Error> {
    let snapshot = ledger.snapshot()?;
    let frontier = ledger.witness_frontier()?;
    let covered = usize::try_from(frontier.anchor.sequence)
        .map_err(|_| LearningOriginalOwnerErrorV1::CommitUncertain)?;
    if snapshot.records().len() > 4096
        || covered > snapshot.records().len()
        || snapshot.records().len() - covered > 1
        || (if covered == 0 { Digest32::ZERO } else {
            snapshot.records()[covered - 1].chain_digest
        }) != frontier.anchor.chain_digest
    {
        return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
    }
    Ok((snapshot, frontier))
}

fn witnessed_snapshot(ledger: &LedgerWriter) -> Result<LedgerSnapshot, Error> {
    let (snapshot, frontier) = original_snapshot(ledger)?;
    if snapshot.records().len() as u64 != frontier.anchor.sequence
        || snapshot.head_digest != frontier.anchor.chain_digest
    {
        return Err(LearningOriginalOwnerErrorV1::CommitUncertain.into());
    }
    Ok(snapshot)
}

fn owner_binding(_: Error) -> LearningOriginalOwnerErrorV1 {
    LearningOriginalOwnerErrorV1::Binding("original source or Generator changed during claim")
}

fn now() -> Result<u64, Error> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)
        .map_err(|_| Error::Binding("system clock"))?.as_secs())
}
