//! Verified join between retrieval assignment preparation and the durable native
//! inference journal. Preparation, dispatch with an unknown external outcome,
//! external publication, native turn/start, and terminal outcome observation are
//! distinct monotonic evidence stages.
//!
//! A write-ahead `NativeDispatch` is deliberately not publication evidence: it
//! is committed before the external App Server effect boundary. Once that
//! dispatch is durable, however, the operation is no longer equivalent to a
//! merely prepared request. Until a typed response or exact turn is observed it
//! is `DispatchOutcomeUnknown`, must be reconciled by exact operation identity,
//! and must never be blindly replayed. Publication is recognized only from an
//! observed typed server response or is implied by a durable native turn.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_agent_components::infer_core::durable_control::native::NativeRunRecord;
use codex_hepta_agent_components::infer_core::durable_control::native::NativeRunStatus;
use codex_hepta_agent_components::learning_ledger::RetrievalPreparationFactV1;
use codex_hepta_agent_components::memory_retrieval::DurableDecisionPortV1;
use codex_hepta_agent_components::memory_retrieval::DurableDecisionRecordV1;
use codex_hepta_agent_components::memory_retrieval::LifecycleErrorV1;
use codex_hepta_agent_components::memory_retrieval::QuarantinedUnknownOutcomeV1;
use codex_hepta_agent_components::memory_retrieval::RetrievalExecutionIdentityV1;
use codex_hepta_agent_components::memory_retrieval::RetrievalLifecyclePhaseV1;
use codex_hepta_agent_components::types::AuthorityPosture;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::StableId;

const RECEIPT_DOMAIN: &[u8] = b"hepta.retrieval-native-delivery-receipt.v3";
const DISPATCH_UNKNOWN_REASON: &str = "native_dispatch_outcome_unknown";
const TERMINAL_INDETERMINATE_REASON: &str = "native_terminal_outcome_indeterminate";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RetrievalDeliveryStageV1 {
    /// An idempotent preparation is durable and no external dispatch is known.
    /// Later freshness fences may still fail. Neither publication nor consumer
    /// use is claimed.
    AssignmentPrepared,
    /// A write-ahead dispatch is durable but no typed server response or exact
    /// turn has been observed. The external outcome may have happened. Recovery
    /// is exact-operation reconciliation only; blind replay is forbidden.
    DispatchOutcomeUnknown,
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
    pub native_principal_id: String,
    pub native_worker_generation: u64,
    /// Exact prepared owner-context digest. Its presence alone is never treated
    /// as publication evidence.
    pub context_digest: Option<Digest32>,
    /// Exact candidate identities in prepared position order, never a sorted set.
    pub prepared_candidate_digests: Vec<Digest32>,
    pub native_revision: Option<u64>,
    pub stage: RetrievalDeliveryStageV1,
    /// Digest of a typed pre-start server response when `stage == Published`.
    pub publication_receipt_digest: Option<Digest32>,
    pub turn_id: Option<String>,
    pub terminal_status: Option<NativeRunStatus>,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// The native owner supplies the expected run identity independently of the
/// record being inspected. Context equality alone cannot correlate two runs.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalNativeBindingV1 {
    pub request_id: String,
    pub principal_id: String,
    pub worker_generation: u64,
}

/// Canonical lifecycle projection of the two existing durable owners. This is
/// not another ledger or writer. `record` can be appended by the already owned
/// durable decision port; `quarantine` is present only when exact-operation
/// reconciliation is required before any further effect or learning use.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalLifecycleProjectionV1 {
    pub record: DurableDecisionRecordV1,
    pub quarantine: Option<QuarantinedUnknownOutcomeV1>,
}

impl RetrievalDeliveryReceiptV1 {
    pub fn validate(&self) -> Result<(), RetrievalDeliveryError> {
        if self.native_principal_id.is_empty() || self.native_worker_generation == 0 {
            return Err(RetrievalDeliveryError::NativeIdentityMismatch);
        }
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
        if self.prepared_candidate_digests.len() > 16
            || self
                .prepared_candidate_digests
                .iter()
                .any(|value| value.is_zero())
            || self
                .prepared_candidate_digests
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != self.prepared_candidate_digests.len()
            || self.context_digest.is_some() == self.prepared_candidate_digests.is_empty()
        {
            return Err(RetrievalDeliveryError::AssignmentPreparationMismatch);
        }
        if self
            .native_request_id
            .as_ref()
            .is_some_and(|value| value.is_empty())
            || self.native_revision == Some(0)
            || self.turn_id.as_ref().is_some_and(|value| value.is_empty())
        {
            return Err(RetrievalDeliveryError::InvalidStageEvidence);
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
            RetrievalDeliveryStageV1::DispatchOutcomeUnknown => {
                if self.context_digest.is_none()
                    || self.native_request_id.is_none()
                    || self.publication_receipt_digest.is_some()
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

    /// True only when recovery must query the already named native operation and
    /// may not create a new effect under the same logical retrieval request.
    #[must_use]
    pub fn requires_exact_operation_reconciliation(&self) -> bool {
        self.stage == RetrievalDeliveryStageV1::DispatchOutcomeUnknown
            || (self.stage == RetrievalDeliveryStageV1::OutcomeObserved
                && self.terminal_status == Some(NativeRunStatus::Indeterminate))
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = RECEIPT_DOMAIN.to_vec();
        push_text(&mut bytes, self.assignment_record_id.as_str());
        push_optional_text(&mut bytes, self.native_request_id.as_deref());
        push_text(&mut bytes, &self.native_principal_id);
        bytes.extend_from_slice(&self.native_worker_generation.to_be_bytes());
        push_optional_digest(&mut bytes, self.context_digest);
        bytes.extend_from_slice(&(self.prepared_candidate_digests.len() as u64).to_be_bytes());
        for candidate in &self.prepared_candidate_digests {
            bytes.extend_from_slice(candidate.as_array());
        }
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
    NativeIdentityMismatch,
    LifecycleIdentityMismatch(&'static str),
    InvalidContextDigest,
    NativeDispatchMissingContext,
    NativeContextDigestMismatch,
    NativeTurnMismatch,
    InvalidPublicationReceipt,
    InvalidStageEvidence,
    AuthorityGranted,
    DigestMismatch,
    Lifecycle(LifecycleErrorV1),
}

impl fmt::Display for RetrievalDeliveryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RetrievalDeliveryError {}

impl From<LifecycleErrorV1> for RetrievalDeliveryError {
    fn from(error: LifecycleErrorV1) -> Self {
        Self::Lifecycle(error)
    }
}

/// Join a tag-10 unexposed preparation with one independently named native run.
/// Inputs must come from their owning durable stores, not caller wire structs.
/// The returned digest is an integrity receipt, never an authority credential.
///
/// The result is the highest stage established by durable evidence. A successful
/// request may advance directly from `AssignmentPrepared` to `NativeStarted`;
/// this does not collapse the semantic distinction, because a write-ahead
/// dispatch produces `DispatchOutcomeUnknown`, never `Published`. A typed server
/// rejection establishes `Published` without claiming a native turn.
pub fn verify_retrieval_delivery_v1(
    preparation: &RetrievalPreparationFactV1,
    binding: &RetrievalNativeBindingV1,
    native: Option<&NativeRunRecord>,
) -> Result<RetrievalDeliveryReceiptV1, RetrievalDeliveryError> {
    preparation
        .validate()
        .map_err(|_| RetrievalDeliveryError::AssignmentPreparationMismatch)?;
    if binding.request_id.is_empty()
        || binding.principal_id.is_empty()
        || binding.worker_generation == 0
        || native.is_some_and(|record| {
            record.request.request_id != binding.request_id
                || record.request.principal_id != binding.principal_id
                || record.request.worker_generation != binding.worker_generation
                || record.revision == 0
        })
    {
        return Err(RetrievalDeliveryError::NativeIdentityMismatch);
    }
    let prepared = preparation.prepared_context_digest;

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
            if record.pre_dispatch_stop.is_some()
                && (record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some())
            {
                return Err(RetrievalDeliveryError::InvalidStageEvidence);
            }
            let Some(dispatch) = &record.dispatch else {
                if record.turn_id.is_some()
                    || record.observation.is_some()
                    || record.dispatch_rejection.is_some()
                {
                    return Err(RetrievalDeliveryError::InvalidStageEvidence);
                }
                return receipt(
                    preparation,
                    binding,
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
                    if record.pre_dispatch_stop.is_some() {
                        RetrievalDeliveryStageV1::AssignmentPrepared
                    } else {
                        RetrievalDeliveryStageV1::DispatchOutcomeUnknown
                    },
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
                    if observation.turn_id != *turn_id
                        || observation.thread_id != dispatch.thread_id
                        || observation.model != record.request.model
                        || observation.model_provider != dispatch.model_provider
                    {
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
        preparation,
        binding,
        native_request_id,
        native_revision,
        stage,
        publication_receipt_digest,
        turn_id,
        terminal_status,
    )
}

/// Project the immutable preparation/native join onto the canonical retrieval
/// lifecycle. The caller remains responsible for appending `record` through its
/// existing `DurableDecisionPortV1` with compare-and-append semantics.
pub fn project_retrieval_delivery_lifecycle_v1(
    receipt: &RetrievalDeliveryReceiptV1,
    binding: &RetrievalNativeBindingV1,
    identity: RetrievalExecutionIdentityV1,
    writer_fence: u64,
    frontier: u64,
) -> Result<RetrievalLifecycleProjectionV1, RetrievalDeliveryError> {
    receipt.validate()?;
    if receipt.native_principal_id.as_str() != binding.principal_id.as_str()
        || receipt.native_worker_generation != binding.worker_generation
        || receipt
            .native_request_id
            .as_deref()
            .is_some_and(|request| request != binding.request_id.as_str())
    {
        return Err(RetrievalDeliveryError::NativeIdentityMismatch);
    }
    if identity.principal() != binding.principal_id.as_str() {
        return Err(RetrievalDeliveryError::LifecycleIdentityMismatch(
            "principal",
        ));
    }
    if identity.request() != binding.request_id.as_str() {
        return Err(RetrievalDeliveryError::LifecycleIdentityMismatch("request"));
    }
    if identity.decision_identity() != receipt.assignment_record_id.as_str() {
        return Err(RetrievalDeliveryError::LifecycleIdentityMismatch(
            "decision_identity",
        ));
    }

    let (phase, quarantine_reason) = match receipt.stage {
        RetrievalDeliveryStageV1::AssignmentPrepared => {
            (RetrievalLifecyclePhaseV1::QualifiedDecision, None)
        }
        RetrievalDeliveryStageV1::DispatchOutcomeUnknown => (
            RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
            Some(DISPATCH_UNKNOWN_REASON),
        ),
        RetrievalDeliveryStageV1::Published => {
            (RetrievalLifecyclePhaseV1::PublishedRetrieval, None)
        }
        RetrievalDeliveryStageV1::NativeStarted => {
            (RetrievalLifecyclePhaseV1::ConsumedRetrieval, None)
        }
        RetrievalDeliveryStageV1::OutcomeObserved
            if receipt.terminal_status == Some(NativeRunStatus::Indeterminate) =>
        {
            (
                RetrievalLifecyclePhaseV1::QuarantinedUnknownOutcome,
                Some(TERMINAL_INDETERMINATE_REASON),
            )
        }
        RetrievalDeliveryStageV1::OutcomeObserved => {
            (RetrievalLifecyclePhaseV1::AcknowledgedRetrieval, None)
        }
    };

    let quarantine = quarantine_reason
        .map(|reason| QuarantinedUnknownOutcomeV1::new(identity.clone(), reason.to_string()))
        .transpose()?;
    let record = DurableDecisionRecordV1 {
        identity,
        phase,
        writer_fence,
        frontier,
        payload_digest: receipt.receipt_digest.to_string(),
    };
    record.validate()?;
    Ok(RetrievalLifecycleProjectionV1 { record, quarantine })
}

/// Append exactly one lifecycle fact through the existing durable owner. An
/// unknown outcome uses the port's quarantine append; every other stage uses
/// compare-and-append. The expected frontier and writer fence are never renewed
/// by this helper, so a stale process cannot regain ownership while recovering.
pub fn append_retrieval_lifecycle_projection_v1<P: DurableDecisionPortV1>(
    port: &mut P,
    expected_frontier: u64,
    projection: &RetrievalLifecycleProjectionV1,
) -> Result<u64, P::Error> {
    match &projection.quarantine {
        Some(quarantine) => port.quarantine_unknown_outcome(
            expected_frontier,
            quarantine,
            projection.record.writer_fence,
            &projection.record.payload_digest,
        ),
        None => port.compare_and_append(expected_frontier, &projection.record),
    }
}

#[allow(clippy::too_many_arguments)]
fn receipt(
    preparation: &RetrievalPreparationFactV1,
    binding: &RetrievalNativeBindingV1,
    native_request_id: Option<String>,
    native_revision: Option<u64>,
    stage: RetrievalDeliveryStageV1,
    publication_receipt_digest: Option<Digest32>,
    turn_id: Option<String>,
    terminal_status: Option<NativeRunStatus>,
) -> Result<RetrievalDeliveryReceiptV1, RetrievalDeliveryError> {
    let mut value = RetrievalDeliveryReceiptV1 {
        assignment_record_id: preparation.assignment.record_id.clone(),
        native_request_id,
        native_principal_id: binding.principal_id.clone(),
        native_worker_generation: binding.worker_generation,
        context_digest: preparation.prepared_context_digest,
        prepared_candidate_digests: preparation
            .prepared_candidate_indices
            .iter()
            .map(|index| {
                preparation
                    .assignment
                    .enumerated_candidate_digests
                    .get(*index as usize)
                    .copied()
                    .ok_or(RetrievalDeliveryError::AssignmentPreparationMismatch)
            })
            .collect::<Result<Vec<_>, _>>()?,
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
        RetrievalDeliveryStageV1::DispatchOutcomeUnknown => 4,
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
