//! Full original signed history and exact immutable E/O observations.
use super::*;

struct NoDynamic;
impl crate::PlasticityOwnerEvidenceResolverV1 for NoDynamic {
    fn resolve(
        &self,
        _: &crate::PlasticityOwnerEvidenceQueryV1,
    ) -> Result<crate::VerifiedPlasticityOwnerEvidenceV1, crate::PlasticityOwnerEvidenceErrorV1>
    {
        Err(crate::PlasticityOwnerEvidenceErrorV1::Unavailable)
    }
}
fn original_window_fixture() -> (
    tempfile::TempDir,
    ClockFixture,
    Arc<ActivatedLearningTrustV1>,
    u64,
) {
    let root = tempfile::tempdir().unwrap();
    let mut fixture = clock_fixture(crate::authbus_ingress::now_ms);
    let now = crate::authbus_ingress::now_ms().unwrap();
    let (trust, _) = learning_trust(
        JournalScope {
            scope_digest: digest("real Window consumer fixture"),
            objective_digest: fixture.parameter.admission.objective_digest,
        },
        now,
        now + 120_000,
    );
    populate_original_dataset_ledger_count(&mut fixture, root.path(), &trust, now, 3);
    (root, fixture, trust, now)
}
fn original_signed_window(
    current: &LedgerSnapshot,
    trust: &ActivatedLearningTrustV1,
    now: u64,
) -> crate::PlasticityDatasetWindowEvidenceV3 {
    let frozen =
        authenticate_ledger_snapshot_prefix_v3(current, current.records()[1].chain_digest, 2)
            .unwrap();
    let plan = DatasetWindowFreezePlanV3 {
        snapshot_id: id("dataset.signed-window.consumer"),
        objective_digest: trust.verifier().objective_digest(),
        inclusion_policy_digest: digest("explicit protected Window consumer inclusion"),
        decision_sequence_start: 1,
        decision_sequence_end: 2,
        maximum_episodes: 1,
        maximum_source_records: 2,
        maximum_encoded_bytes: 8192,
    };
    let payload = dataset_window_freeze_signing_payload_v3(&frozen, &plan).unwrap();
    let evaluator =
        dataset_support::sign(trust, 2, LearningEvidenceRoleV1::Evaluator, &payload, now);
    let producer = trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Evaluator, &evaluator, &payload, now)
        .unwrap()
        .principal()
        .clone();
    let window =
        freeze_dataset_window_from_ledger_v3(&frozen, plan.clone(), producer, now).unwrap();
    crate::PlasticityDatasetWindowEvidenceV3 {
        plan,
        window,
        evaluator,
        verifier: trust.verifier().clone(),
    }
}
fn concrete(
    window: &crate::PlasticityDatasetWindowEvidenceV3,
    fixture: &ClockFixture,
) -> crate::ConcretePlasticityOwnerEvidenceResolverV1 {
    crate::ConcretePlasticityOwnerEvidenceResolverV1::new(
        window.window.receipt.clone(),
        fixture.owner.artifacts.clone(),
        0,
        u64::MAX,
        vec![
            crate::PlasticityArtifactOwnerBindingV1 {
                kind: crate::PlasticityOwnerEvidenceKindV1::UpdateRule,
                artifact_id: id("policy:update"),
            },
            crate::PlasticityArtifactOwnerBindingV1 {
                kind: crate::PlasticityOwnerEvidenceKindV1::MutationPolicy,
                artifact_id: id("policy:mutation"),
            },
        ],
        Box::new(NoDynamic),
    )
    .unwrap()
}
fn query(
    fixture: &ClockFixture,
    window: &DatasetWindowSnapshotReceiptV3,
    head: Digest32,
    now: u64,
) -> crate::PlasticityOwnerEvidenceQueryV1 {
    let admission = &fixture.parameter.admission;
    crate::PlasticityOwnerEvidenceQueryV1 {
        kind: crate::PlasticityOwnerEvidenceKindV1::Dataset,
        evidence_digest: window.receipt.snapshot.dataset_digest,
        objective_digest: window.receipt.snapshot.objective_digest,
        selected_artifact_digest: admission.selected_artifact_digest,
        artifact_registry_head_digest: fixture.owner.artifacts.head_digest(),
        qualification_evidence_head_digest: head,
        window: admission.window.clone(),
        dataset_digest: window.receipt.snapshot.dataset_digest,
        baseline_generation: admission.baseline_generation,
        layer_id: None,
        parameter_id: None,
        signal_eligibility: None,
        signal_modulator: None,
        signal_learning_rate: None,
        signal_lower_bound: None,
        signal_upper_bound: None,
        now,
    }
}
#[test]
fn signed_window_retains_h1_and_original_observer_h2_across_real_unrelated_h3_history() {
    let (root, fixture, trust, now) = original_window_fixture();
    let current = fixture.owner.ledger.snapshot().unwrap();
    let window = original_signed_window(&current, &trust, now);
    let frozen_head = window.window.receipt.snapshot.ledger_head_digest;
    let h2 = current.records()[3].chain_digest;
    let prior = authenticate_ledger_snapshot_prefix_v3(&current, h2, 4).unwrap();
    let before = (
        fs::read(&fixture.files.ledger).unwrap(),
        fs::read(root.path().join("authenticated-dataset-witness.bin")).unwrap(),
    );
    let dataset = window.window.clone();
    let original = concrete(&window, &fixture);
    assert!(
        crate::PlasticityOwnerEvidenceResolverV1::qualification_head(
            &original,
            &current,
            Some(h2),
            now
        )
        .is_err(),
        "old purpose remains strict current"
    );
    let resolver = original
        .with_dataset_window_v3(window, &prior, now)
        .unwrap();
    assert_eq!(
        crate::PlasticityOwnerEvidenceResolverV1::qualification_head(
            &resolver,
            &current,
            Some(h2),
            now
        )
        .unwrap(),
        h2
    );
    let q = query(&fixture, &dataset, h2, now);
    let old = crate::PlasticityOwnerEvidenceResolverV1::resolve_with_ledger(&resolver, &q, &prior)
        .unwrap();
    let after =
        crate::PlasticityOwnerEvidenceResolverV1::resolve_with_ledger(&resolver, &q, &current)
            .unwrap();
    assert_eq!(after, old);
    assert_eq!(after.owner_store_head_digest, frozen_head);
    assert_eq!(after.qualification_evidence_head_digest, h2);
    assert_ne!(h2, frozen_head);
    assert_ne!(h2, current.head_digest);
    let mut admission = fixture.parameter.admission.clone();
    admission.qualification_evidence_head_digest = h2;
    admission.dataset_digest = dataset.receipt.snapshot.dataset_digest;
    admission.owner_evidence_set_digest = after.owner_receipt_digest;
    let payload =
        codex_hepta_agent_components::intelligence::plasticity_admission_signing_payload_v1(
            &admission,
        );
    let observer =
        dataset_support::sign(&trust, 1, LearningEvidenceRoleV1::Observer, &payload, now);
    trust
        .verifier()
        .verify(LearningEvidenceRoleV1::Observer, &observer, &payload, now)
        .unwrap();
    let observed_payload =
        codex_hepta_agent_components::intelligence::plasticity_admission_signing_payload_v1(
            &admission,
        );
    assert_eq!(observed_payload, payload);
    assert!(
        crate::PlasticityOwnerEvidenceResolverV1::resolve(&resolver, &q).is_err(),
        "whole live snapshot is mandatory"
    );
    assert_eq!(
        before,
        (
            fs::read(&fixture.files.ledger).unwrap(),
            fs::read(root.path().join("authenticated-dataset-witness.bin")).unwrap()
        )
    );
}
#[test]
fn altered_signature_policy_or_observation_prefix_cannot_authorize_window_consumer() {
    let (_root, fixture, trust, now) = original_window_fixture();
    let current = fixture.owner.ledger.snapshot().unwrap();
    let mut bad = original_signed_window(&current, &trust, now);
    bad.evaluator.signature[0] ^= 1;
    assert!(
        concrete(&bad, &fixture)
            .with_dataset_window_v3(bad, &current, now)
            .is_err()
    );
    let mut bad = original_signed_window(&current, &trust, now);
    bad.plan.maximum_episodes += 1;
    assert!(
        concrete(&bad, &fixture)
            .with_dataset_window_v3(bad, &current, now)
            .is_err()
    );
    let window = original_signed_window(&current, &trust, now);
    let resolver = concrete(&window, &fixture)
        .with_dataset_window_v3(window, &current, now)
        .unwrap();
    for observed in [
        digest("foreign original head"),
        current.records()[0].chain_digest,
    ] {
        assert!(
            crate::PlasticityOwnerEvidenceResolverV1::qualification_head(
                &resolver,
                &current,
                Some(observed),
                now
            )
            .is_err()
        );
    }
    let mut corrupt = current.clone();
    corrupt.head_digest = digest("foreign full snapshot head");
    assert!(
        crate::PlasticityOwnerEvidenceResolverV1::qualification_head(
            &resolver, &corrupt, None, now
        )
        .is_err()
    );
    assert!(
        crate::PlasticityOwnerEvidenceResolverV1::qualification_head(
            &resolver,
            &current,
            None,
            trust.expires_at() + 1
        )
        .is_err()
    );
}
