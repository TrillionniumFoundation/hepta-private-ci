use super::*;
use crate::learning_operator_artifact_test_support::*;

#[test]
fn real_dual_ledger_fit_publishes_exact_retry_and_recovers_ack_after_expiry() {
    let mut fixture = Fixture::new();
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &fixture.candidate,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    let receipt = fixture
        .artifacts
        .persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || Ok(50_000_000),
        )
        .unwrap();
    let head = fixture.artifacts.service().registry().snapshot();
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &fixture.candidate,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    let retry = fixture
        .artifacts
        .persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || Ok(51_000_000),
        )
        .unwrap();
    assert_eq!(receipt, retry);
    assert_eq!(fixture.artifacts.service().registry().snapshot(), head);
    let mut config = fixture.config.clone();
    config.required_current_head = Some(fixture.publication.signed_current_head.clone());
    config.now = 52_000_000;
    drop(fixture.artifacts);
    let reopened = LearningArtifactOwnerService::open(config).unwrap();
    let adapter = LearningOperatorArtifactOwnerV1::new(
        reopened,
        fixture
            .candidate
            .publication_view()
            .runtime_profile_digest(),
    )
    .unwrap();
    let mut expired_request = fixture.publication.clone();
    expired_request.now = 200_000_000;
    let recovered = adapter.reconcile_status(&expired_request).unwrap().unwrap();
    assert_eq!(
        recovered.status.state_digest,
        receipt.publication.state_digest
    );
    assert!(!recovered.status.authority.grants_any());
}

#[test]
fn reused_evaluation_records_and_wrong_source_or_runtime_do_not_write() {
    let mut fixture = Fixture::new();
    let before = fixture.artifacts.service().registry().snapshot();
    for case in 0..3 {
        let mut run = fixture.run.clone();
        if case == 1 {
            run.training_source_digest = digest("foreign-source");
        }
        if case == 2 {
            run.expected_stop_epoch += 1;
        }
        let evaluation = if case == 0 {
            &fixture.training.receipt
        } else {
            &fixture.evaluation.receipt
        };
        let inputs = LearningOperatorPublicationInputsV1 {
            publication: fixture.publication.clone(),
            run: &run,
            candidate: &fixture.candidate,
            training: &fixture.training.receipt,
            evaluation,
            selection: &fixture.selection,
            control: &fixture.control,
        };
        assert!(matches!(
            fixture.artifacts.persist_with_clock(
                &fixture.training.owner,
                &fixture.evaluation.owner,
                inputs,
                || Ok(50_000_000)
            ),
            Err(LearningOperatorPublicationErrorV1::Rejected(_))
        ));
        assert_eq!(fixture.artifacts.service().registry().snapshot(), before);
        assert!(
            fixture
                .artifacts
                .reconcile_status(&fixture.publication)
                .unwrap()
                .is_none()
        );
    }
}

#[test]
fn expiry_after_real_fsync_preserves_known_storage_receipt() {
    let mut fixture = Fixture::new();
    let samples = std::cell::Cell::new(0);
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &fixture.candidate,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    let result = fixture.artifacts.persist_with_clock(
        &fixture.training.owner,
        &fixture.evaluation.owner,
        inputs,
        || {
            let index = samples.get();
            samples.set(index + 1);
            Ok(if index < 2 { 50_000_000 } else { 100_000_000 })
        },
    );
    let Err(LearningOperatorPublicationErrorV1::PersistedButNotCurrent { receipt, .. }) = result
    else {
        panic!("known persisted result required")
    };
    assert_eq!(
        fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .unwrap()
            .status
            .state_digest,
        receipt.publication.state_digest
    );
}

#[test]
fn expired_cancelled_or_regressed_write_boundary_creates_no_payload_or_checkpoint() {
    for case in 0..6 {
        let mut fixture = Fixture::new();
        let mut run = fixture.run.clone();
        if matches!(case, 1 | 2) {
            run.deadline_unix_micros = 180_000_000;
        }
        if case == 5 {
            run.deadline_unix_micros = 50_000_001;
        }
        let before = fixture.artifacts.service().registry().snapshot();
        let samples = std::cell::Cell::new(0);
        let inputs = LearningOperatorPublicationInputsV1 {
            publication: fixture.publication.clone(),
            run: &run,
            candidate: &fixture.candidate,
            training: &fixture.training.receipt,
            evaluation: &fixture.evaluation.receipt,
            selection: &fixture.selection,
            control: &fixture.control,
        };
        let result = fixture.artifacts.persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || {
                let index = samples.get();
                samples.set(index + 1);
                if index == 0 {
                    return Ok(50_000_000);
                }
                Ok(match case {
                    0 => 90_000_000,
                    1 => 100_000_001,
                    2 => 150_000_000,
                    3 => {
                        fixture.control.cancel();
                        50_000_000
                    }
                    4 => 49_000_000,
                    5 => {
                        std::thread::sleep(std::time::Duration::from_millis(2));
                        50_000_000
                    }
                    _ => unreachable!(),
                })
            },
        );
        assert!(matches!(
            result,
            Err(LearningOperatorPublicationErrorV1::Rejected(_))
        ));
        assert_eq!(samples.get(), 2);
        assert_eq!(fixture.artifacts.service().registry().snapshot(), before);
        assert!(
            fixture
                .artifacts
                .reconcile_status(&fixture.publication)
                .unwrap()
                .is_none()
        );
        assert!(
            !fixture
                .directory
                .path()
                .join("payloads")
                .join(format!(
                    "candidate-{}.bin",
                    fixture.candidate.payload_digest()
                ))
                .exists()
        );
    }
}

#[test]
fn owner_acknowledges_the_actual_dispatch_sample_after_initial_validation() {
    let mut fixture = Fixture::new();
    let samples = std::cell::Cell::new(0);
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &fixture.candidate,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    let receipt = fixture
        .artifacts
        .persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || {
                let index = samples.get();
                samples.set(index + 1);
                Ok(50_000_000 + index * 1_000_000)
            },
        )
        .unwrap();
    assert_eq!(receipt.publication.acknowledged_at, 51_000_000);
    assert_eq!(samples.get(), 4);
}

#[test]
fn expiry_at_final_publication_release_retains_the_exact_acknowledged_receipt() {
    for frozen in [false, true] {
        let mut fixture = Fixture::new();
        let mut run = fixture.run.clone();
        if frozen {
            run.deadline_unix_micros = 51_000_000;
        }
        let samples = std::cell::Cell::new(0);
        let inputs = LearningOperatorPublicationInputsV1 {
            publication: fixture.publication.clone(),
            run: &run,
            candidate: &fixture.candidate,
            training: &fixture.training.receipt,
            evaluation: &fixture.evaluation.receipt,
            selection: &fixture.selection,
            control: &fixture.control,
        };
        let result = fixture.artifacts.persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || {
                let index = samples.get();
                samples.set(index + 1);
                if index == 3 {
                    if !frozen {
                        return Ok(run.deadline_unix_micros);
                    }
                    std::thread::sleep(std::time::Duration::from_millis(1_100));
                }
                Ok(50_000_000)
            },
        );
        let Err(LearningOperatorPublicationErrorV1::PersistedButNotCurrent { receipt, .. }) =
            result
        else {
            panic!("known acknowledged result required")
        };
        assert_eq!(samples.get(), 4);
        let status = fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .unwrap()
            .status;
        assert_eq!(status.state_digest, receipt.publication.state_digest);
        assert_eq!(
            status.acknowledged_at,
            Some(receipt.publication.acknowledged_at)
        );
        assert!(!receipt.publication.authority.grants_any());
    }
}

#[test]
fn current_head_actor_expiry_or_revocation_at_release_preserves_the_exact_ack() {
    for (expires_at, revoked_at, released_at) in [
        (60_000_000, None, 61_000_000),
        (100_000_000, Some(60_000_000), 60_000_000),
    ] {
        let mut fixture = Fixture::new_with_head_actor_window(expires_at, revoked_at);
        let samples = std::cell::Cell::new(0);
        let inputs = LearningOperatorPublicationInputsV1 {
            publication: fixture.publication.clone(),
            run: &fixture.run,
            candidate: &fixture.candidate,
            training: &fixture.training.receipt,
            evaluation: &fixture.evaluation.receipt,
            selection: &fixture.selection,
            control: &fixture.control,
        };
        let result = fixture.artifacts.persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || {
                let index = samples.get();
                samples.set(index + 1);
                Ok(if index < 3 { 59_000_000 } else { released_at })
            },
        );
        let Err(LearningOperatorPublicationErrorV1::PersistedButNotCurrent { receipt, message }) =
            result
        else {
            panic!("known stored result required after CURRENT actor expiry")
        };
        assert!(message.contains("owner CURRENT time window"));
        assert_eq!(samples.get(), 4);
        assert!(
            fixture
                .artifacts
                .service()
                .current_registry_view(released_at)
                .is_err()
        );
        let status = fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .unwrap()
            .status;
        assert_eq!(status.state_digest, receipt.publication.state_digest);
        assert_eq!(
            status.acknowledged_at,
            Some(receipt.publication.acknowledged_at)
        );
        assert!(!receipt.publication.authority.grants_any());
    }
}

pub(crate) fn persist_fixture(fixture: &mut Fixture) {
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &fixture.candidate,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    fixture
        .artifacts
        .persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || Ok(50_000_000),
        )
        .unwrap();
}

#[test]
fn an_identical_later_fit_cannot_reuse_earlier_signed_science_freeze() {
    let mut fixture = Fixture::new();
    let late = fixture.late_candidate();
    assert_eq!(late.payload_digest(), fixture.candidate.payload_digest());
    let before = fixture.artifacts.service().registry().snapshot();
    let inputs = LearningOperatorPublicationInputsV1 {
        publication: fixture.publication.clone(),
        run: &fixture.run,
        candidate: &late,
        training: &fixture.training.receipt,
        evaluation: &fixture.evaluation.receipt,
        selection: &fixture.selection,
        control: &fixture.control,
    };
    assert!(matches!(
        fixture.artifacts.persist_with_clock(
            &fixture.training.owner,
            &fixture.evaluation.owner,
            inputs,
            || Ok(53_000_000)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(_))
    ));
    assert_eq!(fixture.artifacts.service().registry().snapshot(), before);
    assert!(
        fixture
            .artifacts
            .reconcile_status(&fixture.publication)
            .unwrap()
            .is_none()
    );
}
