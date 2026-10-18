//! Public compilation contract for named shared-feature identity parameters.
//! This integration test sits outside the library's private data_plane module.

use codex_hepta_neuron::FeatureSnapshotIdentityV1;
use codex_hepta_neuron::FeatureSnapshotLineageV1;
use codex_hepta_neuron::FeatureSnapshotScopeV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn external_consumer_can_build_valid_explicit_identity() -> Result<(), Box<dyn std::error::Error>> {
    let scope = FeatureSnapshotScopeV1 {
        scope: StableId::new("public.scope")?,
        workspace: StableId::new("public.workspace")?,
        purpose: StableId::new("public.purpose")?,
    };
    let lineage = FeatureSnapshotLineageV1 {
        source_frontier: digest("frontier"),
        model: digest("model"),
        adapter: digest("adapter"),
        tokenizer: digest("tokenizer"),
        normalizer: digest("normalizer"),
        calibration: digest("calibration"),
    };
    let implicit = FeatureSnapshotIdentityV1::new(scope.clone(), lineage)?;
    let explicit = FeatureSnapshotIdentityV1::new_with_question_options(
        scope,
        digest("question"),
        digest("options"),
        lineage,
    )?;
    assert!(!implicit.semantic_digest().is_zero());
    assert!(!explicit.semantic_digest().is_zero());
    assert_ne!(implicit.semantic_digest(), explicit.semantic_digest());
    Ok(())
}
