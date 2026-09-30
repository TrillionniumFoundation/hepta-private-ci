use super::*;
use std::cell::RefCell;
use std::rc::Rc;

use crate::InMemoryProductEvaluationAttemptJournalV1;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use crate::ProductAttemptRecoveryErrorV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::ProductQualificationPublicationStoreV1;
use crate::ReconciledProductQualificationSinkV1;
use crate::reconcile_product_attempt_publication_v1;
use codex_hepta_types::AuthorityPosture;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid test id")
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
            disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            failed_metrics: Vec::new(),
            evidence_digest: digest("decision"),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("trust"),
        authentication_digest: digest("authentication"),
    }
}

#[derive(Default)]
struct StoreState {
    record: Option<ProductQualificationPublicationRecordV1>,
    writes: usize,
    visible: bool,
    commit: bool,
}
#[derive(Clone, Default)]
struct UnknownStore(Rc<RefCell<StoreState>>);
impl ProductQualificationPublicationStoreV1 for UnknownStore {
    fn load(
        &mut self,
        _execution: Digest32,
    ) -> Result<
        Option<ProductQualificationPublicationRecordV1>,
        ProductQualificationPublicationStoreErrorV1,
    > {
        let state = self.0.borrow();
        Ok(if state.visible {
            state.record.clone()
        } else {
            None
        })
    }
    fn compare_and_publish(
        &mut self,
        _expected: Option<Digest32>,
        request: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
    {
        let mut state = self.0.borrow_mut();
        state.writes += 1;
        if state.commit {
            state.record = Some(ProductQualificationPublicationRecordV1::new(
                request.clone(),
                digest("publication"),
            )?);
        }
        Err(ProductQualificationPublicationStoreErrorV1::Indeterminate)
    }
}

fn journal() -> InMemoryProductEvaluationAttemptJournalV1 {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    journal
        .append(ProductEvaluationAttemptTransitionV1::holdout_consumed(
            id("attempt"),
            digest("plan"),
            digest("holdout"),
        ))
        .expect("consume");
    journal
        .append(ProductEvaluationAttemptTransitionV1::comparison_sealed(
            id("attempt"),
            digest("plan"),
            digest("holdout"),
            digest("execution"),
        ))
        .expect("seal");
    journal
}

#[test]
fn absent_record_after_unknown_never_triggers_a_second_write() {
    let store = UnknownStore::default();
    let mut sink = ReconciledProductQualificationSinkV1::new(store.clone());
    for _ in 0..3 {
        assert_eq!(
            sink.persist(digest("execution"), &decision()),
            Err(ProductEvidenceSinkErrorV1::Indeterminate)
        );
    }
    assert_eq!(store.0.borrow().writes, 1);
    assert!(sink.has_pending_reconciliation());
}

#[test]
fn restarted_reconciliation_finds_pending_attempt_without_memory_state() {
    let store = UnknownStore::default();
    store.0.borrow_mut().commit = true;
    let mut journal = journal();
    {
        let mut sink = ReconciledProductQualificationSinkV1::new(store.clone());
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: id("attempt"),
            plan_digest: digest("plan"),
            holdout_record_digest: digest("holdout"),
            journal: &mut journal,
            inner: &mut sink,
            journal_error: None,
        };
        assert_eq!(
            recorded.persist(digest("execution"), &decision()),
            Err(ProductEvidenceSinkErrorV1::Indeterminate)
        );
    }
    assert_eq!(
        journal
            .pending(/*after*/ None, /*limit*/ 1)
            .expect("discover")[0]
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::PublicationPending
    );
    store.0.borrow_mut().visible = true;
    let result =
        reconcile_product_attempt_publication_v1(&mut journal, &mut store.clone(), &id("attempt"))
            .expect("read committed result");
    assert_eq!(
        result.transition.phase,
        ProductEvaluationAttemptPhaseV1::Published
    );
    assert_eq!(result.transition.terminal_digest, digest("publication"));
    assert_eq!(store.0.borrow().writes, 1);
}

#[test]
fn changed_request_or_missing_publication_does_not_settle_pending() {
    let store = UnknownStore::default();
    let mut journal = journal();
    {
        let mut sink = ReconciledProductQualificationSinkV1::new(store.clone());
        let mut recorded = RecordedPublicationSinkV1 {
            attempt_id: id("attempt"),
            plan_digest: digest("plan"),
            holdout_record_digest: digest("holdout"),
            journal: &mut journal,
            inner: &mut sink,
            journal_error: None,
        };
        assert_eq!(
            recorded.persist(digest("execution"), &decision()),
            Err(ProductEvidenceSinkErrorV1::Indeterminate)
        );
    }
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store.clone(), &id("attempt")),
        Err(ProductAttemptRecoveryErrorV1::Unresolved)
    );
    let mut changed = decision();
    changed.authentication_digest = digest("changed-signer");
    let request = ProductQualificationPublicationRequestV1::new(digest("execution"), &changed)
        .expect("request");
    store.0.borrow_mut().record = Some(
        ProductQualificationPublicationRecordV1::new(request, digest("publication"))
            .expect("record"),
    );
    store.0.borrow_mut().visible = true;
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store.clone(), &id("attempt")),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch)
    );
    assert_eq!(
        journal
            .latest(&id("attempt"))
            .expect("latest")
            .expect("exists")
            .transition
            .phase,
        ProductEvaluationAttemptPhaseV1::PublicationPending
    );
    assert_eq!(store.0.borrow().writes, 1);
}
