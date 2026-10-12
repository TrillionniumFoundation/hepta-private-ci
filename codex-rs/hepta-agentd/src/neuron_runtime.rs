//! Agentd-owned Neuron runtime composition.
//!
//! This is the named product-host ownership boundary for neuron.runtime source
//! composition.  It owns the long-lived runtime and the inference.control port
//! together so callers cannot bypass the exact feature-receipt adapter by
//! supplying drive/prediction vectors directly.  Constructing this owner does
//! not itself activate it in the daemon startup path.

use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_ledger::DatasetFreezePlanV2;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_learning_ledger::LedgerWriter;
use codex_hepta_learning_ledger::NeuronTrialCohortTickV1;
use codex_hepta_learning_ledger::NeuronTrialObservedCohortV1;
use codex_hepta_learning_ledger::NeuronTrialObservedTickLinkV1;
use codex_hepta_learning_ledger::NeuronTrialSourceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;

use crate::neuron_selected_artifact::NeuronCandidateModelArtifactErrorV1;
use crate::neuron_selected_artifact::NeuronCandidateModelArtifactV1;
use crate::neuron_selected_artifact::verify_pinned_neuron_model_descriptor_v1;
use crate::neuron_tick_observation::AgentdNeuronTickObservationV1;
use crate::neuron_tick_observation::from_actual_committed_tick;

/// Caller holds preexisting owner handles; the only way through is an
/// actual Agentd Neuron witness read followed by a live native Ledger read.
/// No source text, model Q24 vectors, label or route claim is exported.
const MAX_ISSUED_OBSERVED_TICKS: usize = 256;

/// A complete Observer-signed cohort, not a list of self-asserted tick hashes.
/// All ticks must have been observed by the SAME owning Agentd instance.
/// A single call consumes the process-local series even on verification failure.
pub struct NeuronTrialTickCohortObserverContextV1<'a> {
    pub ledger: &'a LedgerWriter,
    pub frozen_ledger: &'a LedgerSnapshot,
    pub freeze_plan: &'a DatasetFreezePlanV2,
    pub signed_freeze: &'a SignedLearningEvidenceV1,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub episode_ticks: &'a [NeuronTrialCohortTickV1],
    pub signed_observer_batch: &'a SignedLearningEvidenceV1,
    pub now: u64,
}

pub struct NeuronTrialTickObserverContextV1<'a> {
    pub ledger: &'a LedgerWriter,
    pub frozen_ledger: &'a LedgerSnapshot,
    pub freeze_plan: &'a DatasetFreezePlanV2,
    pub signed_freeze: &'a SignedLearningEvidenceV1,
    pub dataset: &'a DatasetSnapshotReceiptV3,
    pub episode_id: &'a StableId,
    pub tick: &'a AgentdNeuronTickObservationV1,
    pub signed_observer_link: &'a SignedLearningEvidenceV1,
    pub now: u64,
}

#[derive(Debug, thiserror::Error)]
pub enum NeuronTrialTickObserverErrorV1 {
    #[error("Neuron owner witness: {0}")]
    Neuron(#[from] NeuronRuntimeError),
    #[error("current native Ledger/Observer: {0}")]
    Ledger(#[from] NeuronTrialSourceError),
}

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
    // Never accept a caller-rehashed tick as evidence that THIS owner executed
    // it. The cache is process-local and intentionally NOT historical proof.
    issued_tick: Option<AgentdNeuronTickObservationV1>,
    // Consecutive, owner-issued, witness-acknowledged observations only.
    // No process restart or failed/direct tick may revive this local trail.
    issued_cohort: Vec<AgentdNeuronTickObservationV1>,
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
            issued_tick: None,
            issued_cohort: Vec::new(),
        }
    }

    pub fn tick(
        &mut self,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        // Also invalidate on failed/direct ticks and uncertain post-commit CAS.
        // No earlier diagnostic may be reused after ANY attempted successor.
        self.issued_tick = None;
        self.issued_cohort.clear();
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick(&mut model, input)
    }

    /// Observe one real inference.control -> Neuron -> acknowledged Journal
    /// execution without copying features, state vectors or private labels
    /// into a diagnostic. This is not a selected production no-change claim.
    pub fn tick_with_observation_v1(
        &mut self,
        input: NeuronTickInputV1,
    ) -> Result<(NeuronRuntimeOutputV1, AgentdNeuronTickObservationV1), NeuronRuntimeError> {
        // Move the trail out BEFORE invoking an effectful ModelPort: if the
        // Worker panics, the old series is no longer accessible from this owner.
        let mut prior = std::mem::take(&mut self.issued_cohort);
        self.issued_tick = None;
        if prior.len() >= MAX_ISSUED_OBSERVED_TICKS {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let attempted = (|| -> Result<
            (NeuronRuntimeOutputV1, AgentdNeuronTickObservationV1),
            NeuronRuntimeError,
        > {
            let input_digest = input.semantic_digest()?;
            // The native Runtime reconciles a pending Witness CAS using the
            // original input, without reinvoking the worker on retry.
            let output = {
                let mut model = InferenceControlModelPort::new(&mut self.inference_control);
                self.runtime.tick(&mut model, input.clone())?
            };
            // The independently durable Witness is checked AFTER the Worker.
            let binding = self.read_local_checkpoint_binding_v1()?;
            let observed = from_actual_committed_tick(&input, input_digest, &output, &binding)?;
            Ok((output, observed))
        })();
        match attempted {
            Ok((output, observed)) => {
                // Never join a second tick to an old series with a gap, changed
                // scope/generation, reused identity or conflicting checkpoint.
                retain_owner_observed_tick(&mut prior, &observed)?;
                self.issued_tick = Some(observed.clone());
                self.issued_cohort = prior;
                Ok((output, observed))
            }
            Err(error) => Err(error), // prior is dropped: fail closed
        }
    }

    /// The observed tick is current only while this very owner retains the
    /// same witnessed checkpoint. This cannot authenticate an old event after
    /// another tick, and cannot replace an independent historical evidence log.
    pub fn revalidate_current_tick_observation_v1(
        &self,
        prior: &AgentdNeuronTickObservationV1,
    ) -> Result<(), NeuronRuntimeError> {
        require_owner_issued_tick(self.issued_tick.as_ref(), prior)?;
        let current = self.read_local_checkpoint_binding_v1()?;
        if prior.local_checkpoint_binding_digest != current.binding_digest
            || prior.checkpoint_after != current.anchor.checkpoint_digest
            || prior.logical_sequence != current.anchor.sequence
        {
            return Err(NeuronRuntimeError::ModelBindingMismatch);
        }
        Ok(())
    }

    /// Admit a post-commit tick to one native Ledger Episode only after a
    /// separately trusted Observer signed the exact causal correlation.
    /// This is a read-only diagnostic and NOT CNS/Artifact route selection.
    pub fn read_observer_linked_tick_v1(
        &mut self,
        query: &NeuronTrialTickObserverContextV1<'_>,
    ) -> Result<NeuronTrialObservedTickLinkV1, NeuronTrialTickObserverErrorV1> {
        // This and the complete-cohort path share one single-use issuance.
        // Even a rejected Observer signature consumes the process-local trail.
        let history = std::mem::take(&mut self.issued_cohort);
        let latest = self.issued_tick.take();
        (|| -> Result<NeuronTrialObservedTickLinkV1, NeuronTrialTickObserverErrorV1> {
            // A multi-tick series must use the whole Observer-signed cohort,
            // never cherry-pick one later outcome from many executed ticks.
            require_single_owner_issued_tick(&history, latest.as_ref(), query.tick)?;
            let before = self.read_local_checkpoint_binding_v1()?;
            if query.tick.local_checkpoint_binding_digest != before.binding_digest
                || query.tick.checkpoint_after != before.anchor.checkpoint_digest
                || query.tick.logical_sequence != before.anchor.sequence
            {
                return Err(NeuronRuntimeError::ModelBindingMismatch.into());
            }
            let link = query.ledger.read_observer_linked_neuron_tick_v1(
                query.frozen_ledger,
                query.freeze_plan,
                query.signed_freeze,
                query.dataset,
                query.episode_id,
                query.tick.diagnostic_digest,
                query.tick.objective_digest,
                query.tick.generation,
                query.signed_observer_link,
                query.now,
            )?;
            if self.read_local_checkpoint_binding_v1()? != before {
                return Err(NeuronRuntimeError::ModelBindingMismatch.into());
            }
            Ok(link)
        })()
    }

    /// Verify an entire Observer-signed native Ledger cohort against actual
    /// successful ticks retained by THIS owning Agentd instance. All rows
    /// must match the complete uninterrupted in-memory series, exactly once.
    /// Even a rejected request consumes it: old Tick/Outcome pairings must not
    /// be reused in a second window. No historical receipts survive restart.
    ///
    /// This is NOT a signed Agentd history, a production route claim or an NDU
    /// authority. Independent durable Tick evidence is still required.
    pub fn read_observer_linked_cohort_v1(
        &mut self,
        query: &NeuronTrialTickCohortObserverContextV1<'_>,
    ) -> Result<NeuronTrialObservedCohortV1, NeuronTrialTickObserverErrorV1> {
        let trail = std::mem::take(&mut self.issued_cohort);
        let latest = self.issued_tick.take();
        let result = (|| -> Result<NeuronTrialObservedCohortV1, NeuronTrialTickObserverErrorV1> {
            let last = trail.last().ok_or(NeuronRuntimeError::ModelBindingMismatch)?;
            require_owner_issued_tick(latest.as_ref(), last)?;
            // Revalidate the current Journal/Witness both before and after the
            // independent Ledger read, without exposing private input bytes.
            let before = self.read_local_checkpoint_binding_v1()?;
            if last.checkpoint_after != before.anchor.checkpoint_digest
                || last.logical_sequence != before.anchor.sequence
                || last.local_checkpoint_binding_digest != before.binding_digest
            {
                return Err(NeuronRuntimeError::ModelBindingMismatch.into());
            }
            require_owner_issued_cohort(&trail, query.episode_ticks)?;
            if trail
                .iter()
                .any(|row| row.objective_digest != query.freeze_plan.objective_digest)
            {
                return Err(NeuronRuntimeError::ModelBindingMismatch.into());
            }
            let link = query.ledger.read_observer_linked_neuron_cohort_v1(
                query.frozen_ledger,
                query.freeze_plan,
                query.signed_freeze,
                query.dataset,
                query.episode_ticks,
                query.signed_observer_batch,
                query.now,
            )?;
            let after = self.read_local_checkpoint_binding_v1()?;
            if before != after {
                return Err(NeuronRuntimeError::ModelBindingMismatch.into());
            }
            Ok(link)
        })();
        // No success or failure returns a reusable in-process historical
        // claim. A fresh Neuron Tick execution is required to start a new trail.
        result
    }

    /// Return the exact locally loaded model configuration and a checkpoint
    /// independently acknowledged by this runtime's Witness store. This does
    /// not prove the current production CNS route selected this runtime.
    /// No inference, mutation or promotion occurs during the read.
    pub fn read_local_checkpoint_binding_v1(
        &self,
    ) -> Result<NeuronLocalCheckpointBindingV1, NeuronRuntimeError> {
        self.runtime.read_local_checkpoint_binding_v1()
    }

    /// Verify one independently signed Model *descriptor* artifact against
    /// this owner-local witnessed config. The artifact is small: the actual
    /// frozen weights remain under their existing physical model/CAS owner.
    /// This does NOT prove CNS route selection or authorize final-use/promotion.
    #[allow(clippy::too_many_arguments)]
    pub fn read_model_artifact_candidate_v1(
        &self,
        verifier: &ArtifactSelectionVerifierV1,
        signed: &SignedArtifactSelectionV1,
        current: VerifiedCurrentRegistryViewV1,
        registry_snapshot: File,
        descriptor_payload: File,
        now: u64,
    ) -> Result<NeuronCandidateModelArtifactV1, NeuronCandidateModelArtifactErrorV1> {
        let local = self.read_local_checkpoint_binding_v1()?;
        verify_pinned_neuron_model_descriptor_v1(
            &local,
            verifier,
            signed,
            current,
            registry_snapshot,
            descriptor_payload,
            now,
        )
    }

    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

/// The legacy single Episode bridge is admissible ONLY for a single actually
/// issued tick. Once a series contains multiple ticks, the complete batch path
/// is mandatory; a caller cannot select just its best observed outcome.
fn require_single_owner_issued_tick(
    history: &[AgentdNeuronTickObservationV1],
    retained: Option<&AgentdNeuronTickObservationV1>,
    presented: &AgentdNeuronTickObservationV1,
) -> Result<(), NeuronRuntimeError> {
    if history.len() != 1 || history.first() != Some(presented) {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    require_owner_issued_tick(retained, presented)
}

/// Only a truly contiguous series from one current owner may be retained.
/// A direct tick, error or interleaved model generation invalidates it.
fn retain_owner_observed_tick(
    history: &mut Vec<AgentdNeuronTickObservationV1>,
    next: &AgentdNeuronTickObservationV1,
) -> Result<(), NeuronRuntimeError> {
    if !next.validate_integrity() || history.len() >= MAX_ISSUED_OBSERVED_TICKS {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    if let Some(last) = history.last() {
        if !last.validate_integrity()
            || last.logical_sequence.checked_add(1) != Some(next.logical_sequence)
            || last.checkpoint_after != next.checkpoint_before
            || last.generation != next.generation
            || last.scope_digest != next.scope_digest
            || last.objective_digest != next.objective_digest
        {
            return Err(NeuronRuntimeError::ModelBindingMismatch);
        }
    }
    if history.iter().any(|row| {
        row.tick_id == next.tick_id || row.diagnostic_digest == next.diagnostic_digest
    }) {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    history.push(next.clone());
    Ok(())
}

/// Exactly one unique owner-issued observed tick per Ledger Episode; caller
/// digests never manufacture additional source evidence.
fn require_owner_issued_cohort(
    history: &[AgentdNeuronTickObservationV1],
    requested: &[NeuronTrialCohortTickV1],
) -> Result<(), NeuronRuntimeError> {
    if history.is_empty()
        || history.len() > MAX_ISSUED_OBSERVED_TICKS
        || history.len() != requested.len()
    {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    let mut seen_ticks = BTreeMap::new();
    let mut seen_ids = BTreeSet::new();
    let mut previous: Option<&AgentdNeuronTickObservationV1> = None;
    for observed in history {
        if !observed.validate_integrity()
            || !seen_ids.insert(&observed.tick_id)
            || seen_ticks
                .insert(observed.diagnostic_digest, observed.generation)
                .is_some()
        {
            return Err(NeuronRuntimeError::ModelBindingMismatch);
        }
        if let Some(before) = previous {
            if before.logical_sequence.checked_add(1) != Some(observed.logical_sequence)
                || before.checkpoint_after != observed.checkpoint_before
                || before.generation != observed.generation
                || before.scope_digest != observed.scope_digest
                || before.objective_digest != observed.objective_digest
            {
                return Err(NeuronRuntimeError::ModelBindingMismatch);
            }
        }
        previous = Some(observed);
    }
    let mut used = BTreeSet::new();
    for row in requested {
        if !used.insert(&row.episode_id)
            || seen_ticks.get(&row.tick_observation_digest) != Some(&row.tick_generation)
        {
            return Err(NeuronRuntimeError::ModelBindingMismatch);
        }
    }
    Ok(())
}

/// Self-consistent digests are insufficient: only the most recently observed
/// success, retained inside the actual process-local Agentd owner, may be
/// linked to an Observer. A restarted host has no retained tick by design.
fn require_owner_issued_tick(
    retained: Option<&AgentdNeuronTickObservationV1>,
    presented: &AgentdNeuronTickObservationV1,
) -> Result<(), NeuronRuntimeError> {
    if retained != Some(presented) || !presented.validate_integrity() {
        return Err(NeuronRuntimeError::ModelBindingMismatch);
    }
    Ok(())
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
