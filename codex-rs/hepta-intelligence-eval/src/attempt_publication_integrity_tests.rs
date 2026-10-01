//! Real reducer plus controlled publication observations; no writer may run.
use super::*;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::SignedEvaluationDecisionV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

struct ReadStore {
    execution: Digest32,
    record: Option<ProductQualificationPublicationRecordV1>,
    reads: usize,
}

impl ProductQualificationPublicationStoreV1 for ReadStore {
    fn load(
        &mut self,
        execution: Digest32,
    ) -> Result<
        Option<ProductQualificationPublicationRecordV1>,
        ProductQualificationPublicationStoreErrorV1,
    > {
        assert_eq!(execution, self.execution);
        self.reads += 1;
        Ok(self.record.clone())
    }

    fn compare_and_publish(
        &mut self,
        _: Option<Digest32>,
        _: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1>
    {
        panic!("reconciliation must not invoke the publication writer");
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn fixture(
    phase: ProductEvaluationAttemptPhaseV1,
) -> (
    InMemoryProductEvaluationAttemptJournalV1,
    StableId,
    ReadStore,
) {
    use ProductEvaluationAttemptPhaseV1 as Phase;
    let attempt = id("attempt:publication-observation");
    let plan = digest("plan");
    let holdout = digest("holdout");
    let execution = digest("execution");
    let decision = SignedEvaluationDecisionV1 {
        decision: IndependentEvaluationDecisionV1 {
            evaluation_id: id("evaluation"),
            candidate_id: id("candidate"),
            baseline_id: id("baseline"),
            disposition: IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            failed_metrics: Vec::new(),
            evidence_digest: digest("evidence"),
            authority: AuthorityPosture::DENY_ALL,
        },
        trust_digest: digest("trust"),
        authentication_digest: digest("authentication"),
    };
    let request =
        ProductQualificationPublicationRequestV1::new(execution, &decision).expect("request");
    let record = ProductQualificationPublicationRecordV1::new(request, digest("publication"))
        .expect("record");
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    for transition in [
        ProductEvaluationAttemptTransitionV1::intent(
            attempt.clone(),
            plan,
            digest("namespace"),
            digest("state"),
        ),
        ProductEvaluationAttemptTransitionV1::holdout_consumed(attempt.clone(), plan, holdout),
        ProductEvaluationAttemptTransitionV1::comparison_sealed(
            attempt.clone(),
            plan,
            holdout,
            execution,
        ),
    ] {
        journal.append(transition).expect("initial phases");
    }
    for step in [
        Phase::QualificationDecided,
        Phase::PublicationPending,
        Phase::Published,
    ] {
        journal
            .append(ProductEvaluationAttemptTransitionV1 {
                attempt_id: attempt.clone(),
                plan_digest: plan,
                phase: step,
                holdout_record_digest: holdout,
                terminal_digest: if step == Phase::Published {
                    record.publication_digest
                } else {
                    record.request.request_digest
                },
            })
            .expect("publication phase");
        if step == phase {
            break;
        }
    }
    (
        journal,
        attempt,
        ReadStore {
            execution,
            record: Some(record),
            reads: 0,
        },
    )
}

#[test]
fn published_reconciliation_reads_the_owner_without_appending() {
    let (mut journal, attempt, mut store) = fixture(ProductEvaluationAttemptPhaseV1::Published);
    let before = journal.history(&attempt).expect("history");
    let receipt = reconcile_product_attempt_publication_v1(&mut journal, &mut store, &attempt)
        .expect("read verified");
    assert_eq!(Some(&receipt), before.last());
    assert_eq!(store.reads, 1);
    assert_eq!(journal.history(&attempt).expect("history"), before);
}

#[test]
fn missing_publication_cannot_be_replaced_by_a_published_journal_label() {
    let (mut journal, attempt, mut store) = fixture(ProductEvaluationAttemptPhaseV1::Published);
    let before = journal.history(&attempt).expect("history");
    store.record = None;
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store, &attempt),
        Err(ProductAttemptRecoveryErrorV1::Unresolved)
    );
    assert_eq!(store.reads, 1);
    assert_eq!(journal.history(&attempt).expect("unchanged"), before);
}

#[test]
fn valid_but_substituted_publication_digest_is_rejected() {
    let (mut journal, attempt, mut store) = fixture(ProductEvaluationAttemptPhaseV1::Published);
    let before = journal.history(&attempt).expect("history");
    let old = store.record.take().expect("record");
    store.record = Some(
        ProductQualificationPublicationRecordV1::new(
            old.request,
            digest("replacement-publication"),
        )
        .expect("valid substituted record"),
    );
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store, &attempt),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch)
    );
    assert_eq!(journal.history(&attempt).expect("unchanged"), before);
}

#[test]
fn corrupt_publication_is_not_accepted_from_terminal_history() {
    let (mut journal, attempt, mut store) = fixture(ProductEvaluationAttemptPhaseV1::Published);
    let before = journal.history(&attempt).expect("history");
    store
        .record
        .as_mut()
        .expect("record")
        .request
        .authentication_digest = digest("substituted-authentication");
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store, &attempt),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch)
    );
    assert_eq!(journal.history(&attempt).expect("unchanged"), before);
}

#[test]
fn absent_pending_publication_stays_unresolved_without_retry() {
    let (mut journal, attempt, mut store) =
        fixture(ProductEvaluationAttemptPhaseV1::PublicationPending);
    let before = journal.history(&attempt).expect("history");
    store.record = None;
    assert_eq!(
        reconcile_product_attempt_publication_v1(&mut journal, &mut store, &attempt),
        Err(ProductAttemptRecoveryErrorV1::Unresolved)
    );
    assert_eq!(journal.history(&attempt).expect("unchanged"), before);
}
