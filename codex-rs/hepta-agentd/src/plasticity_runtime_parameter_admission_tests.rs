use super::*;
use crate::AgentdPlasticityAdmissionInputV1;

fn input(request: &ParameterPlasticityProductRequestV1) -> AgentdPlasticityAdmissionInputV1 {
    AgentdPlasticityAdmissionInputV1 {
        baseline_id: request.admission.baseline_id.clone(),
        objective_digest: request.admission.objective_digest,
        generator_profile: request.generator_profile.clone(),
        generated: request.generated.clone(),
        baseline_generation: request.admission.baseline_generation,
        candidate_generation: request.admission.candidate_generation,
        dataset_digest: request.admission.dataset_digest,
        update_rule_digest: request.admission.update_rule_digest,
        modulator_digest: request.admission.modulator_digest,
        modulator_broadcast_digest: request.admission.modulator_broadcast_digest,
        eligibility_digest: request.admission.eligibility_digest,
    }
}

#[tokio::test]
async fn readonly_admission_resolves_all_original_facts_without_writer_or_anchor_changes() {
    let fixture = clock_fixture(|| Ok(50));
    let before = persistent_bytes(&fixture.files);
    let expected = fixture.parameter.admission.clone();
    let mut request = input(&fixture.parameter);
    let cancellation = CancellationToken::new();
    let task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        fixture.state.clone(),
        Some(fixture.owner),
        cancellation.clone(),
    );
    for _ in 0..2 {
        assert_eq!(
            fixture
                .handle
                .resolve_parameter_admission(request.clone())
                .await
                .expect("same held original owner facts"),
            expected
        );
    }
    request.generated.generator_digest = digest("foreign incomplete search");
    assert!(
        fixture
            .handle
            .resolve_parameter_admission(request)
            .await
            .is_err()
    );
    assert_eq!(persistent_bytes(&fixture.files), before);
    cancellation.cancel();
    task.await.expect("owner task").expect("owner closure");
}

#[tokio::test]
async fn readonly_admission_rechecks_current_custody_and_refuses_missing_current() {
    let mut fixture = clock_fixture(|| Ok(50));
    fixture.owner.current_artifacts = None;
    let before = persistent_bytes(&fixture.files);
    let request = input(&fixture.parameter);
    let cancellation = CancellationToken::new();
    let task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        fixture.state.clone(),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture.handle.resolve_parameter_admission(request).await,
        Err(PlasticityRuntimeCallErrorV1::Unavailable)
    ));
    assert_eq!(persistent_bytes(&fixture.files), before);
    cancellation.cancel();
    task.await.expect("owner task").expect("owner closure");
}
