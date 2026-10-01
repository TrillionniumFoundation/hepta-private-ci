use super::*;
use crate::learning_operator_artifact_test_support::*;

fn persisted_fixture() -> Fixture {
    let mut fixture = Fixture::new();
    // The real owner verifies the admitted immutable manifest, lease and CURRENT.
    crate::learning_operator_artifact_owner::tests::persist_fixture(&mut fixture);
    fixture
}

#[test]
fn v3_load_preserves_distinct_training_and_evaluation_and_predicts_read_only() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, binding, verifier) = fixture.load_inputs();
    assert_ne!(
        binding.model_pin.dataset_digest,
        binding.selection.receipt().dataset_digest
    );
    let mut consumer = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || Ok(50_000_000),
    )
    .unwrap();
    let prediction = consumer
        .predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(51_000_000),
        )
        .unwrap();
    assert_eq!(prediction.value, codex_hepta_types::FixedQ32::from_raw(20));
    assert!(!prediction.authority.grants_any());
}

#[test]
fn v3_load_rejects_training_eval_substitution_and_runtime_relabel() {
    let fixture = persisted_fixture();
    for case in 0..3 {
        let (snapshot, payload, selected, mut binding, verifier) = fixture.load_inputs();
        if case == 0 {
            binding.evaluation = binding.training.clone();
        }
        if case == 1 {
            binding.model_pin.dataset_digest = binding.selection.receipt().dataset_digest;
        }
        if case == 2 {
            binding.expected_runtime_profile_digest = digest("foreign-runtime");
        }
        assert!(
            EvaluatedTabularShadowConsumerV3::load_with_clock(
                fixture.artifacts.service(),
                &fixture.training.owner,
                &fixture.evaluation.owner,
                &verifier,
                snapshot,
                payload,
                selected,
                binding,
                || Ok(50_000_000)
            )
            .is_err()
        );
    }
}

#[test]
fn failed_real_current_read_cannot_revive_consumer_from_restored_backup() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, binding, verifier) = fixture.load_inputs();
    let mut consumer = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || Ok(50_000_000),
    )
    .unwrap();
    let signed = &fixture.publication.signed_current_head;
    let current = fixture.directory.path().join("heads").join(format!(
        "{}-{}.head",
        signed.witness.generation.get(),
        codex_hepta_types::Digest32::of_bytes(&signed.signing_bytes())
    ));
    let backup = std::fs::read(&current).unwrap();
    std::fs::write(&current, b"broken CURRENT").unwrap();
    assert!(
        consumer
            .predict_with_clock(
                fixture.artifacts.service(),
                &fixture.training.owner,
                &fixture.evaluation.owner,
                &verifier,
                &id("sensor"),
                &id("action"),
                || Ok(51_000_000)
            )
            .is_err()
    );
    std::fs::write(current, backup).unwrap();
    assert!(matches!(
        consumer.predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(52_000_000)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "consumer unavailable"
        ))
    ));
}

#[test]
fn cancellation_and_clock_regression_close_loaded_shadow_consumer() {
    for cancel in [true, false] {
        let fixture = persisted_fixture();
        let (snapshot, payload, selected, binding, verifier) = fixture.load_inputs();
        let mut consumer = EvaluatedTabularShadowConsumerV3::load_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            snapshot,
            payload,
            selected,
            binding,
            || Ok(50_000_000),
        )
        .unwrap();
        if cancel {
            fixture.control.cancel();
        }
        assert!(
            consumer
                .predict_with_clock(
                    fixture.artifacts.service(),
                    &fixture.training.owner,
                    &fixture.evaluation.owner,
                    &verifier,
                    &id("sensor"),
                    &id("action"),
                    || Ok(49_000_000)
                )
                .is_err()
        );
        assert!(
            consumer
                .predict_with_clock(
                    fixture.artifacts.service(),
                    &fixture.training.owner,
                    &fixture.evaluation.owner,
                    &verifier,
                    &id("sensor"),
                    &id("action"),
                    || Ok(51_000_000)
                )
                .is_err()
        );
    }
}

#[test]
fn retained_storage_selection_must_be_valid_at_actual_load_and_each_use() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, binding, verifier) =
        fixture.load_inputs_with_selection_expiry(55_000_000);
    assert!(matches!(
        EvaluatedTabularShadowConsumerV3::load_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            snapshot,
            payload,
            selected,
            binding,
            || Ok(55_000_001)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "storage selection currentness"
        ))
    ));
    let (snapshot, payload, selected, binding, verifier) =
        fixture.load_inputs_with_selection_expiry(55_000_000);
    let inclusive_current = fixture
        .artifacts
        .service()
        .current_registry_view(55_000_000)
        .unwrap();
    verifier
        .revalidate_for_use(&selected, &inclusive_current, 55_000_000)
        .unwrap();
    let mut consumer = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || Ok(50_000_000),
    )
    .unwrap();
    consumer
        .predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(54_000_000),
        )
        .unwrap();
    assert!(matches!(
        consumer.predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(55_000_000)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "storage selection currentness"
        ))
    ));
    assert!(matches!(
        consumer.predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(54_000_000)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "consumer unavailable"
        ))
    ));
}

#[test]
fn a_frozen_wall_clock_cannot_hide_actual_load_time_past_the_deadline() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, mut binding, verifier) = fixture.load_inputs();
    binding.deadline_unix_micros = 50_000_001;
    let samples = std::cell::Cell::new(0);
    let result = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || {
            let index = samples.get();
            samples.set(index + 1);
            if index == 1 {
                std::thread::sleep(std::time::Duration::from_millis(2));
            }
            Ok(50_000_000)
        },
    );
    assert!(matches!(
        result,
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "shadow deadline or cancellation"
        ))
    ));
    assert_eq!(samples.get(), 2);
}

#[test]
fn load_release_rechecks_retained_current_and_storage_selection_windows() {
    let fixture = persisted_fixture();
    for expired_at in [55_000_001, 100_000_001] {
        let (snapshot, payload, selected, mut binding, verifier) =
            fixture.load_inputs_with_selection_expiry(55_000_000);
        binding.deadline_unix_micros = 180_000_000;
        let samples = std::cell::Cell::new(0);
        let result = EvaluatedTabularShadowConsumerV3::load_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            snapshot,
            payload,
            selected,
            binding,
            || {
                let index = samples.get();
                samples.set(index + 1);
                Ok(if index < 2 { 50_000_000 } else { expired_at })
            },
        );
        let reason = if expired_at == 55_000_001 {
            "storage selection currentness"
        } else {
            "artifact CURRENT time window"
        };
        assert!(
            matches!(result, Err(LearningOperatorPublicationErrorV1::Rejected(message)) if message == reason)
        );
        assert_eq!(samples.get(), 3);
    }
}

#[test]
fn frozen_load_release_clock_cannot_hide_time_spent_after_the_owner_refresh() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, mut binding, verifier) = fixture.load_inputs();
    binding.deadline_unix_micros = 51_000_000;
    let samples = std::cell::Cell::new(0);
    let result = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || {
            let index = samples.get();
            samples.set(index + 1);
            if index == 2 {
                std::thread::sleep(std::time::Duration::from_millis(1_100));
            }
            Ok(50_000_000)
        },
    );
    assert!(matches!(
        result,
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "shadow deadline or cancellation"
        ))
    ));
    assert_eq!(samples.get(), 3);
}

#[test]
fn prediction_release_expiry_discards_the_result_and_permanently_closes_the_consumer() {
    let fixture = persisted_fixture();
    let (snapshot, payload, selected, binding, verifier) =
        fixture.load_inputs_with_selection_expiry(55_000_000);
    let mut consumer = EvaluatedTabularShadowConsumerV3::load_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        snapshot,
        payload,
        selected,
        binding,
        || Ok(50_000_000),
    )
    .unwrap();
    let samples = std::cell::Cell::new(0);
    let result = consumer.predict_with_clock(
        fixture.artifacts.service(),
        &fixture.training.owner,
        &fixture.evaluation.owner,
        &verifier,
        &id("sensor"),
        &id("action"),
        || {
            let index = samples.get();
            samples.set(index + 1);
            Ok(if index < 2 { 51_000_000 } else { 55_000_001 })
        },
    );
    assert!(matches!(
        result,
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "storage selection currentness"
        ))
    ));
    assert_eq!(samples.get(), 3);
    assert!(matches!(
        consumer.predict_with_clock(
            fixture.artifacts.service(),
            &fixture.training.owner,
            &fixture.evaluation.owner,
            &verifier,
            &id("sensor"),
            &id("action"),
            || Ok(51_000_000)
        ),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "consumer unavailable"
        ))
    ));
}
