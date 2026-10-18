//! Public compilation contract for named shared-feature identity parameters.
//! This integration test sits outside the library's private data_plane module.

use codex_hepta_neuron::{
    FeatureSnapshotIdentityV1, FeatureSnapshotLineageV1, FeatureSnapshotScopeV1,
};
use codex_hepta_types::{Digest32, StableId};

fn stable(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture identifier")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn external_consumer_can_build_valid_explicit_identity() {
    let scope = FeatureSnapshotScopeV1 {
        scope: stable("public.scope"),
        workspace: stable("public.workspace"),
        purpose: stable("public.purpose"),
    };
    let lineage = FeatureSnapshotLineageV1 {
        source_frontier: digest("frontier"),
        model: digest("model"),
        adapter: digest("adapter"),
        tokenizer: digest("tokenizer"),
        normalizer: digest("normalizer"),
        calibration: digest("calibration"),
    };
    let implicit = FeatureSnapshotIdentityV1::new(scope.clone(), lineage)
        .expect("valid legacy-tagged public identity");
    let explicit = FeatureSnapshotIdentityV1::new_with_question_options(
        scope,
        digest("question"),
        digest("options"),
        lineage,
    )
    .expect("valid explicit public identity");
    assert!(!implicit.semantic_digest().is_zero());
    assert!(!explicit.semantic_digest().is_zero());
    assert_ne!(implicit.semantic_digest(), explicit.semantic_digest());
}
