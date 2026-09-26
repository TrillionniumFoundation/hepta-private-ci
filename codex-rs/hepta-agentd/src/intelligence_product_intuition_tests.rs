//! Regressions for the actual product adapter, not a manually bypassed kernel.
use super::*;
use crate::AgentdIntuitionPolicyErrorV2;
use codex_hepta_intelligence::CurrentOwnerStateV1;

fn current_binding(value: &Fixture) -> AgentdIntuitionCurrentBindingV1 {
    let owner = value
        .owners
        .iter()
        .find(|owner| owner.owner_id.as_str() == "intuition.policy")
        .unwrap();
    AgentdIntuitionCurrentBindingV1 {
        snapshot_digest: value.request.snapshot.digest(),
        authority_epoch: value.request.snapshot.authority_epoch(),
        revocation_frontier_digest: value.request.snapshot.revocation_frontier_digest(),
        owner: CurrentOwnerStateV1 {
            owner_id: owner.owner_id.clone(),
            generation: owner.generation,
            implementation_digest: owner.implementation_digest,
            key_digest: owner.key_digest,
            key_epoch: owner.key_epoch,
            authority_epoch: value.request.snapshot.authority_epoch(),
            revocation_frontier_digest: value.request.snapshot.revocation_frontier_digest(),
        },
    }
}

#[test]
fn selected_profile_and_host_generation_are_fenced() {
    let value = fixture();
    let agent = codex_hepta_contracts::AgentId::parse(intuition_support::TEST_AGENT_ID).unwrap();
    let now = wall_clock_ms().unwrap();
    let receipt = value
        .intuition_host
        .decide(
            &agent,
            1,
            current_binding(&value),
            value.inputs.intuition.clone(),
            now,
        )
        .unwrap();
    assert!(!receipt.decision.decision.authority.grants_any());
    assert!(matches!(
        value.intuition_host.decide(
            &agent,
            2,
            current_binding(&value),
            value.inputs.intuition.clone(),
            now
        ),
        Err(AgentdIntuitionPolicyErrorV2::GenerationFence)
    ));
    let mut replaced = value.inputs.intuition.clone();
    replaced.profile.risk_rule = codex_hepta_intuition::CanonicalRiskRuleV1::AlwaysSlowPath;
    assert!(matches!(
        value
            .intuition_host
            .decide(&agent, 1, current_binding(&value), replaced, now),
        Err(AgentdIntuitionPolicyErrorV2::CurrentProfile)
    ));
}

#[test]
fn rotated_trust_frontier_and_expired_evidence_are_rejected() {
    let value = fixture();
    let agent = codex_hepta_contracts::AgentId::parse(intuition_support::TEST_AGENT_ID).unwrap();
    let now = wall_clock_ms().unwrap();
    let mut rotated = current_binding(&value);
    rotated.owner.key_digest = digest("rotated-intuition-root");
    assert!(matches!(
        value
            .intuition_host
            .decide(&agent, 1, rotated, value.inputs.intuition.clone(), now),
        Err(AgentdIntuitionPolicyErrorV2::CurrentTrust)
    ));
    let mut revoked = current_binding(&value);
    revoked.revocation_frontier_digest = digest("new-frontier");
    revoked.owner.revocation_frontier_digest = revoked.revocation_frontier_digest;
    assert!(matches!(
        value
            .intuition_host
            .decide(&agent, 1, revoked, value.inputs.intuition.clone(), now),
        Err(AgentdIntuitionPolicyErrorV2::CurrentTrust)
    ));
    let value = fixture();
    let expired = value.inputs.intuition.runtime.expires_at + 1;
    assert!(matches!(
        value.intuition_host.decide(
            &agent,
            1,
            current_binding(&value),
            value.inputs.intuition.clone(),
            expired
        ),
        Err(AgentdIntuitionPolicyErrorV2::Qualification(_))
    ));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn product_preparation_cannot_fall_back_to_unauthenticated_v2() {
    let value = fixture();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier()).unwrap();
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::IntuitionPolicyUnavailable)
    ));
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn product_adapter_rejects_signature_substitution() {
    let (mut value, trust) = super::signed::signed_fixture();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    value.inputs.intuition.runtime.signature[0] ^= 1;
    let runner = product_runner(path, &value)
        .with_evaluation_trust(trust)
        .unwrap();
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(_))
    ));
}

#[test]
fn product_stage_rereads_current_owner_after_preparation() {
    let value = fixture();
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("authority.json");
    let current = current_binding(&value);
    let stage_input = CanonicalPortInputV1 {
        run_id: value.request.run_id.clone(),
        snapshot_digest: current.snapshot_digest,
        objective_digest: value.request.snapshot.objective_digest(),
        candidate_set_digest: digest("candidate-set"),
        predecessor_digest: digest("predecessor"),
        budget_micros: 10_000_000,
        stage: CanonicalStageV1::IntuitionDecided,
    };
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let host = Arc::clone(&value.intuition_host);
    let saved_input = value.inputs.intuition.clone();
    let saved_current = current.clone();
    let mut ports = AgentdOwnerPortsV1::new(
        value.inputs,
        None,
        value.intuition_host,
        current,
        codex_hepta_contracts::AgentId::parse(intuition_support::TEST_AGENT_ID).unwrap(),
        1,
        FileBackedFreshnessOracleV1::new(path.clone(), authority_verifier()),
    );
    write_authority_file(&path, &value.owners, digest("revoked-after-prepare"));
    assert_eq!(
        ports.decide_intuition(&stage_input).unwrap_err().class,
        CanonicalPortFailureClassV1::Rejected
    );
    // Restoring the old signed file must not resurrect an already-retired host.
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    assert!(matches!(
        host.decide(
            &codex_hepta_contracts::AgentId::parse(intuition_support::TEST_AGENT_ID).unwrap(),
            1,
            saved_current,
            saved_input,
            wall_clock_ms().unwrap()
        ),
        Err(AgentdIntuitionPolicyErrorV2::Retired)
    ));
}
