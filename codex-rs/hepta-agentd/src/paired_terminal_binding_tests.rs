//! Existing real Ledger/Memory fixtures and real local test signatures. The
//! constructed Original delivery here is not human consent or Root evidence.
use super::*;
use crate::PairedPreparationRegistration;
use crate::PairedRecordPinsV1;
use crate::PairedTrainingMaterialManifestV1;
use crate::PairedTrainingPlanV1;
use crate::PairedTrainingReadResult;
use crate::paired_preparation::record_fixture_materials;
use crate::paired_preparation::training::consumer::OriginalPairedTrainingDelivery;
use crate::terminal_learning::PairedTerminalBindingPlanV1;
use crate::terminal_learning::PairedTerminalEventPairV1;
use crate::terminal_learning::PreparedPairedTerminalV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

const FIXTURE_NOW: u64 = 50;
const FAILURE: &[u8] = include_bytes!("../tests/fixtures/paired-record-failure-v1.json");
const CORRECTION: &[u8] = include_bytes!("../tests/fixtures/paired-record-correction-v1.json");

fn inputs(
    fixture: &FixtureOwners,
) -> (OriginalPairedTrainingDelivery, PairedTerminalBindingPlanV1) {
    let manifest = PairedTrainingMaterialManifestV1 {
        failure_sha256: Digest32::of_bytes(FAILURE),
        failure_bytes: FAILURE.len() as u64,
        correction_sha256: Digest32::of_bytes(CORRECTION),
        correction_bytes: CORRECTION.len() as u64,
    };
    let original = PairedTrainingPlanV1 {
        preparation: PairedPreparationRegistration {
            study: digest("pair-study"),
            enrollment: digest("pair-enrollment"),
            frozen_materials: manifest.commitment().unwrap(),
            principal_id: "fixture.principal".into(),
            policy_generation: Generation::new(/*value*/ 1).unwrap(),
        },
        manifest,
        operation: digest("pair-operation"),
    };
    let request = original
        .request_for_original("fixture-turn".into(), digest("fixture-delivery"))
        .unwrap();
    let snapshot = fixture.ledger.lock().unwrap().snapshot().unwrap();
    let event = |name: &str| {
        snapshot
            .records()
            .iter()
            .find(|row| row.event.record_id() == &id(name))
            .unwrap()
            .event_digest
    };
    let plan = PairedTerminalBindingPlanV1 {
        original,
        training: fixture.request.clone(),
        records: PairedRecordPinsV1 {
            failure_record_digest:
                "a7e5d55b674d728752a302f1f40b2eb7af02f284f50ff641123cc049368b48c2"
                    .parse()
                    .unwrap(),
            correction_record_digest:
                "77506dc0d93a2032429b1d3b8797f3b5cc4d42aab26ee2be796f8eb4b6874f48"
                    .parse()
                    .unwrap(),
        },
        failure: PairedTerminalEventPairV1 {
            decision: event("sample.read.decision"),
            outcome: event("sample.read.record"),
        },
        correction: PairedTerminalEventPairV1 {
            decision: event("sample.stop.decision"),
            outcome: event("sample.stop.record"),
        },
    };
    (
        OriginalPairedTrainingDelivery {
            request,
            result: Ok(record_fixture_materials(FAILURE, CORRECTION)),
        },
        plan,
    )
}

fn end() -> tokio::time::Instant {
    tokio::time::Instant::now() + std::time::Duration::from_secs(/*secs*/ 30)
}

fn late_signature(
    fixture: &FixtureOwners,
    prepared: &PreparedPairedTerminalV1,
) -> SignedLearningEvidenceV1 {
    let ledger = fixture.ledger.lock().unwrap();
    let mut signed = sign(
        ledger.verifier(),
        "evaluator",
        LearningEvidenceRoleV1::Evaluator,
        prepared.signing_payload(),
    );
    signed.issued_at = prepared.prepared_at();
    // The same existing Evaluator fixture key, never a product issuer.
    signed.signature = SigningKey::from_bytes(&[4; 32])
        .sign(&signed.signing_bytes())
        .to_bytes();
    signed
}

#[tokio::test]
async fn preparation_retains_exact_records_and_current_dataset_without_a_fit() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let before = fixture.ledger.lock().unwrap().snapshot().unwrap();
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    assert_eq!(prepared.original_records().materials().failure(), FAILURE);
    assert_eq!(
        prepared.original_records().materials().correction(),
        CORRECTION
    );
    assert!(
        prepared
            .signing_payload()
            .starts_with(b"hepta.agentd.paired-terminal-owner-binding.v1\0")
    );
    assert_eq!(fixture.ledger.lock().unwrap().snapshot().unwrap(), before);
    assert_eq!(
        owner
            .readback(fixture.request.clone(), FIXTURE_NOW)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
}

#[tokio::test]
async fn late_owner_signature_fits_existing_events_and_retains_original_bytes() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let before = fixture.ledger.lock().unwrap().snapshot().unwrap();
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    assert_eq!(prepared.original_records().materials().failure(), FAILURE);
    let signature = late_signature(&fixture, &prepared);
    let consume_now = signature.issued_at;
    let receipt = owner
        .consume_paired_original_v1(prepared, signature.clone(), consume_now)
        .await
        .unwrap();
    assert_eq!(receipt.binding_evidence, signature);
    assert_eq!(
        Digest32::of_bytes(&receipt.binding_payload),
        signature.payload_digest
    );
    assert_eq!(receipt.records.materials().failure(), FAILURE);
    assert_eq!(receipt.records.materials().correction(), CORRECTION);
    assert_eq!(
        receipt.records.failure_record().record_digest,
        receipt.plan.records.failure_record_digest
    );
    assert_eq!(
        (
            receipt.training.source_records,
            receipt.training.training_samples
        ),
        (4, 2)
    );
    assert_eq!(receipt.training.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(
        owner
            .readback(fixture.request.clone(), consume_now)
            .await
            .unwrap(),
        receipt.training
    );
    assert_eq!(fixture.ledger.lock().unwrap().snapshot().unwrap(), before);
    // The fixture deliberately associates failure text "0" with native target
    // ONE, and correction text "1" with target ZERO. No bool/text target mapping.
    let artifact = receipt.training.candidate.artifact();
    let loaded = LoadedTabularOperatorV1::from_pinned_payload(
        &receipt.training.payload,
        &TabularPayloadPinV1 {
            payload_digest: Digest32::of_bytes(&receipt.training.payload),
            artifact_digest: artifact.artifact_digest,
            objective_digest: artifact.objective_digest,
            dataset_digest: artifact.dataset_digest,
            sensor_core_digest: artifact.sensor_core_digest,
            training_profile_digest: artifact.training_profile_digest,
            generation: artifact.generation,
        },
    )
    .unwrap();
    assert_eq!(
        loaded
            .predict(&id("single-approved-state"), &id("read"))
            .unwrap()
            .value,
        FixedQ32::ONE
    );
    assert_eq!(
        loaded
            .predict(&id("single-approved-state"), &id("abstain"))
            .unwrap()
            .value,
        FixedQ32::ZERO
    );
}

#[tokio::test]
async fn original_request_unknown_retained_raw_and_canonical_mismatches_refuse() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    for case in 0..6 {
        let (mut delivery, mut plan) = inputs(&fixture);
        match case {
            0 => delivery.request.operation = digest("other-operation"),
            1 => {
                delivery.result = Ok(PairedTrainingReadResult::Unknown {
                    original_delivery: delivery.request.original.delivery_id,
                })
            }
            2 => {
                delivery.result = Ok(PairedTrainingReadResult::RetainedReadOnly {
                    original_delivery: delivery.request.original.delivery_id,
                })
            }
            3 => delivery.result = Ok(record_fixture_materials(b"{}", CORRECTION)),
            4 => plan.records.failure_record_digest = digest("wrong-canonical"),
            5 => delivery.result = Err(crate::AgentdError::Invalid("fixture read refused".into())),
            _ => unreachable!(),
        }
        assert!(
            owner
                .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
                .await
                .is_err()
        );
    }
    assert_eq!(
        owner
            .readback(fixture.request.clone(), FIXTURE_NOW)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
}

#[tokio::test]
async fn exact_four_event_digests_and_episode_roles_refuse_relabelled_links() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    for case in 0..5 {
        let (delivery, mut plan) = inputs(&fixture);
        match case {
            0 => plan.failure.decision = Digest32::ZERO,
            1 => plan.failure.outcome = plan.failure.decision,
            2 => std::mem::swap(&mut plan.failure.decision, &mut plan.failure.outcome),
            3 => std::mem::swap(&mut plan.failure.outcome, &mut plan.correction.outcome),
            4 => plan.failure.outcome = digest("not-a-current-event"),
            _ => unreachable!(),
        }
        assert!(
            owner
                .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
                .await
                .is_err()
        );
    }
}

#[tokio::test]
async fn evaluator_signature_old_time_role_and_changed_job_are_not_authority() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    for case in 0..5 {
        let (delivery, plan) = inputs(&fixture);
        let prepared = owner
            .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
            .await
            .unwrap();
        let mut signature = late_signature(&fixture, &prepared);
        let consume_now = signature.issued_at;
        let prepared = match case {
            0 => {
                signature.signature[0] ^= 1;
                prepared
            }
            1 => {
                signature.role = LearningEvidenceRoleV1::Generator;
                prepared
            }
            2 => {
                signature.issued_at = 20;
                signature.signature = SigningKey::from_bytes(&[4; 32])
                    .sign(&signature.signing_bytes())
                    .to_bytes();
                prepared
            }
            3 | 4 => {
                let (mut delivery, mut plan) = inputs(&fixture);
                if case == 3 {
                    plan.training.profile.generation = Generation::new(/*value*/ 2).unwrap();
                } else {
                    delivery.request.original.delivery_id = digest("another-original-delivery");
                }
                owner
                    .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
                    .await
                    .unwrap()
            }
            _ => unreachable!(),
        };
        assert!(
            owner
                .consume_paired_original_v1(prepared, signature, consume_now)
                .await
                .is_err()
        );
    }
    assert_eq!(
        owner
            .readback(fixture.request.clone(), FIXTURE_NOW)
            .await
            .unwrap_err(),
        TerminalLearningErrorV1::CommitUncertain
    );
}

#[tokio::test]
async fn extra_real_episode_is_refused_even_with_valid_current_dataset_signature() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let (delivery, mut plan) = inputs(&fixture);
    {
        let mut ledger = fixture.ledger.lock().unwrap();
        collect(
            &mut ledger,
            "extra",
            "read",
            FixedQ32::ONE.raw(),
            fixture.request.expected_source_support_digest,
        );
        plan.training.dataset_evidence = sign(
            ledger.verifier(),
            "evaluator",
            LearningEvidenceRoleV1::Evaluator,
            &dataset_freeze_signing_payload_v2(
                &ledger.snapshot().unwrap(),
                &plan.training.dataset_plan,
            )
            .unwrap(),
        );
        let dataset = ledger
            .freeze_dataset(
                plan.training.dataset_plan.clone(),
                &plan.training.dataset_evidence,
                FIXTURE_NOW,
            )
            .unwrap();
        assert_eq!(
            ledger
                .read_dataset_records(&dataset, FIXTURE_NOW)
                .unwrap()
                .iter()
                .filter(|row| matches!(
                    row.event,
                    LedgerEvent::AuthenticatedDecisionV2(_)
                        | LedgerEvent::AuthenticatedOutcomeV2(_)
                ))
                .count(),
            6
        );
        plan.training.expected_dataset_digest = dataset.snapshot.dataset_digest;
    }
    assert!(matches!(
        owner
            .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
            .await,
        Err(TerminalLearningErrorV1::Conflict)
    ));
    assert_eq!(
        fixture
            .ledger
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .len(),
        6
    );
}

#[tokio::test]
async fn memory_replay_revocation_between_prepare_and_consume_refuses() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    let signature = late_signature(&fixture, &prepared);
    let consume_now = signature.issued_at;
    fixture
        .source
        .revoke_shared_experience(&fixture.access, &fixture.grant)
        .await
        .unwrap();
    assert!(
        owner
            .consume_paired_original_v1(prepared, signature, consume_now)
            .await
            .is_err()
    );
}

#[tokio::test]
async fn actual_ledger_append_after_prepare_invalidates_the_frozen_cut() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    let signature = late_signature(&fixture, &prepared);
    let consume_now = signature.issued_at;
    collect(
        &mut fixture.ledger.lock().unwrap(),
        "later",
        "read",
        /*value*/ 0,
        fixture.request.expected_source_support_digest,
    );
    assert!(
        owner
            .consume_paired_original_v1(prepared, signature, consume_now)
            .await
            .is_err()
    );
    assert_eq!(
        fixture
            .ledger
            .lock()
            .unwrap()
            .snapshot()
            .unwrap()
            .records()
            .len(),
        6
    );
}

#[tokio::test]
async fn original_deadline_and_actual_owner_custody_cannot_be_replaced() {
    let fixture = FixtureOwners::new().await;
    let owner = fixture.native_owner();
    assert!(matches!(
        owner
            .train_until(
                fixture.request.clone(),
                FIXTURE_NOW,
                tokio::time::Instant::now()
            )
            .await,
        Err(TerminalLearningErrorV1::DeadlineExceeded)
    ));
    let (delivery, plan) = inputs(&fixture);
    assert!(matches!(
        owner
            .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, tokio::time::Instant::now())
            .await,
        Err(TerminalLearningErrorV1::DeadlineExceeded)
    ));
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    let signature = late_signature(&fixture, &prepared);
    let consume_now = signature.issued_at;
    // A reconstructed owner shares Ledger/Memory, but has different job and
    // compute state. It cannot take custody of the prepared original operation.
    assert!(matches!(
        fixture
            .native_owner()
            .consume_paired_original_v1(prepared, signature, consume_now)
            .await,
        Err(TerminalLearningErrorV1::WrongScope)
    ));
    let (delivery, plan) = inputs(&fixture);
    let prepared = owner
        .prepare_paired_original_v1(delivery, plan, FIXTURE_NOW, end())
        .await
        .unwrap();
    let signature = late_signature(&fixture, &prepared);
    let consume_now = signature.issued_at;
    let other = FixtureOwners::new().await;
    assert!(matches!(
        other
            .native_owner()
            .consume_paired_original_v1(prepared, signature, consume_now)
            .await,
        Err(TerminalLearningErrorV1::WrongScope)
    ));
}

#[path = "terminal_paired_runtime_tests.rs"]
mod runtime_tests;
