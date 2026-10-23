use super::*;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::FinalHoldoutCasRecordV1;
use crate::FinalHoldoutCasStoreError;
use crate::IndependentEvaluationDecisionV1;
use crate::IndependentEvaluationDispositionV1;
use crate::ProductQualificationPublicationRecordV1;
use crate::ProductQualificationPublicationRequestV1;
use crate::ProductQualificationPublicationStoreErrorV1;
use crate::SignedEvaluationDecisionV1;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
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

fn decided(
    journal: &mut InMemoryProductEvaluationAttemptJournalV1,
    attempt: &str,
) -> ProductQualificationPublicationRequestV1 {
    let plan = digest(attempt);
    let request = ProductQualificationPublicationRequestV1::new(digest("execution"), &decision())
        .expect("canonical request");
    for transition in [
        ProductEvaluationAttemptTransitionV1::holdout_consumed(id(attempt), plan, digest("holdout")),
        ProductEvaluationAttemptTransitionV1::comparison_sealed(
            id(attempt), plan, digest("holdout"), digest("execution"),
        ),
        ProductEvaluationAttemptTransitionV1 {
            attempt_id: id(attempt),
            plan_digest: plan,
            phase: ProductEvaluationAttemptPhaseV1::QualificationDecided,
            holdout_record_digest: digest("holdout"),
            terminal_digest: request.request_digest,
        },
    ] {
        journal.append(transition).expect("fixture transition");
    }
    request
}

#[derive(Default)]
struct ReadOnlyPublication {
    record: Option<ProductQualificationPublicationRecordV1>,
    loads: usize,
}

impl ProductQualificationPublicationStoreV1 for ReadOnlyPublication {
    fn load(
        &mut self,
        _execution: Digest32,
    ) -> Result<Option<ProductQualificationPublicationRecordV1>, ProductQualificationPublicationStoreErrorV1> {
        self.loads += 1;
        Ok(self.record.clone())
    }

    fn compare_and_publish(
        &mut self,
        _expected: Option<Digest32>,
        _request: &ProductQualificationPublicationRequestV1,
    ) -> Result<ProductQualificationPublicationRecordV1, ProductQualificationPublicationStoreErrorV1> {
        panic!("read reconciliation must never publish")
    }
}

#[derive(Default)]
struct EmptyHoldout {
    loads: usize,
}

impl FinalHoldoutCasStoreV1 for EmptyHoldout {
    fn load(
        &mut self,
        _binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        self.loads += 1;
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _binding: Digest32,
        _expected: Option<Digest32>,
        _next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        panic!("reconciliation must never consume holdout")
    }
}

#[test]
fn decided_committed_publication_is_reconciled_without_a_write() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let request = decided(&mut journal, "attempt");
    let mut store = ReadOnlyPublication {
        record: Some(ProductQualificationPublicationRecordV1::new(request, digest("publication"))
            .expect("publication")),
        loads: 0,
    };
    let settled = reconcile_product_attempt_publication_v1(&mut journal, &mut store, &id("attempt"))
        .expect("recover decided boundary");
    assert_eq!(settled.transition.phase, ProductEvaluationAttemptPhaseV1::Published);
    assert!(!settled.authority.grants_any());
    let phases: Vec<_> = journal.history(&id("attempt")).expect("history").iter()
        .map(|receipt| receipt.transition.phase).collect();
    assert_eq!(phases, vec![
        ProductEvaluationAttemptPhaseV1::HoldoutConsumed,
        ProductEvaluationAttemptPhaseV1::ComparisonSealed,
        ProductEvaluationAttemptPhaseV1::QualificationDecided,
        ProductEvaluationAttemptPhaseV1::PublicationPending,
        ProductEvaluationAttemptPhaseV1::Published,
    ]);
    let second = reconcile_product_attempt_publication_v1(&mut journal, &mut store, &id("attempt"))
        .expect("idempotent settled recovery");
    assert_eq!(second, settled);
    // Even a locally Published attempt must re-read the external owner. The
    // terminal journal state is not a substitute for durable publication proof.
    assert_eq!(store.loads, 2);
}

#[test]
fn missing_decided_publication_preserves_the_prewrite_phase() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    decided(&mut journal, "attempt");
    let mut store = ReadOnlyPublication::default();
    assert_eq!(reconcile_product_attempt_publication_v1(&mut journal, &mut store, &id("attempt")),
        Err(ProductAttemptRecoveryErrorV1::Unresolved));
    assert_eq!(journal.latest(&id("attempt")).expect("latest").expect("exists").transition.phase,
        ProductEvaluationAttemptPhaseV1::QualificationDecided);
}

struct ForgedHistory {
    history: Vec<ProductEvaluationAttemptReceiptV1>,
    latest: Option<ProductEvaluationAttemptReceiptV1>,
}

impl ProductEvaluationAttemptJournalV1 for ForgedHistory {
    fn append(&mut self, _transition: ProductEvaluationAttemptTransitionV1)
        -> Result<ProductEvaluationAttemptReceiptV1, ProductEvaluationAttemptJournalErrorV1> {
        panic!("invalid history must fail before journal mutation")
    }

    fn latest(&mut self, _attempt: &StableId)
        -> Result<Option<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
        Ok(self.latest.clone())
    }

    fn history(&mut self, _attempt: &StableId)
        -> Result<Vec<ProductEvaluationAttemptReceiptV1>, ProductEvaluationAttemptJournalErrorV1> {
        Ok(self.history.clone())
    }
}

#[test]
fn individually_valid_frames_cannot_be_spliced_across_attempts() {
    let mut a = InMemoryProductEvaluationAttemptJournalV1::default();
    let mut b = InMemoryProductEvaluationAttemptJournalV1::default();
    decided(&mut a, "attempt-a");
    decided(&mut b, "attempt-b");
    let mut history = a.history(&id("attempt-a")).expect("history a");
    history[1] = b.history(&id("attempt-b")).expect("history b")[1].clone();
    let latest = history.last().cloned();
    let mut forged = ForgedHistory { history, latest };
    let mut store = ReadOnlyPublication::default();
    assert_eq!(reconcile_product_attempt_publication_v1(&mut forged, &mut store, &id("attempt-a")),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch));
    assert_eq!(store.loads, 0);
}

#[test]
fn stale_latest_pointer_is_not_an_authoritative_history() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    decided(&mut journal, "attempt");
    let history = journal.history(&id("attempt")).expect("history");
    let latest = Some(history[0].clone());
    let mut forged = ForgedHistory { history, latest };
    assert_eq!(validated_history(&mut forged, &id("attempt")),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch));
}

#[test]
fn a_complete_tail_without_its_predecessor_is_rejected() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    decided(&mut journal, "attempt");
    let mut history = journal.history(&id("attempt")).expect("history");
    history.remove(0);
    let latest = history.last().cloned();
    let mut forged = ForgedHistory { history, latest };
    assert_eq!(validated_history(&mut forged, &id("attempt")),
        Err(ProductAttemptRecoveryErrorV1::EvidenceMismatch));
}

#[test]
fn pending_cursor_advances_past_unresolved_attempts() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    journal.append(ProductEvaluationAttemptTransitionV1::intent(
        id("a-blocked"), digest("blocked-plan"), digest("namespace"), digest("owner-state"),
    )).expect("intent");
    let request = decided(&mut journal, "b-committed");
    let mut publication = ReadOnlyPublication {
        record: Some(ProductQualificationPublicationRecordV1::new(request, digest("publication"))
            .expect("record")),
        loads: 0,
    };
    let mut holdout = EmptyHoldout::default();
    let (first, cursor) = RecordedProductEvaluationRunnerV1::<EmptyHoldout>::reconcile_pending_page(
        &mut journal, &mut holdout, &mut publication, None, 1,
    ).expect("first page");
    assert_eq!(first[0].1, Err(ProductAttemptRecoveryErrorV1::Unresolved));
    assert_eq!(cursor, Some(id("a-blocked")));
    let (second, cursor) = RecordedProductEvaluationRunnerV1::<EmptyHoldout>::reconcile_pending_page(
        &mut journal, &mut holdout, &mut publication, cursor.as_ref(), 1,
    ).expect("second page");
    assert_eq!(second[0].0, id("b-committed"));
    assert_eq!(second[0].1.as_ref().expect("settled").transition.phase,
        ProductEvaluationAttemptPhaseV1::Published);
    let (last, cursor) = RecordedProductEvaluationRunnerV1::<EmptyHoldout>::reconcile_pending_page(
        &mut journal, &mut holdout, &mut publication, cursor.as_ref(), 1,
    ).expect("end of sweep");
    assert!(last.is_empty());
    assert!(cursor.is_none());
    assert_eq!(holdout.loads, 1);
    assert_eq!(publication.loads, 1);
}

#[test]
fn invalid_page_limits_fail_before_owner_reads() {
    let mut journal = InMemoryProductEvaluationAttemptJournalV1::default();
    let mut holdout = EmptyHoldout::default();
    let mut publication = ReadOnlyPublication::default();
    for limit in [0, 1025] {
        assert!(matches!(RecordedProductEvaluationRunnerV1::<EmptyHoldout>::reconcile_pending_page(
            &mut journal, &mut holdout, &mut publication, None, limit,
        ), Err(ProductAttemptRecoveryErrorV1::Journal(ProductEvaluationAttemptJournalErrorV1::Capacity))));
    }
    assert_eq!(holdout.loads, 0);
    assert_eq!(publication.loads, 0);
}
