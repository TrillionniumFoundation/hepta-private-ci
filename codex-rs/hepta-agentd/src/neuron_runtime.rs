//! Agentd-owned neuron runtime with mandatory signed final-use admission.
//!
//! A bare digest cannot authenticate an NDU read receipt. This product owner
//! denies the old unsigned entry, verifies a pinned issuer grant and consumes
//! one durable nonce for every model invocation. Low-level neuron.tick remains
//! a mechanism for independent qualification, never an Agentd serving port.

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
use codex_hepta_neuron::NeuronSignedEffectAdmissionV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::NduSnapshotRefV1;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;
use codex_hepta_types::StableId;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
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
    metrics_flushed: AtomicBool,
    original_evidence_bound: bool,
}

/// The kernel-authority issuer signs this exact complete binding after
/// independently verifying the NDU owner and selected immutable snapshot.
pub fn neuron_ndu_final_use_binding_v1(
    neuron_owner_id: &StableId,
    input: &NeuronTickInputV1,
    snapshot: &NduSnapshotRefV1,
    authenticated_read_receipt_digest: Digest32,
) -> Result<FinalUseBinding, NeuronRuntimeError> {
    codex_hepta_neuron::neuron_tick_final_use_binding_v1(
        neuron_owner_id,
        input,
        snapshot,
        authenticated_read_receipt_digest,
    )
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
            metrics_flushed: AtomicBool::new(false),
            original_evidence_bound: false,
        }
    }

    /// Production composition requires independently configured pinned issuer
    /// trust, durable nonce state and a protected revocation frontier.
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
            metrics_flushed: AtomicBool::new(false),
            original_evidence_bound: false,
        }
    }

    /// Source-level production composition with a separately durable
    /// business-tick intent. The WAL must be securely bootstrapped under an
    /// independently owned directory; a signed nonce is not a replay fence.
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
            metrics_flushed: AtomicBool::new(false),
            original_evidence_bound: false,
        }
    }

    /// Bootstrap the real intent WAL from an externally provisioned private
    /// path and the actual Neuron journal's verified scope/generation.
    /// This never substitutes an in-memory model-effect ledger.
    pub fn new_authorized_durable_from_path(
        runtime: NeuronRuntime<W>,
        inference_control: P,
        neuron_owner_id: StableId,
        final_use: FinalUseAuthority,
        ndu_read_verifier: NduReadVerifierV1,
        path: &std::path::Path,
        max_records: usize,
    ) -> Result<Self, crate::neuron_effect_bootstrap::NeuronEffectBootstrapErrorV1> {
        let intent = crate::neuron_effect_bootstrap::bootstrap_durable_neuron_effect_intent_v1(
            path,
            runtime.journal_scope(),
            runtime.generation(),
            max_records,
        )?;
        Ok(Self::new_authorized_durable(
            runtime,
            inference_control,
            neuron_owner_id,
            final_use,
            ndu_read_verifier,
            intent,
        ))
    }

    /// Observation-only compatibility path: a caller-provided trait object
    /// cannot claim provenance from the original Evidence WAL owner.
    pub fn with_metric_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        self.metrics_flushed.store(false, Ordering::Release);
        self.original_evidence_bound = false;
        self.metric_sink = Some(sink);
        self
    }

    /// Existing real Evidence-owned group-commit writer, NOT a signer.
    /// The caller must separately authenticate NDU/Control/CNS/Final-use.
    pub(crate) fn with_original_evidence_sink(
        mut self,
        sink: Arc<codex_hepta_evidence::metrics_sink::DurablePhaseMetricSinkV1>,
    ) -> Self {
        self.metrics_flushed.store(false, Ordering::Release);
        self.original_evidence_bound = true;
        self.metric_sink = Some(sink);
        self
    }

    pub fn production_metrics_ready(&self) -> bool {
        if !effect_intent_ready_v1(self.effect_intent_status()) {
            return false;
        }
        metrics_ready_v1(
            self.metric_sink.as_deref(),
            &self.failed_metrics,
            &self.metrics_flushed,
            self.original_evidence_bound,
        )
    }

    /// Wait for original Evidence's bounded real group-fsync ACK.
    pub fn flush_production_metrics(&self) -> bool {
        if !effect_intent_ready_v1(self.effect_intent_status()) {
            self.metrics_flushed.store(false, Ordering::Release);
            return false;
        }
        flush_metrics_v1(
            self.metric_sink.as_deref(),
            &self.failed_metrics,
            &self.metrics_flushed,
            self.original_evidence_bound,
        )
    }

    pub fn effect_intent_status(&self) -> Option<NeuronEffectIntentStatusV1> {
        self.effect_intent
            .as_ref()
            .map(DurableNeuronEffectIntentV1::status)
    }

    /// Boot-only readback from the ORIGINAL locked business-effect WAL;
    /// never a public authority or a new model invocation path.
    pub(crate) fn recovered_completed_effect_ids_v1(&self) -> Option<Vec<Digest32>> {
        self.effect_intent
            .as_ref()?
            .completed_tick_digests_v1()
            .ok()
    }

    /// The old unsigned entry is not a serving path.
    #[deprecated(note = "unsigned Agentd neuron ticks are denied; use tick_bound")]
    pub fn tick(
        &mut self,
        _input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        Err(NeuronRuntimeError::InvalidInput)
    }

    /// A physical effect cannot begin without an original Evidence fsync
    /// frontier, and its positive result cannot leave before terminal fsync.
    /// An indeterminate telemetry barrier NEVER authorizes model replay.
    pub fn tick_bound(
        &mut self,
        input: NeuronTickInputV1,
        signed_read: &SignedNduSnapshotReadV1,
        signed_grant: &SignedFinalUseGrant,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        // The installed non-test Agentd still lacks independent ORIGINAL
        // Control Begin/CNS signed effect/Commit custody. Refuse before
        // writing even a negative Evidence row: otherwise an untrusted call
        // would persist telemetry without an Effect Intent, making the
        // next legitimate cold restart look like torn execution history.
        // This is a deny-only hold, NOT a route to mint Control authority.
        if !cfg!(test) {
            return Err(NeuronRuntimeError::OriginalEffectOwnerUnverified);
        }
        let operation_digest = input.semantic_digest()?;
        begin_signed_tick_v1(
            self.metric_sink.as_deref(),
            &self.failed_metrics,
            &self.metrics_flushed,
            self.original_evidence_bound,
        )?;
        // Evidence must use the independently recovered Neuron Journal's
        // domain-separated scope, never a caller-supplied bare subject hash.
        let journal_scope = self.runtime.journal_scope();
        let started = Instant::now();
        let result = self.tick_bound_inner(input, signed_read, signed_grant);
        if !observe_and_commit_neuron_phase_v1(
            self.metric_sink.as_deref(),
            &self.failed_metrics,
            &self.metrics_flushed,
            self.original_evidence_bound,
            journal_scope,
            operation_digest,
            started.elapsed(),
            result.is_ok(),
        ) {
            return Err(NeuronRuntimeError::TelemetryIndeterminate);
        }
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
        let authenticated_read_receipt_digest = read_verifier
            .verify(signed_read)
            .map_err(|_| NeuronRuntimeError::InvalidInput)?;
        let snapshot = &signed_read.snapshot;
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
        if signed_grant.grant.binding != binding {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        // The old signed-only constructor cannot publish physical effects:
        // no durable business-tick Prepare means crash recovery could replay
        // a second grant for the same already-entered model invocation.
        let effect_intent = self
            .effect_intent
            .as_mut()
            .ok_or(NeuronRuntimeError::PendingReconciliation)?;
        let mut model = InferenceControlModelPort::new(&mut self.inference_control);
        self.runtime.tick_with_ndu_snapshot(
            &mut model,
            input,
            NeuronSignedEffectAdmissionV1 {
                snapshot,
                admitted_read_receipt_digest: authenticated_read_receipt_digest,
                effect_intent,
                neuron_owner_id: owner_id,
                authority,
                signed_grant,
            },
            || {
                read_verifier
                    .verify(signed_read)
                    .map_err(|_| NeuronRuntimeError::InvalidInput)
            },
        )
    }

    /// Read-only diagnostics. Mutable runtime/worker access is intentionally
    /// not exposed: it would bypass the exact signed owner entry.
    pub fn runtime(&self) -> &NeuronRuntime<W> {
        &self.runtime
    }
}

/// A durable unresolved original model effect must not be declared ready
/// merely because the independent Evidence writer reports a healthy fsync.
fn effect_intent_ready_v1(status: Option<NeuronEffectIntentStatusV1>) -> bool {
    status.is_some_and(|intent| !intent.poisoned && intent.unresolved_tick.is_none())
}

/// Real elapsed-time observation only. Metrics cannot mint an authority,
/// overwrite committed state or replay an ambiguous signed Neuron effect.
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

/// Queue health and an unsigned callback are not original Evidence custody.
fn metrics_ready_v1(
    sink: Option<&dyn PhaseMetricSinkV1>,
    failed_metrics: &AtomicU64,
    metrics_flushed: &AtomicBool,
    original_evidence_bound: bool,
) -> bool {
    original_evidence_bound
        && metrics_flushed.load(Ordering::Acquire)
        && failed_metrics.load(Ordering::Acquire) == 0
        && sink.is_some_and(|writer| writer.healthy())
}

/// Consume the last fsync ACK before entering the next signed tick.
fn begin_signed_tick_v1(
    sink: Option<&dyn PhaseMetricSinkV1>,
    failed_metrics: &AtomicU64,
    metrics_flushed: &AtomicBool,
    original_evidence_bound: bool,
) -> Result<(), NeuronRuntimeError> {
    if !metrics_ready_v1(
        sink,
        failed_metrics,
        metrics_flushed,
        original_evidence_bound,
    ) {
        return Err(NeuronRuntimeError::PendingReconciliation);
    }
    metrics_flushed.store(false, Ordering::Release);
    Ok(())
}

fn flush_metrics_v1(
    sink: Option<&dyn PhaseMetricSinkV1>,
    failed_metrics: &AtomicU64,
    metrics_flushed: &AtomicBool,
    original_evidence_bound: bool,
) -> bool {
    if !original_evidence_bound || failed_metrics.load(Ordering::Acquire) != 0 {
        return false;
    }
    let Some(sink) = sink else {
        return false;
    };
    if !sink.healthy() || sink.flush().is_err() || !sink.healthy() {
        failed_metrics.fetch_add(1, Ordering::Release);
        metrics_flushed.store(false, Ordering::Release);
        return false;
    }
    metrics_flushed.store(true, Ordering::Release);
    metrics_ready_v1(
        Some(sink),
        failed_metrics,
        metrics_flushed,
        original_evidence_bound,
    )
}

/// Record exactly one actual signed Neuron call and require its original
/// Evidence FIFO fsync ACK before releasing a successful outcome.
fn observe_and_commit_neuron_phase_v1(
    sink: Option<&dyn PhaseMetricSinkV1>,
    failed_metrics: &AtomicU64,
    metrics_flushed: &AtomicBool,
    original_evidence_bound: bool,
    journal_scope: JournalScope,
    operation_digest: Digest32,
    elapsed: Duration,
    succeeded: bool,
) -> bool {
    let Some(sink) = sink else {
        failed_metrics.fetch_add(1, Ordering::Release);
        return false;
    };
    if !original_evidence_bound {
        failed_metrics.fetch_add(1, Ordering::Release);
        return false;
    }
    observe_phase_v1(
        Some(sink),
        failed_metrics,
        journal_scope.scope_digest,
        operation_digest,
        PhaseMetricKindV1::NeuronFeature,
        elapsed,
        succeeded,
    );
    flush_metrics_v1(
        Some(sink),
        failed_metrics,
        metrics_flushed,
        original_evidence_bound,
    )
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
