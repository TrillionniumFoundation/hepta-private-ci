use codex_hepta_intelligence_eval::AnchoredProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FencedFinalHoldoutOwnerV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorStoreV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptAnchorV1;
use codex_hepta_intelligence_eval::ProductEvaluationAttemptJournalErrorV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;
use codex_hepta_intelligence_eval::RegisteredPairedEvaluationRunnerV1;
use codex_hepta_types::Digest32;

struct CompileAnchor;

impl ProductEvaluationAttemptAnchorStoreV1 for CompileAnchor {
    fn load(
        &mut self,
        _binding: Digest32,
    ) -> Result<Option<ProductEvaluationAttemptAnchorV1>, ProductEvaluationAttemptJournalErrorV1>
    {
        Ok(None)
    }

    fn compare_and_swap(
        &mut self,
        _binding: Digest32,
        _expected: Option<ProductEvaluationAttemptAnchorV1>,
        _next: ProductEvaluationAttemptAnchorV1,
    ) -> Result<(), ProductEvaluationAttemptJournalErrorV1> {
        Ok(())
    }
}

fn assert_durable_journal<T: DurableProductEvaluationAttemptJournalV1>() {}

#[test]
fn recorded_production_surface_is_public_and_composable() {
    assert_durable_journal::<AnchoredProductEvaluationAttemptJournalV1<CompileAnchor>>();
    let _recorded_constructor: fn(
        FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1>,
    ) -> RecordedProductEvaluationRunnerV1<
        LockedFileFinalHoldoutCasStoreV1,
    > = RecordedProductEvaluationRunnerV1::new;
    let _provider_type: Option<&dyn FinalHoldoutProviderV1> = None;
    let _sink_type: Option<&dyn ProductQualificationEvidenceSinkV1> = None;

    let _paired_constructor: fn(
        FencedFinalHoldoutOwnerV1<LockedFileFinalHoldoutCasStoreV1>,
    ) -> RegisteredPairedEvaluationRunnerV1<
        LockedFileFinalHoldoutCasStoreV1,
    > = RegisteredPairedEvaluationRunnerV1::new;
}
