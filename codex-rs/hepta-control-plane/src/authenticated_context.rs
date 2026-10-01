//! Authenticated request-local planning over a canonical cognitive read.
//!
//! The established adapter remains available as `plan_observed_context`. New
//! product callers supply exact record identities and a request binding; the
//! verified item count is derived here and can no longer be asserted
//! independently by the caller.

use std::collections::BTreeSet;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::NduPlanningError;
use crate::ObservedContextPlanV1;
use crate::ObservedContextV1;
use crate::PlannerError;
use crate::plan_observed_context;

const MAX_AUTHENTICATED_CONTEXT_RECORDS: usize = 4;

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct AuthenticatedContextRecordV1 {
    pub record_id: StableId,
    pub revision: u64,
    pub content_digest: Digest32,
}

/// Canonical host evidence for one already-authenticated owner read.
///
/// `request_binding_digest` binds request identity, normalized query, retrieval
/// profile and any selected ranker/model policy.  The record count is derived
/// from `records`; it is intentionally absent from this contract.
pub struct AuthenticatedObservedContextV1<'a> {
    pub owner_id: StableId,
    pub body_generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub read_digest: Digest32,
    pub request_binding_digest: Digest32,
    pub records: &'a [AuthenticatedContextRecordV1],
    pub encoded_context: &'a [u8],
    pub maximum_context_bytes: u32,
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
}

/// Derive the verified count and bind the exact record set plus request identity
/// into the support digest consumed by the existing NDU/planner implementation.
pub fn plan_authenticated_observed_context(
    observed: AuthenticatedObservedContextV1<'_>,
) -> Result<ObservedContextPlanV1, NduPlanningError> {
    use NduPlanningError as E;

    if observed.records.len() > MAX_AUTHENTICATED_CONTEXT_RECORDS {
        return Err(E::Planner(PlannerError::LimitExceeded(
            "authenticated context records",
        )));
    }
    if observed.source_snapshot_digest.is_zero() {
        return Err(E::Planner(PlannerError::EmptyDigest(
            "authenticated source snapshot",
        )));
    }
    if observed.read_digest.is_zero() {
        return Err(E::Planner(PlannerError::EmptyDigest(
            "authenticated read receipt",
        )));
    }
    if observed.request_binding_digest.is_zero() {
        return Err(E::Planner(PlannerError::EmptyDigest(
            "context request binding",
        )));
    }

    let mut normalized = observed.records.to_vec();
    normalized.sort();
    let mut identities = BTreeSet::new();
    let mut record_bytes = b"hepta.control.authenticated-context-records.v1\0".to_vec();
    record_bytes.extend_from_slice(&(normalized.len() as u64).to_be_bytes());
    for record in &normalized {
        if record.revision == 0 || record.content_digest.is_zero() {
            return Err(E::Planner(PlannerError::PreparedPlanMismatch));
        }
        let identity = (record.record_id.clone(), record.revision);
        if !identities.insert(identity) {
            return Err(E::Planner(PlannerError::DuplicateCandidate(format!(
                "duplicate authenticated context record {}@{}",
                record.record_id, record.revision
            ))));
        }
        record_bytes.extend_from_slice(&(record.record_id.as_str().len() as u64).to_be_bytes());
        record_bytes.extend_from_slice(record.record_id.as_str().as_bytes());
        record_bytes.extend_from_slice(&record.revision.to_be_bytes());
        record_bytes.extend_from_slice(record.content_digest.as_array());
    }
    let record_set_digest = Digest32::of_bytes(&record_bytes);

    let mut bound_read = b"hepta.control.authenticated-context-read.v1\0".to_vec();
    bound_read.extend_from_slice(observed.read_digest.as_array());
    bound_read.extend_from_slice(observed.request_binding_digest.as_array());
    bound_read.extend_from_slice(record_set_digest.as_array());
    let bound_read_digest = Digest32::of_bytes(&bound_read);
    let verified_item_count =
        u32::try_from(normalized.len()).map_err(|_| E::Planner(PlannerError::Arithmetic))?;

    plan_observed_context(ObservedContextV1 {
        owner_id: observed.owner_id,
        body_generation: observed.body_generation,
        source_snapshot_digest: observed.source_snapshot_digest,
        read_digest: bound_read_digest,
        verified_item_count,
        encoded_context: observed.encoded_context,
        maximum_context_bytes: observed.maximum_context_bytes,
        observed_at_micros: observed.observed_at_micros,
        expires_at_micros: observed.expires_at_micros,
    })
}

#[cfg(test)]
mod authenticated_tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).unwrap()
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn duplicate_authenticated_record_identity_is_rejected() {
        let record = AuthenticatedContextRecordV1 {
            record_id: id("record"),
            revision: 1,
            content_digest: digest("content"),
        };
        let records = vec![record.clone(), record];
        let error = plan_authenticated_observed_context(AuthenticatedObservedContextV1 {
            owner_id: id("owner"),
            body_generation: Generation::new(1).unwrap(),
            source_snapshot_digest: digest("snapshot"),
            read_digest: digest("read"),
            request_binding_digest: digest("request"),
            records: &records,
            encoded_context: b"{}",
            maximum_context_bytes: 1024,
            observed_at_micros: 1,
            expires_at_micros: 2,
        })
        .unwrap_err();
        assert!(matches!(
            error,
            NduPlanningError::Planner(PlannerError::DuplicateCandidate(_))
        ));
    }
}
