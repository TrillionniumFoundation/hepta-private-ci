use codex_hepta_intelligence_eval::product::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::product::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::product::ProductQualificationReceiptV1;
use codex_hepta_intelligence_eval::product::RecordedProductEvaluationRunnerV1;

#[test]
fn canonical_product_facade_is_public_without_raw_runner() {
    let names = [
        std::any::type_name::<ProductQualificationReceiptV1>(),
        std::any::type_name::<RecordedProductEvaluationRunnerV1<FixtureStore>>(),
        std::any::type_name::<AnchoredProductEvaluationAttemptJournalV1<FixtureAnchor>>(),
        std::any::type_name::<&dyn DurableProductEvaluationAttemptJournalV1>(),
    ];
    assert!(
        names
            .iter()
            .all(|name| name.contains("codex_hepta_intelligence_eval"))
    );
}

// Type-name instantiation does not require trait implementations. The compile-fail
// API-surface fixture separately proves that the raw runner is not externally public.
struct FixtureStore;
struct FixtureAnchor;
