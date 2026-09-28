//! Verified join between retrieval assignment preparation and the durable native
//! inference journal. Preparation, external publication, native turn/start, and
//! terminal outcome observation are distinct monotonic evidence stages.
//!
//! A write-ahead `NativeDispatch` is deliberately not publication evidence: it
//! is committed before the external App Server effect boundary. Publication is
//! recognized only from an observed typed server response or is implied by a
//! durable native turn. Unknown socket outcomes therefore remain prepared and
//! reconcile-only rather than becoming false exposures.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_learning_ledger::RetrievalAssignmentFact;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-native-delivery-receipt.v2";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalDeliveryStageV1 {
    /// Final owner/ranker/lifecycle fences passed and the idempotent assignment
    /// fact is durable. No external effect is claimed.
    AssignmentPrepared,
    /// The App Server returned a typed response before turn/start. Successful
    /// requests normally advance directly to `NativeStarted`.
    Published,
    /// An exact App Server turn identity is durable.
    NativeStarted,
    /// A matching terminal native observation is durable.
    OutcomeObserved,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalDeliveryReceiptV1 {
    pub assignment_record_id: StableId,
    pub native_request_id: Option<String>,
    /// Exact prepared owner-context digest. Its presence alone is never treated
    /// as publication evidence.
    pub context_digest: Option<Digest32>,
    pub native_revision: Option<u64>,
    pub stage: RetrievalDeliveryStageV1,
    /// Digest of a typed pre-start server response when `stage == Published`.
    pub publication_receipt_digest: Option<Digest32>,
    pub turn_id: Option<String>,
    pub terminal_status: Option<NativeRunStatus>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl RetrievalDeliveryReceiptV1 {
    pub fn validate(&self) -> Result<(), RetrievalDeliveryError> {
        if self.authority.grants_any() {
            return Err(RetrievalDeliveryError::AuthorityGranted);
        }
        if self.context_digest.is_some_and(Digest32::is_zero)
            || self
                .publication_receipt_digest
                .is_some_and(Digest32::is_zero)
        {
            return Err(RetrievalDeliveryError::InvalidContextDigest);
        }
        if self.native_request_id.is_some() != self.native_revision.is_some() {
            return Err(RetrievalDeliveryError::InvalidStageEvidence);
        }
        match self.stage {
            RetrievalDeliveryStageV1::AssignmentPrepared => {
                if self.publication_receipt_digest.is_some()
                    || self.turn_id.is_some()
                    || self.terminal_status.is_some()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
            }
            RetrievalDeliveryStageV1::Published => {
                if self.context_digest.is_none()
                    || self.native_request_id.is_none()
                    || self.publication_receipt_digest.is_none()
                    || self.turn_id.is_some()
                    || self.terminal_status.is_some()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
            }
            RetrievalDeliveryStageV1::NativeStarted => {
                if self.context_digest.is_none()
                    || self.native_request_id.is_none()
                    || self.publication_receipt_digest.is_some()
                    || self.turn_id.is_none()
                    || self.terminal_status.is_some()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
            }
            RetrievalDeliveryStageV1::OutcomeObserved => {
                if self.context_digest.is_none()
                    || self.native_request_id.is_none()
                    || self.publication_receipt_digest.is_some()
                    || self.turn_id.is_none()
                    || self.terminal_status.is_none()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
            }
        }
        if self.receipt_digest != self.compute_digest() {
            return Err(RetrievalDeliveryError::DigestMismatch);
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = RECEIPT_DOMAIN.to_vec();
        push_text(&mut bytes, self.assignment_record_id.as_str());
        push_optional_text(&mut bytes, self.native_request_id.as_deref());
        push_optional_digest(&mut bytes, self.context_digest);
        match self.native_revision {
            Some(revision) => {
                bytes.push(1);
                bytes.extend_from_slice(&revision.to_be_bytes());
            }
            None => bytes.push(0),
        }
        bytes.push(stage_code(self.stage));
        push_optional_digest(&mut bytes, self.publication_receipt_digest);
        push_optional_text(&mut bytes, self.turn_id.as_deref());
        bytes.push(match self.terminal_status {
            None => 0,
            Some(NativeRunStatus::Completed) => 1,
            Some(NativeRunStatus::Failed) => 2,
            Some(NativeRunStatus::Interrupted) => 3,
            Some(NativeRunStatus::Indeterminate) => 4,
        });
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RetrievalDeliveryError {
    AssignmentPreparationMismatch,
    InvalidContextDigest,
    NativeDispatchMissingContext,
    NativeContextDigestMismatch,
    NativeTurnMismatch,
    InvalidPublicationReceipt,
    InvalidStageEvidence,
    AuthorityGranted,
    DigestMismatch,
}

impl fmt::Display for RetrievalDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RetrievalDeliveryError {}

/// Join one durable retrieval assignment with at most one durable native run.
///
/// The result is the highest stage established by durable evidence. A successful
/// request may advance directly from `AssignmentPrepared` to `NativeStarted`;
/// this does not collapse the semantic distinction, because a write-ahead
/// dispatch never produces `Published`. A typed server rejection establishes
/// `Published` without claiming a native turn.
pub fn verify_retrieval_delivery_v1(
    assignment: &RetrievalAssignmentFact,
    native: Option<&NativeRunRecord>,
) -> Result<RetrievalDeliveryReceiptV1, RetrievalDeliveryError> {
    let prepared = assignment.published_context_digest;
    if assignment.context_exposed != prepared.is_some()
        || assignment.context_exposed == assignment.delivered_candidate_indices.is_empty()
    {
        return Err(RetrievalDeliveryError::AssignmentPreparationMismatch);
    }
    if prepared.is_some_and(Digest32::is_zero) {
        return Err(RetrievalDeliveryError::InvalidContextDigest);
    }

    let (
        native_request_id,
        native_revision,
        stage,
        publication_receipt_digest,
        turn_id,
        terminal_status,
    ) = match (prepared, native) {
        (None, None) => (
            None,
            None,
            RetrievalDeliveryStageV1::AssignmentPrepared,
            None,
            None,
            None,
        ),
        (None, Some(record)) => {
            if record
                .dispatch
                .as_ref()
                .and_then(|dispatch| dispatch.owner_context_digest.as_ref())
                .is_some()
            {
                return Err(RetrievalDeliveryError::AssignmentPreparationMismatch);
            }
            (
                None,
                None,
                RetrievalDeliveryStageV1::AssignmentPrepared,
                None,
                None,
                None,
            )
        }
        (Some(_), None) => (
            None,
            None,
            RetrievalDeliveryStageV1::AssignmentPrepared,
            None,
            None,
            None,
        ),
        (Some(expected), Some(record)) => {
            let request_id = Some(record.request.request_id.clone());
            let revision = Some(record.revision);
            let Some(dispatch) = &record.dispatch else {
                return receipt(
                    assignment,
                    request_id,
                    revision,
                    RetrievalDeliveryStageV1::AssignmentPrepared,
                    None,
                    None,
                    None,
                );
            };
            let Some(raw) = dispatch.owner_context_digest.as_deref() else {
                return Err(RetrievalDeliveryError::NativeDispatchMissingContext);
            };
            let actual = raw
                .parse::<Digest32>()
                .map_err(|_| RetrievalDeliveryError::InvalidContextDigest)?;
            if actual != expected {
                return Err(RetrievalDeliveryError::NativeContextDigestMismatch);
            }
            if record.dispatch_rejection.is_some()
                && (record.turn_id.is_some() || record.observation.is_some())
            {
                return Err(RetrievalDeliveryError::InvalidStageEvidence);
            }
            match (
                &record.turn_id,
                &record.observation,
                &record.dispatch_rejection,
            ) {
                (None, None, Some(rejection)) => {
                    let response_digest = rejection
                        .response_digest
                        .parse::<Digest32>()
                        .map_err(|_| RetrievalDeliveryError::InvalidPublicationReceipt)?;
                    (
                        request_id,
                        revision,
                        RetrievalDeliveryStageV1::Published,
                        Some(response_digest),
                        None,
                        None,
                    )
                }
                (None, None, None) => (
                    request_id,
                    revision,
                    RetrievalDeliveryStageV1::AssignmentPrepared,
                    None,
                    None,
                    None,
                ),
                (None, Some(_), _) => {
                    return Err(RetrievalDeliveryError::NativeTurnMismatch);
                }
                (Some(_), _, Some(_)) => {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
                (Some(turn_id), None, None) => (
                    request_id,
                    revision,
                    RetrievalDeliveryStageV1::NativeStarted,
                    None,
                    Some(turn_id.clone()),
                    None,
                ),
                (Some(turn_id), Some(observation), None) => {
                    if observation.turn_id != *turn_id {
                        return Err(RetrievalDeliveryError::NativeTurnMismatch);
                    }
                    if observation.terminal_observed {
                        (
                            request_id,
                            revision,
                            RetrievalDeliveryStageV1::OutcomeObserved,
                            None,
                            Some(turn_id.clone()),
                            Some(observation.status),
                        )
                    } else {
                        (
                            request_id,
                            revision,
                            RetrievalDeliveryStageV1::NativeStarted,
                            None,
                            Some(turn_id.clone()),
                            None,
                        )
                    }
                }
            }
        }
    };
    receipt(
        assignment,
        native_request_id,
        native_revision,
        stage,
        publication_receipt_digest,
        turn_id,
        terminal_status,
    )
}

fn receipt(
    assignment: &RetrievalAssignmentFact,
    native_request_id: Option<String>,
    native_revision: Option<u64>,
    stage: RetrievalDeliveryStageV1,
    publication_receipt_digest: Option<Digest32>,
    turn_id: Option<String>,
    terminal_status: Option<NativeRunStatus>,
) -> Result<RetrievalDeliveryReceiptV1, RetrievalDeliveryError> {
    let mut value = RetrievalDeliveryReceiptV1 {
        assignment_record_id: assignment.record_id.clone(),
        native_request_id,
        context_digest: assignment.published_context_digest,
        native_revision,
        stage,
        publication_receipt_digest,
        turn_id,
        terminal_status,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    value.receipt_digest = value.compute_digest();
    value.validate()?;
    Ok(value)
}

fn stage_code(stage: RetrievalDeliveryStageV1) -> u8 {
    match stage {
        RetrievalDeliveryStageV1::AssignmentPrepared => 0,
        RetrievalDeliveryStageV1::Published => 1,
        RetrievalDeliveryStageV1::NativeStarted => 2,
        RetrievalDeliveryStageV1::OutcomeObserved => 3,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_optional_text(bytes: &mut Vec<u8>, value: Option<&str>) {
    match value {
        Some(value) => {
            bytes.push(1);
            push_text(bytes, value);
        }
        None => bytes.push(0),
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

#[cfg(test)]
#[path = "retrieval_delivery_tests.rs"]
mod tests;
