use crate::paired_supervised_host_clock::PairedHostClockV1;
use crate::paired_supervised_test_support::SigningFixture;
use crate::paired_supervised_test_support::Sink;
use crate::paired_supervised_test_support::inputs;
use crate::paired_supervised_test_support::runner;
use crate::*;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;

#[test]
fn paired_public_owner_uses_actual_time_even_when_inner_signers_remain_valid() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    assert!(
        signing
            .verifier
            .verify(
                LearningEvidenceRoleV1::Generator,
                &registration.generator_evidence,
                plan.frozen.plan_digest.as_array(),
                801,
            )
            .is_ok()
    );
    assert!(!signing.trust.is_current_at(801));
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let before = owner.holdout_state_digest();
    // This public API accepts no timestamp or caller-defined clock. Historical
    // fixture evidence cannot be admitted at the actual host time.
    assert!(
        owner
            .evaluate_registered_paired_supervised(&registration, &mut provider, &signing.trust,)
            .is_err()
    );
    assert_eq!(provider.metadata_count, 0);
    assert_eq!(provider.release_count, 0);
    assert_eq!(owner.holdout_state_digest(), before);
}

#[test]
fn paired_root_expiry_during_metadata_stops_before_cas() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let before = owner.holdout_state_digest();
    assert!(
        owner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &signing.trust,
                &mut PairedHostClockV1::fixture(&[30, 801]),
            )
            .is_err()
    );
    assert_eq!(provider.metadata_count, 1);
    assert_eq!(provider.release_count, 0);
    assert_eq!(owner.holdout_state_digest(), before);
}

#[test]
fn paired_root_expiry_after_cas_keeps_consumption_and_does_not_release() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let before = owner.holdout_state_digest();
    assert!(
        owner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &signing.trust,
                &mut PairedHostClockV1::fixture(&[30, 30, 801]),
            )
            .is_err()
    );
    let consumed = owner.holdout_state_digest();
    assert_ne!(consumed, before);
    assert_eq!(provider.release_count, 0);
    assert!(
        owner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &signing.trust,
                &mut PairedHostClockV1::fixture(&[30]),
            )
            .is_err()
    );
    assert_eq!(owner.holdout_state_digest(), consumed);
    assert_eq!(provider.release_count, 0);
}

#[test]
fn paired_actual_clock_regression_stops_before_consumption() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let before = owner.holdout_state_digest();
    assert!(
        owner
            .evaluate_paired_with_clock(
                &registration,
                &mut provider,
                &signing.trust,
                &mut PairedHostClockV1::fixture(&[30, 29]),
            )
            .is_err()
    );
    assert_eq!(provider.release_count, 0);
    assert_eq!(owner.holdout_state_digest(), before);
}

#[test]
fn paired_root_expiry_at_actual_sink_boundary_never_publishes() {
    let plan = freeze_paired_supervised_plan_v1(inputs(128)).unwrap();
    let signing = SigningFixture::new(false);
    let registration = signing.register(&plan);
    let mut provider = signing.provider(&plan);
    let mut owner = runner();
    let execution = owner
        .evaluate_paired_with_clock(
            &registration,
            &mut provider,
            &signing.trust,
            &mut PairedHostClockV1::fixture(&[30]),
        )
        .unwrap();
    let context = signing.context();
    let evidence = signing.evaluation(&execution, &context);
    let consumed = owner.holdout_state_digest();
    let mut sink = Sink::default();
    assert!(
        owner
            .qualify_paired_with_clock(
                &execution,
                &context,
                &evidence,
                &signing.trust,
                &mut sink,
                &mut PairedHostClockV1::fixture(&[30, 801]),
            )
            .is_err()
    );
    assert_eq!(sink.calls, 0);
    assert_eq!(owner.holdout_state_digest(), consumed);
    // The production entrypoint also samples actual time and offers no way to
    // replay the fixture's old time into the publication owner.
    assert!(
        owner
            .qualify_paired_and_persist(&execution, &context, &evidence, &signing.trust, &mut sink,)
            .is_err()
    );
    assert_eq!(sink.calls, 0);
}
