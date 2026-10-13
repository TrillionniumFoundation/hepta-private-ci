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

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_infer_core::durable_control::Assignment;
use codex_hepta_infer_core::durable_control::ControlReceipt;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::RequestState;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::model_worker::Error as WorkerError;
use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::NeuronFileBoundModelLoadV1;
use crate::model_worker::NeuronPreopenedWeightModelDriver;
use crate::model_worker::NeuronWeightFileDiagnosticErrorV1;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;
use crate::neuron_worker_control::WorkerNeuronControlPort;
use crate::neuron_worker_control::WorkerNeuronTokenCostV1;

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
    Control(ControlError),
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

impl From<ControlError> for NeuronDurableAssignmentErrorV1 {
    fn from(value: ControlError) -> Self {
        Self::Control(value)
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
    let typed_request_digest = neuron_feature_request_digest_v1(request)
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
        // The durable semantic identity must be the exact typed request,
        // not an arbitrary valid SHA-256 supplied alongside a payload hash.
        // This also binds request ID, generation and selected model identity,
        // which the feature-payload digest alone does not cover.
        || record.request.semantic_digest != typed_request_digest.to_string()
        || assignment.worker_id != worker.worker_id()
        || assignment.worker_generation != worker.worker_generation()
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

/// The strict same-host pre-Worker path: first inspect the actual fsynced
/// inference.control Assigned state and actual in-memory loaded Worker, then
/// fsync a SINGLE-USE Dispatching transition on the SAME inference journal.
/// Only after that durable commit can a WorkerNeuronControlPort be returned.
///
/// On crash, Dispatching cannot be reclaimed, even with a fresh Worker whose
/// process-local tombstones were lost. Unknown outcomes require independent
/// reconciliation; this does not sign a final-use grant, authenticate time,
/// prove that Laya weights were loaded or authorize production CNS selection.
pub fn claim_neuron_durable_dispatch_v1<'a, D: ModelDriver + NeuronFeatureDriver>(
    owner: &mut DurableInferenceControl,
    worker: &'a mut InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    now_ms: u64,
) -> Result<(ControlReceipt, WorkerNeuronControlPort<'a, D>), NeuronDurableAssignmentErrorV1> {
    // This reads BOTH source owners before any durable or physical side effect.
    let matched = read_neuron_durable_assignment_v1(owner, worker, request, now_ms)?;
    let record = owner
        .get(&matched.request_id)
        .ok_or(NeuronDurableAssignmentErrorV1::Missing)?;
    let reservation = record
        .reservation
        .as_ref()
        .ok_or(NeuronDurableAssignmentErrorV1::Mismatch)?;
    let assignment: Assignment = record
        .assignment
        .clone()
        .ok_or(NeuronDurableAssignmentErrorV1::Mismatch)?;
    let authorization = WorkerRequest {
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

    // Owner mutex/File lock spans the comparison and fsynced transition. If
    // the journal write/sync fails, the port is NEVER returned. Reopening an
    // ambiguous owner requires external reconciliation, not a blind retry.
    let claim = owner.claim_dispatch(
        now_ms,
        &matched.request_id,
        matched.control_revision,
        &matched.reservation_id,
        &assignment,
    )?;
    if claim.state != RequestState::Dispatching
        || claim.idempotent
        || claim.revision != matched.control_revision + 1
    {
        return Err(NeuronDurableAssignmentErrorV1::Stale);
    }
    Ok((
        claim,
        WorkerNeuronControlPort::from_reserved_worker(
            worker,
            request.model_id.to_string(),
            authorization,
            request.generation,
            now_ms,
        ),
    ))
}

/// A single-use, fsynced Neuron dispatch guarded by the *actual Worker's*
/// file-bound model-load ordinal. This is intentionally stricter than the
/// legacy assigned-Worker seam and does not construct a selection authority.
#[derive(Debug, Eq, PartialEq)]
pub enum NeuronFileBoundDispatchErrorV1 {
    LoadIdentityMismatch,
    Load(NeuronWeightFileDiagnosticErrorV1),
    Durable(NeuronDurableAssignmentErrorV1),
}

impl fmt::Display for NeuronFileBoundDispatchErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronFileBoundDispatchErrorV1 {}

/// Authenticate the in-process *physical* load generation before consuming
/// one inference.control reservation. A stale/foreign/superseded load ticket
/// does not append Dispatching. After the fsynced claim succeeds the returned
/// port retains an exclusive mutable borrow of the same Worker, so a different
/// model cannot be loaded/unloaded through its owner before this invocation.
///
/// This method neither proves the external driver actually decoded the given
/// bytes nor supplies a CNS-selected route, trusted CAS immutability, signed
/// Final-use, host incarnation or independently measured inference outcome.
/// Those are separate mandatory production-owner gates.
pub fn claim_neuron_file_bound_durable_dispatch_v1<
    'a,
    D: NeuronPreopenedWeightModelDriver + NeuronFeatureDriver,
>(
    owner: &mut DurableInferenceControl,
    worker: &'a mut InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    file_load: &NeuronFileBoundModelLoadV1,
    now_ms: u64,
) -> Result<(ControlReceipt, WorkerNeuronControlPort<'a, D>), NeuronFileBoundDispatchErrorV1> {
    // These identities are taken from the exact live Worker, not a caller-
    // constructed ModelLoadObservation or a separate equal-hash file.
    if !file_load.validate_integrity()
        || file_load.model_load().model_id != request.model_id.as_str()
        || file_load.model_load().worker_generation != worker.worker_generation()
        || file_load.loaded_weights_digest() != request.weights_digest
    {
        return Err(NeuronFileBoundDispatchErrorV1::LoadIdentityMismatch);
    }
    worker
        .revalidate_file_bound_model_load_v1(now_ms, file_load)
        .map_err(NeuronFileBoundDispatchErrorV1::Load)?;

    // Current Worker state and its file-backed load are still protected by
    // the exclusive borrow. Only the original owner can fsync Dispatching.
    claim_neuron_durable_dispatch_v1(owner, worker, request, now_ms)
        .map_err(NeuronFileBoundDispatchErrorV1::Durable)
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


/// A known-terminal physical token observation correlated to a live Worker
/// instance and the fsynced inference.control Dispatching record.
/// Diagnostic only: not a signed meter, price, NDU value or final-use grant.
const COST_SOURCE_DOMAIN: &[u8] = b"hepta.infer-worker.neuron-cost-source.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronObservedCostSourceV1 {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    /// Actual Worker model-load ordinal, distinct from process incarnation.
    pub model_load_revision: u64,
    pub model_id: String,
    pub control_revision: u64,
    pub request_digest: Digest32,
    pub feature_receipt_digest: Digest32,
    pub cost_diagnostic_digest: Digest32,
    pub terminal_status: NeuronFeatureTerminalStatusV1,
    pub observed_tokens: u32,
    pub source_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronObservedCostSourceV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = COST_SOURCE_DOMAIN.to_vec();
        for id in [&self.request_id, &self.reservation_id, &self.worker_id, &self.model_id] {
            let raw = id.as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.worker_generation.to_be_bytes());
        bytes.extend_from_slice(&self.model_load_revision.to_be_bytes());
        bytes.extend_from_slice(&self.control_revision.to_be_bytes());
        for digest in [
            self.request_digest,
            self.feature_receipt_digest,
            self.cost_diagnostic_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(match self.terminal_status {
            NeuronFeatureTerminalStatusV1::Succeeded => 0,
            NeuronFeatureTerminalStatusV1::Failed => 1,
            NeuronFeatureTerminalStatusV1::Cancelled => 2,
            NeuronFeatureTerminalStatusV1::Indeterminate => 3,
        });
        bytes.extend_from_slice(&self.observed_tokens.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.request_id.is_empty()
            && !self.reservation_id.is_empty()
            && !self.worker_id.is_empty()
            && !self.model_id.is_empty()
            && self.worker_generation > 0
            && self.model_load_revision > 0
            && self.control_revision >= 4
            && !self.request_digest.is_zero()
            && !self.feature_receipt_digest.is_zero()
            && !self.cost_diagnostic_digest.is_zero()
            && matches!(
                self.terminal_status,
                NeuronFeatureTerminalStatusV1::Succeeded | NeuronFeatureTerminalStatusV1::Failed
            )
            && !self.source_digest.is_zero()
            && self.source_digest == self.computed_digest()
    }
}

#[derive(Debug, Eq, PartialEq)]
pub enum NeuronObservedCostSourceErrorV1 {
    Missing,
    Stale,
    Binding,
    Worker(WorkerError),
}

impl fmt::Display for NeuronObservedCostSourceErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for NeuronObservedCostSourceErrorV1 {}
impl From<WorkerError> for NeuronObservedCostSourceErrorV1 {
    fn from(value: WorkerError) -> Self {
        Self::Worker(value)
    }
}

/// Require the actual in-memory cost from THIS Worker incarnation, a verified
/// typed feature receipt, and a matching single-use durable Dispatching claim.
/// This cannot issue a numeric resource debit: tokens and quota usage units
/// have distinct units and no authoritative conversion is present here.
pub fn read_neuron_observed_cost_source_v1<D: ModelDriver>(
    owner: &DurableInferenceControl,
    worker: &InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    receipt: &NeuronFeatureReceiptV1,
    cost: &WorkerNeuronTokenCostV1,
    now_ms: u64,
) -> Result<NeuronObservedCostSourceV1, NeuronObservedCostSourceErrorV1> {
    let request_digest = neuron_feature_request_digest_v1(request)
        .map_err(|_| NeuronObservedCostSourceErrorV1::Binding)?;
    verify_neuron_feature_receipt_v1(request, receipt)
        .map_err(|_| NeuronObservedCostSourceErrorV1::Binding)?;
    if !cost.validate_integrity()
        || !cost.matches_live_worker(worker)
        || cost.terminal_status() != receipt.status
        || cost.receipt_digest() != receipt.receipt_digest
    {
        return Err(NeuronObservedCostSourceErrorV1::Binding);
    }
    let record = owner
        .get(request.request_id.as_str())
        .ok_or(NeuronObservedCostSourceErrorV1::Missing)?;
    if record.state != RequestState::Dispatching
        || record.revision < 4
        || record.terminal_observation_digest.is_some()
    {
        return Err(NeuronObservedCostSourceErrorV1::Stale);
    }
    let reservation = record.reservation.as_ref()
        .ok_or(NeuronObservedCostSourceErrorV1::Binding)?;
    let assignment = record.assignment.as_ref()
        .ok_or(NeuronObservedCostSourceErrorV1::Binding)?;
    if record.request.semantic_digest != request_digest.to_string()
        || record.request.request_id != request.request_id.as_str()
        || assignment.worker_id != worker.worker_id()
        || assignment.worker_generation != worker.worker_generation()
        || !cost.matches_source(request, &reservation.reservation_id, request_digest)
        || cost.consumed_tokens() > record.request.maximum_tokens
        || cost.consumed_tokens() > reservation.maximum_tokens
        || reservation.quota_units == 0
    {
        return Err(NeuronObservedCostSourceErrorV1::Binding);
    }
    // Match the entire canonical feature payload, not only the typed
    // semantic digest and an equal reservation ID. A generic legacy WAL can
    // contain a syntactically valid but unrelated payload hash.
    let reconstructed = NeuronFeatureRequest {
        authorization: WorkerRequest {
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
        },
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    };
    if canonical_neuron_feature_payload_digest(&reconstructed) != record.request.payload_digest {
        return Err(NeuronObservedCostSourceErrorV1::Binding);
    }
    let model = worker.inspected_neuron_manifest(now_ms, request.model_id.as_str())?;
    if model.model_id != request.model_id.as_str()
        || model.model_digest != record.request.model_digest
        || model.model_digest != receipt.runtime_tuple.model_manifest_digest.to_string()
        || model.weights_digest != request.weights_digest.to_string()
        || model.weights_digest != receipt.runtime_tuple.weights_digest.to_string()
        || model.tokenizer_digest != receipt.runtime_tuple.tokenizer_digest.to_string()
        || model.preprocessor_digest != receipt.runtime_tuple.preprocessor_digest.to_string()
        || model.quantization_digest != receipt.runtime_tuple.quantization_digest.to_string()
        || model.runtime_digest != receipt.runtime_tuple.runtime_digest.to_string()
        || model.device_digest != receipt.runtime_tuple.device_digest.to_string()
    {
        return Err(NeuronObservedCostSourceErrorV1::Binding);
    }
    let mut result = NeuronObservedCostSourceV1 {
        request_id: request.request_id.to_string(),
        reservation_id: reservation.reservation_id.clone(),
        worker_id: assignment.worker_id.clone(),
        worker_generation: assignment.worker_generation,
        model_load_revision: cost.model_load_revision(),
        model_id: request.model_id.to_string(),
        control_revision: record.revision,
        request_digest,
        feature_receipt_digest: receipt.receipt_digest,
        cost_diagnostic_digest: cost.diagnostic_digest(),
        terminal_status: receipt.status,
        observed_tokens: cost.consumed_tokens(),
        source_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    result.source_digest = result.computed_digest();
    if !result.validate_integrity() {
        return Err(NeuronObservedCostSourceErrorV1::Binding);
    }
    Ok(result)
}

/// Cross-check the last observed report against a fresh read of BOTH owners.
/// A self-rehashed stale report cannot survive settlement, cancellation,
/// Worker restart, a different model load, or a missing current resource grant.
pub fn revalidate_neuron_observed_cost_source_v1<D: ModelDriver>(
    owner: &DurableInferenceControl,
    worker: &InferenceWorker<D>,
    request: &NeuronFeatureRequestV1,
    receipt: &NeuronFeatureReceiptV1,
    cost: &WorkerNeuronTokenCostV1,
    previous: &NeuronObservedCostSourceV1,
    now_ms: u64,
) -> Result<(), NeuronObservedCostSourceErrorV1> {
    if !previous.validate_integrity() {
        return Err(NeuronObservedCostSourceErrorV1::Stale);
    }
    let current = read_neuron_observed_cost_source_v1(
        owner, worker, request, receipt, cost, now_ms,
    )?;
    if current != *previous {
        return Err(NeuronObservedCostSourceErrorV1::Stale);
    }
    Ok(())
}

/// Retrospective, read-only comparison of a known-terminal Worker token
/// observation with the ACTUAL fsynced inference.control settlement.
/// Historical correlation is not an independent usage attestation, NDU input,
/// signed terminal outcome, route selection or authorization to debit quota.
const SETTLED_COST_DOMAIN: &[u8] = b"hepta.infer-worker.neuron-settled-cost.diagnostic.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSettledCostDiagnosticV1 {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub model_id: String,
    pub model_load_revision: u64,
    pub dispatch_revision: u64,
    pub settlement_revision: u64,
    pub request_digest: Digest32,
    pub feature_receipt_digest: Digest32,
    pub observed_cost_source_digest: Digest32,
    pub terminal_observation_digest: Digest32,
    pub terminal_status: NeuronFeatureTerminalStatusV1,
    pub settled_tokens: u32,
    /// Units recorded by the external charging owner, NEVER derived from tokens.
    pub settled_usage_units: u64,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronSettledCostDiagnosticV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = SETTLED_COST_DOMAIN.to_vec();
        for id in [
            &self.request_id,
            &self.reservation_id,
            &self.worker_id,
            &self.model_id,
        ] {
            let raw = id.as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        for number in [
            self.worker_generation,
            self.model_load_revision,
            self.dispatch_revision,
            self.settlement_revision,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for digest in [
            self.request_digest,
            self.feature_receipt_digest,
            self.observed_cost_source_digest,
            self.terminal_observation_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(match self.terminal_status {
            NeuronFeatureTerminalStatusV1::Succeeded => 0,
            NeuronFeatureTerminalStatusV1::Failed => 1,
            NeuronFeatureTerminalStatusV1::Cancelled => 2,
            NeuronFeatureTerminalStatusV1::Indeterminate => 3,
        });
        bytes.extend_from_slice(&self.settled_tokens.to_be_bytes());
        bytes.extend_from_slice(&self.settled_usage_units.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.request_id.is_empty()
            && !self.reservation_id.is_empty()
            && !self.worker_id.is_empty()
            && !self.model_id.is_empty()
            && self.worker_generation > 0
            && self.model_load_revision > 0
            && self.dispatch_revision >= 4
            && self.dispatch_revision.checked_add(1) == Some(self.settlement_revision)
            && !self.request_digest.is_zero()
            && !self.feature_receipt_digest.is_zero()
            && !self.observed_cost_source_digest.is_zero()
            && !self.terminal_observation_digest.is_zero()
            && matches!(
                self.terminal_status,
                NeuronFeatureTerminalStatusV1::Succeeded | NeuronFeatureTerminalStatusV1::Failed
            )
            && !self.diagnostic_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronSettledCostErrorV1 {
    Missing,
    NotSettled,
    Mismatch,
    Stale,
}

impl fmt::Display for NeuronSettledCostErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronSettledCostErrorV1 {}

/// A settlement is evaluated HISTORICALLY: it may be inspected after Worker
/// retirement, restart or resource-grant expiry. No fresh physical model use
/// follows from this read. Its input observed_cost_source must have been
/// captured and independently retained while the exact live Worker and
/// fsynced Dispatching owner were available.
///
/// The WAL persists request/assignment, terminal disposition, observed token
/// count and separately priced usage units; it does NOT retain the complete
/// terminal observation payload. This check therefore cannot independently
/// prove output bytes or an authenticated physical meter.
pub fn read_neuron_settled_cost_diagnostic_v1(
    owner: &DurableInferenceControl,
    request: &NeuronFeatureRequestV1,
    receipt: &NeuronFeatureReceiptV1,
    observed_cost_source: &NeuronObservedCostSourceV1,
) -> Result<NeuronSettledCostDiagnosticV1, NeuronSettledCostErrorV1> {
    let request_digest =
        neuron_feature_request_digest_v1(request).map_err(|_| NeuronSettledCostErrorV1::Mismatch)?;
    verify_neuron_feature_receipt_v1(request, receipt)
        .map_err(|_| NeuronSettledCostErrorV1::Mismatch)?;
    if !observed_cost_source.validate_integrity()
        || observed_cost_source.request_id != request.request_id.as_str()
        || observed_cost_source.model_id != request.model_id.as_str()
        || observed_cost_source.request_digest != request_digest
        || observed_cost_source.feature_receipt_digest != receipt.receipt_digest
        || observed_cost_source.terminal_status != receipt.status
    {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    let expected_state = match receipt.status {
        NeuronFeatureTerminalStatusV1::Succeeded => RequestState::Completed,
        NeuronFeatureTerminalStatusV1::Failed => RequestState::Failed,
        NeuronFeatureTerminalStatusV1::Cancelled
        | NeuronFeatureTerminalStatusV1::Indeterminate => {
            return Err(NeuronSettledCostErrorV1::Mismatch);
        }
    };
    let record = owner
        .get(request.request_id.as_str())
        .ok_or(NeuronSettledCostErrorV1::Missing)?;
    if record.state != expected_state || record.terminal_observation_digest.is_none() {
        return Err(NeuronSettledCostErrorV1::NotSettled);
    }
    // The same native durable owner replays the FULL Settle event and now
    // retains its output field. A generic matching token-count WAL cannot
    // inherit a different typed Neuron model result after restart.
    if record.terminal_output_digest.as_deref()
        != Some(receipt.output_digest.to_string().as_str())
    {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    let reservation = record
        .reservation
        .as_ref()
        .ok_or(NeuronSettledCostErrorV1::Mismatch)?;
    let assignment = record
        .assignment
        .as_ref()
        .ok_or(NeuronSettledCostErrorV1::Mismatch)?;
    if observed_cost_source
        .control_revision
        .checked_add(1)
        != Some(record.revision)
        || record.request.request_id != request.request_id.as_str()
        || record.request.semantic_digest != request_digest.to_string()
        || record.request.model_digest != receipt.runtime_tuple.model_manifest_digest.to_string()
        || reservation.reservation_id != observed_cost_source.reservation_id
        || assignment.worker_id != observed_cost_source.worker_id
        || assignment.worker_generation != observed_cost_source.worker_generation
        || record.consumed_tokens != observed_cost_source.observed_tokens
        || record.consumed_tokens > record.request.maximum_tokens
        || record.consumed_tokens > reservation.maximum_tokens
        || record.usage_units > reservation.quota_units
    {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    // Unlike the generic durable inference WAL, the Neuron typed feature
    // request has an independently canonical Q24 payload identity. Rebuild
    // the *entire* Worker payload at historical settlement time as well as
    // at pre-dispatch admission: otherwise a legacy request with the right
    // semantic digest but different bytes could inherit another execution's
    // token-cost report after crash recovery.
    let actual_payload = canonical_neuron_feature_payload_digest(&NeuronFeatureRequest {
        authorization: WorkerRequest {
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
        },
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        weights_digest: request.weights_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    });
    if actual_payload != record.request.payload_digest {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    let terminal_observation_digest = Digest32::from_str(
        record
            .terminal_observation_digest
            .as_deref()
            .ok_or(NeuronSettledCostErrorV1::NotSettled)?,
    )
    .map_err(|_| NeuronSettledCostErrorV1::Mismatch)?;
    if terminal_observation_digest.is_zero() {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    let mut report = NeuronSettledCostDiagnosticV1 {
        request_id: record.request.request_id.clone(),
        reservation_id: reservation.reservation_id.clone(),
        worker_id: assignment.worker_id.clone(),
        worker_generation: assignment.worker_generation,
        model_id: request.model_id.to_string(),
        model_load_revision: observed_cost_source.model_load_revision,
        dispatch_revision: observed_cost_source.control_revision,
        settlement_revision: record.revision,
        request_digest,
        feature_receipt_digest: receipt.receipt_digest,
        observed_cost_source_digest: observed_cost_source.source_digest,
        terminal_observation_digest,
        terminal_status: receipt.status,
        settled_tokens: record.consumed_tokens,
        settled_usage_units: record.usage_units,
        diagnostic_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    report.diagnostic_digest = report.computed_digest();
    if !report.validate_integrity() {
        return Err(NeuronSettledCostErrorV1::Mismatch);
    }
    Ok(report)
}

/// Re-read the durable settlement; a copied, edited or superseded report
/// cannot be treated as a second credit or fresh Worker observation.
pub fn revalidate_neuron_settled_cost_diagnostic_v1(
    owner: &DurableInferenceControl,
    request: &NeuronFeatureRequestV1,
    receipt: &NeuronFeatureReceiptV1,
    observed_cost_source: &NeuronObservedCostSourceV1,
    previous: &NeuronSettledCostDiagnosticV1,
) -> Result<(), NeuronSettledCostErrorV1> {
    if !previous.validate_integrity() {
        return Err(NeuronSettledCostErrorV1::Stale);
    }
    let current = read_neuron_settled_cost_diagnostic_v1(
        owner,
        request,
        receipt,
        observed_cost_source,
    )?;
    if current != *previous {
        return Err(NeuronSettledCostErrorV1::Stale);
    }
    Ok(())
}

#[cfg(test)]
#[path = "neuron_durable_assignment_tests.rs"]
mod tests;
