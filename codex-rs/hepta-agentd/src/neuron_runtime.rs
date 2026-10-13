//! Agentd-owned neuron runtime with mandatory signed final-use admission.
//!
//! A bare digest cannot authenticate an NDU read receipt. This product owner
//! denies the old unsigned entry, verifies a pinned issuer grant and consumes
//! one durable nonce for every model invocation. Low-level neuron.tick remains
//! a mechanism for independent qualification, never an Agentd serving port.

use crate::neuron_effect_bootstrap::NeuronEffectBootstrapErrorV1;
use crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1;
use crate::neuron_effect_bootstrap::verify_neuron_effect_scope_v1;
use crate::neuron_ndu_read::NduReadVerifierV1;
use crate::neuron_ndu_read::SignedNduSnapshotReadV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::DurableNeuronEffectIntentV1;
use codex_hepta_neuron::InferenceControlModelPort;
use codex_hepta_neuron::JournalScope;
use codex_hepta_neuron::NeuronEffectIntentStatusV1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

pub struct AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    runtime: NeuronRuntime<W>,
    inference_control: P,
    final_use: Option<FinalUseAuthority>,
    neuron_owner_id: Option<StableId>,
    ndu_read_verifier: Option<NduReadVerifierV1>,
    effect_intent: Option<DurableNeuronEffectIntentV1>,
    metric_sink: Option<Arc<dyn PhaseMetricSinkV1>>,
    failed_metrics: AtomicU64,
}

/// The kernel-authority issuer signs this exact complete binding after
/// independently verifying the NDU owner and selected immutable snapshot.
pub fn neuron_ndu_final_use_binding_v1(
    neuron_owner_id: &StableId,
    input: &NeuronTickInputV1,
    snapshot: &NduSnapshotRefV1,
    authenticated_read_receipt_digest: Digest32,
) -> Result<FinalUseBinding, NeuronRuntimeError> {
    if snapshot.scope_id != input.subject_id
        || snapshot.snapshot_digest != input.ndu_snapshot_digest
        || authenticated_read_receipt_digest.is_zero()
    {
        return Err(NeuronRuntimeError::InvalidInput);
    }
    let tick_digest = input.semantic_digest()?;
    let snapshot_ref_digest = snapshot
        .semantic_digest()
        .map_err(|_| NeuronRuntimeError::InvalidInput)?;
    let mut payload = b"hepta.agentd.neuron-final-use.v1".to_vec();
    payload.extend_from_slice(tick_digest.as_array());
    payload.extend_from_slice(snapshot_ref_digest.as_array());
    payload.extend_from_slice(authenticated_read_receipt_digest.as_array());
    let owner = neuron_owner_id.as_str().as_bytes();
    payload.extend_from_slice(&(owner.len() as u64).to_be_bytes());
    payload.extend_from_slice(owner);
    Ok(FinalUseBinding {
        subject_id: input.subject_id.to_string(),
        destination_id: neuron_owner_id.to_string(),
        request_sha256: *tick_digest.as_array(),
        scope_sha256: *snapshot_ref_digest.as_array(),
        payload_sha256: *Digest32::of_bytes(&payload).as_array(),
    })
}

impl<W, P> AgentdNeuronOwner<W, P>
where
    W: AnchorWitnessStore,
    P: NeuronInferenceControlPort,
{
    /// Legacy source-only constructor deliberately has no serving authority.
    pub fn new(runtime: NeuronRuntime<W>, inference_control: P) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: None,
            neuron_owner_id: None,
            ndu_read_verifier: None,
            effect_intent: None,
            metric_sink: None,
            failed_metrics: AtomicU64::new(0),
        }
    }

    /// Retained for source compatibility only: lacking the independent durable
    /// business-tick effect journal, tick_bound fails closed. New serving
    /// compositions must use new_authorized_durable instead.
    pub fn new_authorized(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: Some(final_use),
            neuron_owner_id: Some(neuron_owner_id),
            ndu_read_verifier: Some(ndu_read_verifier),
            effect_intent: None,
            metric_sink: None,
            failed_metrics: AtomicU64::new(0),
        }
    }

    /// The verified NDU read and independent final-use nonce are joined to a
    /// distinct durable tick-intent fence. The caller must obtain this journal
    /// from the Control-owned scope/generation bootstrap, using owner-only
    /// storage whose parent directory entry is durably synchronized.
    pub fn new_authorized_durable(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
        effect_intent: DurableNeuronEffectIntentV1,
    ) -> Self {
        Self {
            runtime,
            inference_control,
            final_use: Some(final_use),
            neuron_owner_id: Some(neuron_owner_id),
            ndu_read_verifier: Some(ndu_read_verifier),
            effect_intent: Some(effect_intent),
            metric_sink: None,
            failed_metrics: AtomicU64::new(0),
        }
    }

    /// Production-oriented construction from a protected, durably named
    /// journal path. The journal's generation is derived from the actual
    /// runtime, not from an independent caller hint.
    ///
    /// The pinned NDU verifier and one-shot Final-use authority remain
    /// independently initialized inputs; this method never creates trust or
    /// overrides the recorded unresolved intent after a crash.
    pub fn new_authorized_durable_from_path(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
        effect_intent_path: &std::path::Path,
        scope: JournalScope,
        max_records: usize,
    ) -> Result<Self, NeuronEffectBootstrapErrorV1> {
        let generation = runtime.generation();
        // Never create a durable intent file under a caller's mismatched
        // subject/objective when the recovered sparse journal says otherwise.
        verify_neuron_effect_scope_v1(runtime.journal_scope(), scope)?;
        let effect_intent = bootstrap_durable_neuron_effect_intent_v1(
            effect_intent_path,
            scope,
            generation,
            max_records,
        )?;
        Ok(Self::new_authorized_durable(
            runtime,
            inference_control,
            neuron_owner_id,
            final_use,
            ndu_read_verifier,
            effect_intent,
        ))
    }

    /// Connect to the Evidence-owned durable sink. Telemetry is
    /// non-authorizing and must never replay an uncertain external effect.
    pub fn with_metric_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metric_sink = Some(sink);
        self
    }

    pub fn production_metrics_ready(&self) -> bool {
        self.metric_sink.as_ref().is_some_and(|sink| sink.healthy())
            && self.failed_metrics.load(Ordering::Acquire) == 0
    }

    /// Explicit group-commit barrier for qualification, outside any model
    /// effect fence. A missing or failed sink denies acceptance readiness.
    pub fn flush_production_metrics(&self) -> bool {
        let Some(sink) = &self.metric_sink else {
            return false;
        };
        if sink.flush().is_err() {
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return false;
        }
        self.production_metrics_ready()
    }

    fn emit_phase(
        &self,
        scope_id: &StableId,
        operation_digest: Digest32,
        phase: PhaseMetricKindV1,
        elapsed: Duration,
        succeeded: bool,
    ) {
        observe_phase_v1(
            self.metric_sink.as_deref(),
            &self.failed_metrics,
            Digest32::of_bytes(scope_id.as_str().as_bytes()),
            operation_digest,
            phase,
            elapsed,
            succeeded,
        );
    }

    /// Read-only reconciliation diagnostics; unresolved work must be
    /// independently inspected, never automatically replayed.
    pub fn effect_intent_status(&self) -> Option<NeuronEffectIntentStatusV1> {
        self.effect_intent
            .as_ref()
            .map(DurableNeuronEffectIntentV1::status)
    }

    /// The old unsigned entry is not a serving path.
    #[deprecated(note = "unsigned Agentd neuron ticks are denied; use tick_bound")]
    pub fn tick(
        &mut self,
        _input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        Err(NeuronRuntimeError::InvalidInput)
    }

    /// One independently issuer-signed grant permits one snapshot-bound tick.
    /// The token is revalidated at physical effect entry; revocation during
    /// a synchronous invocation is fenced by with_verified_effect.
    pub fn tick_bound(
        &mut self,
        input: NeuronTickInputV1,
        signed_read: &SignedNduSnapshotReadV1,
        signed_grant: &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let started = Instant::now();
        let scope = input.subject_id.clone();
        let operation = input.semantic_digest()?;
        let result = self.tick_bound_inner(input, signed_read, signed_grant);
        self.emit_phase(
            &scope,
            operation,
            PhaseMetricKindV1::NeuronFeature,
            started.elapsed(),
            result.is_ok(),
        );
        result
    }

    fn tick_bound_inner(
        &mut self,
        input: NeuronTickInputV1,
        signed_read: &SignedNduSnapshotReadV1,
        signed_grant: &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        let read_verifier = self
            .ndu_read_verifier
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        let read_started = Instant::now();
        let read_result = read_verifier.verify(signed_read);
        self.emit_phase(
            &input.subject_id,
            input.semantic_digest()?,
            PhaseMetricKindV1::NduRead,
            read_started.elapsed(),
            read_result.is_ok(),
        );
        let authenticated_read_receipt_digest =
            read_result.map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let snapshot = &signed_read.snapshot;
        if snapshot.generation != self.runtime.generation() {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let input_digest = input.semantic_digest()?;
        let effect_intent = self
            .effect_intent
            .as_ref()
            .ok_or(NeuronRuntimeError::PendingReconciliation)?;
        if !effect_intent.matches_tick_scope(
            &input.subject_id,
            input.objective_digest,
            snapshot.generation,
        ) {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        effect_intent
            .can_prepare(input_digest)
            .map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
        let authority = self
            .final_use
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        let owner_id = self
            .neuron_owner_id
            .as_ref()
            .ok_or(NeuronRuntimeError::InvalidInput)?;
        if signed_grant.grant.authority_epoch != snapshot.revocation_epoch {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let binding = neuron_ndu_final_use_binding_v1(
            owner_id,
            &input,
            snapshot,
            authenticated_read_receipt_digest,
        )?;
        let authority_started = Instant::now();
        let claimed = FinalUseAuthority::claim(authority, signed_grant, &binding);
        self.emit_phase(
            &input.subject_id,
            input_digest,
            PhaseMetricKindV1::FinalUse,
            authority_started.elapsed(),
            claimed.is_ok(),
        );
        let token = claimed.map_err(|_| NeuronRuntimeError::InvalidInput)?;
        // Claim persistence may advance past an NDU read cutover/expiry.
        // Consume the nonce but deny the model effect if the live frontier or
        // the protected clock changed while authority was being claimed.
        let still_current = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        if still_current != authenticated_read_receipt_digest {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        let previous_checkpoint = input.checkpoint_digest;
        let metric_scope = Digest32::of_bytes(input.subject_id.as_str().as_bytes());
        let metric_sink = self.metric_sink.as_deref();
        let failed_metrics = &self.failed_metrics;
        let effect_intent = self
            .effect_intent
            .as_mut()
            .ok_or(NeuronRuntimeError::PendingReconciliation)?;
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        let outcome = FinalUseAuthority::with_verified_effect(authority, token, &binding, || {
            // Sync business-tick Prepare while holding the independently
            // verified effect fence, before the physical encoder/Head call.
            // Even a driver error or process crash now leaves an unresolved
            // durable intent. A freshly signed nonce cannot replay that tick.
            let prepare_started = Instant::now();
            let prepared = effect_intent.prepare(input_digest, previous_checkpoint);
            observe_phase_v1(
                metric_sink,
                failed_metrics,
                metric_scope,
                input_digest,
                PhaseMetricKindV1::Wal,
                prepare_started.elapsed(),
                prepared.is_ok(),
            );
            prepared.map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
            self.runtime.tick_with_ndu_snapshot_guarded(
                &mut model,
                input,
                snapshot,
                authenticated_read_receipt_digest,
                || {
                    let observed = read_verifier
                        .verify(signed_read)
                        .map_err(|_| NeuronRuntimeError::NduStaleAfterEffect)?;
                    if observed == authenticated_read_receipt_digest {
                        Ok(())
                    } else {
                        Err(NeuronRuntimeError::NduStaleAfterEffect)
                    }
                },
            )
        })
        .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let output = outcome?;
        // Never publish a successful serving result if CNS/NDU advanced
        // during checkpoint persistence. In this case the durable Prepare
        // deliberately remains unresolved for independent reconciliation.
        let observed = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::NduStaleAfterEffect)?;
        if observed != authenticated_read_receipt_digest {
            return Err(NeuronRuntimeError::NduStaleAfterEffect);
        }
        // Resolve only after the checkpoint, witness, and post-effect live NDU
        // frontier are independently verified. A sync failure cannot erase the
        // unresolved Prepare; never retry the model on this failure.
        let resolved_started = Instant::now();
        let resolved = effect_intent.resolve(input_digest, output.tick.checkpoint_after);
        observe_phase_v1(
            metric_sink,
            failed_metrics,
            metric_scope,
            input_digest,
            PhaseMetricKindV1::Wal,
            resolved_started.elapsed(),
            resolved.is_ok(),
        );
        resolved.map_err(|_| NeuronRuntimeError::PendingReconciliation)?;
        Ok(output)
    }

    /// Read-only diagnostics. Mutable runtime/worker access is intentionally
    /// not exposed: it would bypass the exact signed owner entry.
    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

/// A sink failure latches acceptance readiness without affecting
/// Final-use authorization, committed state or replay semantics.
fn observe_phase_v1(
    sink: Option<&dyn PhaseMetricSinkV1>,
    failed_metrics: &AtomicU64,
    scope_digest: Digest32,
    operation_digest: Digest32,
    phase: PhaseMetricKindV1,
    elapsed: Duration,
    succeeded: bool,
) {
    if let Some(sink) = sink {
        if sink
            .record(PhaseMetricEventV1 {
                scope_digest,
                operation_digest,
                phase,
                latency_micros: u64::try_from(elapsed.as_micros()).unwrap_or(u64::MAX),
                succeeded,
            })
            .is_err()
        {
            failed_metrics.fetch_add(1, Ordering::Release);
        }
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
