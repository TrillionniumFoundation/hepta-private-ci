use super::*;

#[derive(Clone, Copy)]
enum FinalAdmissionChange {
    Fenced,
    Draining,
    Cancelled,
    GenerationAdvanced,
}

fn clock_with_final_admission_change(
    fixture: &ClockFixture,
    cancellation: &CancellationToken,
    change: FinalAdmissionChange,
) -> Box<dyn FnMut() -> Result<u64, AgentdError> + Send> {
    let state = Arc::clone(&fixture.state);
    let registry = fixture._daemon.registry.clone();
    let agent_id = fixture._daemon.identity.agent_id.clone();
    let cancellation = cancellation.clone();
    let mut initial = true;
    let mut final_change = Some(change);
    Box::new(move || {
        if initial {
            initial = false;
        } else if let Some(change) = final_change.take() {
            match change {
                FinalAdmissionChange::Fenced => state.mark_fenced(),
                FinalAdmissionChange::Draining => state.mark_draining().expect("drain owner"),
                FinalAdmissionChange::Cancelled => cancellation.cancel(),
                FinalAdmissionChange::GenerationAdvanced => {
                    registry
                        .compare_and_transition(&agent_id, 2, AgentLifecycle::Draining)
                        .expect("advance fleet generation");
                }
            }
        }
        Ok(50)
    })
}

#[tokio::test]
async fn parameter_losing_final_admission_preserves_registry_and_anchor_bytes() {
    for change in [
        FinalAdmissionChange::Fenced,
        FinalAdmissionChange::Draining,
        FinalAdmissionChange::Cancelled,
        FinalAdmissionChange::GenerationAdvanced,
    ] {
        let mut fixture = clock_fixture(|| Ok(50));
        let cancellation = CancellationToken::new();
        fixture.owner.clock = clock_with_final_admission_change(&fixture, &cancellation, change);
        let before = persistent_bytes(&fixture.files);
        let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
            Arc::clone(&fixture.state),
            Some(fixture.owner),
            cancellation.clone(),
        );
        assert!(matches!(
            fixture
                .handle
                .propose_parameter(fixture.parameter, 50)
                .await,
            Err(PlasticityRuntimeCallErrorV1::Unavailable)
        ));
        cancellation.cancel();
        owner_task
            .await
            .expect("owner join")
            .expect("owner shutdown");
        assert_eq!(persistent_bytes(&fixture.files), before);
    }
}

#[tokio::test]
async fn topology_losing_final_admission_preserves_registry_and_anchor_bytes() {
    for change in [
        FinalAdmissionChange::Fenced,
        FinalAdmissionChange::Draining,
        FinalAdmissionChange::Cancelled,
        FinalAdmissionChange::GenerationAdvanced,
    ] {
        let mut fixture = clock_fixture(|| Ok(50));
        let cancellation = CancellationToken::new();
        fixture.owner.clock = clock_with_final_admission_change(&fixture, &cancellation, change);
        let before = persistent_bytes(&fixture.files);
        let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
            Arc::clone(&fixture.state),
            Some(fixture.owner),
            cancellation.clone(),
        );
        assert!(matches!(
            fixture.handle.propose_topology(fixture.topology, 50).await,
            Err(PlasticityRuntimeCallErrorV1::Unavailable)
        ));
        cancellation.cancel();
        owner_task
            .await
            .expect("owner join")
            .expect("owner shutdown");
        assert_eq!(persistent_bytes(&fixture.files), before);
    }
}

#[tokio::test]
async fn rejected_expired_parameter_cannot_be_revived_by_cross_request_clock_rollback() {
    let mut fixture = clock_fixture(|| Ok(50));
    let mut samples = [Some(50), None, Some(45), Some(45)].into_iter();
    fixture.owner.clock = Box::new(move || {
        samples
            .next()
            .expect("host clock sample")
            .ok_or_else(|| AgentdError::Protocol("clock unavailable".to_string()))
    });
    fixture.parameter.generator_attestation.expires_at = 49;
    fixture.parameter.generator_attestation.signature = SigningFixture::new().keys[0]
        .sign(&fixture.parameter.generator_attestation.signing_bytes())
        .to_bytes();
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .handle
            .propose_parameter(fixture.parameter.clone(), 45)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Parameter(
            AgentdPlasticityHostErrorV1::Product(
                ParameterPlasticityProductErrorV1::GeneratorEvidence(
                    SignedEvidenceError::ValidityWindow
                )
            )
        ))
    ));
    // A clock failure followed by two requests at 45 must not erase the
    // owner's previous successful observation 50, even after rejected attempts.
    for _ in 0..3 {
        assert!(matches!(
            fixture
                .handle
                .propose_parameter(fixture.parameter.clone(), 45)
                .await,
            Err(PlasticityRuntimeCallErrorV1::ClockUnavailable)
        ));
    }
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[tokio::test]
async fn rejected_revoked_topology_cannot_be_revived_by_cross_request_clock_rollback() {
    let mut fixture = clock_fixture(|| Ok(50));
    let mut samples = [50, 51, 50, 50].into_iter();
    fixture.owner.clock = Box::new(move || Ok(samples.next().expect("host clock sample")));
    let signing = SigningFixture::new();
    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("plasticity-scope"),
        objective_digest: fixture.topology.admission.objective_digest,
        authority_epoch: 7,
        signers: signing
            .principals
            .iter()
            .zip(&signing.keys)
            .enumerate()
            .map(|(index, (principal, key))| TrustedLearningSignerV1 {
                principal: principal.clone(),
                controller_id: id(&format!("plasticity-controller-{index}")),
                verifying_key: key.verifying_key().to_bytes(),
                roles: vec![match index {
                    0 => LearningEvidenceRoleV1::Generator,
                    1 => LearningEvidenceRoleV1::Observer,
                    _ => LearningEvidenceRoleV1::Evaluator,
                }],
                revoked_at: (index == 0).then_some(51),
            })
            .collect(),
    })
    .expect("scheduled revocation verifier");
    for (evidence, key) in [
        (
            &mut fixture.topology.generator_attestation,
            &signing.keys[0],
        ),
        (&mut fixture.topology.observer_attestation, &signing.keys[1]),
        (
            &mut fixture.topology.evaluator_attestation,
            &signing.keys[2],
        ),
    ] {
        evidence.trust_digest = verifier.trust_digest();
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    }
    fixture.owner.verifier = verifier;
    let before = persistent_bytes(&fixture.files);
    let cancellation = CancellationToken::new();
    let owner_task = crate::plasticity_runtime::spawn_plasticity_runtime_v1(
        Arc::clone(&fixture.state),
        Some(fixture.owner),
        cancellation.clone(),
    );
    assert!(matches!(
        fixture
            .handle
            .propose_topology(fixture.topology.clone(), 50)
            .await,
        Err(PlasticityRuntimeCallErrorV1::Topology(
            AgentdTopologyHostErrorV1::Product(
                TopologyPlasticityProductErrorV1::EvaluatorEvidence(SignedEvidenceError::Revoked)
            )
        ))
    ));
    // Revocation was observed only by the final pre-append sample 51. The
    // rejected proposal must still retain that floor when the next clock is 50.
    assert!(matches!(
        fixture.handle.propose_topology(fixture.topology, 50).await,
        Err(PlasticityRuntimeCallErrorV1::ClockUnavailable)
    ));
    cancellation.cancel();
    owner_task
        .await
        .expect("owner join")
        .expect("owner shutdown");
    assert_eq!(persistent_bytes(&fixture.files), before);
}

#[test]
fn cancellation_during_guard_interval_remains_before_final_admission() {
    use crate::plasticity_runtime::FinalPlasticityAdmissionV1;
    use std::cell::RefCell;
    use std::time::Instant;

    thread_local! {
        static CANCELLATION: RefCell<Option<CancellationToken>> = const { RefCell::new(None) };
    }
    fn cancel_during_interval(_: &Instant) -> u128 {
        CANCELLATION.with(|slot| slot.borrow().as_ref().expect("token").cancel());
        0
    }

    let fixture = clock_fixture(|| Ok(50));
    let cancellation = CancellationToken::new();
    CANCELLATION.with(|slot| *slot.borrow_mut() = Some(cancellation.clone()));
    let mut admission = FinalPlasticityAdmissionV1 {
        state: &fixture.state,
        cancellation: &cancellation,
        generation: 2,
        guard: None,
        unavailable: false,
        current_artifacts: fixture.owner.current_artifacts.as_ref(),
        artifacts: &fixture.owner.artifacts,
        baseline: fixture.parameter.admission.baseline_id.clone(),
    };
    let mut floor = None;
    assert!(
        admission
            .observe(&mut || Ok(50), &mut floor, cancel_during_interval)
            .is_err()
    );
    assert!(admission.unavailable);
    assert!(admission.guard.is_none());
    assert_eq!(floor, Some(50));
    assert!(
        fixture
            .state
            .plasticity_admission_ready()
            .expect("guard released")
    );
    CANCELLATION.with(|slot| *slot.borrow_mut() = None);
}
