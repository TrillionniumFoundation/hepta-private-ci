use super::*;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;
use std::sync::atomic::Ordering;

#[path = "intelligence_canonical_runtime_test_support.rs"]
mod support;
use support::*;

async fn assert_no_admission(fixture: &RuntimeFixture) {
    assert!(run_state(fixture).await.is_none());
    assert_eq!(
        fixture.state.active_run_count().expect("active capacity"),
        0
    );
    assert_eq!(
        fixture
            .state
            .unresolved_run_count()
            .expect("unresolved runs"),
        0
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn running_canonical_admission_preserves_the_recovered_run_start() {
    let fixture = runtime_fixture(/*body_generation*/ 1, /*drain_on_build*/ false).await;
    let outcome = fixture
        .state
        .start_canonical_intelligence(&fixture.record)
        .await
        .expect("canonical owner admission");
    let Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    }) = outcome
    else {
        panic!("Ready")
    };
    let original = &fixture.record;
    let expected = crate::AgentRunSnapshot {
        run_id: original.snapshot.run_id.to_string(),
        request_digest: original.admission.admitted_source_digest.to_string(),
        objective_digest: original.snapshot.objective_digest.to_string(),
        body_digest: original.runtime_body_digest.to_string(),
        artifact_set_digest: original.snapshot.artifact_set_digest.to_string(),
        authority_epoch: original.snapshot.authority_epoch,
        generation: original.snapshot.generation,
        fence_digest: original.snapshot.fence_digest.to_string(),
        deadline_ms: (original.admission.deadline_unix_micros + 999) / 1_000,
    };
    assert_eq!(prepared.run_snapshot(), expected);
    assert_eq!(prepared.snapshot.body_generation().get(), 1);
    assert_eq!(run_receipt.generation, 2);
    assert_eq!(run_receipt.phase, crate::RunPhase::ContextAttached);
    assert_ne!(
        expected.request_digest,
        prepared.envelope.trace_digest.to_string()
    );
    assert_ne!(
        expected.artifact_set_digest,
        prepared.envelope.snapshot_digest.to_string()
    );
    assert_eq!(
        run_state(&fixture).await.expect("admitted run").snapshot,
        expected
    );
    assert_eq!(
        fixture
            .journal
            .get(&original.snapshot.run_id)
            .expect("read"),
        Some(original)
    );
    let mut mixed = prepared.clone();
    mixed.context_attachment.artifact_set_digest = digest("replacement-artifacts").to_string();
    assert!(mixed.require_original_run_start(original).is_err());
    let mut mixed = prepared;
    mixed.run_snapshot.generation = 3;
    assert!(mixed.require_original_run_start(original).is_err());
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_recovery_rejects_old_generation_fence_and_signature_before_provider() {
    let fixture = runtime_fixture(/*body_generation*/ 1, /*drain_on_build*/ false).await;
    for field in 0..3 {
        let mut changed = fixture.record.clone();
        match field {
            0 => {
                changed.snapshot.generation = 1;
                changed.snapshot.fence_digest =
                    crate::state::objective_run_fence(fixture.state.identity(), 1)
                        .parse()
                        .expect("old fence");
            }
            1 => changed.snapshot.fence_digest = digest("different-owner-fence"),
            _ => changed.authentication.signature[0] ^= 1,
        }
        assert!(
            fixture
                .state
                .start_canonical_intelligence(&changed)
                .await
                .is_err()
        );
        assert_eq!(fixture.provider.calls.load(Ordering::SeqCst), 0);
        assert_no_admission(&fixture).await;
    }
    let mut trust: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&fixture.trust_path).expect("trust"))
            .expect("trust JSON");
    trust["revoked"] = serde_json::json!(true);
    private_json(&fixture.trust_path, &trust);
    assert!(
        fixture
            .state
            .start_canonical_intelligence(&fixture.record)
            .await
            .is_err()
    );
    assert_eq!(fixture.provider.calls.load(Ordering::SeqCst), 0);
    assert_no_admission(&fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_body_does_not_alias_the_run_lifecycle_generation() {
    let fixture = runtime_fixture(/*body_generation*/ 2, /*drain_on_build*/ false).await;
    assert!(
        fixture
            .state
            .start_canonical_intelligence(&fixture.record)
            .await
            .is_err()
    );
    assert_eq!(fixture.provider.calls.load(Ordering::SeqCst), 1);
    assert_no_admission(&fixture).await;
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn owner_transition_during_canonical_preparation_never_refreshes_the_old_run() {
    let fixture = runtime_fixture(/*body_generation*/ 1, /*drain_on_build*/ true).await;
    assert!(
        fixture
            .state
            .start_canonical_intelligence(&fixture.record)
            .await
            .is_err()
    );
    assert_eq!(
        fixture
            .state
            .current_generation()
            .expect("Draining generation"),
        3
    );
    assert_eq!(fixture.provider.calls.load(Ordering::SeqCst), 1);
    assert_no_admission(&fixture).await;
    assert_eq!(fixture.record.snapshot.generation, 2);
    assert_eq!(
        fixture
            .journal
            .get(&fixture.record.snapshot.run_id)
            .expect("read"),
        Some(&fixture.record)
    );
}
