use super::*;
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
        deadline_ms: original.admission.deadline_unix_micros.div_ceil(1_000),
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
    let status = run_state(&fixture).await.expect("admitted run");
    assert_eq!(status.run_id, expected.run_id);
    assert_eq!(status.generation, expected.generation);
    assert_eq!(status.fence_digest, expected.fence_digest);
    assert_eq!(status.phase, crate::AgentRunPhase::ContextAttached);
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

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn recovered_ordinary_field_run_returns_the_registered_weight_evidence() {
    let candidate = format!("candidate:field:{}", digest("registered-candidate"));
    let fixture = runtime_fixture_for_candidate(1, false, &candidate).await;
    let record = &fixture.record;
    let Some(crate::AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    }) = fixture
        .state
        .start_canonical_intelligence(record)
        .await
        .unwrap()
    else {
        panic!("expected ordinary signed field admission");
    };
    let read = prepared.coupled_field_readback().unwrap();
    assert_eq!(Some(read), fixture.expected_field.as_ref());
    assert_eq!(
        read.binding.artifact_bytes_digest,
        Digest32::of_bytes(&[0x44, 0x01, 0xf8, 0x00])
    );
    assert_eq!(read.binding.candidate_id, id(&candidate));
    assert_eq!(run_receipt.phase, crate::RunPhase::ContextAttached);
    assert!(!prepared.envelope.authority.grants_any());
    assert_eq!(
        run_state(&fixture).await.unwrap().run_id,
        prepared.run_snapshot().run_id
    );
    assert_eq!(
        prepared.run_snapshot().request_digest,
        record.admission.admitted_source_digest.to_string()
    );
    assert_eq!(
        fixture.journal.get(&record.snapshot.run_id).unwrap(),
        Some(record)
    );
    let expected = read.clone();
    let original = record.clone();
    let (path, binding, signed, verifier) = fixture.field_verification.unwrap();
    let file_bytes = std::fs::read(&path).unwrap();
    assert!(!file_bytes.is_empty());
    drop(fixture.state);
    let cold = AgentdCoupledFieldRunFileV1::open(
        binding.run_id.clone(),
        std::fs::File::open(&path).unwrap(),
    )
    .unwrap();
    assert_eq!(
        cold.verify_retained(
            &original,
            &binding,
            &signed,
            &verifier,
            wall_clock_ms().unwrap()
        )
        .unwrap(),
        expected
    );
    let mut wrong = original.clone();
    wrong.snapshot.model_tuple_digest = digest("another-published-model-tuple");
    assert!(
        cold.verify_retained(
            &wrong,
            &binding,
            &signed,
            &verifier,
            wall_clock_ms().unwrap()
        )
        .is_err()
    );
    drop(cold);
    let proof = prepared.coupled_field_readback.as_ref().unwrap();
    for boundary in [0, 8, 120, file_bytes.len() - 1, file_bytes.len()] {
        let interrupted = tempfile::NamedTempFile::new().unwrap();
        std::fs::write(interrupted.path(), &file_bytes[..boundary]).unwrap();
        let slot = AgentdCoupledFieldRunFileV1::open(
            binding.run_id.clone(),
            interrupted.reopen().unwrap(),
        )
        .unwrap();
        assert!(
            AgentdCoupledFieldRunFileV1::open(
                binding.run_id.clone(),
                interrupted.reopen().unwrap()
            )
            .is_err()
        );
        slot.retain(&original, proof).unwrap();
        assert_eq!(std::fs::read(interrupted.path()).unwrap(), file_bytes);
    }
    let mut corrupted = file_bytes;
    corrupted[8 + 4 * 32] ^= 1;
    std::fs::write(&path, &corrupted).unwrap();
    let reopened = AgentdCoupledFieldRunFileV1::open(
        binding.run_id.clone(),
        std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(&path)
            .unwrap(),
    )
    .unwrap();
    assert!(reopened.retain(&original, proof).is_err());
    assert_eq!(std::fs::read(&path).unwrap(), corrupted);
    assert!(
        reopened
            .verify_retained(
                &original,
                &binding,
                &signed,
                &verifier,
                wall_clock_ms().unwrap()
            )
            .is_err()
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_field_receipt_remains_empty_after_owner_transition() {
    let candidate = format!("candidate:field:{}", digest("registered-candidate"));
    let fixture = runtime_fixture_for_candidate(1, true, &candidate).await;
    let (path, ..) = fixture.field_verification.as_ref().unwrap();
    assert!(
        fixture
            .state
            .start_canonical_intelligence(&fixture.record)
            .await
            .is_err()
    );
    assert_no_admission(&fixture).await;
    assert!(std::fs::read(path).unwrap().is_empty());
}
