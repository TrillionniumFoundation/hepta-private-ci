use super::*;
use crate::intelligence_product::evaluation_tests::evidence_fixture;
use codex_hepta_intelligence::build_legal_candidates;
use pretty_assertions::assert_eq;

fn signed_fixture() -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    signed_fixture_with_body_generation(7)
}

fn signed_fixture_with_body_generation(
    body_generation: u64,
) -> (
    Fixture,
    codex_hepta_learning_ledger::ActivatedLearningTrustV1,
) {
    let mut value = fixture();
    let key = SigningKey::from_bytes(&[47; 32]);
    for owner in &mut value.owners {
        if owner.owner_id.as_str() == "learning.eval" {
            owner.key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
        }
    }
    let snapshot = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: snapshot.objective_digest(),
        authority_epoch: snapshot.authority_epoch(),
        body_generation: generation(body_generation),
        configuration_digest: snapshot.configuration_digest(),
        revocation_frontier_digest: snapshot.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .expect("snapshot with real test evaluator key");
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone()).expect("context compilation");
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).expect("legal set");
    let binding = AgentdEvaluationBindingV1 {
        run_id: value.request.run_id.clone(),
        objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = evidence_fixture(&binding, wall_clock_ms().expect("clock"));
    value.inputs.signed_evaluation = Some(signed);
    (value, trust)
}

fn published_fixture_record(
    value: &Fixture,
    generation: u64,
    fence_digest: Digest32,
) -> codex_hepta_learning_ledger::RunStartRecordV1 {
    use codex_hepta_intelligence::ObjectiveRunBindingsV1;
    use codex_hepta_intelligence::compile_and_publish_objective_run_v1;
    use codex_hepta_learning_ledger::DurableRunStartJournal;
    use codex_hepta_learning_ledger::RunStartAuthenticationV1;
    use codex_hepta_learning_ledger::RunStartJournal;

    let mut journal = DurableRunStartJournal::create(
        tempfile::tempfile().expect("RunStart file"),
        digest("canonical-publication-owner"),
        4,
    )
    .expect("RunStart journal");
    compile_and_publish_objective_run_v1(
        &value.inputs.objective_envelope,
        &value.inputs.objective_profile,
        &value.inputs.objective_context,
        ObjectiveRunBindingsV1 {
            authentication: RunStartAuthenticationV1 {
                issuer_id: id("adapter.console"),
                key_epoch: 1,
                message_id: id("message.canonical.lifecycle"),
                sequence: 1,
                expires_at_ms: wall_clock_ms().expect("clock") + 60_000,
                scope_digest: digest("signed-objective-scope"),
                signed_body_digest: digest("signed-objective-body"),
                signature: [7; 64],
            },
            run_id: value.request.run_id.clone(),
            runtime_body_digest: digest("runtime-body"),
            preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompt"),
            artifact_set_digest: digest("artifact"),
            authority_epoch: value.request.snapshot.authority_epoch(),
            generation,
            fence_digest,
            expected_run_start_head: Digest32::ZERO,
        },
        &mut journal,
    )
    .expect("proof-bearing destination publication");
    journal
        .get(&value.request.run_id)
        .expect("read immutable publication")
        .expect("published record")
        .clone()
}

#[test]
fn durable_objective_port_revalidates_admission_and_rejects_changed_identities() {
    let original = fixture();
    let record = published_fixture_record(&original, 7, digest("test-runtime-fence"));
    let port_input = CanonicalPortInputV1 {
        run_id: original.request.run_id.clone(),
        snapshot_digest: original.request.snapshot.digest(),
        objective_digest: record.snapshot.objective_digest,
        candidate_set_digest: digest("candidate-set"),
        predecessor_digest: digest("predecessor"),
        budget_micros: 10_000_000,
        stage: CanonicalStageV1::ObjectiveValidated,
    };
    let mut current = fixture();
    // Request-local clock evidence is checked afresh and must not be mistaken
    // for the old proof's authentication-context identity.
    current.inputs.objective_context.now_unix_micros += 1_000;
    let mut ports = AgentdOwnerPortsV1::new(current.inputs, None);
    ports.objective_publication = Some(
        ObjectivePublicationValidationV1::from_run_start(&record)
            .expect("durable compiled binding"),
    );
    let receipt = ports
        .validate_objective(&port_input)
        .expect("current admission consumes the existing compiled identity");
    assert_eq!(receipt.output_digest, record.snapshot.objective_digest);
    assert!(!receipt.authority.grants_any());

    for mutation in ["source", "profile", "unit", "hard", "revision", "expired"] {
        let mut changed = fixture();
        match mutation {
            "source" => {
                changed
                    .inputs
                    .objective_envelope
                    .structured_intent
                    .provenance
                    .source_digest = digest("different-source");
                changed.inputs.objective_context.source_authentication =
                    ObjectiveSourceAuthenticationV1::Principal {
                        principal_scope_digest: changed
                            .inputs
                            .objective_envelope
                            .principal_scope_digest,
                        source_digest: digest("different-source"),
                    };
            }
            "profile" => {
                changed.inputs.objective_profile.profile_revision = revision(2);
            }
            "unit" => {
                changed.inputs.objective_profile.constraints[0].expected_unit =
                    "milliseconds".to_string();
                changed
                    .inputs
                    .objective_envelope
                    .structured_intent
                    .constraints[0]
                    .unit = "milliseconds".to_string();
            }
            "hard" => {
                changed
                    .inputs
                    .objective_envelope
                    .structured_intent
                    .constraints[0]
                    .bound_q32 += 1;
            }
            "expired" => {
                changed.inputs.objective_context.now_unix_micros += 600_000_000;
            }
            "revision" => {
                changed.inputs.objective_context.revision = revision(8);
            }
            _ => unreachable!("closed mutation cases"),
        }
        changed.inputs.objective_context.selected_profile_digest = changed
            .inputs
            .objective_profile
            .digest()
            .expect("changed profile remains structurally valid");
        changed.inputs.objective_envelope.intent_digest =
            canonical_objective_intent_digest_v1(&changed.inputs.objective_envelope)
                .expect("changed intent has its own canonical digest");
        let mut ports = AgentdOwnerPortsV1::new(changed.inputs, None);
        ports.objective_publication = Some(
            ObjectivePublicationValidationV1::from_run_start(&record)
                .expect("unchanged destination publication"),
        );
        assert!(
            ports.validate_objective(&port_input).is_err(),
            "mutation {mutation}"
        );
    }
    let mut tampered = record.clone();
    tampered.objective_semantic_bytes[0] ^= 1;
    assert!(ObjectivePublicationValidationV1::from_run_start(&tampered).is_err());
    let mut tampered_protocol = record.clone();
    tampered_protocol.objective_function_v1_bytes[0] ^= 1;
    assert!(ObjectivePublicationValidationV1::from_run_start(&tampered_protocol).is_err());
    tampered_protocol.objective_function_v1_digest =
        Digest32::of_bytes(&tampered_protocol.objective_function_v1_bytes);
    assert!(ObjectivePublicationValidationV1::from_run_start(&tampered_protocol).is_err());
    let mut predecessor = record.clone();
    let mut proof_bytes = predecessor
        .admission
        .objective_admission_proof
        .as_ref()
        .expect("persisted proof")
        .canonical_bytes()
        .to_vec();
    let compiler_start = b"hepta.objective.admission-proof.v1".len() + 3 * 32;
    proof_bytes[compiler_start..compiler_start + 32]
        .copy_from_slice(digest("predecessor-compiler-contract").as_array());
    predecessor.admission.objective_admission_proof = Some(
        codex_hepta_learning_ledger::RunStartAdmissionProofV1::from_canonical_bytes(
            &proof_bytes,
            Digest32::of_bytes(&proof_bytes),
        )
        .expect("self-consistent historical predecessor proof"),
    );
    let mut ports = AgentdOwnerPortsV1::new(fixture().inputs, None);
    ports.objective_publication = Some(
        ObjectivePublicationValidationV1::from_run_start(&predecessor)
            .expect("historical bytes remain inspectable"),
    );
    assert!(ports.validate_objective(&port_input).is_err());
    let mut abstained = record;
    abstained.disposition =
        codex_hepta_learning_ledger::RunStartObjectiveDispositionV1::ExplicitAbstain;
    assert!(ObjectivePublicationValidationV1::from_run_start(&abstained).is_err());
}

#[cfg(unix)]
#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn running_lifecycle_generation_preserves_exact_durable_canonical_binding() {
    let (directory, _registry, agentd) =
        crate::state::isolation_tests::fixture().expect("real Running owner");
    let current_generation = agentd.current_generation().expect("live lifecycle");
    assert_eq!(agentd.identity().spawn_generation, 1);
    assert_eq!(current_generation, 2);
    let (value, trust) = signed_fixture_with_body_generation(current_generation);
    let fence_digest = Digest32::from_str(&crate::state::objective_run_fence(
        agentd.identity(),
        current_generation,
    ))
    .expect("live durable fence");
    let record = published_fixture_record(&value, current_generation, fence_digest);
    let authority_file = directory.path().join("canonical-lifecycle-authority.json");
    write_authority_file(
        &authority_file,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let invocation = crate::AgentdIntelligenceInvocationV1 {
        request: value.request,
        inputs: value.inputs,
    };
    invocation
        .validate(agentd.identity(), &record, current_generation)
        .expect("Running is current although its generation differs from spawn");
    assert!(
        invocation
            .validate(
                agentd.identity(),
                &record,
                agentd.identity().spawn_generation
            )
            .is_err()
    );
    let mut mixed = record.clone();
    mixed.snapshot.fence_digest = digest("other-process-fence");
    assert!(
        invocation
            .validate(agentd.identity(), &mixed, current_generation)
            .is_err()
    );
    let composition = RuntimeComposition {
        agent_id: agentd.identity().agent_id.as_str().to_string(),
        supervisor_generation: agentd.identity().spawn_generation,
        agentd_generation: agentd.identity().spawn_generation,
        configuration_digest: digest("runtime-config").to_string(),
        ports_digest: digest("runtime-ports").to_string(),
        max_active_runs: 8,
    };
    assert_eq!(
        composition.agentd_generation,
        agentd.identity().spawn_generation
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(authority_file, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root evaluator trust");
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = runner
        .prepare_for_run_start(&composition, &record, invocation.request, invocation.inputs)
        .await
        .expect("canonical owner preparation")
    else {
        panic!("expected canonical preparation to reach ready");
    };
    let run = prepared.run_snapshot();
    let context = prepared.context_attachment();
    assert_eq!(run.generation, current_generation);
    assert_eq!(run.fence_digest, fence_digest.to_string());
    assert_eq!(
        run.deadline_ms,
        record.admission.deadline_unix_micros / 1_000
    );
    assert_eq!(context.generation, run.generation);
    assert_eq!(context.fence_digest, run.fence_digest);
    assert_eq!(context.deadline_ms, run.deadline_ms);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_evaluation_completes_existing_owner_preparation_and_run_admission() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let mut coordinator = product_test_coordinator();
    let outcome = runner
        .prepare_and_admit(&mut coordinator, value.request, value.inputs)
        .await
        .expect("signed preparation");
    let AgentdIntelligenceAdmittedOutcomeV1::Ready {
        prepared,
        run_receipt,
    } = outcome
    else {
        panic!("expected the signed existing path to reach ready");
    };
    assert!(!prepared.envelope.evaluation_receipt_digest.is_zero());
    assert!(!prepared.envelope.authority.grants_any());
    assert_eq!(run_receipt.run_id, prepared.run_snapshot().run_id);
    assert_eq!(run_receipt.phase, crate::RunPhase::ContextAttached);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn durable_objective_deadline_cannot_be_extended_by_owner_preparation() {
    let (value, trust) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = AgentdIntelligenceProductRunnerV1::new(path.clone(), authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("host-root trust");
    let mut coordinator = product_test_coordinator();
    let AgentdIntelligenceProductOutcomeV1::Ready(mut prepared) = runner
        .prepare(&coordinator, value.request, value.inputs)
        .await
        .expect("real owner preparation")
    else {
        panic!("expected the signed existing path to reach ready");
    };
    let mut expected_snapshot = prepared.run_snapshot();
    let mut expected_attachment = prepared.context_attachment();
    let original_deadline_ms = expected_snapshot.deadline_ms;
    let objective_deadline_ms = original_deadline_ms - 10;
    expected_snapshot.deadline_ms = objective_deadline_ms;
    expected_attachment.deadline_ms = objective_deadline_ms;
    prepared.bind_to_objective_deadline(objective_deadline_ms * 1_000 + 999);
    assert_eq!(prepared.run_snapshot(), expected_snapshot);
    assert_eq!(prepared.context_attachment(), expected_attachment);
    // Repeat the real owner composition with a different computation budget.
    // Its local clock/budget deadline must not replace the durable identity.
    let (mut retry_value, retry_trust) = signed_fixture();
    retry_value.request.budget.total_micros += 1_000_000;
    let retry_runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("retry runner")
        .with_evaluation_trust(retry_trust)
        .expect("retry host-root trust");
    let AgentdIntelligenceProductOutcomeV1::Ready(mut retry) = retry_runner
        .prepare(&coordinator, retry_value.request, retry_value.inputs)
        .await
        .expect("repeated real owner preparation")
    else {
        panic!("expected signed retry preparation to reach ready");
    };
    assert_ne!(retry.run_snapshot().deadline_ms, original_deadline_ms);
    let mut expected_retry_snapshot = retry.run_snapshot();
    let mut expected_retry_attachment = retry.context_attachment();
    expected_retry_snapshot.deadline_ms = objective_deadline_ms;
    expected_retry_attachment.deadline_ms = objective_deadline_ms;
    retry.bind_to_objective_deadline(objective_deadline_ms * 1_000 + 999);
    assert_eq!(retry.run_snapshot(), expected_retry_snapshot);
    assert_eq!(retry.context_attachment(), expected_retry_attachment);
    let snapshot = prepared.run_snapshot();
    assert_eq!(
        coordinator.start_run(
            objective_deadline_ms,
            crate::RunSnapshot {
                run_id: snapshot.run_id,
                request_digest: snapshot.request_digest,
                objective_digest: snapshot.objective_digest,
                body_digest: snapshot.body_digest,
                artifact_set_digest: snapshot.artifact_set_digest,
                authority_epoch: snapshot.authority_epoch,
                generation: snapshot.generation,
                fence_digest: snapshot.fence_digest,
                deadline_ms: snapshot.deadline_ms,
            },
        ),
        Err(crate::AgentRunError::InvalidDeadline),
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn signed_input_cannot_install_host_trust_or_change_actual_context() {
    let (value, _) = signed_fixture();
    let directory = tempfile::tempdir().expect("directory");
    let path = directory.path().join("authority.json");
    write_authority_file(
        &path,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner =
        AgentdIntelligenceProductRunnerV1::new(path.clone(), authority_verifier()).expect("runner");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::InvalidAuthorityVerifier)
    ));

    let (mut value, trust) = signed_fixture();
    value.inputs.context_request.items[0].content_digest = digest("substituted-context");
    let runner = AgentdIntelligenceProductRunnerV1::new(path, authority_verifier())
        .expect("runner")
        .with_evaluation_trust(trust)
        .expect("trust");
    assert!(matches!(
        runner
            .prepare(&product_test_coordinator(), value.request, value.inputs)
            .await,
        Err(AgentdIntelligenceProductError::Canonical(
            CanonicalIntelligenceError::PortFailure {
                stage: CanonicalStageV1::EvaluationAdmitted,
                ..
            }
        ))
    ));
}
