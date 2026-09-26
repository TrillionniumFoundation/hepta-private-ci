//! Idempotent publication adapter for product qualification evidence.
//!
//! Stores may acknowledge a commit, reject it, or lose the acknowledgement after
//! committing it. This adapter turns the accepted-but-unknown case into a
//! read-after-write reconciliation protocol keyed by the temporal execution
//! digest. A conflicting record is never overwritten.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationPublicationRequestV1 {
    pub execution_digest: Digest32,
    pub decision_evidence_digest: Digest32,
    pub trust_digest: Digest32,
    pub authentication_digest: Digest32,
    pub request_digest: Digest32,
}

impl ProductQualificationPublicationRequestV1 {
    fn new(
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Self, ProductEvidenceSinkErrorV1> {
        if execution_digest.is_zero()
            || decision.decision.evidence_digest.is_zero()
            || decision.trust_digest.is_zero()
            || decision.authentication_digest.is_zero()
            || decision.decision.authority.grants_any()
        {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        let mut request = Self {
            execution_digest,
            decision_evidence_digest: decision.decision.evidence_digest,
            trust_digest: decision.trust_digest,
            authentication_digest: decision.authentication_digest,
            request_digest: Digest32::ZERO,
        };
        request.request_digest = publication_request_digest(&request);
        Ok(request)
    }

    fn validate(&self) -> Result<(), ProductQualificationPublicationStoreErrorV1> {
        if self.execution_digest.is_zero()
            || self.decision_evidence_digest.is_zero()
            || self.trust_digest.is_zero()
            || self.authentication_digest.is_zero()
            || self.request_digest.is_zero()
            || self.request_digest != publication_request_digest(self)
        {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductQualificationPublicationRecordV1 {
    pub request: ProductQualificationPublicationRequestV1,
    pub publication_digest: Digest32,
    pub record_digest: Digest32,
}

impl ProductQualificationPublicationRecordV1 {
    pub fn new(
        request: ProductQualificationPublicationRequestV1,
        publication_digest: Digest32,
    ) -> Result<Self, ProductQualificationPublicationStoreErrorV1> {
        request.validate()?;
        if publication_digest.is_zero() {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        let mut record = Self {
            request,
            publication_digest,
            record_digest: Digest32::ZERO,
        };
        record.record_digest = publication_record_digest(&record);
        Ok(record)
    }

    pub fn validate(&self) -> Result<(), ProductQualificationPublicationStoreErrorV1> {
        self.request.validate()?;
        if self.publication_digest.is_zero()
            || self.record_digest.is_zero()
            || self.record_digest != publication_record_digest(self)
        {
            return Err(ProductQualificationPublicationStoreErrorV1::Rejected);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductQualificationPublicationStoreErrorV1 {
    Conflict,
    Rejected,
    Unavailable,
    Indeterminate,
}

impl fmt::Display for ProductQualificationPublicationStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductQualificationPublicationStoreErrorV1 {}

/// Durable store contract for exactly-once semantic publication.
///
/// `compare_and_publish` must be linearizable for one `execution_digest`. If it
/// returns `Indeterminate`, the record may already be committed and the caller
/// must use `load` before retrying. A committed key may never be overwritten with
/// a different request digest.
pub trait ProductQualificationPublicationStoreV1 {
    fn load(
        &mut self,
        execution_digest: Digest32,
    ) -> Result<Option<ProductQualificationPublicationRecordV1>, ProductQualificationPublicationStoreErrorV1>;

    fn compare_and_publish(
        &mut self,
        expected_record_digest: Option<Digest32>,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>;
}

pub struct ReconciledProductQualificationSinkV1<S> {
    store: S,
    pending: Option<ProductQualificationPublicationRequestV1>,
}

impl<S: ProductQualificationPublicationStoreV1> ReconciledProductQualificationSinkV1<S> {
    #[must_use]
    pub fn new(store: S) -> Self {
        Self {
            store,
            pending: None,
        }
    }

    #[must_use]
    pub fn has_pending_reconciliation(&self) -> bool {
        self.pending.is_some()
    }

    pub fn reconcile_pending(
        &mut self,
    ) -> Result<Option<Digest32>, ProductEvidenceSinkErrorV1> {
        let Some(request) = self.pending.clone() else {
            return Ok(None);
        };
        match self.store.load(request.execution_digest) {
            Ok(Some(record)) => {
                validate_matching_record(&request, &record)?;
                self.pending = None;
                Ok(Some(record.publication_digest))
            }
            Ok(None) => Ok(None),
            Err(error) => Err(map_store_error(error)),
        }
    }

    #[must_use]
    pub fn into_inner(self) -> S {
        self.store
    }

    fn load_matching(
        &mut self,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<Option<Digest32>, ProductEvidenceSinkErrorV1> {
        match self.store.load(request.execution_digest) {
            Ok(Some(record)) => {
                validate_matching_record(request, &record)?;
                Ok(Some(record.publication_digest))
            }
            Ok(None) => Ok(None),
            Err(error) => Err(map_store_error(error)),
        }
    }
}

impl<S: ProductQualificationPublicationStoreV1> ProductQualificationEvidenceSinkV1
    for ReconciledProductQualificationSinkV1<S>
{
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let request = ProductQualificationPublicationRequestV1::new(execution_digest, decision)?;
        if let Some(pending) = &self.pending {
            if pending != &request {
                return Err(ProductEvidenceSinkErrorV1::Indeterminate);
            }
            if let Some(publication) = self.reconcile_pending()? {
                return Ok(publication);
            }
        }
        if let Some(publication) = self.load_matching(&request)? {
            self.pending = None;
            return Ok(publication);
        }

        match self.store.compare_and_publish(None, &request) {
            Ok(record) => {
                validate_matching_record(&request, &record)?;
                self.pending = None;
                Ok(record.publication_digest)
            }
            Err(ProductQualificationPublicationStoreErrorV1::Indeterminate) => {
                self.pending = Some(request);
                self.reconcile_pending()?
                    .ok_or(ProductEvidenceSinkErrorV1::Indeterminate)
            }
            Err(error) => Err(map_store_error(error)),
        }
    }
}

fn validate_matching_record(
    request: &ProductQualificationPublicationRequestV1,
    record: &ProductQualificationPublicationRecordV1,
) -> Result<(), ProductEvidenceSinkErrorV1> {
    record
        .validate()
        .map_err(|_| ProductEvidenceSinkErrorV1::Rejected)?;
    if &record.request != request {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    Ok(())
}

fn publication_request_digest(request: &ProductQualificationPublicationRequestV1) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.publication-request.v1".to_vec();
    for digest in [
        request.execution_digest,
        request.decision_evidence_digest,
        request.trust_digest,
        request.authentication_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn publication_record_digest(record: &ProductQualificationPublicationRecordV1) -> Digest32 {
    let mut bytes = b"hepta.learning-eval.publication-record.v1".to_vec();
    bytes.extend_from_slice(record.request.request_digest.as_array());
    bytes.extend_from_slice(record.publication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn map_store_error(
    error: ProductQualificationPublicationStoreErrorV1,
) -> ProductEvidenceSinkErrorV1 {
    match error {
        ProductQualificationPublicationStoreErrorV1::Conflict
        | ProductQualificationPublicationStoreErrorV1::Rejected => {
            ProductEvidenceSinkErrorV1::Rejected
        }
        ProductQualificationPublicationStoreErrorV1::Unavailable => {
            ProductEvidenceSinkErrorV1::Unavailable
        }
        ProductQualificationPublicationStoreErrorV1::Indeterminate => {
            ProductEvidenceSinkErrorV1::Indeterminate
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::IndependentEvaluationDecisionV1;
    use crate::IndependentEvaluationDispositionV1;
    use codex_hepta_types::AuthorityPosture;
    use codex_hepta_types::StableId;

    #[derive(Default)]
    struct FaultStore {
        record: Option<ProductQualificationPublicationRecordV1>,
        accept_then_lose_ack: bool,
    }

    impl ProductQualificationPublicationStoreV1 for FaultStore {
        fn load(
            &mut self,
            execution_digest: Digest32,
        ) -> Result<Option<ProductQualificationPublicationRecordV1>, ProductQualificationPublicationStoreErrorV1>
        {
            Ok(self
                .record
                .clone()
                .filter(|record| record.request.execution_digest == execution_digest))
        }

        fn compare_and_publish(
            &mut self,
            expected_record_digest: Option<Digest32>,
            request: &ProductQualificationPublicationRequestV1,
        ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
        {
            let current = self.record.as_ref().map(|record| record.record_digest);
            if current != expected_record_digest {
                return Err(ProductQualificationPublicationStoreErrorV1::Conflict);
            }
            let record = ProductQualificationPublicationRecordV1::new(
                request.clone(),
                Digest32::of_bytes(b"durable-publication"),
            )?;
            self.record = Some(record.clone());
            if self.accept_then_lose_ack {
                self.accept_then_lose_ack = false;
                Err(ProductQualificationPublicationStoreErrorV1::Indeterminate)
            } else {
                Ok(record)
            }
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("valid test id")
    }

    fn decision() -> SignedEvaluationDecisionV1 {
        SignedEvaluationDecisionV1 {
            decision: IndependentEvaluationDecisionV1 {
                evaluation_id: id("evaluation:1"),
                candidate_id: id("candidate:1"),
                baseline_id: id("candidate:0"),
                disposition:
                    IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                failed_metrics: Vec::new(),
                evidence_digest: Digest32::of_bytes(b"decision"),
                authority: AuthorityPosture::DENY_ALL,
            },
            trust_digest: Digest32::of_bytes(b"trust"),
            authentication_digest: Digest32::of_bytes(b"authentication"),
        }
    }

    #[test]
    fn accepted_unknown_is_reconciled_without_duplicate_publish() {
        let store = FaultStore {
            accept_then_lose_ack: true,
            ..FaultStore::default()
        };
        let mut sink = ReconciledProductQualificationSinkV1::new(store);
        let execution = Digest32::of_bytes(b"execution");
        let first = sink.persist(execution, &decision()).expect("reconciled publish");
        assert!(!first.is_zero());
        assert!(!sink.has_pending_reconciliation());

        let second = sink.persist(execution, &decision()).expect("idempotent replay");
        assert_eq!(first, second);
        let store = sink.into_inner();
        assert!(store.record.is_some());
    }

    #[test]
    fn conflicting_semantics_are_never_overwritten() {
        let mut sink = ReconciledProductQualificationSinkV1::new(FaultStore::default());
        let execution = Digest32::of_bytes(b"execution");
        sink.persist(execution, &decision()).expect("first publish");

        let mut changed = decision();
        changed.authentication_digest = Digest32::of_bytes(b"different authentication");
        assert_eq!(
            sink.persist(execution, &changed),
            Err(ProductEvidenceSinkErrorV1::Rejected)
        );
    }
}
