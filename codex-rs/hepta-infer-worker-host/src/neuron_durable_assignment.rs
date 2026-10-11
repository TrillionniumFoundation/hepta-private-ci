//! Read-only, durable inference.control -> loaded Neuron Worker correlation.
//!
//! InferenceControl retains the actual fsynced request/reservation/assignment.
//! This module reopens that live owner handle, checks the assigned Worker and
//! actual loaded model, and compares the entire canonical Neuron feature input.
//! A diagnostic is NEVER a reservation consumption, authorization, signed
//! model-load receipt or proof of crash-safe exactly-once execution.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::model_worker::Error as WorkerError;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

const DOMAIN: &[u8] = b"hepta.infer-worker.neuron-assigned-source.diagnostic.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronDurableAssignmentDiagnosticV1 {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub control_revision: u64,
    pub assignment_digest: Digest32,
    pub request_semantic_digest: Digest32,
    pub model_digest: Digest32,
    pub weights_digest: Digest32,
    pub payload_digest: Digest32,
    pub request_deadline_ms: u64,
    pub reservation_valid_until_ms: u64,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronDurableAssignmentDiagnosticV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        for identity in [&self.request_id, &self.reservation_id, &self.worker_id] {
            let value = identity.as_bytes();
            bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
            bytes.extend_from_slice(value);
        }
        for value in [
            self.worker_generation,
            self.control_revision,
            self.request_deadline_ms,
            self.reservation_valid_until_ms,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.assignment_digest,
            self.request_semantic_digest,
            self.model_digest,
            self.weights_digest,
            self.payload_digest,
        ] {
            bytes.extend_from_slice(value.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.request_id.is_empty()
            && !self.reservation_id.is_empty()
            && !self.worker_id.is_empty()
            && self.worker_generation > 0
            && self.control_revision >= 3
            && self.request_deadline_ms > 0
            && self.reservation_valid_until_ms > 0
            && !self.assignment_digest.is_zero()
            && !self.request_semantic_digest.is_zero()
            && !self.model_digest.is_zero()
            && !self.weights_digest.is_zero()
            && !self.payload_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronDurableAssignmentErrorV1 {
    Missing,
    NotAssigned,
    Mismatch,
    Stale,
    Expired,
    Worker(WorkerError),
}

impl fmt::Display for NeuronDurableAssignmentErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronDurableAssignmentErrorV1 {}

impl From<WorkerError> for NeuronDurableAssignmentErrorV1 {
    fn from(value: WorkerError) -> Self {
        Self::Worker(value)
    }
}

fn digest(raw: &str) -> Result<Digest32, NeuronDurableAssignmentErrorV1> {
    Digest32::from_str(raw).map_err(|_| NeuronDurableAssignmentErrorV1::Mismatch)
}

/// Inspect an actual durable control-owner Assigned record against this loaded
/// Worker and typed Neuron feature request. Does NOT consume the reservation.
///
/// A caller MUST independently obtain a current signed final-use/Worker lease,
/// durably commit the execution intent and revalidate after any intervening
/// owner change, including cancellations, before performing a model effect.
/// Reading this report cannot authorize a Worker invocation. In particular,
/// on restart a previously Assigned request may already have been executed.
pub fn read_neuron_durable_assignment_v1<D: ModelDriver>(
    owner: &DurableInferenceControl,
    worker: &InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    now_ms: u64,
) -> Result<NeuronDurableAssignmentDiagnosticV1, NeuronDurableAssignmentErrorV1> {
    // The control journal authenticates assignment identity, but it does
    // not validate Neuron Q24 feature bounds. Check the typed source contract
    // before accepting a digest that happens to match malformed data.
    neuron_feature_request_digest_v1(request)
        .map_err(|_| NeuronDurableAssignmentErrorV1::Mismatch)?;
    let record = owner
        .get(request.request_id.as_str())
        .ok_or(NeuronDurableAssignmentErrorV1::Missing)?;
    if record.state != RequestState::Assigned {
        return Err(NeuronDurableAssignmentErrorV1::NotAssigned);
    }
    let reservation = record
        .reservation
        .as_ref()
        .ok_or(NeuronDurableAssignmentErrorV1::Mismatch)?;
    let assignment = record
        .assignment
        .as_ref()
        .ok_or(NeuronDurableAssignmentErrorV1::Mismatch)?;
    if record.revision < 3
        || record.request.request_id != request.request_id.as_str()
        || assignment.worker_id != worker.worker_id()
        || assignment.worker_generation != worker.worker_generation()
        || assignment.worker_generation != request.generation.get()
        || assignment.assignment_digest.is_empty()
        || reservation.authority_epoch == 0
        || reservation.maximum_tokens < record.request.maximum_tokens
        || reservation.quota_units == 0
    {
        return Err(NeuronDurableAssignmentErrorV1::Mismatch);
    }
    if now_ms >= record.request.deadline_ms || now_ms >= reservation.valid_until_ms {
        return Err(NeuronDurableAssignmentErrorV1::Expired);
    }
    // A loaded ModelManifest can change independently of the control journal;
    // read it from the actual Worker, not from a caller-authored model tuple.
    let loaded = worker.inspected_neuron_manifest(now_ms, request.model_id.as_str())?;
    if loaded.model_id != request.model_id.as_str()
        || loaded.model_digest != record.request.model_digest
        || loaded.weights_digest != request.weights_digest.to_string()
        || record.request.maximum_tokens > loaded.maximum_tokens
    {
        return Err(NeuronDurableAssignmentErrorV1::Mismatch);
    }
    let author = WorkerRequest {
        request_id: record.request.request_id.clone(),
        reservation_id: reservation.reservation_id.clone(),
        model_digest: record.request.model_digest.clone(),
        payload_digest: record.request.payload_digest.clone(),
        maximum_tokens: record.request.maximum_tokens,
        deadline_ms: record.request.deadline_ms.min(reservation.valid_until_ms),
        lease_payload_digest: record.request.payload_digest.clone(),
        reservation_model_digest: record.request.model_digest.clone(),
        reservation_maximum_tokens: reservation.maximum_tokens,
        cancelled: false,
    };
    let feature = NeuronFeatureRequest {
        authorization: author,
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    };
    if canonical_neuron_feature_payload_digest(&feature) != record.request.payload_digest {
        return Err(NeuronDurableAssignmentErrorV1::Mismatch);
    }
    // A durable Assigned entry can outlive an actual Worker attempt in this
    // process. Never report it as an unconsumed correlation if this Worker
    // already tombstoned either request or reservation, even when the control
    // owner has not yet received the terminal acknowledgement.
    worker.verify_neuron_attempt_unconsumed(
        &record.request.request_id,
        &reservation.reservation_id,
    )?;
    let mut report = NeuronDurableAssignmentDiagnosticV1 {
        request_id: record.request.request_id.clone(),
        reservation_id: reservation.reservation_id.clone(),
        worker_id: assignment.worker_id.clone(),
        worker_generation: assignment.worker_generation,
        control_revision: record.revision,
        assignment_digest: digest(&assignment.assignment_digest)?,
        request_semantic_digest: digest(&record.request.semantic_digest)?,
        model_digest: digest(&record.request.model_digest)?,
        weights_digest: request.weights_digest,
        payload_digest: digest(&record.request.payload_digest)?,
        request_deadline_ms: record.request.deadline_ms,
        reservation_valid_until_ms: reservation.valid_until_ms,
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    report.diagnostic_digest = report.computed_digest();
    if !report.validate_integrity() {
        return Err(NeuronDurableAssignmentErrorV1::Mismatch);
    }
    Ok(report)
}


/// Verify that a previously read diagnostic still equals the current *real*
/// durable inference.control assignment and this Worker instance's loaded
/// model, grant, reservation and in-process attempt tombstones.
///
/// A stale digest can always be recomputed by a caller; equality with a new
/// owner read is required. This is only a read-side freshness check and does
/// not fence changes between this return and an actual model invocation.
/// The physical dispatch owner must commit a durable single-use intent first
/// and reconcile uncertain outcomes on restart.
pub fn revalidate_neuron_durable_assignment_v1<D: ModelDriver>(
    owner: &DurableInferenceControl,
    worker: &InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    previous: &NeuronDurableAssignmentDiagnosticV1,
    now_ms: u64,
) -> Result<(), NeuronDurableAssignmentErrorV1> {
    if !previous.validate_integrity() || previous.request_id != request.request_id.as_str() {
        return Err(NeuronDurableAssignmentErrorV1::Stale);
    }
    let current = read_neuron_durable_assignment_v1(owner, worker, request, now_ms)?;
    if &current != previous {
        return Err(NeuronDurableAssignmentErrorV1::Stale);
    }
    Ok(())
}

#[cfg(test)]
#[path = "neuron_durable_assignment_tests.rs"]
mod tests;
