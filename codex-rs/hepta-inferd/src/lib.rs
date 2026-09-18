//! Exact-bound inference dispatch planning.
//!
//! A dispatch plan names a worker and frozen request/reservation/lease digests.
//! It is not provider dispatch authority and does not execute a model.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_SCHEDULING_CANDIDATES: usize = 256;
const MAX_SCHEDULE_TOKENS: u64 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibleWorker {
    pub worker_id: StableId,
    pub worker_generation: u64,
    pub lease_digest: Digest32,
    pub model_digest: Digest32,
    pub available_concurrency: u32,
    pub available_tokens: u64,
    /// Lower values are preferred. Capacity and stable worker identity break ties.
    pub preference_rank: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ScheduleRequest {
    pub dispatch_id: StableId,
    pub request_id: StableId,
    pub request_digest: Digest32,
    pub reservation_digest: Digest32,
    pub model_digest: Digest32,
    pub deadline_ms: u64,
    pub required_tokens: u64,
    pub eligible_workers: Vec<EligibleWorker>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerAssignment {
    pub plan: DispatchPlan,
    pub eligible_snapshot_digest: Digest32,
    pub selection_digest: Digest32,
}


#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchRequest {
    pub dispatch_id: StableId,
    pub request_id: StableId,
    pub worker_id: StableId,
    pub request_digest: Digest32,
    pub reservation_digest: Digest32,
    pub lease_digest: Digest32,
    pub model_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchPlan {
    pub dispatch_id: StableId,
    pub request_id: StableId,
    pub worker_id: StableId,
    pub plan_digest: Digest32,
    pub provider_dispatch_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    DeadlineExpired,
    BindingMismatch(&'static str),
    InvalidCandidateCount,
    InvalidRequiredTokens,
    InvalidWorkerCandidate(&'static str),
    DuplicateWorker,
    NoFeasibleWorker,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn plan(
    now_ms: u64,
    request: DispatchRequest,
    expected_request: Digest32,
    expected_reservation: Digest32,
    expected_lease: Digest32,
    expected_model: Digest32,
) -> Result<DispatchPlan, Error> {
    for (name, digest) in [
        ("request", request.request_digest),
        ("reservation", request.reservation_digest),
        ("lease", request.lease_digest),
        ("model", request.model_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    for (name, actual, expected) in [
        ("request", request.request_digest, expected_request),
        (
            "reservation",
            request.reservation_digest,
            expected_reservation,
        ),
        ("lease", request.lease_digest, expected_lease),
        ("model", request.model_digest, expected_model),
    ] {
        if actual != expected {
            return Err(Error::BindingMismatch(name));
        }
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.plan.v1");
    push_id(&mut bytes, &request.dispatch_id);
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &request.worker_id);
    bytes.extend_from_slice(request.request_digest.as_array());
    bytes.extend_from_slice(request.reservation_digest.as_array());
    bytes.extend_from_slice(request.lease_digest.as_array());
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    Ok(DispatchPlan {
        dispatch_id: request.dispatch_id,
        request_id: request.request_id,
        worker_id: request.worker_id,
        plan_digest: Digest32::of_bytes(&bytes),
        provider_dispatch_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}


pub fn schedule(now_ms: u64, request: ScheduleRequest) -> Result<WorkerAssignment, Error> {
    if request.eligible_workers.is_empty()
        || request.eligible_workers.len() > MAX_SCHEDULING_CANDIDATES
    {
        return Err(Error::InvalidCandidateCount);
    }
    if request.required_tokens == 0 || request.required_tokens > MAX_SCHEDULE_TOKENS {
        return Err(Error::InvalidRequiredTokens);
    }
    if request.request_digest.is_zero() {
        return Err(Error::EmptyDigest("request"));
    }
    if request.reservation_digest.is_zero() {
        return Err(Error::EmptyDigest("reservation"));
    }
    if request.model_digest.is_zero() {
        return Err(Error::EmptyDigest("model"));
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }

    let mut canonical = request.eligible_workers.clone();
    canonical.sort_by(|left, right| left.worker_id.as_str().cmp(right.worker_id.as_str()));
    for pair in canonical.windows(2) {
        if pair[0].worker_id == pair[1].worker_id {
            return Err(Error::DuplicateWorker);
        }
    }
    for worker in &canonical {
        if worker.worker_generation == 0 {
            return Err(Error::InvalidWorkerCandidate("generation"));
        }
        if worker.lease_digest.is_zero() {
            return Err(Error::EmptyDigest("lease"));
        }
        if worker.model_digest.is_zero() {
            return Err(Error::EmptyDigest("candidate model"));
        }
    }
    let eligible_snapshot_digest = worker_snapshot_digest(&canonical);

    let selected = canonical
        .iter()
        .filter(|worker| {
            worker.model_digest == request.model_digest
                && worker.available_concurrency > 0
                && worker.available_tokens >= request.required_tokens
        })
        .min_by(|left, right| {
            left.preference_rank
                .cmp(&right.preference_rank)
                .then_with(|| right.available_tokens.cmp(&left.available_tokens))
                .then_with(|| left.worker_id.as_str().cmp(right.worker_id.as_str()))
        })
        .ok_or(Error::NoFeasibleWorker)?;

    let plan = plan(
        now_ms,
        DispatchRequest {
            dispatch_id: request.dispatch_id,
            request_id: request.request_id,
            worker_id: selected.worker_id.clone(),
            request_digest: request.request_digest,
            reservation_digest: request.reservation_digest,
            lease_digest: selected.lease_digest,
            model_digest: request.model_digest,
            deadline_ms: request.deadline_ms,
        },
        request.request_digest,
        request.reservation_digest,
        selected.lease_digest,
        request.model_digest,
    )?;

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.selection.v1");
    bytes.extend_from_slice(eligible_snapshot_digest.as_array());
    bytes.extend_from_slice(plan.plan_digest.as_array());
    bytes.extend_from_slice(&selected.worker_generation.to_be_bytes());
    bytes.extend_from_slice(&request.required_tokens.to_be_bytes());
    let selection_digest = Digest32::of_bytes(&bytes);

    Ok(WorkerAssignment {
        plan,
        eligible_snapshot_digest,
        selection_digest,
    })
}

fn worker_snapshot_digest(workers: &[EligibleWorker]) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.eligible-workers.v1");
    bytes.extend_from_slice(&u32::try_from(workers.len()).unwrap_or(u32::MAX).to_be_bytes());
    for worker in workers {
        push_id(&mut bytes, &worker.worker_id);
        bytes.extend_from_slice(&worker.worker_generation.to_be_bytes());
        bytes.extend_from_slice(worker.lease_digest.as_array());
        bytes.extend_from_slice(worker.model_digest.as_array());
        bytes.extend_from_slice(&worker.available_concurrency.to_be_bytes());
        bytes.extend_from_slice(&worker.available_tokens.to_be_bytes());
        bytes.extend_from_slice(&worker.preference_rank.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
