//! Authenticated bounded worker-side inference microbatch execution.
//!
//! The planner is not an effect owner. Each dequeued item is independently
//! checked against the loaded model and a fresh kernel-authority signed,
//! one-shot final-use grant. The existing real model driver runs each item.
//! This batches admission and shared storage, not GPU execution kernels.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_agentd::DurablePhaseMetricSinkV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::microbatch::BoundedMicrobatchSchedulerV1;
use codex_hepta_infer_core::microbatch::InferenceIntentV1;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_infer_core::microbatch::MicrobatchLimitsV1;
use codex_hepta_infer_core::microbatch::SchedulerErrorV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::PhaseMetricEventV1;
use codex_hepta_types::PhaseMetricKindV1;
use codex_hepta_types::PhaseMetricSinkV1;
use codex_hepta_types::StableId;

use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest_with_slice;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;

// This is a generation-lifetime deduplication bound, not the concurrent
// scheduler max_pending. Exhaustion requires an externally fenced rollover.
const MAX_WORKER_RETIRED_IDS: usize = 1_048_576;

fn retired_identity(id: &StableId) -> Digest32 {
    Digest32::of_parts(&[b"hepta.worker.retired-request.v1", id.as_str().as_bytes()])
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BatchWorkerErrorV1 {
    InvalidRequest,
    InvalidBinding,
    Duplicate,
    NoAdmission,
    Scheduler(SchedulerErrorV1),
    Authority,
    Worker,
    BatchUnsupported,
    /// The configured Evidence sink failed or was unhealthy before effect.
    /// Callers must reconcile durable intents; the Worker never replays.
    MetricsUnavailable,
    /// The scheduler accepted the request, but its Admission Evidence write
    /// failed. The original identity may remain pending; reconcile it rather
    /// than treating this error as proof that enqueue never happened.
    AdmissionTelemetryIndeterminate,
    /// The model effect MAY have executed and its original Final-use nonce
    /// MAY be consumed, but terminal Evidence recording or commit failed.
    /// The caller
    /// must reconcile the exact request, never treat this as a safe retry.
    /// A single missing batch member also withholds all successful receipts
    /// for that one physical batch, without altering its real effects.
    TerminalTelemetryIndeterminate,
    /// The monotonic observation crossed this request's execution deadline
    /// before entering a model backend. No late request is executed.
    DeadlineExpired,
    /// A live CNS scope frontier advanced or a deadline elapsed while the
    /// external backend ran. Treat its outcome as unresolved; never publish
    /// the stale result as success or automatically replay the effect.
    StaleAfterEffect,
    Capacity,
}

#[derive(Debug)]
pub struct BatchWorkerItemOutcomeV1 {
    pub request_id: StableId,
    pub result: Result<NeuronFeatureReceiptV1, BatchWorkerErrorV1>,
}

#[derive(Debug)]
pub struct BatchWorkerPollV1 {
    pub expired: Vec<StableId>,
    pub outcomes: Vec<BatchWorkerItemOutcomeV1>,
    pub scanned_lanes: usize,
    pub pending: usize,
}

/// Read the authoritative, live Control/CNS route binding for a Scope.
/// A consumer-provided key or a signed historical grant is not currentness.
/// The production composition must inject its original Control-owned reader;
/// this port alone does not establish atomic effect/cutover linearization.
pub trait MicrobatchScopeFrontierV1: std::fmt::Debug + Send + Sync {
    fn current(&self, scope: &StableId) -> Result<MicrobatchKeyV1, BatchWorkerErrorV1>;
}

fn scope_binding_current(
    frontier: Option<&Arc<dyn MicrobatchScopeFrontierV1>>,
    key: &MicrobatchKeyV1,
) -> bool {
    frontier
        .and_then(|owner| owner.current(&key.scope_id).ok())
        .as_ref()
        == Some(key)
}

/// Account for time spent in telemetry, signature verification, prior requests
/// and the actual device call. Caller time is the starting observation only.
fn dispatch_now_ms_v1(observed_at_ms: u64, started: Instant) -> u64 {
    observed_at_ms.saturating_add(u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX))
}

struct PendingV1 {
    model_id: String,
    request: NeuronFeatureRequest,
    feature: SharedFeatureBufferV1,
    signed: SignedFinalUseGrant,
    binding: FinalUseBinding,
}

/// One exclusive batch owner; no API exposes its underlying worker mutably.
/// Recovered durable control state must independently resolve all orphaned
/// requests before constructing this in-memory queue again.
pub struct AuthenticatedNeuronMicrobatchWorkerV1<D: ModelDriver + NeuronFeatureDriver> {
    scheduler: BoundedMicrobatchSchedulerV1,
    worker: InferenceWorker<D>,
    authority: FinalUseAuthority,
    // Absent until independent Control composition installs a live reader.
    // No new admission or backend effect may proceed while it is absent.
    scope_frontier: Option<Arc<dyn MicrobatchScopeFrontierV1>>,
    // A Control reader cannot be rebound once installed or once an
    // admission/cutover/poll has started. This does not attest its origin.
    frontier_binding_frozen: bool,
    // A late sink must never make uninstrumented historical work "ready".
    unmetered_activity: bool,
    // The very first successfully queued intent fixes a lifetime monotonic
    // anchor. Replaying a nondecreasing but frozen caller now_ms cannot
    // extend its own deadline across future polls.
    queue_clock_anchor: Option<(u64, Instant)>,
    // Preserve the original raw caller clock too: max(raw, monotonic anchor)
    // must never hide a caller timestamp regression and silently bypass the
    // scheduler's ClockRegressed fail-closed contract.
    last_caller_now_ms: Option<u64>,
    pending: BTreeMap<StableId, PendingV1>,
    retired: BTreeSet<Digest32>,
    metric_sink: Option<Arc<dyn PhaseMetricSinkV1>>,
    // Only the same-crate original Evidence bootstrap may mark this true
    // after binding a CONCRETE DurablePhaseMetricSinkV1. A generic caller
    // with an arbitrary PhaseMetricSinkV1 must not execute signed effects
    // in non-test binaries even if its sink lies about fsync/healthy().
    original_evidence_bound: bool,
    #[cfg(test)]
    research_test_effects_allowed: bool,
    failed_metrics: AtomicU64,
    // healthy() alone does not mean Evidence has fsynced the asynchronous
    // Record queue. Only an explicit successful post-record flush can
    // re-establish production telemetry readiness.
    metrics_flushed: AtomicBool,
    maximum_pending: usize,
}

pub fn neuron_batch_final_use_binding_v1(
    worker_id: &str,
    key: &MicrobatchKeyV1,
    request: &NeuronFeatureRequest,
) -> Result<FinalUseBinding, BatchWorkerErrorV1> {
    neuron_batch_final_use_binding_with_slice_v1(
        worker_id,
        key,
        request,
        &request.feature_vector_q24,
    )
}

/// Revalidate final-use using the identical, immutable Arc-backed Q24 slice
/// that was sealed at admission. Never rematerialize an owned request to hash.
fn neuron_batch_final_use_binding_with_slice_v1(
    worker_id: &str,
    key: &MicrobatchKeyV1,
    request: &NeuronFeatureRequest,
    features: &[i64],
) -> Result<FinalUseBinding, BatchWorkerErrorV1> {
    let payload_hex = canonical_neuron_feature_payload_digest_with_slice(request, features);
    if request.authorization.payload_digest != payload_hex
        || request.authorization.lease_payload_digest != payload_hex
        || Digest32::from_str(&request.authorization.model_digest).ok() != Some(key.model_digest)
    {
        return Err(BatchWorkerErrorV1::InvalidBinding);
    }
    let payload_digest =
        Digest32::from_str(&payload_hex).map_err(|_| BatchWorkerErrorV1::InvalidBinding)?;
    // Exact-request final use must also cover quota, reservation model, and
    // cancellation state. A signed feature payload alone does not authorize
    // changes to the surrounding worker/reservation claims.
    let authorization = &request.authorization;
    let mut request_bytes = b"hepta.worker.batch-request.v1".to_vec();
    for field in [
        authorization.request_id.as_bytes(),
        authorization.reservation_id.as_bytes(),
        authorization.model_digest.as_bytes(),
        authorization.reservation_model_digest.as_bytes(),
    ] {
        request_bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        request_bytes.extend_from_slice(field);
    }
    request_bytes.extend_from_slice(&authorization.deadline_ms.to_be_bytes());
    request_bytes.extend_from_slice(&authorization.maximum_tokens.to_be_bytes());
    request_bytes.extend_from_slice(&authorization.reservation_maximum_tokens.to_be_bytes());
    request_bytes.push(u8::from(authorization.cancelled));
    request_bytes.extend_from_slice(payload_digest.as_array());

    let mut scope_bytes = b"hepta.worker.batch-scope.v1".to_vec();
    for field in [key.scope_id.as_str().as_bytes(), worker_id.as_bytes()] {
        scope_bytes.extend_from_slice(&(field.len() as u64).to_be_bytes());
        scope_bytes.extend_from_slice(field);
    }
    scope_bytes.extend_from_slice(key.model_digest.as_array());
    scope_bytes.extend_from_slice(&key.generation.get().to_be_bytes());
    scope_bytes.extend_from_slice(&key.route_fence.to_be_bytes());
    scope_bytes.extend_from_slice(&key.authority_epoch.to_be_bytes());
    Ok(FinalUseBinding {
        subject_id: key.scope_id.to_string(),
        destination_id: worker_id.to_string(),
        request_sha256: *Digest32::of_bytes(&request_bytes).as_array(),
        scope_sha256: *Digest32::of_bytes(&scope_bytes).as_array(),
        payload_sha256: *payload_digest.as_array(),
    })
}

impl<D: ModelDriver + NeuronFeatureDriver> AuthenticatedNeuronMicrobatchWorkerV1<D> {
    pub fn new(
        worker: InferenceWorker<D>,
        authority: FinalUseAuthority,
        limits: MicrobatchLimitsV1,
    ) -> Result<Self, BatchWorkerErrorV1> {
        let scheduler =
            BoundedMicrobatchSchedulerV1::new(limits).map_err(BatchWorkerErrorV1::Scheduler)?;
        Ok(Self {
            scheduler,
            worker,
            authority,
            scope_frontier: None,
            frontier_binding_frozen: false,
            unmetered_activity: false,
            queue_clock_anchor: None,
            last_caller_now_ms: None,
            pending: BTreeMap::new(),
            retired: BTreeSet::new(),
            metric_sink: None,
            original_evidence_bound: false,
            #[cfg(test)]
            research_test_effects_allowed: false,
            failed_metrics: AtomicU64::new(0),
            metrics_flushed: AtomicBool::new(false),
            maximum_pending: limits.max_pending,
        })
    }

    /// A compatibility builder for source-only callers. Refusing a late
    /// replacement permanently poisons production readiness, rather than
    /// silently accepting a fresh journal as historical Evidence.
    pub fn with_metric_sink(mut self, sink: Arc<dyn PhaseMetricSinkV1>) -> Self {
        let _ = self.bind_metric_sink(sink);
        self
    }

    /// Bind one Evidence-owned sink before any request admission or poll.
    /// Replacing the original sink would lose the correlation between the
    /// model effects and their emitted Admission/terminal metric history.
    /// The original sink is retained and a rebinding attempt poisons further
    /// effects, even when the caller presents a healthy replacement.
    pub fn bind_metric_sink(
        &mut self,
        sink: Arc<dyn PhaseMetricSinkV1>,
    ) -> Result<(), BatchWorkerErrorV1> {
        if self.metric_sink.is_some()
            || self.frontier_binding_frozen
            || self.unmetered_activity
            || self.failed_metrics.load(Ordering::Acquire) != 0
        {
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return Err(BatchWorkerErrorV1::MetricsUnavailable);
        }
        self.metric_sink = Some(sink);
        self.metrics_flushed.store(false, Ordering::Release);
        Ok(())
    }

    /// Only the original Evidence-bound product composition can call this
    /// crate-private typed binder. Generic public metric binders remain
    /// research/test compatibility paths and never mint this provenance.
    pub(crate) fn bind_original_evidence_sink(
        &mut self,
        sink: Arc<DurablePhaseMetricSinkV1>,
    ) -> Result<(), BatchWorkerErrorV1> {
        self.bind_metric_sink(sink)?;
        self.original_evidence_bound = true;
        Ok(())
    }

    /// Bind exactly one original Control-owned live frontier at startup.
    /// Do not permit a stale reader to replace it later, even if the local
    /// queue is empty. An untrusted caller-supplied reader is NOT attested by
    /// this method; the production composition owns provenance verification.
    pub fn bind_live_scope_frontier(
        &mut self,
        frontier: Arc<dyn MicrobatchScopeFrontierV1>,
    ) -> Result<(), BatchWorkerErrorV1> {
        if self.frontier_binding_frozen || self.scope_frontier.is_some() {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        self.scope_frontier = Some(frontier);
        Ok(())
    }

    fn binding_current(&self, key: &MicrobatchKeyV1) -> bool {
        scope_binding_current(self.scope_frontier.as_ref(), key)
    }

    /// The monotonic anchor must never turn a regressing raw caller timestamp
    /// into an apparently valid effective timestamp. Only successful queue
    /// operations advance this watermark. Rejected future-dated admissions
    /// and rejected polls cannot poison it.
    fn validate_caller_now_ms(&self, observed_ms: u64) -> Result<(), BatchWorkerErrorV1> {
        if self
            .last_caller_now_ms
            .is_some_and(|last| observed_ms < last)
        {
            return Err(BatchWorkerErrorV1::Scheduler(
                SchedulerErrorV1::ClockRegressed,
            ));
        }
        Ok(())
    }

    /// Prevent indefinitely extending a queued intent by reusing the same
    /// previously admitted caller timestamp in a later poll or enqueue.
    /// Initial timestamp provenance still belongs to the real Control owner.
    fn queue_effective_now_ms(&self, observed_ms: u64) -> u64 {
        let Some((anchored_ms, anchored_at)) = self.queue_clock_anchor else {
            return observed_ms;
        };
        observed_ms.max(dispatch_now_ms_v1(anchored_ms, anchored_at))
    }

    /// Research-only runs may omit a sink, but such runs can never satisfy
    /// production_metrics_ready. Once a sink is configured, any failure is a
    /// permanent rejection gate for new effects in this Worker lifetime.
    fn original_evidence_or_test_fixture_ready(&self) -> bool {
        #[cfg(test)]
        {
            self.original_evidence_bound || self.research_test_effects_allowed
        }
        #[cfg(not(test))]
        {
            self.original_evidence_bound
        }
    }

    fn metrics_available_for_effect(&self) -> bool {
        // Test-only research drivers still exercise historical scalar/native
        // fixtures without a physical Evidence writer. Production binaries
        // must enter through the typed original-Evidence owner, not through
        // a public generic sink that can forge a flush ACK.
        self.original_evidence_or_test_fixture_ready()
            && self.failed_metrics.load(Ordering::Acquire) == 0
            && self.metric_sink.as_ref().is_none_or(|sink| sink.healthy())
    }

    /// Production readiness is a separate Evidence barrier, never implicit
    /// authorization from one successful model execution. A failed write
    /// remains latched even if the current metric sink later reports healthy.
    pub fn production_metrics_ready(&self) -> bool {
        self.original_evidence_or_test_fixture_ready()
            && self.scope_frontier.is_some()
            && !self.unmetered_activity
            && self.metrics_flushed.load(Ordering::Acquire)
            && self.metric_sink.as_ref().is_some_and(|sink| sink.healthy())
            && self.failed_metrics.load(Ordering::Acquire) == 0
    }

    /// Flush only after worker effects have settled; do not replay an effect
    /// when telemetry is uncommitted or unavailable.
    pub fn flush_production_metrics(&self) -> bool {
        let Some(sink) = &self.metric_sink else {
            return false;
        };
        if sink.flush().is_err() {
            self.metrics_flushed.store(false, Ordering::Release);
            self.failed_metrics.fetch_add(1, Ordering::Release);
            return false;
        }
        // The Worker owns all mutable dispatch paths, and callers invoke
        // this barrier only after in-flight effects have settled. Any
        // subsequent metric record invalidates this acknowledgement.
        self.metrics_flushed.store(true, Ordering::Release);
        self.production_metrics_ready()
    }

    pub fn pending(&self) -> usize {
        self.pending.len()
    }

    /// Admission copies no feature vector; queued payloads share Arc<[i64]>.
    /// Final-use signature verification and durable nonce claim occur only at
    /// actual worker execution, immediately before the model driver is called.
    pub fn enqueue(
        &mut self,
        now_ms: u64,
        model_id: String,
        request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        self.frontier_binding_frozen = true;
        if self.metric_sink.is_none() {
            self.unmetered_activity = true;
        }
        let started = Instant::now();
        let caller_now_ms = now_ms;
        let now_ms = self.queue_effective_now_ms(now_ms);
        let scope_digest = Digest32::of_bytes(key.scope_id.as_str().as_bytes());
        let operation_digest = Digest32::of_bytes(request.authorization.request_id.as_bytes());
        // Keep failed Admission telemetry observable without allowing an
        // invalid caller clock to consume a queue ID or a Final-use nonce.
        let result = self
            .validate_caller_now_ms(caller_now_ms)
            .and_then(|()| self.enqueue_inner(now_ms, model_id, request, key, signed));
        let queued = result.is_ok();
        if queued {
            self.last_caller_now_ms = Some(caller_now_ms);
        }
        if queued && self.queue_clock_anchor.is_none() {
            // Only a successful scheduler admission sets the anchor. A
            // rejected future-dated request must not poison the owner clock.
            self.queue_clock_anchor = Some((now_ms, started));
        }
        if let Some(sink) = &self.metric_sink {
            self.metrics_flushed.store(false, Ordering::Release);
            let metric_result = sink.record(PhaseMetricEventV1 {
                scope_digest,
                operation_digest,
                phase: PhaseMetricKindV1::Admission,
                latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
                succeeded: result.is_ok(),
            });
            if metric_result.is_err() {
                self.failed_metrics.fetch_add(1, Ordering::Release);
                if queued {
                    // The queue now owns this identity, but Evidence did not
                    // acknowledge its admission. No signed effect may follow
                    // until the original durable owner reconciles the intent.
                    return Err(BatchWorkerErrorV1::AdmissionTelemetryIndeterminate);
                }
            }
        }
        result
    }

    fn enqueue_inner(
        &mut self,
        now_ms: u64,
        model_id: String,
        mut request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        if !self.metrics_available_for_effect() {
            return Err(BatchWorkerErrorV1::MetricsUnavailable);
        }
        let id = StableId::new(request.authorization.request_id.clone())
            .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        if self.retired.contains(&retired_identity(&id)) || self.pending.contains_key(&id) {
            return Err(BatchWorkerErrorV1::Duplicate);
        }
        if self.pending.len() >= self.maximum_pending
            || self.retired.len() + self.pending.len() >= MAX_WORKER_RETIRED_IDS
        {
            return Err(BatchWorkerErrorV1::Capacity);
        }
        if key.generation.get() != self.worker.worker_generation()
            || key.authority_epoch != self.worker.authority_epoch()
            || signed.grant.authority_epoch != key.authority_epoch
            || !self
                .worker
                .model_matches_digest(&model_id, key.model_digest)
            || request.authorization.cancelled
            || !self.binding_current(&key)
        {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let binding = neuron_batch_final_use_binding_v1(self.worker.worker_id(), &key, &request)?;
        if signed.grant.binding != binding {
            return Err(BatchWorkerErrorV1::InvalidBinding);
        }
        let feature =
            SharedFeatureBufferV1::from_vec(std::mem::take(&mut request.feature_vector_q24))
                .map_err(|_| BatchWorkerErrorV1::InvalidRequest)?;
        self.scheduler
            .enqueue(
                now_ms,
                InferenceIntentV1 {
                    request_id: id.clone(),
                    key,
                    feature_digest: feature.digest(),
                    shared_features: Some(feature.clone()),
                    deadline_ms: request.authorization.deadline_ms,
                },
            )
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        self.pending.insert(
            id,
            PendingV1 {
                model_id,
                request,
                feature,
                signed,
                binding,
            },
        );
        Ok(())
    }

    /// Never replay an unknown or failed external effect. Every result,
    /// including authority denial, is terminal within this local generation.
    pub fn poll_and_execute(
        &mut self,
        now_ms: u64,
    ) -> Result<BatchWorkerPollV1, BatchWorkerErrorV1> {
        self.frontier_binding_frozen = true;
        if self.metric_sink.is_none() {
            self.unmetered_activity = true;
        }
        // Fail before dequeue if Admission telemetry poisoned this owner.
        // Keep already durably admitted intent identities available for
        // original-owner reconciliation, never invoke or retry a backend.
        if !self.metrics_available_for_effect() {
            return Err(BatchWorkerErrorV1::MetricsUnavailable);
        }
        // A fresh poll-local Instant alone cannot account for time spent in
        // the queue if a caller resubmits a stale but nonregressing clock.
        // Reject raw regressions *before* the anchored max() can hide them.
        self.validate_caller_now_ms(now_ms)?;
        let caller_now_ms = now_ms;
        let now_ms = self.queue_effective_now_ms(now_ms);
        let started = Instant::now();
        let poll = self
            .scheduler
            .poll_physically_compatible(now_ms)
            .map_err(BatchWorkerErrorV1::Scheduler)?;
        self.last_caller_now_ms = Some(caller_now_ms);
        // Carry only small immutable request identity/fence metadata across
        // execution. No Q24 feature vector or model payload is copied.
        // Final receipt publication rechecks every original member AFTER
        // the Evidence writer has confirmed the durable flush.
        let publication_checks: BTreeMap<StableId, (MicrobatchKeyV1, u64)> = poll
            .batch
            .as_ref()
            .map(|batch| {
                batch
                    .requests
                    .iter()
                    .map(|intent| {
                        (
                            intent.request_id.clone(),
                            (intent.key.clone(), intent.deadline_ms),
                        )
                    })
                    .collect()
            })
            .unwrap_or_default();
        if let (Some(sink), Some(batch)) = (&self.metric_sink, &poll.batch) {
            self.metrics_flushed.store(false, Ordering::Release);
            // One phase sample per admitted request, not just the first
            // member of a batch (which would silently undercount throughput).
            for intent in &batch.requests {
                let metric_result = sink.record(PhaseMetricEventV1 {
                    scope_digest: Digest32::of_bytes(intent.key.scope_id.as_str().as_bytes()),
                    operation_digest: Digest32::of_bytes(intent.request_id.as_str().as_bytes()),
                    phase: PhaseMetricKindV1::Microbatch,
                    latency_micros: u64::try_from(started.elapsed().as_micros())
                        .unwrap_or(u64::MAX),
                    succeeded: true,
                });
                if metric_result.is_err() {
                    self.failed_metrics.fetch_add(1, Ordering::Release);
                }
            }
        }
        for id in &poll.expired_request_ids {
            self.pending.remove(id);
            self.retired.insert(retired_identity(&id));
        }
        let mut outcomes = Vec::new();
        if let Some(batch) = poll.batch {
            if !self.metrics_available_for_effect() {
                // An Evidence record failed *after* dequeue but before any
                // Final-use claim. Deny all members explicitly and retire
                // their queue identities without entering the driver.
                for intent in batch.requests {
                    let id = intent.request_id;
                    self.pending.remove(&id);
                    self.retired.insert(retired_identity(&id));
                    outcomes.push(BatchWorkerItemOutcomeV1 {
                        request_id: id,
                        result: Err(BatchWorkerErrorV1::MetricsUnavailable),
                    });
                }
                return Ok(BatchWorkerPollV1 {
                    expired: poll.expired_request_ids,
                    outcomes,
                    scanned_lanes: poll.scanned_lanes,
                    pending: self.pending.len(),
                });
            }
            if batch.requests.len() > 1 {
                outcomes.extend(self.execute_native_batch(
                    now_ms,
                    started,
                    &batch.key,
                    batch.requests,
                ));
            } else {
                for intent in batch.requests {
                    let id = intent.request_id;
                    self.retired.insert(retired_identity(&id));
                    let outcome = match self.pending.remove(&id) {
                        None => Err(BatchWorkerErrorV1::NoAdmission),
                        Some(mut pending) => {
                            if !self.metrics_available_for_effect() {
                                Err(BatchWorkerErrorV1::MetricsUnavailable)
                            } else if intent.deadline_ms <= dispatch_now_ms_v1(now_ms, started) {
                                Err(BatchWorkerErrorV1::DeadlineExpired)
                            } else if pending.feature.digest() != intent.feature_digest
                                || pending.signed.grant.authority_epoch
                                    != intent.key.authority_epoch
                                || !self.binding_current(&intent.key)
                            {
                                Err(BatchWorkerErrorV1::InvalidBinding)
                            } else {
                                pending.request.feature_vector_q24 =
                                    pending.feature.as_slice().to_vec();
                                let start = Instant::now();
                                let frontier = self.scope_frontier.clone();
                                let key = intent.key;
                                let deadline_ms = intent.deadline_ms;
                                let mut result = FinalUseAuthority::claim(
                                    &self.authority,
                                    &pending.signed,
                                    &pending.binding,
                                )
                                .map_err(|_| BatchWorkerErrorV1::Authority)
                                .and_then(|token| {
                                    FinalUseAuthority::with_verified_effect(
                                        &self.authority,
                                        token,
                                        &pending.binding,
                                        || {
                                            if !scope_binding_current(frontier.as_ref(), &key) {
                                                return Err(BatchWorkerErrorV1::InvalidBinding);
                                            }
                                            let effect_now_ms = dispatch_now_ms_v1(now_ms, started);
                                            if effect_now_ms >= deadline_ms {
                                                return Err(BatchWorkerErrorV1::DeadlineExpired);
                                            }
                                            let result = self
                                                .worker
                                                .run_neuron_features_receipt(
                                                    effect_now_ms,
                                                    &pending.model_id,
                                                    pending.request,
                                                )
                                                .map_err(|_| BatchWorkerErrorV1::Worker);
                                            if !scope_binding_current(frontier.as_ref(), &key)
                                                || dispatch_now_ms_v1(now_ms, started)
                                                    >= deadline_ms
                                            {
                                                return Err(BatchWorkerErrorV1::StaleAfterEffect);
                                            }
                                            result
                                        },
                                    )
                                    .map_err(|_| BatchWorkerErrorV1::Authority)?
                                });
                                if let Some(sink) = &self.metric_sink {
                                    self.metrics_flushed.store(false, Ordering::Release);
                                    let metric_result = sink.record(PhaseMetricEventV1 {
                                        scope_digest: Digest32::of_bytes(
                                            batch.key.scope_id.as_str().as_bytes(),
                                        ),
                                        operation_digest: Digest32::of_bytes(
                                            id.as_str().as_bytes(),
                                        ),
                                        phase: PhaseMetricKindV1::NeuronFeature,
                                        latency_micros: u64::try_from(start.elapsed().as_micros())
                                            .unwrap_or(u64::MAX),
                                        succeeded: matches!(
                                            &result,
                                            Ok(receipt) if receipt.status
                                                == NeuronFeatureTerminalStatusV1::Succeeded
                                        ),
                                    });
                                    if metric_result.is_err() {
                                        self.failed_metrics.fetch_add(1, Ordering::Release);
                                        // The signed effect cannot be undone. Do not publish
                                        // a successful receipt without its terminal Evidence.
                                        if result.is_ok() {
                                            result = Err(
                                                BatchWorkerErrorV1::TerminalTelemetryIndeterminate,
                                            );
                                        }
                                    }
                                }
                                result
                            }
                        }
                    };
                    outcomes.push(BatchWorkerItemOutcomeV1 {
                        request_id: id,
                        result: outcome,
                    });
                }
            }
        }
        // An accepted async Evidence record is not an fsynced WAL row.
        // Publish no successful signed effect while its terminal evidence
        // remains in the writer queue. Flush outside all Final-use fences,
        // after the original backend and its terminal records have settled.
        if self.metric_sink.is_some() && outcomes.iter().any(|item| item.result.is_ok()) {
            if !self.flush_production_metrics() {
                // The physical effect has already happened. The original
                // durable nonce/identity remains consumed; a failure to
                // confirm the group commit can never authorize a retry.
                for item in &mut outcomes {
                    if item.result.is_ok() {
                        item.result = Err(BatchWorkerErrorV1::TerminalTelemetryIndeterminate);
                    }
                }
            } else {
                // A real fsync may block while Control moves the CNS route
                // or an individual member crosses its deadline. The batch
                // is not partly publishable even after durable Evidence.
                let after_commit_ms = dispatch_now_ms_v1(now_ms, started);
                let stale = outcomes.iter().any(|item| {
                    item.result.is_ok()
                        && publication_checks
                            .get(&item.request_id)
                            .is_none_or(|(key, deadline)| {
                                *deadline <= after_commit_ms || !self.binding_current(key)
                            })
                });
                if stale {
                    for item in &mut outcomes {
                        if item.result.is_ok() {
                            item.result = Err(BatchWorkerErrorV1::StaleAfterEffect);
                        }
                    }
                }
            }
        }
        Ok(BatchWorkerPollV1 {
            expired: poll.expired_request_ids,
            outcomes,
            scanned_lanes: poll.scanned_lanes,
            pending: self.pending.len(),
        })
    }

    /// One physical model-driver call for the entire homogeneous batch. If
    /// any member cannot be authenticated/fenced, none crosses the model
    /// boundary. All dequeued identities are terminal, even after unknown
    /// backend outcomes: replay requires external reconciliation.
    fn execute_native_batch(
        &mut self,
        now_ms: u64,
        dispatch_started: Instant,
        key: &MicrobatchKeyV1,
        intents: Vec<InferenceIntentV1>,
    ) -> Vec<BatchWorkerItemOutcomeV1> {
        let started = Instant::now();
        let mut items = Vec::with_capacity(intents.len());
        for intent in intents {
            self.retired.insert(retired_identity(&intent.request_id));
            let pending = self.pending.remove(&intent.request_id);
            items.push((intent, pending));
        }

        let executed = (|| -> Result<Vec<NeuronFeatureReceiptV1>, BatchWorkerErrorV1> {
            let mut model_id: Option<&str> = None;
            for (intent, pending) in &items {
                let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                if intent.deadline_ms <= dispatch_now_ms_v1(now_ms, dispatch_started) {
                    return Err(BatchWorkerErrorV1::DeadlineExpired);
                }
                if pending.feature.digest() != intent.feature_digest
                    || !intent.key.physical_compatible_with(key)
                    || !self.binding_current(&intent.key)
                    || pending.signed.grant.authority_epoch != intent.key.authority_epoch
                    || pending.request.authorization.request_id != intent.request_id.as_str()
                {
                    return Err(BatchWorkerErrorV1::InvalidBinding);
                }
                if let Some(previous) = model_id {
                    if previous != pending.model_id {
                        return Err(BatchWorkerErrorV1::InvalidBinding);
                    }
                } else {
                    // Reject unsupported batches before allocating or
                    // hashing any re-materialized feature vector, and before
                    // any signed nonce can be consumed.
                    if !self.worker.can_run_neuron_feature_batch(&pending.model_id) {
                        return Err(BatchWorkerErrorV1::BatchUnsupported);
                    }
                    model_id = Some(&pending.model_id);
                }
                if neuron_batch_final_use_binding_with_slice_v1(
                    self.worker.worker_id(),
                    &intent.key,
                    &pending.request,
                    pending.feature.as_slice(),
                )? != pending.binding
                {
                    return Err(BatchWorkerErrorV1::InvalidBinding);
                }
            }
            let model_id = model_id.ok_or(BatchWorkerErrorV1::NoAdmission)?.to_owned();
            // Prevalidate all members before one durable nonce-group claim.
            // A denied member never causes a partially dispatched model batch.
            let entries = items
                .iter()
                .map(|(_, pending)| {
                    let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                    Ok((&pending.signed, &pending.binding))
                })
                .collect::<Result<Vec<_>, BatchWorkerErrorV1>>()?;
            let tokens = self
                .authority
                .claim_batch(&entries)
                .map_err(|_| BatchWorkerErrorV1::Authority)?;
            let claimed = tokens
                .into_iter()
                .zip(items.iter())
                .map(|(token, (_, pending))| {
                    let pending = pending.as_ref().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                    Ok((token, pending.binding.clone()))
                })
                .collect::<Result<Vec<_>, BatchWorkerErrorV1>>()?;
            // All signed bindings were checked before the group claim. Move
            // each owned request exactly once instead of cloning its identity
            // strings and rebuilding a second request just for final-use.
            let requests = items
                .iter_mut()
                .map(|(_, pending)| {
                    let pending = pending.take().ok_or(BatchWorkerErrorV1::NoAdmission)?;
                    let mut request = pending.request;
                    request.feature_vector_q24 = pending.feature.as_slice().to_vec();
                    Ok(request)
                })
                .collect::<Result<Vec<_>, BatchWorkerErrorV1>>()?;
            // Re-read every original Scope/fence before and after the single
            // physical backend call; the representative batch key grants none
            // of its other members authority. A raced effect is unresolved.
            let frontier = self.scope_frontier.clone();
            let scope_keys = items
                .iter()
                .map(|(intent, _)| intent.key.clone())
                .collect::<Vec<_>>();
            let deadlines = items
                .iter()
                .map(|(intent, _)| intent.deadline_ms)
                .collect::<Vec<_>>();
            let mut stale_before_effect = false;
            let mut deadline_before_effect = false;
            let mut stale_after_effect = false;
            let executed =
                FinalUseAuthority::with_verified_effect_batch(&self.authority, claimed, || {
                    if scope_keys
                        .iter()
                        .any(|key| !scope_binding_current(frontier.as_ref(), key))
                    {
                        stale_before_effect = true;
                        return Err(crate::model_worker::Error::FeatureContract);
                    }
                    let effect_now_ms = dispatch_now_ms_v1(now_ms, dispatch_started);
                    if deadlines.iter().any(|deadline| *deadline <= effect_now_ms) {
                        deadline_before_effect = true;
                        return Err(crate::model_worker::Error::DeadlineExpired);
                    }
                    let result = self.worker.run_neuron_features_batch_receipts(
                        effect_now_ms,
                        &model_id,
                        requests,
                    );
                    if scope_keys
                        .iter()
                        .any(|key| !scope_binding_current(frontier.as_ref(), key))
                        || deadlines.iter().any(|deadline| {
                            *deadline <= dispatch_now_ms_v1(now_ms, dispatch_started)
                        })
                    {
                        stale_after_effect = true;
                    }
                    result
                });
            if stale_after_effect {
                return Err(BatchWorkerErrorV1::StaleAfterEffect);
            }
            if deadline_before_effect {
                return Err(BatchWorkerErrorV1::DeadlineExpired);
            }
            if stale_before_effect {
                return Err(BatchWorkerErrorV1::InvalidBinding);
            }
            executed
                .map_err(|_| BatchWorkerErrorV1::Authority)?
                .map_err(|error| match error {
                    crate::model_worker::Error::BatchUnsupported => {
                        BatchWorkerErrorV1::BatchUnsupported
                    }
                    _ => BatchWorkerErrorV1::Worker,
                })
        })();

        let mut results = match executed {
            Ok(receipts) if receipts.len() == items.len() => {
                receipts.into_iter().map(Ok).collect::<Vec<_>>()
            }
            Ok(_) => vec![Err(BatchWorkerErrorV1::Worker); items.len()],
            Err(error) => vec![Err(error); items.len()],
        };
        let mut outcomes = Vec::with_capacity(items.len());
        let mut lost_terminal_evidence = false;
        for ((intent, _), result) in items.into_iter().zip(results.drain(..)) {
            if let Some(sink) = &self.metric_sink {
                self.metrics_flushed.store(false, Ordering::Release);
                let metric_result = sink.record(PhaseMetricEventV1 {
                    scope_digest: Digest32::of_bytes(intent.key.scope_id.as_str().as_bytes()),
                    operation_digest: Digest32::of_bytes(intent.request_id.as_str().as_bytes()),
                    phase: PhaseMetricKindV1::NeuronFeature,
                    latency_micros: u64::try_from(started.elapsed().as_micros())
                        .unwrap_or(u64::MAX),
                    succeeded: matches!(
                        &result,
                        Ok(receipt) if receipt.status
                            == NeuronFeatureTerminalStatusV1::Succeeded
                    ),
                });
                if metric_result.is_err() {
                    self.failed_metrics.fetch_add(1, Ordering::Release);
                    lost_terminal_evidence = true;
                }
            }
            outcomes.push(BatchWorkerItemOutcomeV1 {
                request_id: intent.request_id,
                result,
            });
        }
        if lost_terminal_evidence {
            // The original physical batch already ran. Failure of even one
            // member's terminal Evidence means the group cannot publish a
            // partially certified set of successful results. Preserve real
            // effect/nonce histories; never dispatch or claim another grant.
            for outcome in &mut outcomes {
                if outcome.result.is_ok() {
                    outcome.result = Err(BatchWorkerErrorV1::TerminalTelemetryIndeterminate);
                }
            }
        }
        outcomes
    }

    /// Cutover drops all stale queued requests without ever invoking a driver.
    pub fn fence_scope(
        &mut self,
        scope: &StableId,
        generation: codex_hepta_types::Generation,
        fence: u64,
        authority_epoch: u64,
    ) -> Vec<StableId> {
        self.frontier_binding_frozen = true;
        let removed =
            self.scheduler
                .retain_scope_binding(scope, generation, fence, authority_epoch);
        for id in &removed {
            self.pending.remove(id);
            self.retired.insert(retired_identity(&id));
        }
        removed
    }
}

#[cfg(test)]
#[path = "batched_neuron_tests.rs"]
mod tests;
