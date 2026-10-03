use super::*;
use crate::plasticity_runtime::input_context::PlasticityInputContextV2;

pub(super) fn fixture_round() -> crate::AgentdSelfIterationRoundV1 {
    let round:crate::AgentdSelfIterationRoundV1=serde_json::from_value(serde_json::json!({
        "goal":"goal.context", "ordinal":1, "candidate_admissions":2,
        "policy":digest("window.context").to_string(),"execution":digest("execution.context").to_string(),
        "admitted_at_ms":1,"deadline_ms":100,
    })).expect("typed fixture original round");
    crate::AgentdSelfIterationRoundV1::decode(&round.canonical_bytes().expect("original codec"))
        .expect("whole original round bytes")
}
fn context(
    fixture: &ClockFixture,
    sources: &OwnerSources,
    pin: Digest32,
) -> PlasticityInputContextV2 {
    PlasticityInputContextV2 {
        baseline_source: None,
        baseline_material: None,
        round: fixture_round(),
        source: (PathBuf::from("/fixture/root-context"), pin),
        predecessor: fixture.owner.artifacts.head_digest(),
        baseline: id("artifact:baseline"),
        artifacts: sources.artifacts.clone(),
        current_artifacts: crate::plasticity_runtime::current_artifacts::fixture_current_artifacts(
            &sources.artifacts,
        ),
        resolver: Box::new(resolver(sources)),
        policy: sources.owner_policy.clone(),
        verifier: SigningFixture::new().verifier(sources.objective_digest),
    }
}

#[tokio::test]
async fn whole_current_refresh_accepts_original_no_change_request_and_old_inputs_cannot_append() {
    let mut fixture = clock_fixture(|| Ok(50));
    let directory = tempfile::tempdir().expect("new original fact fixture");
    let sources = build_owner_sources(
        directory.path(),
        &fixture.owner.ledger,
        digest("plasticity-clock-objective"),
        digest("plasticity-selected-after-current"),
    );
    let signing = SigningFixture::new();
    let verifier = signing.verifier(sources.objective_digest);
    let fresh = signed_request(&sources, &fixture.owner.ledger, &signing, &verifier);
    assert_eq!(fresh.generated.candidates.len(), 1);
    assert_eq!(
        fresh.generated.candidates[0].kind,
        codex_hepta_agent_components::plasticity::ParameterCandidateKindV2::NoChange
    );
    assert!(fresh.no_change_attestation.is_some());
    assert!(fresh.evaluations.is_empty());
    let old = fixture.parameter.clone();
    let before = persistent_bytes(&fixture.files);
    let ledger_before = fs::read(&fixture.files.ledger).expect("same held ledger");
    let packet = context(&fixture, &sources, digest("protected context fixture"));
    let cancellation = CancellationToken::new();
    fixture
        .owner
        .admit_input_context(
            &fixture.state,
            &cancellation,
            fixture
                .state
                .current_generation()
                .expect("runtime generation"),
            packet,
        )
        .expect("explicit whole admission");
    assert_eq!(persistent_bytes(&fixture.files), before);
    assert_eq!(
        fs::read(&fixture.files.ledger).expect("same ledger bytes"),
        ledger_before
    );
    let task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        fixture.state.clone(),
        Some(fixture.owner),
        cancellation.clone(),
    );
    let receipt = fixture
        .handle
        .propose_parameter(fresh, 50)
        .await
        .expect("new authentic input facts");
    assert_eq!(
        receipt.disposition,
        ParameterPlasticityDispositionV1::NoAdmissibleUpdate
    );
    let committed = persistent_bytes(&fixture.files);
    assert_ne!(committed, before);
    assert!(fixture.handle.propose_parameter(old, 50).await.is_err());
    assert_eq!(persistent_bytes(&fixture.files), committed);
    cancellation.cancel();
    task.await.expect("owner task").expect("closure");
}

#[test]
fn stale_predecessor_and_changed_packet_for_same_round_preserve_the_original_context() {
    let mut fixture = clock_fixture(|| Ok(50));
    let directory = tempfile::tempdir().expect("new original fact fixture");
    let sources = build_owner_sources(
        directory.path(),
        &fixture.owner.ledger,
        digest("plasticity-clock-objective"),
        digest("plasticity-selected-next"),
    );
    let before = persistent_bytes(&fixture.files);
    let generation = fixture
        .state
        .current_generation()
        .expect("runtime generation");
    let cancel = CancellationToken::new();
    let mut packet = context(&fixture, &sources, digest("context one"));
    packet.predecessor = digest("foreign predecessor");
    assert!(
        fixture
            .owner
            .admit_input_context(&fixture.state, &cancel, generation, packet)
            .is_err()
    );
    let packet = context(&fixture, &sources, digest("context one"));
    fixture
        .owner
        .admit_input_context(&fixture.state, &cancel, generation, packet)
        .expect("exact original predecessor");
    let selected = fixture.owner.artifacts.head_digest();
    let packet = context(&fixture, &sources, digest("context changed"));
    assert!(
        fixture
            .owner
            .admit_input_context(&fixture.state, &cancel, generation, packet)
            .is_err()
    );
    assert_eq!(fixture.owner.artifacts.head_digest(), selected);
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[test]
fn selected_parameter_artifact_identity_is_distinct_from_stable_runtime_model_identity() {
    use codex_hepta_agent_components::learning_artifacts::ArtifactKind;
    use codex_hepta_agent_components::learning_artifacts::ArtifactManifest;
    use codex_hepta_agent_components::types::Generation;
    let model = id("model.runtime.stable");
    let selected = ArtifactManifest {
        artifact_id: id("artifact.parameters.generation2"),
        kind: ArtifactKind::Parameters,
        generation: Generation::new(2).expect("successor"),
        predecessor_id: Some(id("artifact.parameters.generation1")),
        content_digest: digest("actual frozen native head"),
        objective_digest: digest("training objective"),
        support_digest: digest("full original artifact admission"),
        producer_id: id("original.parameter.generator"),
        compatibility_digest: digest("original runtime profile"),
        encoded_size_bytes: 128,
    };
    assert_ne!(selected.artifact_id, model);
    crate::plasticity_process_bootstrap::validate_context_baseline_artifact(
        &selected,
        selected.generation,
        selected.content_digest,
        selected.objective_digest,
    )
    .expect("original selected parameter artifact matches full actual head tuple");
    assert!(
        crate::plasticity_process_bootstrap::validate_context_baseline_artifact(
            &selected,
            selected.generation.next().expect("foreign generation"),
            selected.content_digest,
            selected.objective_digest,
        )
        .is_err()
    );
    assert!(
        crate::plasticity_process_bootstrap::validate_context_baseline_artifact(
            &selected,
            selected.generation,
            digest("foreign native head"),
            selected.objective_digest,
        )
        .is_err()
    );
}
