use std::any::type_name;
use std::fs;
use std::path::PathBuf;

use codex_hepta_intelligence_eval::DurableProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::FinalHoldoutProviderV1;
use codex_hepta_intelligence_eval::LockedFileFinalHoldoutCasStoreV1;
use codex_hepta_intelligence_eval::LockedFileProductEvaluationAttemptJournalV1;
use codex_hepta_intelligence_eval::ProductQualificationEvidenceSinkV1;
use codex_hepta_intelligence_eval::RecordedProductEvaluationRunnerV1;

fn assert_durable_journal<T: DurableProductEvaluationAttemptJournalV1>() {}

#[test]
fn recorded_production_surface_is_public_and_composable() {
    assert_durable_journal::<LockedFileProductEvaluationAttemptJournalV1>();
    let runner = type_name::<
        RecordedProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    >();
    assert!(runner.contains("RecordedProductEvaluationRunnerV1"));

    let provider = type_name::<dyn FinalHoldoutProviderV1>();
    let sink = type_name::<dyn ProductQualificationEvidenceSinkV1>();
    assert!(provider.contains("FinalHoldoutProviderV1"));
    assert!(sink.contains("ProductQualificationEvidenceSinkV1"));
}

#[test]
fn raw_decision_and_runner_are_private_in_default_builds() {
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let source = fs::read_to_string(manifest.join("src/lib.rs"))
        .expect("read learning.eval public API surface");

    assert!(source.contains(
        "#[cfg(feature = \"trusted-inprocess-eval\")]\n\
         pub use product_runner::ProductEvaluationRunnerV1;"
    ));
    assert!(source.contains(
        "#[cfg(not(feature = \"trusted-inprocess-eval\"))]\n\
         pub(crate) use product_runner::ProductEvaluationRunnerV1;"
    ));
    assert!(source.contains(
        "pub(crate) use signed_evaluation::decide_with_signed_evidence_v2;"
    ));
    assert!(!source.lines().any(|line| {
        line.trim() == "pub use signed_evaluation::decide_with_signed_evidence_v2;"
    }));
}
