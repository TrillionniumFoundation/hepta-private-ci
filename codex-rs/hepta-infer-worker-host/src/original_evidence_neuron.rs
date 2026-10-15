//! Strict original-Evidence-bound entry for the existing signed Neuron Worker.
//!
//! The generic microbatch core retains compatibility with research-only
//! PhaseMetricSinkV1 fixtures. This composition accepts NO injected sink:
//! it opens exactly one protected original Evidence WAL/marker actor, holds
//! that writer for its lifetime and exposes no mutable generic Worker.
//!
//! This is still not a release grant. An external original Control owner must
//! independently attest the live CNS Scope reader, signed Final-use issuer,
//! recovery policy and immutable model artifacts before production serving.

#[cfg(unix)]
use std::path::Component;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_agentd::DurablePhaseMetricSinkV1;
use codex_hepta_agentd::MetricsCommittedSampleQueryV1;
use codex_hepta_agentd::MetricsCommittedSampleReadbackV1;
use codex_hepta_agentd::MetricsLocalFrontierV1;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::SharedFeatureBufferV1;
use codex_hepta_infer_core::microbatch::MicrobatchKeyV1;
use codex_hepta_infer_core::microbatch::MicrobatchLimitsV1;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::batched_neuron::AuthenticatedNeuronMicrobatchWorkerV1;
use crate::batched_neuron::BatchWorkerErrorV1;
use crate::batched_neuron::BatchWorkerPollV1;
use crate::batched_neuron::MicrobatchScopeFrontierV1;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;

/// The original Evidence actor uses the same protected WAL and owner marker
/// for both synchronous fsync ACK and read-only membership observation.
#[derive(Clone, Debug)]
pub struct OriginalEvidenceWriterConfigV1 {
    pub wal_path: PathBuf,
    pub queue_capacity: usize,
    pub group_size: usize,
    pub flush_interval_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OriginalEvidenceWorkerBootstrapErrorV1 {
    UnsupportedHost,
    UnsafeEvidenceRoot,
    OriginalEvidenceUnavailable,
    /// Existing fsynced Evidence means prior requests may have consumed
    /// Final-use nonces or performed model effects. This in-memory queue
    /// has no independently reconciled original Control state; reopening
    /// it as empty would permit a differently signed duplicate request.
    PriorHistoryNeedsReconciliation,
    /// The caller-supplied live Scope frontier has not been tied to an
    /// independently authenticated original Control/CNS owner. A trait
    /// object alone is never adequate production-source attestation.
    UnverifiedOriginalControl,
    Worker(BatchWorkerErrorV1),
}

impl std::fmt::Display for OriginalEvidenceWorkerBootstrapErrorV1 {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{self:?}")
    }
}

impl std::error::Error for OriginalEvidenceWorkerBootstrapErrorV1 {}

/// P0 DENY_ALL until the original Control/CNS signer is actually wired.
/// This has NO caller inputs and is not a positive security attestation.
/// The normal library always denies. Explicit internal unit-test fixtures
/// may exercise the full signed Worker mechanics against their fake frontier;
/// this permission does NOT compile into the production library.
pub fn require_original_control_v1() -> Result<(), OriginalEvidenceWorkerBootstrapErrorV1> {
    #[cfg(not(test))]
    {
        Err(OriginalEvidenceWorkerBootstrapErrorV1::UnverifiedOriginalControl)
    }
    #[cfg(test)]
    {
        Ok(())
    }
}

/// This is a concrete Evidence *provenance* barrier, not a Control signer.
/// No API returns the underlying generic worker or accepts another sink.
/// A recovered signed model effect is never automatically replayed.
pub struct OriginalEvidenceBoundNeuronWorkerV1<D: ModelDriver + NeuronFeatureDriver> {
    owner: AuthenticatedNeuronMicrobatchWorkerV1<D>,
    original_evidence: Arc<DurablePhaseMetricSinkV1>,
}

impl<D: ModelDriver + NeuronFeatureDriver> OriginalEvidenceBoundNeuronWorkerV1<D> {
    pub fn open(
        worker: InferenceWorker<D>,
        authority: FinalUseAuthority,
        limits: MicrobatchLimitsV1,
        live_scope_frontier: Arc<dyn MicrobatchScopeFrontierV1>,
        config: OriginalEvidenceWriterConfigV1,
    ) -> Result<Self, OriginalEvidenceWorkerBootstrapErrorV1> {
        #[cfg(not(unix))]
        {
            let _ = (worker, authority, limits, live_scope_frontier, config);
            Err(OriginalEvidenceWorkerBootstrapErrorV1::UnsupportedHost)
        }
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt as _;

            // Must be the first runtime gate in production, before any WAL
            // open, queue bootstrap, authority claim or model invocation.
            // A trait object can never self-certify its original CNS owner.
            require_original_control_v1()?;

            // The operator preprovisions this private canonical directory.
            // Relative, symlinked or aliasable ancestors cannot be used to
            // switch a successful Worker onto a different historical WAL.
            let path = &config.wal_path;
            if !path.is_absolute()
                || path.file_name().is_none()
                || path
                    .components()
                    .any(|part| matches!(part, Component::ParentDir | Component::CurDir))
            {
                return Err(OriginalEvidenceWorkerBootstrapErrorV1::UnsafeEvidenceRoot);
            }
            let parent = path
                .parent()
                .ok_or(OriginalEvidenceWorkerBootstrapErrorV1::UnsafeEvidenceRoot)?;
            let original = std::fs::canonicalize(parent)
                .map_err(|_| OriginalEvidenceWorkerBootstrapErrorV1::UnsafeEvidenceRoot)?;
            let metadata = std::fs::symlink_metadata(parent)
                .map_err(|_| OriginalEvidenceWorkerBootstrapErrorV1::UnsafeEvidenceRoot)?;
            if original.as_path() != parent
                || !metadata.file_type().is_dir()
                || (metadata.permissions().mode() & 0o077) != 0
            {
                return Err(OriginalEvidenceWorkerBootstrapErrorV1::UnsafeEvidenceRoot);
            }

            // This constructor does not create a Final-use signer or Control
            // snapshot. Both owners are injected and independently checked
            // by the existing signed effect and Scope-fence logic.
            let mut owner = AuthenticatedNeuronMicrobatchWorkerV1::new(worker, authority, limits)
                .map_err(OriginalEvidenceWorkerBootstrapErrorV1::Worker)?;
            owner
                .bind_live_scope_frontier(live_scope_frontier)
                .map_err(OriginalEvidenceWorkerBootstrapErrorV1::Worker)?;
            let original_evidence = Arc::new(
                DurablePhaseMetricSinkV1::open(
                    path,
                    config.queue_capacity,
                    config.group_size,
                    config.flush_interval_ms,
                )
                .map_err(|_| OriginalEvidenceWorkerBootstrapErrorV1::OriginalEvidenceUnavailable)?,
            );
            owner
                .bind_original_evidence_sink(original_evidence.clone())
                .map_err(OriginalEvidenceWorkerBootstrapErrorV1::Worker)?;
            if !owner.flush_production_metrics() {
                return Err(OriginalEvidenceWorkerBootstrapErrorV1::OriginalEvidenceUnavailable);
            }
            // An original WAL that already contains committed model history
            // cannot be adopted by a newly empty in-memory dedup queue.
            // A new Final-use nonce for the same logical request could then
            // repeat an old physical effect. Until the independent original
            // Control owner supplies and verifies durable reconciliation,
            // cold restart with ANY committed group is denied, including
            // groups containing failed/indeterminate terminal observations.
            // This readback is deliberately startup-only; never scan the
            // full WAL during a Cell inference hot path.
            let recovered = original_evidence
                .read_local_frontier()
                .map_err(|_| OriginalEvidenceWorkerBootstrapErrorV1::OriginalEvidenceUnavailable)?;
            if recovered.sequence != 0 || recovered.committed_rows != 0 {
                return Err(
                    OriginalEvidenceWorkerBootstrapErrorV1::PriorHistoryNeedsReconciliation,
                );
            }
            Ok(Self {
                owner,
                original_evidence,
            })
        }
    }

    /// An enqueue is not an effect receipt. Multiple admitted intents may
    /// share ONE pre-dispatch group-commit barrier on the next poll.
    pub fn enqueue(
        &mut self,
        now_ms: u64,
        model_id: String,
        request: NeuronFeatureRequest,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        if !self.original_evidence.healthy() {
            return Err(BatchWorkerErrorV1::MetricsUnavailable);
        }
        self.owner.enqueue(now_ms, model_id, request, key, signed)
    }

    /// Original-Evidence-only Arc-backed admission. Same original locked
    /// WAL owner, live Control/CNS and independent signed grant as enqueue.
    ///
    /// The preview never issues Final-use or makes an unavailable Evidence
    /// owner usable; queued identities still require admission fsync before
    /// any physical model effect in poll_and_execute.
    pub fn enqueue_shared_features(
        &mut self,
        now_ms: u64,
        model_id: String,
        request: NeuronFeatureRequest,
        shared_features: SharedFeatureBufferV1,
        key: MicrobatchKeyV1,
        signed: SignedFinalUseGrant,
    ) -> Result<(), BatchWorkerErrorV1> {
        if !self.original_evidence.healthy() {
            return Err(BatchWorkerErrorV1::MetricsUnavailable);
        }
        self.owner.enqueue_shared_features(
            now_ms, model_id, request, shared_features, key, signed,
        )
    }

    /// First commit ALL preceding Admission Evidence, only then dequeue and
    /// enter Final-use. The original signed Worker already commits terminal
    /// Evidence before success publication and rechecks CNS/deadline after
    /// its physical backend call. No full-WAL scan occurs in this hot path.
    pub fn poll_and_execute(
        &mut self,
        now_ms: u64,
    ) -> Result<BatchWorkerPollV1, BatchWorkerErrorV1> {
        if !self.owner.production_metrics_ready() && !self.owner.flush_production_metrics() {
            // Admission may already be pending; keep exact identities for
            // original-owner reconciliation, NEVER replay physical effects.
            return Err(BatchWorkerErrorV1::AdmissionTelemetryIndeterminate);
        }
        let mut observed = self.owner.poll_and_execute(now_ms)?;
        if !self.original_evidence.healthy() || !self.owner.production_metrics_ready() {
            for item in &mut observed.outcomes {
                if item.result.is_ok() {
                    item.result = Err(BatchWorkerErrorV1::TerminalTelemetryIndeterminate);
                }
            }
        }
        Ok(observed)
    }

    /// A cutover may retire queued identities, but must not conceal the
    /// preceding admitted intents when their original WAL is unhealthy.
    pub fn fence_scope(
        &mut self,
        scope: &StableId,
        generation: Generation,
        fence: u64,
        authority_epoch: u64,
    ) -> Result<Vec<StableId>, BatchWorkerErrorV1> {
        let removed = self
            .owner
            .fence_scope(scope, generation, fence, authority_epoch);
        if !self.owner.flush_production_metrics() {
            return Err(BatchWorkerErrorV1::AdmissionTelemetryIndeterminate);
        }
        Ok(removed)
    }

    pub fn pending(&self) -> usize {
        self.owner.pending()
    }

    /// Read-only ORIGINAL LOCAL WAL observation. This is O(committed WAL)
    /// and is for an independent Observer lane, never each inference tick.
    /// Its result is UNSIGNED and grants no authorization by itself.
    pub fn observe_original_frontier(&self) -> Result<MetricsLocalFrontierV1, BatchWorkerErrorV1> {
        self.original_evidence
            .read_local_frontier()
            .map_err(|_| BatchWorkerErrorV1::MetricsUnavailable)
    }

    /// An exact committed sample is not an original model-effect receipt or
    /// independent signer proof. It is only one necessary Evidence join input.
    pub fn observe_exact_committed_sample(
        &self,
        query: MetricsCommittedSampleQueryV1,
    ) -> Result<Option<MetricsCommittedSampleReadbackV1>, BatchWorkerErrorV1> {
        self.original_evidence
            .read_committed_sample(query)
            .map_err(|_| BatchWorkerErrorV1::MetricsUnavailable)
    }
}
