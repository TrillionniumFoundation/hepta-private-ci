//! Generation-fenced shared-feature microbatch worker.
//!
//! The public unsigned path is restricted to a deterministic reference backend.
//! Arbitrary/native backends enter only behind an independent signed FinalUse
//! grant, current NDU snapshot, and a synchronous revocation effect fence.
//! Every receipt remains DENY_ALL and is not a deployment or promotion proof.

use std::collections::BTreeSet;
use std::fmt;
use std::sync::Arc;
use std::time::Instant;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::claim_final_use;
use codex_hepta_neuron::NeuronBatchMetricV1;
use codex_hepta_neuron::NeuronMetricsErrorV1;
use codex_hepta_neuron::NeuronMetricsGroupCommitWriterV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const MAX_BATCH: usize = 256;
const MAX_DIM: usize = 4096;
const MAX_WIDTH: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronMicrobatchErrorV1 {
    InvalidSnapshot,
    InvalidPlan,
    DuplicateRequest,
    DuplicateReservation,
    WorkerMismatch,
    GenerationMismatch,
    ScopeMismatch,
    DeadlineExpired,
    PlanReplayed,
    BackendRejected,
    BackendOutputMismatch,
    FinalUse(FinalUseError),
    Metrics(NeuronMetricsErrorV1),
    ClockUnavailable,
    Poisoned,
}

impl fmt::Display for NeuronMicrobatchErrorV1 {
    fn fmt(&self, fmt: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(fmt, "{self:?}")
    }
}

impl std::error::Error for NeuronMicrobatchErrorV1 {}

impl From<NeuronMetricsErrorV1> for NeuronMicrobatchErrorV1 {
    fn from(error: NeuronMetricsErrorV1) -> Self {
        Self::Metrics(error)
    }
}

impl From<FinalUseError> for NeuronMicrobatchErrorV1 {
    fn from(error: FinalUseError) -> Self {
        Self::FinalUse(error)
    }
}

/// Exact principal/scope and model generation for one immutable shared input.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSnapshotIdentityV1 {
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub generation: Generation,
    pub authority_epoch: u64,
    pub encoder_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub normalizer_digest: Digest32,
    pub source_digest: Digest32,
}

#[derive(Clone, Debug)]
pub struct NeuronFrozenFeatureV1 {
    identity: NeuronSnapshotIdentityV1,
    features_q24: Arc<[i64]>,
    semantic_digest: Digest32,
}

impl NeuronFrozenFeatureV1 {
    pub fn freeze(
        identity: NeuronSnapshotIdentityV1,
        features: Vec<i64>,
    ) -> Result<Self, NeuronMicrobatchErrorV1> {
        if !(1..=MAX_DIM).contains(&features.len())
            || identity.authority_epoch == 0
            || [
                identity.scope_digest,
                identity.ndu_snapshot_digest,
                identity.encoder_digest,
                identity.tokenizer_digest,
                identity.normalizer_digest,
                identity.source_digest,
            ]
            .iter()
            .any(|digest| digest.is_zero())
        {
            return Err(NeuronMicrobatchErrorV1::InvalidSnapshot);
        }
        let mut bytes = b"hepta.neuron.shared-feature.v1\0".to_vec();
        add_name(&mut bytes, identity.subject_id.as_str());
        for digest in [
            identity.scope_digest,
            identity.ndu_snapshot_digest,
            identity.encoder_digest,
            identity.tokenizer_digest,
            identity.normalizer_digest,
            identity.source_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&identity.generation.get().to_be_bytes());
        bytes.extend_from_slice(&identity.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&(features.len() as u64).to_be_bytes());
        for value in &features {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Self {
            identity,
            features_q24: Arc::from(features),
            semantic_digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn identity(&self) -> &NeuronSnapshotIdentityV1 {
        &self.identity
    }

    pub fn features_q24(&self) -> &[i64] {
        &self.features_q24
    }

    pub fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronBatchHeadV1 {
    pub request_id: StableId,
    pub reservation_id: StableId,
    pub head_digest: Digest32,
    pub expected_width: usize,
}

#[derive(Clone, Debug)]
pub struct NeuronMicrobatchPlanV1 {
    worker_id: StableId,
    snapshot: Arc<NeuronFrozenFeatureV1>,
    deadline_unix_ms: u64,
    heads: Vec<NeuronBatchHeadV1>,
    digest: Digest32,
}

impl NeuronMicrobatchPlanV1 {
    pub fn freeze(
        worker_id: StableId,
        snapshot: Arc<NeuronFrozenFeatureV1>,
        deadline_unix_ms: u64,
        heads: Vec<NeuronBatchHeadV1>,
    ) -> Result<Self, NeuronMicrobatchErrorV1> {
        if heads.is_empty() || heads.len() > MAX_BATCH || deadline_unix_ms == 0 {
            return Err(NeuronMicrobatchErrorV1::InvalidPlan);
        }
        let mut seen_requests = BTreeSet::new();
        let mut seen_reservations = BTreeSet::new();
        let mut bytes = b"hepta.neuron.microbatch-plan.v1\0".to_vec();
        add_name(&mut bytes, worker_id.as_str());
        bytes.extend_from_slice(snapshot.semantic_digest.as_array());
        bytes.extend_from_slice(&deadline_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&(heads.len() as u64).to_be_bytes());
        for head in &heads {
            if head.head_digest.is_zero() || !(1..=MAX_WIDTH).contains(&head.expected_width) {
                return Err(NeuronMicrobatchErrorV1::InvalidPlan);
            }
            if !seen_requests.insert(head.request_id.as_str()) {
                return Err(NeuronMicrobatchErrorV1::DuplicateRequest);
            }
            if !seen_reservations.insert(head.reservation_id.as_str()) {
                return Err(NeuronMicrobatchErrorV1::DuplicateReservation);
            }
            add_name(&mut bytes, head.request_id.as_str());
            add_name(&mut bytes, head.reservation_id.as_str());
            bytes.extend_from_slice(head.head_digest.as_array());
            bytes.extend_from_slice(&(head.expected_width as u64).to_be_bytes());
        }
        Ok(Self {
            worker_id,
            snapshot,
            deadline_unix_ms,
            heads,
            digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }

    pub fn size(&self) -> usize {
        self.heads.len()
    }

    /// Issuer request only. It cannot be consumed as authority on its own.
    pub fn final_use_binding(&self) -> FinalUseBinding {
        let mut scope = b"hepta.neuron.microbatch-scope.v1\0".to_vec();
        scope.extend_from_slice(self.snapshot.identity.scope_digest.as_array());
        scope.extend_from_slice(self.snapshot.identity.ndu_snapshot_digest.as_array());
        scope.extend_from_slice(&self.snapshot.identity.generation.get().to_be_bytes());
        scope.extend_from_slice(&self.snapshot.identity.authority_epoch.to_be_bytes());
        let mut payload = b"hepta.neuron.microbatch-payload.v1\0".to_vec();
        payload.extend_from_slice(self.snapshot.semantic_digest.as_array());
        payload.extend_from_slice(self.digest.as_array());
        payload.extend_from_slice(&self.deadline_unix_ms.to_be_bytes());
        FinalUseBinding {
            subject_id: self.snapshot.identity.subject_id.as_str().to_owned(),
            destination_id: "neuron.microbatch.worker.v1".to_owned(),
            request_sha256: self.digest.into_array(),
            scope_sha256: Digest32::of_bytes(&scope).into_array(),
            payload_sha256: Digest32::of_bytes(&payload).into_array(),
        }
    }
}

fn add_name(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

/// Backends must honor one batch invocation, preserve each request identity,
/// and return only observed terminal results. No implicit per-row fallback.
pub trait NeuronMicrobatchBackendV1 {
    fn execute_batch(
        &mut self,
        snapshot: &NeuronFrozenFeatureV1,
        heads: &[NeuronBatchHeadV1],
    ) -> Result<Vec<NeuronBatchHeadResultV1>, NeuronMicrobatchErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronBatchHeadResultV1 {
    pub request_id: StableId,
    pub head_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub elapsed_micros: u64,
}

/// Explicitly NOT a learned encoder/head. Executes deterministic Q24 fixture
/// math and counts batch invocations for structural/lock/WAL qualification.
#[derive(Default)]
pub struct ReferenceNeuronBatchBackendV1 {
    pub batch_invocations: u64,
}

impl NeuronMicrobatchBackendV1 for ReferenceNeuronBatchBackendV1 {
    fn execute_batch(
        &mut self,
        snapshot: &NeuronFrozenFeatureV1,
        heads: &[NeuronBatchHeadV1],
    ) -> Result<Vec<NeuronBatchHeadResultV1>, NeuronMicrobatchErrorV1> {
        self.batch_invocations += 1;
        let mut outputs = Vec::with_capacity(heads.len());
        for head in heads {
            let began = Instant::now();
            let drive = (0..head.expected_width)
                .map(|index| snapshot.features_q24[index % snapshot.features_q24.len()])
                .collect::<Vec<_>>();
            outputs.push(NeuronBatchHeadResultV1 {
                request_id: head.request_id.clone(),
                head_digest: head.head_digest,
                prediction_q24: vec![0; head.expected_width],
                drive_q24: drive,
                elapsed_micros: u64::try_from(began.elapsed().as_micros()).unwrap_or(u64::MAX),
            });
        }
        Ok(outputs)
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct NeuronHostResourceSampleV1 {
    /// Measured from the OS by the host; None means unavailable, NOT zero.
    pub process_cpu_micros: Option<u64>,
    pub resident_bytes: Option<u64>,
    pub lock_wait_micros: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronMicrobatchExecutionV1 {
    pub plan_digest: Digest32,
    pub execution_digest: Digest32,
    pub results: Vec<NeuronBatchHeadResultV1>,
    pub metric_sequence: u64,
    pub metric_head: Digest32,
    pub authority: AuthorityPosture,
}

/// The writer acknowledges completion only after metrics fsync. If backend
/// execution or durability is uncertain, the plan is not redispatchable from
/// this generation's process owner.
pub struct NeuronMicrobatchWorkerV1 {
    worker_id: StableId,
    generation: Generation,
    scope_digest: Digest32,
    metrics: NeuronMetricsGroupCommitWriterV1,
    attempted: BTreeSet<Digest32>,
    poisoned: bool,
}

impl NeuronMicrobatchWorkerV1 {
    pub fn new(
        worker_id: StableId,
        generation: Generation,
        scope_digest: Digest32,
        metrics: NeuronMetricsGroupCommitWriterV1,
    ) -> Result<Self, NeuronMicrobatchErrorV1> {
        if scope_digest != metrics.scope_digest() || generation != metrics.generation() {
            return Err(NeuronMicrobatchErrorV1::ScopeMismatch);
        }
        Ok(Self {
            worker_id,
            generation,
            scope_digest,
            metrics,
            attempted: BTreeSet::new(),
            poisoned: false,
        })
    }

    /// Safe unsigned seam: its backend type is a fixed, explicit reference
    /// implementation, not an arbitrary provider or physical device executor.
    pub fn run_reference(
        &mut self,
        now_unix_ms: u64,
        plan: &NeuronMicrobatchPlanV1,
        backend: &mut ReferenceNeuronBatchBackendV1,
        resources: NeuronHostResourceSampleV1,
    ) -> Result<NeuronMicrobatchExecutionV1, NeuronMicrobatchErrorV1> {
        self.execute(now_unix_ms, plan, backend, resources)
    }

    /// Physical/custom backend calls must obtain a signed independent claim
    /// and hold a revocation fence throughout execution + metric durability.
    pub fn run_authorized<B: NeuronMicrobatchBackendV1>(
        &mut self,
        now_unix_ms: u64,
        plan: &NeuronMicrobatchPlanV1,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        backend: &mut B,
        resources: NeuronHostResourceSampleV1,
    ) -> Result<NeuronMicrobatchExecutionV1, NeuronMicrobatchErrorV1> {
        // Reject an expired plan even if a caller supplied an old timestamp.
        // The signed grant must expire no later than the batch deadline;
        // FinalUseAuthority independently verifies its own protected clock.
        let now_from_system = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| NeuronMicrobatchErrorV1::ClockUnavailable)?;
        let system_unix_ms = u64::try_from(now_from_system.as_millis())
            .map_err(|_| NeuronMicrobatchErrorV1::ClockUnavailable)?;
        let effective_now_ms = now_unix_ms.max(system_unix_ms);
        self.preflight(effective_now_ms, plan)?;
        if signed.grant.authority_epoch != plan.snapshot.identity.authority_epoch
            || signed.grant.expires_at_unix_ms > plan.deadline_unix_ms
            || authority.revocation_head()?.authority_epoch
                != plan.snapshot.identity.authority_epoch
        {
            return Err(NeuronMicrobatchErrorV1::InvalidPlan);
        }
        let expected = plan.final_use_binding();
        let token = claim_final_use(authority, signed, &expected)?;
        authority
            .with_verified_effect(token, &expected, || {
                self.execute(effective_now_ms, plan, backend, resources)
            })
            .map_err(NeuronMicrobatchErrorV1::FinalUse)?
    }

    fn preflight(
        &self,
        now_unix_ms: u64,
        plan: &NeuronMicrobatchPlanV1,
    ) -> Result<(), NeuronMicrobatchErrorV1> {
        if self.poisoned {
            return Err(NeuronMicrobatchErrorV1::Poisoned);
        }
        if plan.worker_id != self.worker_id {
            return Err(NeuronMicrobatchErrorV1::WorkerMismatch);
        }
        if plan.snapshot.identity.generation != self.generation {
            return Err(NeuronMicrobatchErrorV1::GenerationMismatch);
        }
        if plan.snapshot.identity.scope_digest != self.scope_digest {
            return Err(NeuronMicrobatchErrorV1::ScopeMismatch);
        }
        if now_unix_ms >= plan.deadline_unix_ms {
            return Err(NeuronMicrobatchErrorV1::DeadlineExpired);
        }
        if self.attempted.contains(&plan.digest)
            || self.metrics.contains_committed_plan(plan.digest)
        {
            return Err(NeuronMicrobatchErrorV1::PlanReplayed);
        }
        Ok(())
    }

    fn execute<B: NeuronMicrobatchBackendV1>(
        &mut self,
        now_unix_ms: u64,
        plan: &NeuronMicrobatchPlanV1,
        backend: &mut B,
        resources: NeuronHostResourceSampleV1,
    ) -> Result<NeuronMicrobatchExecutionV1, NeuronMicrobatchErrorV1> {
        self.preflight(now_unix_ms, plan)?;
        if !self.attempted.insert(plan.digest) {
            return Err(NeuronMicrobatchErrorV1::PlanReplayed);
        }
        let began = Instant::now();
        let observed = backend.execute_batch(&plan.snapshot, &plan.heads)?;
        if observed.len() != plan.heads.len() {
            return Err(NeuronMicrobatchErrorV1::BackendOutputMismatch);
        }
        let mut digest_bytes = b"hepta.neuron.microbatch-execution.v1\0".to_vec();
        digest_bytes.extend_from_slice(plan.digest.as_array());
        let mut latencies = Vec::with_capacity(observed.len());
        for (head, output) in plan.heads.iter().zip(&observed) {
            if output.request_id != head.request_id
                || output.head_digest != head.head_digest
                || output.drive_q24.len() != head.expected_width
                || output.prediction_q24.len() != head.expected_width
            {
                return Err(NeuronMicrobatchErrorV1::BackendOutputMismatch);
            }
            add_name(&mut digest_bytes, output.request_id.as_str());
            digest_bytes.extend_from_slice(output.head_digest.as_array());
            for array in [&output.drive_q24, &output.prediction_q24] {
                digest_bytes.extend_from_slice(&(array.len() as u64).to_be_bytes());
                for value in array {
                    digest_bytes.extend_from_slice(&value.to_be_bytes());
                }
            }
            latencies.push(output.elapsed_micros);
        }
        let digest = Digest32::of_bytes(&digest_bytes);
        latencies.sort_unstable();
        let percentile = |ppm: usize| -> u64 {
            let index = (latencies.len() * ppm).div_ceil(100).saturating_sub(1);
            latencies[index]
        };
        let metric = NeuronBatchMetricV1 {
            plan_digest: plan.digest,
            execution_digest: digest,
            request_count: plan.heads.len() as u32,
            elapsed_micros: u64::try_from(began.elapsed().as_micros()).unwrap_or(u64::MAX),
            observed_cpu_micros: resources.process_cpu_micros.unwrap_or(0),
            observed_rss_bytes: resources.resident_bytes.unwrap_or(0),
            p95_micros: percentile(95),
            p99_micros: percentile(99),
            lock_wait_micros: resources.lock_wait_micros.unwrap_or(0),
            measurements_mask: u8::from(resources.process_cpu_micros.is_some())
                | (u8::from(resources.resident_bytes.is_some()) << 1)
                | (u8::from(resources.lock_wait_micros.is_some()) << 2),
        };
        let commit = match self.metrics.append_group(&[metric]) {
            Ok(commit) => commit,
            Err(error) => {
                self.poisoned = true;
                return Err(error.into());
            }
        };
        Ok(NeuronMicrobatchExecutionV1 {
            plan_digest: plan.digest,
            execution_digest: digest,
            results: observed,
            metric_sequence: commit.final_sequence,
            metric_head: commit.final_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[cfg(test)]
#[path = "neuron_microbatch_tests.rs"]
mod tests;
