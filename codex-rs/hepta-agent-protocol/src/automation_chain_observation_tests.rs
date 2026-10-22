use super::*;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::Sha256Digest;

fn fixture() -> (
    AutomationEffectChainObservation,
    ExpectedAutomationTaskAcceptanceV1,
) {
    let effect = ProviderEffectIntent::new(
        ProviderEffectKey::for_operation("pon-task", "run-1", "publish-1").unwrap(),
        Sha256Digest::for_bytes(b"original exact packet"),
    );
    let expected = ExpectedAutomationTaskAcceptanceV1 {
        effect: effect.clone(),
        min_confirmation_depth: 1,
        min_confirmation_work_depth_hex: format!("{}01", "00".repeat(63)),
        block_id: "01".repeat(32),
        task_id: "03".repeat(32),
        owner: "04".repeat(32),
        provider: "05".repeat(32),
        output_sha256: "06".repeat(32),
        accept_tx_id: "07".repeat(32),
    };
    let observation = AutomationEffectChainObservation {
        schema_version: AUTOMATION_EFFECT_CHAIN_OBSERVATION_VERSION,
        block_id: expected.block_id.clone(),
        stored_exact: true,
        block_height: Some(5),
        block_chainwork_hex: Some(format!("{}01", "00".repeat(63))),
        active_tip: "02".repeat(32),
        active_tip_height: 7,
        active_tip_chainwork_hex: format!("{}03", "00".repeat(63)),
        active_chain_member: true,
        active_depth: Some(2),
        active_work_depth_hex: Some(format!("{}02", "00".repeat(63))),
        active_membership_sql_lookups: Some(2),
        active_membership_sql_budget: 1024,
        confirmation_policy_min_depth: 1,
        confirmation_policy_min_work_depth_hex: format!("{}01", "00".repeat(63)),
        confirmation_policy_satisfied: true,
        provider_effect_key: Some(effect.key.as_str().to_owned()),
        payload_sha256: Some(effect.payload_sha256.as_str().to_owned()),
        accepted_task: Some(AutomationEffectTaskAcceptanceV1 {
            schema_version: 1,
            task_id: expected.task_id.clone(),
            owner: expected.owner.clone(),
            provider: expected.provider.clone(),
            output_sha256: expected.output_sha256.clone(),
            accept_tx_id: expected.accept_tx_id.clone(),
            accepted_in_exact_packet: true,
            current_status: "settled".to_string(),
        }),
        owner_generation: 3,
        local_target_only: true,
        global_absence_authority: false,
        confirmation_authority: false,
        finality_authority: false,
        execution_authority: false,
    };
    (observation, expected)
}

#[test]
fn task_acceptance_compares_original_effect_and_all_independent_owner_expectations() {
    let (observation, expected) = fixture();
    assert!(observation.matches_expected_task_acceptance(&expected));
    let bytes = serde_json::to_vec(&observation).unwrap();
    assert_eq!(
        serde_json::from_slice::<AutomationEffectChainObservation>(&bytes).unwrap(),
        observation
    );
    for field in 0..10 {
        let mut other = expected.clone();
        match field {
            0 => other.block_id = "11".repeat(32),
            1 => other.task_id = "11".repeat(32),
            2 => other.owner = "11".repeat(32),
            3 => other.provider = "11".repeat(32),
            4 => other.output_sha256 = "11".repeat(32),
            5 => other.accept_tx_id = "11".repeat(32),
            6 => {
                other.effect.key =
                    ProviderEffectKey::for_operation("pon-task", "run-2", "publish-1").unwrap()
            }
            7 => other.effect.payload_sha256 = Sha256Digest::for_bytes(b"another packet"),
            8 => other.min_confirmation_depth = 2,
            _ => other.min_confirmation_work_depth_hex = format!("{}02", "00".repeat(63)),
        }
        assert!(!observation.matches_expected_task_acceptance(&other));
    }
}

#[test]
fn legacy_reorg_missing_task_and_authority_claims_never_match_an_upgrade() {
    let (observation, expected) = fixture();
    for case in 0..13 {
        let mut other = observation.clone();
        match case {
            0 => other.schema_version = 3,
            1 => other.accepted_task = None,
            2 => other.active_chain_member = false,
            3 => other.stored_exact = false,
            4 => other.confirmation_policy_satisfied = false,
            5 => other.provider_effect_key = None,
            6 => other.payload_sha256 = None,
            7 => other.owner_generation = 0,
            8 => other.local_target_only = false,
            9 => other.global_absence_authority = true,
            10 => other.confirmation_authority = true,
            11 => other.finality_authority = true,
            _ => other.execution_authority = true,
        }
        assert!(!other.matches_expected_task_acceptance(&expected));
    }
    let mut legacy = serde_json::to_value(&observation).unwrap();
    legacy["schema_version"] = serde_json::json!(3);
    legacy.as_object_mut().unwrap().remove("accepted_task");
    let legacy: AutomationEffectChainObservation = serde_json::from_value(legacy).unwrap();
    assert!(!legacy.matches_expected_task_acceptance(&expected));
}

#[test]
fn claimed_confirmation_success_cannot_hide_inconsistent_or_under_policy_work() {
    let (observation, expected) = fixture();
    for case in 0..9 {
        let mut other = observation.clone();
        match case {
            0 => other.confirmation_policy_min_depth = 3,
            1 => other.confirmation_policy_min_depth = 0,
            2 => other.active_depth = Some(3),
            3 => other.confirmation_policy_min_work_depth_hex = format!("{}03", "00".repeat(63)),
            4 => other.active_work_depth_hex = Some(format!("{}03", "00".repeat(63))),
            5 => other.active_tip_chainwork_hex = "00".repeat(64),
            6 => other.active_membership_sql_lookups = Some(1025),
            7 => other.block_id = other.active_tip.clone(),
            _ => other.confirmation_policy_min_work_depth_hex = "x".repeat(128),
        }
        assert!(!other.matches_expected_task_acceptance(&expected));
    }
}
