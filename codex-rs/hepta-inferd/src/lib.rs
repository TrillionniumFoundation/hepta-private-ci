//! Exact-bound inference dispatch planning.
//!
//! A dispatch plan names a worker and frozen request/reservation/lease digests.
//! It is not provider dispatch authority and does not execute a model.

#![forbid(unsafe_code)]

use std::cmp::Ordering;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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

pub const MAX_SCHEDULING_BATCH: usize = 256;
const MAX_SCHEDULED_TOKENS: u32 = 1_000_000;

/// Frozen reservation inputs required by the deterministic scheduler.
///
/// These are exact semantic bindings, not quota or provider authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SchedulingReservation {
    pub assignment_id: StableId,
    pub request_id: StableId,
    pub request_digest: Digest32,
    pub reservation_digest: Digest32,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub payload_digest: Digest32,
    pub maximum_tokens: u32,
    pub required_memory_bytes: u64,
    pub deadline_ms: u64,
}

/// One worker lease/resource view inside a frozen eligible-worker snapshot.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibleWorker {
    pub worker_id: StableId,
    pub generation: u64,
    pub lease_digest: Digest32,
    pub model_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub template_digest: Digest32,
    pub payload_digest: Digest32,
    pub maximum_tokens: u32,
    pub available_memory_bytes: u64,
    pub in_flight: u32,
    pub maximum_in_flight: u32,
}

/// Caller-supplied frozen scheduler view. Ordering does not affect its digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibleWorkerSnapshot {
    pub snapshot_id: StableId,
    pub workers: Vec<EligibleWorker>,
}

/// Deterministic assignment evidence. It grants no provider dispatch authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerAssignment {
    pub assignment_id: StableId,
    pub request_id: StableId,
    pub worker_id: StableId,
    pub worker_generation: u64,
    pub lease_digest: Digest32,
    pub snapshot_digest: Digest32,
    pub assignment_digest: Digest32,
    pub provider_dispatch_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    DeadlineExpired,
    BindingMismatch(&'static str),
    InvalidSchedulingInput(&'static str),
    DuplicateWorker,
    NoEligibleWorker,
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

/// Digest a frozen worker snapshot independently of caller vector ordering.
#[must_use]
pub fn eligible_worker_snapshot_digest(snapshot: &EligibleWorkerSnapshot) -> Digest32 {
    let mut workers: Vec<&EligibleWorker> = snapshot.workers.iter().collect();
    workers.sort_by(|left, right| {
        left.worker_id
            .cmp(&right.worker_id)
            .then(left.generation.cmp(&right.generation))
    });
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.eligible-worker-snapshot.v1");
    push_id(&mut bytes, &snapshot.snapshot_id);
    bytes.extend_from_slice(&u32::try_from(workers.len()).unwrap_or(u32::MAX).to_be_bytes());
    for worker in workers {
        push_id(&mut bytes, &worker.worker_id);
        bytes.extend_from_slice(&worker.generation.to_be_bytes());
        for digest in [
            worker.lease_digest,
            worker.model_digest,
            worker.tokenizer_digest,
            worker.template_digest,
            worker.payload_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&worker.maximum_tokens.to_be_bytes());
        bytes.extend_from_slice(&worker.available_memory_bytes.to_be_bytes());
        bytes.extend_from_slice(&worker.in_flight.to_be_bytes());
        bytes.extend_from_slice(&worker.maximum_in_flight.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

/// Choose one feasible worker with a deterministic, order-independent ranking.
///
/// Ranking is: lowest utilization ratio, then greatest spare memory, then
/// lexicographically smallest stable worker id, then greatest generation.
/// The result is planning evidence only and grants no provider authority.
pub fn schedule(
    now_ms: u64,
    reservation: SchedulingReservation,
    snapshot: EligibleWorkerSnapshot,
) -> Result<WorkerAssignment, Error> {
    validate_scheduling_reservation(now_ms, &reservation)?;
    validate_snapshot(&snapshot)?;
    let snapshot_digest = eligible_worker_snapshot_digest(&snapshot);

    let selected = snapshot
        .workers
        .iter()
        .filter(|worker| worker_is_feasible(&reservation, worker))
        .min_by(|left, right| compare_workers(&reservation, left, right))
        .ok_or(Error::NoEligibleWorker)?;

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.worker-assignment.v1");
    push_id(&mut bytes, &reservation.assignment_id);
    push_id(&mut bytes, &reservation.request_id);
    bytes.extend_from_slice(reservation.request_digest.as_array());
    bytes.extend_from_slice(reservation.reservation_digest.as_array());
    bytes.extend_from_slice(snapshot_digest.as_array());
    push_id(&mut bytes, &selected.worker_id);
    bytes.extend_from_slice(&selected.generation.to_be_bytes());
    bytes.extend_from_slice(selected.lease_digest.as_array());
    bytes.extend_from_slice(&reservation.deadline_ms.to_be_bytes());

    Ok(WorkerAssignment {
        assignment_id: reservation.assignment_id,
        request_id: reservation.request_id,
        worker_id: selected.worker_id.clone(),
        worker_generation: selected.generation,
        lease_digest: selected.lease_digest,
        snapshot_digest,
        assignment_digest: Digest32::of_bytes(&bytes),
        provider_dispatch_authority: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_scheduling_reservation(
    now_ms: u64,
    reservation: &SchedulingReservation,
) -> Result<(), Error> {
    for (name, digest) in [
        ("request", reservation.request_digest),
        ("reservation", reservation.reservation_digest),
        ("model", reservation.model_digest),
        ("tokenizer", reservation.tokenizer_digest),
        ("template", reservation.template_digest),
        ("payload", reservation.payload_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if reservation.maximum_tokens == 0 || reservation.maximum_tokens > MAX_SCHEDULED_TOKENS {
        return Err(Error::InvalidSchedulingInput("maximum tokens"));
    }
    if reservation.required_memory_bytes == 0 {
        return Err(Error::InvalidSchedulingInput("required memory"));
    }
    if now_ms >= reservation.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

fn validate_snapshot(snapshot: &EligibleWorkerSnapshot) -> Result<(), Error> {
    if snapshot.workers.is_empty() || snapshot.workers.len() > MAX_SCHEDULING_BATCH {
        return Err(Error::InvalidSchedulingInput("worker batch"));
    }
    let mut ids = BTreeSet::new();
    for worker in &snapshot.workers {
        if !ids.insert(worker.worker_id.clone()) {
            return Err(Error::DuplicateWorker);
        }
        for (name, digest) in [
            ("lease", worker.lease_digest),
            ("worker model", worker.model_digest),
            ("worker tokenizer", worker.tokenizer_digest),
            ("worker template", worker.template_digest),
            ("worker payload", worker.payload_digest),
        ] {
            if digest.is_zero() {
                return Err(Error::EmptyDigest(name));
            }
        }
        if worker.generation == 0
            || worker.maximum_tokens == 0
            || worker.available_memory_bytes == 0
            || worker.maximum_in_flight == 0
            || worker.in_flight > worker.maximum_in_flight
        {
            return Err(Error::InvalidSchedulingInput("worker capacity"));
        }
    }
    Ok(())
}

fn worker_is_feasible(
    reservation: &SchedulingReservation,
    worker: &EligibleWorker,
) -> bool {
    worker.model_digest == reservation.model_digest
        && worker.tokenizer_digest == reservation.tokenizer_digest
        && worker.template_digest == reservation.template_digest
        && worker.payload_digest == reservation.payload_digest
        && worker.maximum_tokens >= reservation.maximum_tokens
        && worker.available_memory_bytes >= reservation.required_memory_bytes
        && worker.in_flight < worker.maximum_in_flight
}

fn compare_workers(
    reservation: &SchedulingReservation,
    left: &EligibleWorker,
    right: &EligibleWorker,
) -> Ordering {
    let left_load = u64::from(left.in_flight) * u64::from(right.maximum_in_flight);
    let right_load = u64::from(right.in_flight) * u64::from(left.maximum_in_flight);
    left_load
        .cmp(&right_load)
        .then_with(|| {
            let left_spare = left
                .available_memory_bytes
                .saturating_sub(reservation.required_memory_bytes);
            let right_spare = right
                .available_memory_bytes
                .saturating_sub(reservation.required_memory_bytes);
            right_spare.cmp(&left_spare)
        })
        .then_with(|| left.worker_id.cmp(&right.worker_id))
        .then_with(|| right.generation.cmp(&left.generation))
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
