//! Idempotent and reconcilable durable qualification publication.
//!
//! `ProductQualificationEvidenceSinkV1` is the narrow runner-facing contract.
//! This module defines the stronger host contract required to survive an
//! accepted-but-response-lost write without duplicating or equivocating a
//! qualification record.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ProductEvidenceSinkErrorV1;
use crate::ProductQualificationEvidenceSinkV1;
use crate::SignedEvaluationDecisionV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct QualificationPublicationRecordV1 {
    pub execution_digest: Digest32,
    pub decision_digest: Digest32,
    pub publication_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum QualificationPublicationLookupV1 {
    Missing,
    Committed(QualificationPublicationRecordV1),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum IdempotentQualificationEvidenceSinkErrorV1 {
    Rejected,
    Unavailable,
    /// The write may have committed. Callers must reconcile by lookup before
    /// retrying or abandoning the operation.
    Indeterminate,
    /// The idempotency key already names different semantics.
    Conflict,
    Corrupt,
}

impl fmt::Display for IdempotentQualificationEvidenceSinkErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for IdempotentQualificationEvidenceSinkErrorV1 {}

/// Host-owned durable publication store.
///
/// `execution_digest` is the idempotency key. A repeated call with the same key
/// and same `decision_digest` must return the existing committed record. Reusing
/// the key for different semantics must return `Conflict`. An accepted-or-unknown
/// write must return `Indeterminate`, never `Rejected`.
pub trait IdempotentQualificationEvidenceSinkV1 {
    fn lookup(
        &mut self,
        execution_digest: Digest32,
    ) -> Result<QualificationPublicationLookupV1, IdempotentQualificationEvidenceSinkErrorV1>;

    fn persist_once(
        &mut self,
        execution_digest: Digest32,
        decision_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<QualificationPublicationRecordV1, IdempotentQualificationEvidenceSinkErrorV1>;
}

impl<T: IdempotentQualificationEvidenceSinkV1 + ?Sized>
    IdempotentQualificationEvidenceSinkV1 for &mut T
{
    fn lookup(
        &mut self,
        execution_digest: Digest32,
    ) -> Result<QualificationPublicationLookupV1, IdempotentQualificationEvidenceSinkErrorV1> {
        (**self).lookup(execution_digest)
    }

    fn persist_once(
        &mut self,
        execution_digest: Digest32,
        decision_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<QualificationPublicationRecordV1, IdempotentQualificationEvidenceSinkErrorV1> {
        (**self).persist_once(execution_digest, decision_digest, decision)
    }
}

/// Adapter that implements the product runner's narrow sink surface while
/// enforcing idempotency and accepted-or-unknown reconciliation.
pub struct ReconcilingQualificationEvidenceSinkV1<S> {
    inner: S,
}

impl<S> ReconcilingQualificationEvidenceSinkV1<S> {
    #[must_use]
    pub const fn new(inner: S) -> Self {
        Self { inner }
    }

    #[must_use]
    pub fn inner(&self) -> &S {
        &self.inner
    }

    #[must_use]
    pub fn inner_mut(&mut self) -> &mut S {
        &mut self.inner
    }

    #[must_use]
    pub fn into_inner(self) -> S {
        self.inner
    }
}

impl<S: IdempotentQualificationEvidenceSinkV1> ProductQualificationEvidenceSinkV1
    for ReconcilingQualificationEvidenceSinkV1<S>
{
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        if execution_digest.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }
        let decision_digest = qualification_decision_digest_v1(decision);
        if decision_digest.is_zero() {
            return Err(ProductEvidenceSinkErrorV1::Rejected);
        }

        match self.inner.lookup(execution_digest) {
            Ok(QualificationPublicationLookupV1::Committed(record)) => {
                return validate_record(record, execution_digest, decision_digest)
            }
            Ok(QualificationPublicationLookupV1::Missing) => {}
            Err(error) => return Err(map_lookup_error(error)),
        }

        match self
            .inner
            .persist_once(execution_digest, decision_digest, decision)
        {
            Ok(record) => validate_record(record, execution_digest, decision_digest),
            Err(IdempotentQualificationEvidenceSinkErrorV1::Indeterminate) => {
                match self.inner.lookup(execution_digest) {
                    Ok(QualificationPublicationLookupV1::Committed(record)) => {
                        validate_record(record, execution_digest, decision_digest)
                    }
                    Ok(QualificationPublicationLookupV1::Missing) | Err(_) => {
                        Err(ProductEvidenceSinkErrorV1::Indeterminate)
                    }
                }
            }
            Err(error) => Err(map_persist_error(error)),
        }
    }
}

#[must_use]
pub fn qualification_decision_digest_v1(decision: &SignedEvaluationDecisionV1) -> Digest32 {
    let mut bytes = b"hepta.intelligence-eval.qualification-publication-decision.v1\0".to_vec();
    push_id(&mut bytes, &decision.decision.evaluation_id);
    push_id(&mut bytes, &decision.decision.candidate_id);
    push_id(&mut bytes, &decision.decision.baseline_id);
    bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
    bytes.extend_from_slice(decision.trust_digest.as_array());
    bytes.extend_from_slice(decision.authentication_digest.as_array());
    bytes.push(match decision.decision.disposition {
        crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => 0,
        crate::IndependentEvaluationDispositionV1::Ineligible => 1,
        crate::IndependentEvaluationDispositionV1::InsufficientEvidence => 2,
    });
    bytes.extend_from_slice(&(decision.decision.failed_metrics.len() as u64).to_be_bytes());
    for metric_id in &decision.decision.failed_metrics {
        push_id(&mut bytes, metric_id);
    }
    bytes.push(u8::from(decision.decision.authority.grants_any()));
    Digest32::of_bytes(&bytes)
}

fn validate_record(
    record: QualificationPublicationRecordV1,
    execution_digest: Digest32,
    decision_digest: Digest32,
) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
    if record.execution_digest != execution_digest
        || record.decision_digest != decision_digest
        || record.publication_digest.is_zero()
    {
        return Err(ProductEvidenceSinkErrorV1::Rejected);
    }
    Ok(record.publication_digest)
}

const fn map_lookup_error(
    error: IdempotentQualificationEvidenceSinkErrorV1,
) -> ProductEvidenceSinkErrorV1 {
    match error {
        IdempotentQualificationEvidenceSinkErrorV1::Unavailable => {
            ProductEvidenceSinkErrorV1::Unavailable
        }
        IdempotentQualificationEvidenceSinkErrorV1::Indeterminate => {
            ProductEvidenceSinkErrorV1::Indeterminate
        }
        IdempotentQualificationEvidenceSinkErrorV1::Rejected
        | IdempotentQualificationEvidenceSinkErrorV1::Conflict
        | IdempotentQualificationEvidenceSinkErrorV1::Corrupt => {
            ProductEvidenceSinkErrorV1::Rejected
        }
    }
}

const fn map_persist_error(
    error: IdempotentQualificationEvidenceSinkErrorV1,
) -> ProductEvidenceSinkErrorV1 {
    map_lookup_error(error)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    bytes.extend_from_slice(&(value.as_str().len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_str().as_bytes());
}

#[cfg(test)]
mod tests {
    use codex_hepta_types::AuthorityPosture;

    use super::*;
    use crate::IndependentEvaluationDecisionV1;
    use crate::IndependentEvaluationDispositionV1;

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum Mode {
        Normal,
        CommitThenIndeterminate,
        IndeterminateWithoutCommit,
    }

    struct FakeSink {
        mode: Mode,
        record: Option<QualificationPublicationRecordV1>,
        persist_calls: usize,
    }

    impl FakeSink {
        fn new(mode: Mode) -> Self {
            Self {
                mode,
                record: None,
                persist_calls: 0,
            }
        }
    }

    impl IdempotentQualificationEvidenceSinkV1 for FakeSink {
        fn lookup(
            &mut self,
            _execution_digest: Digest32,
        ) -> Result<QualificationPublicationLookupV1, IdempotentQualificationEvidenceSinkErrorV1>
        {
            Ok(self.record.map_or(
                QualificationPublicationLookupV1::Missing,
                QualificationPublicationLookupV1::Committed,
            ))
        }

        fn persist_once(
            &mut self,
            execution_digest: Digest32,
            decision_digest: Digest32,
            _decision: &SignedEvaluationDecisionV1,
        ) -> Result<QualificationPublicationRecordV1, IdempotentQualificationEvidenceSinkErrorV1>
        {
            self.persist_calls += 1;
            let record = QualificationPublicationRecordV1 {
                execution_digest,
                decision_digest,
                publication_digest: digest("publication"),
            };
            match self.mode {
                Mode::Normal => {
                    self.record = Some(record);
                    Ok(record)
                }
                Mode::CommitThenIndeterminate => {
                    self.record = Some(record);
                    Err(IdempotentQualificationEvidenceSinkErrorV1::Indeterminate)
                }
                Mode::IndeterminateWithoutCommit => {
                    Err(IdempotentQualificationEvidenceSinkErrorV1::Indeterminate)
                }
            }
        }
    }

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).expect("test id")
    }

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    fn decision() -> SignedEvaluationDecisionV1 {
        SignedEvaluationDecisionV1 {
            decision: IndependentEvaluationDecisionV1 {
                evaluation_id: id("evaluation"),
                candidate_id: id("candidate"),
                baseline_id: id("baseline"),
                disposition:
                    IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
                failed_metrics: Vec::new(),
                evidence_digest: digest("evidence"),
                authority: AuthorityPosture::DENY_ALL,
            },
            trust_digest: digest("trust"),
            authentication_digest: digest("authentication"),
        }
    }

    #[test]
    fn accepted_but_response_lost_is_reconciled_by_lookup() {
        let execution = digest("execution");
        let mut sink = ReconcilingQualificationEvidenceSinkV1::new(FakeSink::new(
            Mode::CommitThenIndeterminate,
        ));
        let publication = sink
            .persist(execution, &decision())
            .expect("reconciled publication");
        assert_eq!(publication, digest("publication"));
        assert_eq!(sink.inner().persist_calls, 1);
    }

    #[test]
    fn exact_retry_returns_existing_commit_without_second_write() {
        let execution = digest("execution");
        let decision = decision();
        let decision_digest = qualification_decision_digest_v1(&decision);
        let mut fake = FakeSink::new(Mode::Normal);
        fake.record = Some(QualificationPublicationRecordV1 {
            execution_digest: execution,
            decision_digest,
            publication_digest: digest("publication"),
        });
        let mut sink = ReconcilingQualificationEvidenceSinkV1::new(fake);
        assert_eq!(
            sink.persist(execution, &decision),
            Ok(digest("publication"))
        );
        assert_eq!(sink.inner().persist_calls, 0);
    }

    #[test]
    fn unknown_write_without_committed_record_remains_indeterminate() {
        let mut sink = ReconcilingQualificationEvidenceSinkV1::new(FakeSink::new(
            Mode::IndeterminateWithoutCommit,
        ));
        assert_eq!(
            sink.persist(digest("execution"), &decision()),
            Err(ProductEvidenceSinkErrorV1::Indeterminate)
        );
    }

    #[test]
    fn idempotency_key_reuse_with_different_decision_is_rejected() {
        let execution = digest("execution");
        let mut fake = FakeSink::new(Mode::Normal);
        fake.record = Some(QualificationPublicationRecordV1 {
            execution_digest: execution,
            decision_digest: digest("other-decision"),
            publication_digest: digest("publication"),
        });
        let mut sink = ReconcilingQualificationEvidenceSinkV1::new(fake);
        assert_eq!(
            sink.persist(execution, &decision()),
            Err(ProductEvidenceSinkErrorV1::Rejected)
        );
    }
}
