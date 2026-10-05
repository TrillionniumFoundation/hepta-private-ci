use super::*;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::IntelligenceAuthorityVerifierV1;
use crate::learning_operator_shadow_loader::EvaluatedTabularShadowConsumerV4;
use codex_hepta_agent_components::learning_artifacts::LearningArtifactOwnerService;
use ed25519_dalek::SigningKey;

#[path = "learning_operator_artifact_test_support.rs"]
mod fixture;
#[path = "learning_operator_ledger_tests.rs"]
mod ledger;
#[allow(dead_code)]
#[path = "cognitive_ranker_paired_test_support.rs"]
mod paired;
#[path = "learning_operator_qualification_tests.rs"]
mod qualification;
use fixture::Fixture;
use fixture::id;

fn runner(fixture: &Fixture) -> AgentdIntelligenceProductRunnerV1 {
    AgentdIntelligenceProductRunnerV1::new(
        fixture.directory.path().join("host-authority"),
        IntelligenceAuthorityVerifierV1 {
            signer_id: "product-host".to_owned(),
            verifying_key: SigningKey::from_bytes(&[71; 32]).verifying_key().to_bytes(),
        },
    )
    .unwrap()
    .with_evaluation_trust(fixture.training.owner.activated_trust().clone())
    .unwrap()
}

fn persist_fixture(
    fixture: &mut Fixture,
) -> Result<LearningOperatorStorageReceiptV2, LearningOperatorPublicationErrorV1> {
    runner(fixture).persist_learning_operator_candidate(
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &mut fixture.artifacts,
        LearningOperatorPublicationInputsV2 {
            run: &fixture.run,
            candidate: &fixture.candidate,
            training: &fixture.training.receipt,
            evaluation: &fixture.evaluation.receipt,
            selection: &fixture.selection,
            control: &fixture.control,
            publication: fixture.publication.clone(),
        },
    )
}

#[test]
fn real_product_owner_ack_reconciles_reopens_and_loads_original_fit_for_shadow() {
    let mut fixture = Fixture::new();
    let receipt = persist_fixture(&mut fixture).unwrap();
    assert!(!receipt.publication().authority.grants_any());
    let status = fixture
        .artifacts
        .reconcile_status(&fixture.publication)
        .unwrap()
        .unwrap();
    assert_eq!(
        status.status.state_digest,
        receipt.publication().state_digest
    );
    assert!(!status.status.authority.grants_any());
    let repeated = persist_fixture(&mut fixture).unwrap();
    assert_eq!(receipt, repeated);
    let head = fixture
        .artifacts
        .service()
        .registry()
        .snapshot()
        .head_digest;
    let runtime = fixture
        .candidate
        .publication_view()
        .runtime_profile_digest();
    let mut config = fixture.config.clone();
    config.now = paired::now_millis();
    assert!(LearningArtifactOwnerService::open(config.clone()).is_err());
    drop(fixture.artifacts);
    assert!(LearningArtifactOwnerService::open(config.clone()).is_err());
    config.required_current_head = Some(fixture.publication.signed_current_head.clone());
    config.now = paired::now_millis();
    let replacement = LearningOperatorArtifactOwnerV2::new(
        LearningArtifactOwnerService::open(config).unwrap(),
        runtime,
    )
    .unwrap();
    fixture.artifacts = replacement;
    assert_eq!(
        fixture
            .artifacts
            .service()
            .registry()
            .snapshot()
            .head_digest,
        head
    );
    let (snapshot, payload, selected, binding, verifier) = fixture.load_inputs(receipt);
    let mut consumer = EvaluatedTabularShadowConsumerV4::load(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
    )
    .unwrap();
    let prediction = consumer
        .predict_shadow(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
        )
        .unwrap();
    assert_eq!(prediction.value.raw(), 20);
    fixture.control.cancel();
    assert!(
        consumer
            .predict_shadow(
                fixture.artifacts.service(),
                &fixture.training.owner,
                &fixture.evaluation.owner,
                &verifier,
                &id("sensor"),
                &id("action"),
            )
            .is_err()
    );
    assert!(
        consumer
            .predict_shadow(
                fixture.artifacts.service(),
                &fixture.training.owner,
                &fixture.evaluation.owner,
                &verifier,
                &id("sensor"),
                &id("action"),
            )
            .is_err()
    );
}

#[test]
fn cancellation_and_elapsed_budget_reject_before_any_owner_write() {
    let mut fixture = Fixture::new();
    let head = fixture
        .artifacts
        .service()
        .registry()
        .snapshot()
        .head_digest;
    fixture.run.deadline_unix_micros = wall_clock_micros().unwrap() - 1;
    assert!(matches!(
        persist_fixture(&mut fixture),
        Err(LearningOperatorPublicationErrorV1::Rejected(_))
    ));
    assert!(
        fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .is_none()
    );
    fixture.run.deadline_unix_micros = wall_clock_micros().unwrap() + 30_000_000;
    fixture.control.cancel();
    assert!(matches!(
        persist_fixture(&mut fixture),
        Err(LearningOperatorPublicationErrorV1::Rejected(_))
    ));
    assert_eq!(
        fixture
            .artifacts
            .service()
            .registry()
            .snapshot()
            .head_digest,
        head
    );
    assert!(
        fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .is_none()
    );
}

#[test]
fn evaluation_before_a_different_final_use_fit_cannot_publish_the_later_fit() {
    let mut fixture = Fixture::new();
    fixture.candidate = fixture.late_candidate();
    assert!(matches!(
        persist_fixture(&mut fixture),
        Err(LearningOperatorPublicationErrorV1::Rejected(_))
    ));
    assert!(
        fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .is_none()
    );
}

#[test]
fn independent_runtime_pin_mismatch_closes_stored_shadow_without_activation() {
    let mut fixture = Fixture::new();
    let receipt = persist_fixture(&mut fixture).unwrap();
    let (snapshot, payload, selected, mut binding, verifier) = fixture.load_inputs(receipt);
    binding.model_pin.runtime_profile_digest = fixture::digest("other-runtime");
    assert!(
        EvaluatedTabularShadowConsumerV4::load(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            snapshot,
            payload,
            selected,
            binding,
        )
        .is_err()
    );
}
