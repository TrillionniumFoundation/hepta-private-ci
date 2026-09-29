//! Semantic retrieval is a versioned profile of the existing inference owner.
//!
//! All events share DurableInferenceControl's file, fsync, poison state, record
//! capacity and exclusive writer lock. No model is invoked by this module.
//! A dispatch fence survives a crash; neither cancellation nor reopening can
//! turn it into permission to execute again. Stored results are observations,
//! not current source authorization, learned efficacy or external task success.

use std::collections::BTreeMap;
use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::DurableInferenceControl;
use super::Error;
use super::InferenceRequest;
use super::RequestRecord;
use super::RequestState;
use super::validate_digest;
use super::validate_identity;
use crate::MAX_RETRIEVAL_FRAME_BYTES;
use crate::SemanticRetrievalRequestV1;

pub(super) const JOURNAL_PREFIX: &str = "semantic-retrieval-v1|";
// Vec<u8> uses at most four JSON bytes per input byte; reserve bounded metadata
// plus result/cancel/ack space for every still-open semantic admission.
const FUTURE_RECORD_BYTES: u64 = 4 * MAX_RETRIEVAL_FRAME_BYTES as u64 + 16_384;
const DELIVERY_ACK_BYTES: u64 = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticAdmissionV1 {
    pub request_wire: Vec<u8>,
    pub principal_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub maximum_tokens: u32,
    pub maximum_memory_bytes: u64,
    /// Identity of the host's already verified grant; not a grant by itself.
    pub authority_binding_digest: String,
}

/// Exact per-call resource identity for the modern experimental worker.
/// This is a persisted bound, not device measurement or execution authority.
/// Its new critical journal event is rejected by older readers; V1 bytes retain
/// their old meaning. A changed resident/KV/transient split is a conflict even
/// when the total remains equal.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticResourceLimitsV2 {
    pub model_id: String,
    pub resident_bytes: u64,
    pub kv_bytes: u64,
    pub transient_bytes: u64,
}

impl SemanticResourceLimitsV2 {
    pub fn total_bytes(&self) -> Result<u64, Error> {
        validate_identity(&self.model_id, "semantic model")?;
        if self.resident_bytes == 0 {
            return Err(Error::InvalidTransition);
        }
        self.resident_bytes
            .checked_add(self.kv_bytes)
            .and_then(|bytes| bytes.checked_add(self.transient_bytes))
            .ok_or(Error::ArithmeticOverflow)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SemanticPhaseV1 {
    Reserved,
    DispatchFenced,
    Completed,
    NotDispatched,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SemanticCompletionV1 {
    /// Entire validated HPTARS V1 reply; no digest-only or stdout-ACK result.
    pub reply_wire: Vec<u8>,
    /// Unknown measurement is None, not zero. It prevents eligible delivery,
    /// but does not erase an otherwise complete observed computation result.
    pub observed_memory_bytes: Option<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRecordV1 {
    pub admission: SemanticAdmissionV1,
    /// None identifies the legacy admission. It is not a zero-resource budget.
    pub resource_limits: Option<SemanticResourceLimitsV2>,
    pub revision: u64,
    pub admitted_at_ms: u64,
    pub phase: SemanticPhaseV1,
    pub cancel_requested: bool,
    pub stop_reason: Option<String>,
    pub completion: Option<SemanticCompletionV1>,
    pub completion_digest: Option<String>,
    pub within_resource_budget: bool,
    pub delivery_ack_digest: Option<String>,
}

impl SemanticRecordV1 {
    /// Eligibility only: the consumer must still revalidate source/artifact
    /// currentness, authority, generation and deadline at actual use.
    pub fn delivery_pending(&self) -> bool {
        self.phase == SemanticPhaseV1::Completed
            && self.within_resource_budget
            && !self.cancel_requested
            && self.delivery_ack_digest.is_none()
    }

    pub fn execution_unknown(&self) -> bool {
        self.phase == SemanticPhaseV1::DispatchFenced
    }

    fn reserved_bytes(&self) -> u64 {
        if self.holds_slot() {
            FUTURE_RECORD_BYTES
        } else if self.delivery_pending() {
            DELIVERY_ACK_BYTES
        } else {
            0
        }
    }

    fn holds_slot(&self) -> bool {
        matches!(
            self.phase,
            SemanticPhaseV1::Reserved | SemanticPhaseV1::DispatchFenced
        )
    }
}

#[derive(Clone, Debug, Default)]
pub(super) struct SemanticJournal {
    pub(super) records: BTreeMap<String, SemanticRecordV1>,
    // Rebuilt by the same replay reducer; never a second persisted authority.
    reservation_ids: BTreeSet<String>,
    maximum_in_flight: Option<usize>,
    in_flight: usize,
    pending_bytes: u64,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
enum Event {
    ReserveResourcesV2 {
        admission: SemanticAdmissionV1,
        resource_limits: SemanticResourceLimitsV2,
        maximum_in_flight: usize,
        now_ms: u64,
    },
    Reserve {
        admission: SemanticAdmissionV1,
        maximum_in_flight: usize,
        now_ms: u64,
    },
    Fence {
        request_id: String,
        expected_revision: u64,
        now_ms: u64,
    },
    Cancel {
        request_id: String,
    },
    Stop {
        request_id: String,
        reason: String,
    },
    Complete {
        request_id: String,
        completion: SemanticCompletionV1,
    },
    Acknowledge {
        request_id: String,
        receipt_digest: String,
    },
}

// File locks otherwise survive until the last duplicated or fork-inherited
// descriptor closes. Explicit release at owner destruction prevents an unrelated
// concurrent child spawn from retaining this owner's fence until exec. The file
// remains private and all journal writes have completed before this destructor.
impl Drop for DurableInferenceControl {
    fn drop(&mut self) {
        // Failure is conservative: closing all descriptors still releases the
        // lock, and another open must continue to fail rather than steal it.
        let _ = self.file.unlock();
    }
}

impl DurableInferenceControl {
    pub fn reserve_semantic(
        &mut self,
        now_ms: u64,
        admission: SemanticAdmissionV1,
        maximum_in_flight: usize,
    ) -> Result<SemanticRecordV1, Error> {
        self.reserve_semantic_profile(now_ms, admission, maximum_in_flight, None)
    }

    /// Atomically persist the admission and exact resource tuple in the same
    /// owner journal. Never retrofit resources onto a legacy or existing call.
    pub fn reserve_semantic_with_resources(
        &mut self,
        now_ms: u64,
        admission: SemanticAdmissionV1,
        maximum_in_flight: usize,
        resource_limits: SemanticResourceLimitsV2,
    ) -> Result<SemanticRecordV1, Error> {
        self.reserve_semantic_profile(now_ms, admission, maximum_in_flight, Some(resource_limits))
    }

    fn reserve_semantic_profile(
        &mut self,
        now_ms: u64,
        admission: SemanticAdmissionV1,
        maximum_in_flight: usize,
        resource_limits: Option<SemanticResourceLimitsV2>,
    ) -> Result<SemanticRecordV1, Error> {
        self.semantic_ready()?;
        let request = validate_admission(&admission)?;
        if let Some(limits) = &resource_limits
            && limits.total_bytes()? != admission.maximum_memory_bytes
        {
            return Err(Error::Conflict);
        }
        if self
            .semantic
            .maximum_in_flight
            .is_some_and(|limit| limit != maximum_in_flight)
        {
            return Err(Error::Conflict);
        }
        if let Some(record) = self.semantic.records.get(&request.operation_id) {
            // Replay audit facts even after expiry; this never issues a new
            // dispatch or makes a revoked/expired result eligible for use.
            return if record.admission == admission && record.resource_limits == resource_limits {
                Ok(record.clone())
            } else {
                Err(Error::Conflict)
            };
        }
        if now_ms >= request.deadline_ms {
            return Err(Error::InvalidTime);
        }
        if self.records.contains_key(&request.operation_id)
            || self.native.records.contains_key(&request.operation_id)
        {
            return Err(Error::Conflict);
        }
        if self.records.len() + self.native.records.len() >= self.capacity {
            return Err(Error::CapacityExceeded);
        }
        // Owner-only profile, matching the existing hosted admission rule.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if self.file.metadata()?.permissions().mode() & 0o077 != 0 {
                return Err(Error::InvalidIdentity(
                    "semantic journal must be owner-only",
                ));
            }
        }
        let reserve = self
            .semantic
            .pending_result_bytes()
            .checked_add(2 * FUTURE_RECORD_BYTES)
            .and_then(|bytes| bytes.checked_add(2 * super::MAX_JOURNAL_LINE_BYTES as u64))
            .ok_or(Error::ArithmeticOverflow)?;
        if self
            .journal_bytes
            .checked_add(reserve)
            .is_none_or(|bytes| bytes > super::MAX_JOURNAL_BYTES)
        {
            return Err(Error::CapacityExceeded);
        }
        let event = match resource_limits {
            Some(resource_limits) => Event::ReserveResourcesV2 {
                admission,
                resource_limits,
                maximum_in_flight,
                now_ms,
            },
            None => Event::Reserve {
                admission,
                maximum_in_flight,
                now_ms,
            },
        };
        self.commit_semantic(event)
    }

    /// The only transition that permits a live caller to enter the driver.
    /// Repeated/recovered DispatchFenced returns InvalidTransition. A caller
    /// that loses the returned record must look up/reconcile, never redispatch.
    pub fn fence_semantic_dispatch(
        &mut self,
        request_id: &str,
        expected_revision: u64,
        now_ms: u64,
    ) -> Result<SemanticRecordV1, Error> {
        self.commit_semantic(Event::Fence {
            request_id: request_id.to_string(),
            expected_revision,
            now_ms,
        })
    }

    pub fn cancel_semantic(&mut self, request_id: &str) -> Result<SemanticRecordV1, Error> {
        self.commit_semantic(Event::Cancel {
            request_id: request_id.to_string(),
        })
    }

    /// Only the durable Reserved state proves that the driver was not entered.
    pub fn stop_semantic_before_dispatch(
        &mut self,
        request_id: &str,
        reason: String,
    ) -> Result<SemanticRecordV1, Error> {
        self.commit_semantic(Event::Stop {
            request_id: request_id.to_string(),
            reason,
        })
    }

    /// Trusted observer port. Validate and persist full results, including late
    /// or over-budget results; delivery eligibility is a separate fact. A
    /// driver error, timeout or cancellation ACK is not a completion.
    pub fn complete_semantic(
        &mut self,
        request_id: &str,
        completion: SemanticCompletionV1,
    ) -> Result<SemanticRecordV1, Error> {
        self.commit_semantic(Event::Complete {
            request_id: request_id.to_string(),
            completion,
        })
    }

    /// Record an already validated downstream owner acknowledgement. This
    /// does not directly mutate Neuron, TaskFlow or the learning ledger.
    pub fn acknowledge_semantic_delivery(
        &mut self,
        request_id: &str,
        receipt_digest: String,
    ) -> Result<SemanticRecordV1, Error> {
        self.commit_semantic(Event::Acknowledge {
            request_id: request_id.to_string(),
            receipt_digest,
        })
    }

    pub fn semantic_record(&self, request_id: &str) -> Result<Option<&SemanticRecordV1>, Error> {
        self.semantic_ready()?;
        Ok(self.semantic.records.get(request_id))
    }

    fn semantic_ready(&self) -> Result<(), Error> {
        if self.poisoned {
            Err(Error::WriterUnavailable)
        } else {
            Ok(())
        }
    }

    fn commit_semantic(&mut self, event: Event) -> Result<SemanticRecordV1, Error> {
        self.semantic_ready()?;
        let prepared = self.semantic.prepare(&event, &self.records)?;
        if self.semantic.records.get(&prepared.0) == Some(&prepared.1) {
            return Ok(prepared.1);
        }
        let encoded =
            serde_json::to_string(&event).map_err(|_| Error::CorruptJournal("semantic encode"))?;
        self.append_with_semantic_reservation(&format!("{JOURNAL_PREFIX}{encoded}\n"), prepared.5)?;
        // Domain validation precedes append. Publication follows fsync;
        // failed writes poison the owner rather than publish cached success.
        let result = prepared.1.clone();
        self.semantic.publish(prepared, &mut self.records);
        Ok(result)
    }
}

// The primary record is an internal identity reservation only. Public legacy
// get/mutation paths reject semantic IDs rather than exposing this sentinel
// as an alternative state machine. Native IDs share the same capacity check.
type Prepared = (
    String,
    SemanticRecordV1,
    Option<RequestRecord>,
    usize,
    usize,
    u64,
);

impl SemanticJournal {
    pub(super) fn pending_result_bytes(&self) -> u64 {
        self.pending_bytes
    }

    pub(super) fn replay(
        &mut self,
        json: &str,
        primary: &mut BTreeMap<String, RequestRecord>,
    ) -> Result<(), Error> {
        let event: Event =
            serde_json::from_str(json).map_err(|_| Error::CorruptJournal("semantic decode"))?;
        let prepared = self.prepare(&event, primary)?;
        self.publish(prepared, primary);
        Ok(())
    }

    fn prepare(
        &self,
        event: &Event,
        primary: &BTreeMap<String, RequestRecord>,
    ) -> Result<Prepared, Error> {
        if let Event::Reserve {
            admission,
            maximum_in_flight,
            now_ms,
        }
        | Event::ReserveResourcesV2 {
            admission,
            maximum_in_flight,
            now_ms,
            ..
        } = event
        {
            let resource_limits = match event {
                Event::ReserveResourcesV2 {
                    resource_limits, ..
                } => Some(resource_limits.clone()),
                Event::Reserve { .. } => None,
                Event::Fence { .. }
                | Event::Cancel { .. }
                | Event::Stop { .. }
                | Event::Complete { .. }
                | Event::Acknowledge { .. } => return Err(Error::InvalidTransition),
            };
            if let Some(limits) = &resource_limits
                && limits.total_bytes()? != admission.maximum_memory_bytes
            {
                return Err(Error::Conflict);
            }
            let input = validate_admission(admission)?;
            if *now_ms >= input.deadline_ms {
                return Err(Error::InvalidTime);
            }
            if !(1..=256).contains(maximum_in_flight) || self.in_flight >= *maximum_in_flight {
                return Err(Error::CapacityExceeded);
            }
            if self
                .maximum_in_flight
                .is_some_and(|limit| limit != *maximum_in_flight)
                || primary.contains_key(&input.operation_id)
                || self.records.contains_key(&input.operation_id)
                || self.reservation_ids.contains(&admission.reservation_id)
            {
                return Err(Error::Conflict);
            }
            let wire_digest = Digest32::of_bytes(&admission.request_wire).to_string();
            let encoded = serde_json::to_vec(admission)
                .map_err(|_| Error::CorruptJournal("semantic admission"))?;
            let marker = RequestRecord {
                request: InferenceRequest {
                    request_id: input.operation_id.clone(),
                    principal_id: admission.principal_id.clone(),
                    model_digest: input.bundle_digest,
                    payload_digest: wire_digest,
                    maximum_tokens: admission.maximum_tokens,
                    deadline_ms: input.deadline_ms,
                    semantic_digest: Digest32::of_bytes(&encoded).to_string(),
                },
                revision: 1,
                state: RequestState::Pending,
                reservation: None,
                assignment: None,
                terminal_observation_digest: None,
                consumed_tokens: 0,
                usage_units: 0,
            };
            let record = SemanticRecordV1 {
                admission: admission.clone(),
                resource_limits,
                revision: 1,
                admitted_at_ms: *now_ms,
                phase: SemanticPhaseV1::Reserved,
                cancel_requested: false,
                stop_reason: None,
                completion: None,
                completion_digest: None,
                within_resource_budget: false,
                delivery_ack_digest: None,
            };
            let pending = self
                .pending_bytes
                .checked_add(record.reserved_bytes())
                .ok_or(Error::ArithmeticOverflow)?;
            return Ok((
                input.operation_id,
                record,
                Some(marker),
                *maximum_in_flight,
                self.in_flight + 1,
                pending,
            ));
        }
        let id = match event {
            Event::Reserve { .. } | Event::ReserveResourcesV2 { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Fence { request_id, .. }
            | Event::Cancel { request_id }
            | Event::Stop { request_id, .. }
            | Event::Complete { request_id, .. }
            | Event::Acknowledge { request_id, .. } => request_id,
        };
        let old = self.records.get(id).ok_or(Error::RequestNotFound)?;
        let mut next = old.clone();
        match event {
            Event::Reserve { .. } | Event::ReserveResourcesV2 { .. } => {
                return Err(Error::InvalidTransition);
            }
            Event::Fence {
                expected_revision,
                now_ms,
                ..
            } => {
                if old.revision != *expected_revision {
                    return Err(Error::StaleRevision);
                }
                if old.phase != SemanticPhaseV1::Reserved || old.cancel_requested {
                    return Err(Error::InvalidTransition);
                }
                let request = validate_admission(&old.admission)?;
                if *now_ms < old.admitted_at_ms || *now_ms >= request.deadline_ms {
                    return Err(Error::InvalidTime);
                }
                next.phase = SemanticPhaseV1::DispatchFenced;
            }
            Event::Cancel { .. } => {
                next.cancel_requested = true;
                if old.phase == SemanticPhaseV1::Reserved {
                    next.phase = SemanticPhaseV1::NotDispatched;
                    next.stop_reason = Some("cancelled_before_dispatch".to_string());
                }
            }
            Event::Stop { reason, .. } => {
                validate_identity(reason, "semantic stop reason")?;
                if old.phase == SemanticPhaseV1::NotDispatched {
                    if old.stop_reason.as_ref() != Some(reason) {
                        return Err(Error::Conflict);
                    }
                } else if old.phase == SemanticPhaseV1::Reserved {
                    next.phase = SemanticPhaseV1::NotDispatched;
                    next.stop_reason = Some(reason.clone());
                } else {
                    return Err(Error::InvalidTransition);
                }
            }
            Event::Complete { completion, .. } => {
                let request = validate_admission(&old.admission)?;
                let reply = request
                    .decode_reply(&completion.reply_wire)
                    .map_err(|_| Error::CorruptJournal("semantic reply binding"))?;
                if old.phase == SemanticPhaseV1::Completed {
                    if old.completion.as_ref() != Some(completion) {
                        return Err(Error::Conflict);
                    }
                } else if old.phase == SemanticPhaseV1::DispatchFenced {
                    let total = reply
                        .input_tokens
                        .checked_add(reply.output_tokens)
                        .ok_or(Error::ArithmeticOverflow)?;
                    next.within_resource_budget = total <= u64::from(old.admission.maximum_tokens)
                        && completion.observed_memory_bytes.is_some_and(|memory| {
                            memory > 0 && memory <= old.admission.maximum_memory_bytes
                        });
                    let encoded = serde_json::to_vec(completion)
                        .map_err(|_| Error::CorruptJournal("semantic completion"))?;
                    next.completion_digest = Some(Digest32::of_bytes(&encoded).to_string());
                    next.completion = Some(completion.clone());
                    next.phase = SemanticPhaseV1::Completed;
                } else {
                    return Err(Error::InvalidTransition);
                }
            }
            Event::Acknowledge { receipt_digest, .. } => {
                validate_digest(receipt_digest, "semantic downstream receipt")?;
                if let Some(existing) = &old.delivery_ack_digest {
                    if existing != receipt_digest {
                        return Err(Error::Conflict);
                    }
                } else {
                    if !old.delivery_pending() {
                        return Err(Error::InvalidTransition);
                    }
                    next.delivery_ack_digest = Some(receipt_digest.clone());
                }
            }
        }
        let slots = self
            .in_flight
            .checked_sub(usize::from(old.holds_slot() && !next.holds_slot()))
            .ok_or(Error::CorruptJournal("semantic slot accounting"))?;
        if &next != old {
            next.revision = next
                .revision
                .checked_add(1)
                .ok_or(Error::ArithmeticOverflow)?;
        }
        let pending = self
            .pending_bytes
            .checked_sub(old.reserved_bytes())
            .and_then(|bytes| bytes.checked_add(next.reserved_bytes()))
            .ok_or(Error::CorruptJournal("semantic byte accounting"))?;
        Ok((
            id.clone(),
            next,
            None,
            self.maximum_in_flight.ok_or(Error::InvalidTransition)?,
            slots,
            pending,
        ))
    }

    fn publish(&mut self, prepared: Prepared, primary: &mut BTreeMap<String, RequestRecord>) {
        let (id, record, marker, limit, slots, pending) = prepared;
        if let Some(marker) = marker {
            // Publication occurs only after the existing journal append/fsync,
            // or after that exact event has been validated during replay. Keep
            // terminal reservations: settlement does not permit ID reuse.
            self.reservation_ids
                .insert(record.admission.reservation_id.clone());
            primary.insert(id.clone(), marker);
        }
        self.records.insert(id, record);
        self.maximum_in_flight = Some(limit);
        self.in_flight = slots;
        self.pending_bytes = pending;
    }
}

fn validate_admission(
    admission: &SemanticAdmissionV1,
) -> Result<SemanticRetrievalRequestV1, Error> {
    let request = SemanticRetrievalRequestV1::decode(&admission.request_wire)
        .map_err(|_| Error::CorruptJournal("semantic request binding"))?;
    validate_identity(&request.operation_id, "semantic request")?;
    validate_identity(&admission.principal_id, "semantic principal")?;
    validate_identity(&admission.reservation_id, "semantic reservation")?;
    validate_identity(&admission.worker_id, "semantic worker")?;
    validate_digest(
        &admission.authority_binding_digest,
        "semantic authority binding",
    )?;
    if admission.worker_generation != request.generation
        || admission.maximum_tokens == 0
        || admission.maximum_tokens > super::MAX_TOKENS
        || admission.maximum_memory_bytes == 0
    {
        return Err(Error::InvalidTransition);
    }
    Ok(request)
}

#[cfg(test)]
#[path = "semantic_control_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "semantic_owner_lock_tests.rs"]
mod owner_lock_tests;

#[cfg(test)]
#[path = "semantic_resource_tests.rs"]
mod resource_tests;
