use codex_hepta_contracts::ProviderEffectIntent;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;
use pretty_assertions::assert_eq;

use super::*;

fn plan() -> ActionCheckPlanV1 {
    ActionCheckPlanV1 {
        binding: ActionSkillBindingV1 {
            provider_intent: ProviderEffectIntent::new(
                ProviderEffectKey::for_logical_effect("destination", "effect").expect("key"),
                Sha256Digest::for_bytes(b"payload"),
            ),
            effect_intent_digest: Sha256Digest::for_bytes(b"intent"),
            contract_digest: Sha256Digest::for_bytes(b"contract"),
            destination_id: "destination".to_string(),
        },
        generation: 1,
        effective_model_digest: Sha256Digest::for_bytes(b"model"),
        source_frontier_digest: Sha256Digest::for_bytes(b"source"),
        checker_digest: Sha256Digest::for_bytes(b"checker"),
        remediation_digest: Sha256Digest::for_bytes(b"response"),
        cost_unit: "registered-unit".to_string(),
        timing: ActionCheckTimeV1::Known {
            clock_id: "same-host-clock".to_string(),
            occurred_at_ms: 10,
            available_at_ms: 20,
            max_age_ms: 20,
        },
        estimate: ActionCheckEstimateV1 {
            error_ppm: 500_000,
            detection_ppm: 1_000_000,
            false_positive_ppm: 0,
            remediation_success_ppm: 1_000_000,
            error_loss: 100,
            check_cost: 10,
            true_positive_response_cost: 10,
            false_positive_response_cost: 10,
        },
    }
}

fn now() -> ActionCheckClockV1 {
    ActionCheckClockV1::Known {
        clock_id: "same-host-clock".to_string(),
        at_ms: 30,
    }
}

fn recommendation(plan: &ActionCheckPlanV1) -> ActionCheckRecommendationV1 {
    plan.assess(&plan.binding, &now())
        .expect("assessment")
        .recommendation
}

#[test]
fn ineffective_checker_or_failed_remediation_cannot_claim_avoided_loss() {
    let mut plan = plan();
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Check);
    plan.estimate.detection_ppm = 0;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
    plan.estimate.detection_ppm = 1_000_000;
    plan.estimate.remediation_success_ppm = 0;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
}

#[test]
fn response_cost_is_paid_on_failed_remediation_and_false_positives() {
    let mut plan = plan();
    plan.estimate.remediation_success_ppm = 500_000;
    plan.estimate.true_positive_response_cost = 40;
    // Expected benefit 25, cost 10 + 20; response cost is not halved by success.
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
    plan.estimate.true_positive_response_cost = 0;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Check);
    plan.estimate.false_positive_ppm = 1_000_000;
    plan.estimate.false_positive_response_cost = 40;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
}

#[test]
fn exact_boundary_and_maximum_costs_do_not_round_or_overflow() {
    let mut plan = plan();
    plan.estimate.error_ppm = 1_000_000;
    plan.estimate.error_loss = 1;
    plan.estimate.true_positive_response_cost = 0;
    plan.estimate.check_cost = 1;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
    plan.estimate.error_loss = 2;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Check);
    plan.estimate.error_loss = u64::MAX;
    plan.estimate.true_positive_response_cost = u64::MAX;
    plan.estimate.false_positive_response_cost = u64::MAX;
    plan.estimate.check_cost = u64::MAX;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Skip);
}

#[test]
fn missing_and_stale_time_stay_unknown_and_future_receipts_are_rejected() {
    let mut plan = plan();
    let later = ActionCheckClockV1::Known {
        clock_id: "same-host-clock".to_string(),
        at_ms: 31,
    };
    assert_eq!(
        plan.assess(&plan.binding, &later)
            .expect("stale")
            .recommendation,
        ActionCheckRecommendationV1::Unknown
    );
    assert_eq!(
        plan.assess(&plan.binding, &ActionCheckClockV1::Unknown)
            .expect("unknown")
            .recommendation,
        ActionCheckRecommendationV1::Unknown
    );
    plan.timing = ActionCheckTimeV1::Unknown;
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Unknown);
    plan.timing = ActionCheckTimeV1::Known {
        clock_id: "same-host-clock".to_string(),
        occurred_at_ms: 10,
        available_at_ms: 20,
        max_age_ms: 19,
    };
    assert_eq!(recommendation(&plan), ActionCheckRecommendationV1::Unknown);
    if let ActionCheckTimeV1::Known {
        available_at_ms, ..
    } = &mut plan.timing
    {
        *available_at_ms = 32;
    }
    assert_eq!(
        plan.assess(&plan.binding, &now()),
        Err(ActionSkillError::Observation)
    );
}

#[test]
fn plan_identity_changes_with_pins_and_original_attempt_is_required() {
    let mut plan = plan();
    let original = plan.assess(&plan.binding, &now()).expect("original");
    plan.generation += 1;
    assert_ne!(
        plan.assess(&plan.binding, &now())
            .expect("new")
            .assessment_digest,
        original.assessment_digest
    );
    let mut other = plan.binding.clone();
    other.effect_intent_digest = Sha256Digest::for_bytes(b"other-attempt");
    assert_eq!(
        plan.assess(&other, &now()),
        Err(ActionSkillError::Invocation)
    );
    plan.estimate.error_ppm = 1_000_001;
    assert_eq!(
        plan.assess(&plan.binding, &now()),
        Err(ActionSkillError::Invocation)
    );
}

#[test]
fn unknown_clock_does_not_bypass_present_evidence_bounds() {
    let mut plan = plan();
    plan.timing = ActionCheckTimeV1::Unknown;
    let oversized = ActionCheckClockV1::Known {
        clock_id: "x".repeat(129),
        at_ms: 30,
    };
    assert_eq!(
        plan.assess(&plan.binding, &oversized),
        Err(ActionSkillError::Observation)
    );
    plan.timing = ActionCheckTimeV1::Known {
        clock_id: "x".repeat(129),
        occurred_at_ms: 10,
        available_at_ms: 20,
        max_age_ms: 20,
    };
    assert_eq!(
        plan.assess(&plan.binding, &ActionCheckClockV1::Unknown),
        Err(ActionSkillError::Observation)
    );
    plan.timing = ActionCheckTimeV1::Known {
        clock_id: "same-host-clock".to_string(),
        occurred_at_ms: 21,
        available_at_ms: 20,
        max_age_ms: 20,
    };
    assert_eq!(
        plan.assess(&plan.binding, &ActionCheckClockV1::Unknown),
        Err(ActionSkillError::Observation)
    );
}

#[test]
fn deserialized_original_binding_is_validated_before_assessment() {
    let original = serde_json::to_value(plan()).expect("serialized plan");
    let roundtrip: ActionCheckPlanV1 = serde_json::from_value(original.clone()).expect("plan");
    assert_eq!(
        recommendation(&roundtrip),
        ActionCheckRecommendationV1::Check
    );
    for (path, invalid) in [
        (
            "/binding/provider_intent/schema_version",
            serde_json::json!(0),
        ),
        (
            "/binding/provider_intent/key",
            serde_json::json!("invalid-key"),
        ),
        (
            "/binding/provider_intent/payload_sha256",
            serde_json::json!("invalid-digest"),
        ),
        (
            "/binding/effect_intent_digest",
            serde_json::json!("invalid-digest"),
        ),
        (
            "/binding/contract_digest",
            serde_json::json!("invalid-digest"),
        ),
        ("/binding/destination_id", serde_json::json!("")),
        (
            "/binding/destination_id",
            serde_json::json!("destination with spaces"),
        ),
        (
            "/binding/destination_id",
            serde_json::json!("d".repeat(129)),
        ),
    ] {
        let mut value = original.clone();
        *value.pointer_mut(path).expect("binding field") = invalid;
        let plan: ActionCheckPlanV1 = serde_json::from_value(value).expect("plan shape");
        for current in [now(), ActionCheckClockV1::Unknown] {
            assert_eq!(
                plan.assess(&plan.binding, &current),
                Err(ActionSkillError::Invocation),
                "{path}"
            );
        }
    }
}
