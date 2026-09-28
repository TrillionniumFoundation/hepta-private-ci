use std::collections::BTreeSet;

use serde_json::Value;

const TRACEABILITY: &str =
    include_str!("../../../docs/modules/cognitive.types/TRACEABILITY.json");
const SOURCE_EXPORT: &str =
    include_str!("../../../.github/workflows/cognitive-types-source-export.yml");
const COGNITIVE_QUALIFICATION: &str =
    include_str!("../../../.github/workflows/cognitive-types-qualification.yml");
const HNMF_QUALIFICATION: &str =
    include_str!("../../../.github/workflows/hnmf-qualification.yml");
const COGNITIVE_READ: &str =
    include_str!("../../hepta-cognitive-read/src/authoritative.rs");
const COGNITIVE_STORE: &str = include_str!("../../hepta-cognitive-store/src/v2.rs");
const MEMORY_RETRIEVAL: &str =
    include_str!("../../hepta-memory-retrieval/src/generation_bound.rs");
const COMPACT_ENGINE: &str = include_str!("../../hepta-compact-engine/src/qualified.rs");
const INTELLIGENCE_CONTROL: &str =
    include_str!("../../hepta-intelligence/src/canonical.rs");
const AGENTD_PRODUCT_RUNNER: &str =
    include_str!("../../hepta-agentd/src/intelligence_product_runner.rs");

#[test]
fn traceability_manifest_has_closed_unique_invariant_inventory() {
    let document: Value = serde_json::from_str(TRACEABILITY).expect("traceability JSON");
    assert_eq!(
        document["schema"],
        "hepta.cognitive-types.traceability.v1"
    );
    assert_eq!(document["schemaVersion"], 1);
    assert_eq!(document["module"], "cognitive.types");
    assert_eq!(
        document["evidencePolicy"],
        "exact_head_and_two_parent_synthetic_merge"
    );

    let claim = document["claimBoundary"]
        .as_object()
        .expect("claim boundary object");
    assert_eq!(claim.get("sourceImplemented"), Some(&Value::Bool(true)));
    for key in [
        "productExecutionProved",
        "independentAcceptance",
        "activation",
        "release",
    ] {
        assert_eq!(claim.get(key), Some(&Value::Bool(false)), "claim {key}");
    }

    let expected = BTreeSet::from([
        "CTYPE-CONSUMER-01",
        "CTYPE-DIGEST-01",
        "CTYPE-EVIDENCE-01",
        "CTYPE-ID-01",
        "CTYPE-MUTATION-01",
        "CTYPE-PERF-01",
        "CTYPE-VALIDATE-01",
        "CTYPE-WIRE-01",
        "CTYPE-WRITE-01",
    ]);
    let rows = document["invariants"]
        .as_array()
        .expect("invariant array");
    let mut actual = BTreeSet::new();
    for row in rows {
        let id = row["id"].as_str().expect("invariant id");
        assert!(actual.insert(id), "duplicate invariant {id}");
        assert!(
            !row["title"].as_str().expect("invariant title").is_empty(),
            "empty title for {id}"
        );
        for key in ["source", "tests"] {
            let paths = row[key].as_array().expect("path array");
            assert!(!paths.is_empty(), "{id} has no {key}");
            assert!(
                paths.iter().all(|path| path
                    .as_str()
                    .is_some_and(|path| !path.is_empty() && !path.contains("working-copy"))),
                "{id} contains an invalid {key} path"
            );
        }
        assert!(
            row["requiredEvidence"]
                .as_str()
                .is_some_and(|value| value.starts_with("current_")),
            "{id} does not require current evidence"
        );
    }
    assert_eq!(actual, expected);
}

#[test]
fn all_registered_consumer_and_product_traceability_anchors_exist() {
    for (name, source, entrypoint) in [
        (
            "cognitive.read",
            COGNITIVE_READ,
            "adapt_authoritative_read_to_canonical_v1",
        ),
        (
            "cognitive.store",
            COGNITIVE_STORE,
            "bind_canonical_event_to_product_receipt_v1",
        ),
        (
            "memory.retrieval",
            MEMORY_RETRIEVAL,
            "adapt_generation_bound_recall_to_canonical_v1",
        ),
        (
            "compact.engine",
            COMPACT_ENGINE,
            "build_qualified_candidate_with_canonical_events",
        ),
        (
            "intelligence.control",
            INTELLIGENCE_CONTROL,
            "prepare_intelligence_run_with_canonical_recall",
        ),
        (
            "runtime.agentd product",
            AGENTD_PRODUCT_RUNNER,
            "prepare_with_canonical_recall",
        ),
    ] {
        assert!(
            source.contains(entrypoint),
            "{name} lost traceability entrypoint {entrypoint}"
        );
    }
}

#[test]
fn qualification_and_export_workflows_are_read_only() {
    for (name, workflow) in [
        ("source export", SOURCE_EXPORT),
        ("cognitive qualification", COGNITIVE_QUALIFICATION),
        ("HNMF qualification", HNMF_QUALIFICATION),
    ] {
        assert!(workflow.contains("contents: read"), "{name} lacks read permission");
        assert!(
            !workflow.contains("contents: write"),
            "{name} can write repository contents"
        );
        assert!(!workflow.contains("git push"), "{name} pushes source changes");
        assert!(
            !workflow.contains("persist-credentials: true"),
            "{name} persists write credentials"
        );
    }
}

#[test]
fn source_exports_are_bound_to_each_immutable_candidate() {
    for token in [
        "group: cognitive-types-source-export-${{ github.sha }}",
        "cancel-in-progress: false",
        "test \"$(git rev-parse HEAD)\" = \"$GITHUB_SHA\"",
        "git rev-parse HEAD^{tree}",
        "git archive --format=tar HEAD",
        "git bundle create \"$export_dir/source.bundle\" HEAD",
        "sha256sum source.tar source.bundle",
    ] {
        assert!(SOURCE_EXPORT.contains(token), "missing export token: {token}");
    }
}
