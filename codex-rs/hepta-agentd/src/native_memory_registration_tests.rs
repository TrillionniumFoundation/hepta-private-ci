//! Controlled authority/source fixtures. These are boundary checks, not a
//! trained-model qualification or proof of deployed clock/issuer continuity.

use std::sync::atomic::Ordering;

use codex_hepta_types::Digest32;
use std::assert_eq;

use super::*;
use crate::native_memory_test_support::Fixture;
use crate::native_memory_test_support::fixture;

fn source(f: &Fixture) -> NativeMemorySourceConfigV1 {
    NativeMemorySourceConfigV1 {
        access: f.access.clone(),
        key: f.admission.query().key.clone(),
        claim: f.claim.clone(),
        model: f.config.clone(),
    }
}

#[tokio::test]
async fn registered_source_requires_exact_key_live_authority_and_retained_ancestry() {
    let mut f = fixture().await;
    std::fs::create_dir_all(&f.config.checkpoint).unwrap();
    let manifest = serde_json::to_vec(&serde_json::json!({
        "roots": [f.claim.production.source_content_sha256.as_str()],
        "scope": f.config.scope,
    }))
    .unwrap();
    std::fs::write(f.config.checkpoint.join("lineage.json"), &manifest).unwrap();
    f.config.pins.manifest_sha256 = Digest32::of_bytes(&manifest).to_string();
    let query = f.admission.query();
    let runtime = CancellationToken::new();
    let mut substituted = source(&f);
    substituted.key.relation = "different-repair".to_string();
    assert!(
        AgentdNativeMemoryCell::from_registered_source(
            Arc::clone(&f.writer),
            substituted,
            query,
            runtime.child_token(),
        )
        .await
        .is_err()
    );
    let cell = AgentdNativeMemoryCell::from_registered_source(
        Arc::clone(&f.writer),
        source(&f),
        query,
        runtime.child_token(),
    )
    .await
    .unwrap();
    assert_eq!(cell.backend_dispatch_attempts(), 0);
    runtime.cancel();
    assert!(cell.status("cancelled-runtime".to_string()).await.is_err());
    assert!(
        AgentdNativeMemoryCell::from_registered_source(
            Arc::clone(&f.writer),
            source(&f),
            query,
            runtime.child_token(),
        )
        .await
        .is_err()
    );
    f.verifier.0.store(/*val*/ true, Ordering::SeqCst);
    assert!(
        AgentdNativeMemoryCell::from_registered_source(
            Arc::clone(&f.writer),
            source(&f),
            query,
            CancellationToken::new(),
        )
        .await
        .is_err()
    );
    f.verifier.0.store(/*val*/ false, Ordering::SeqCst);
    let altered = serde_json::to_vec(&serde_json::json!({
        "roots": [Digest32::of_bytes(b"different source").to_string()],
        "scope": f.config.scope,
    }))
    .unwrap();
    std::fs::write(f.config.checkpoint.join("lineage.json"), &altered).unwrap();
    assert!(
        AgentdNativeMemoryCell::from_registered_source(
            Arc::clone(&f.writer),
            source(&f),
            query,
            CancellationToken::new(),
        )
        .await
        .is_err()
    );
    f.config.pins.manifest_sha256 = Digest32::of_bytes(&altered).to_string();
    assert!(
        AgentdNativeMemoryCell::from_registered_source(
            Arc::clone(&f.writer),
            source(&f),
            query,
            CancellationToken::new(),
        )
        .await
        .is_err()
    );
}
