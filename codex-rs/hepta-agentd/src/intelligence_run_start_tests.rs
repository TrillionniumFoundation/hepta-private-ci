//! Durable-owner projection tests. AuthBus signature verification itself remains
//! covered by the actual objective ingress tests; this layer cannot authenticate.
use super::*;
use crate::AgentdIntelligenceInvocationV1;
use codex_hepta_intelligence::ObjectiveRunBindingsV1;
use codex_hepta_intelligence::compile_and_publish_objective_run_v1;
use codex_hepta_learning_ledger::DurableRunStartJournal;
use codex_hepta_learning_ledger::RunStartAuthenticationV1;
use codex_hepta_learning_ledger::RunStartRecordV1;

fn durable_inputs() -> (
    Fixture,
    RunStartRecordV1,
    RuntimeComposition,
    tempfile::TempDir,
    AgentdIntelligenceProductRunnerV1,
) {
    let (mut value, _) = signed_fixture();
    let directory = tempfile::tempdir().unwrap();
    let authority = directory.path().join("authority.json");
    let mut composition = product_test_coordinator().composition().clone();
    composition.agent_id = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".to_string();
    composition.agentd_generation = value.request.snapshot.body_generation().get();
    composition.supervisor_generation = composition.agentd_generation;
    let intuition = intuition_support::build(
        value.inputs.intuition.request.clone(),
        value.inputs.intuition.profile.scorer.model_digest,
        &composition.agent_id,
        composition.agentd_generation,
        wall_clock_ms().unwrap(),
    );
    value.inputs.intuition = intuition.input;
    value.intuition_host = intuition.host;
    let mut fence = b"hepta:agentd:objective-fence:v1\0".to_vec();
    fence.extend_from_slice(composition.agent_id.as_bytes());
    fence.extend_from_slice(&composition.agentd_generation.to_be_bytes());
    fence.extend_from_slice(&composition.agentd_generation.to_be_bytes());
    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .open(directory.path().join("run-start.journal"))
        .unwrap();
    let mut journal = DurableRunStartJournal::create(file, digest("run-start-scope"), 16).unwrap();
    let record_id = value.request.run_id.clone();
    compile_and_publish_objective_run_v1(
        &value.inputs.objective_envelope,
        &value.inputs.objective_profile,
        &value.inputs.objective_context,
        ObjectiveRunBindingsV1 {
            authentication: RunStartAuthenticationV1 {
                signed_body_bytes: Vec::new(),
                issuer_id: id("adapter.console"),
                key_epoch: 1,
                message_id: id("message.1"),
                sequence: 1,
                expires_at_ms: NOW_MICROS / 1000 + 60_000,
                scope_digest: digest("scope"),
                signed_body_digest: digest("signed-objective"),
                signature: [1; 64],
            },
            run_id: record_id.clone(),
            runtime_body_digest: value.inputs.neural_tick.body_digest,
            preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model-tuple"),
            prompt_registry_digest: value.inputs.prompt_request.registry_snapshot_digest,
            artifact_set_digest: digest("selected-artifact-set"),
            authority_epoch: value.request.snapshot.authority_epoch(),
            generation: composition.agentd_generation,
            fence_digest: Digest32::of_bytes(&fence),
            expected_run_start_head: Digest32::ZERO,
        },
        &mut journal,
    )
    .unwrap();
    let record = journal.get(&record_id).unwrap().unwrap().clone();
    let old = &value.request.snapshot;
    value.request.snapshot = CanonicalIntelligenceSnapshotV1::admit(CanonicalSnapshotRequestV1 {
        objective_digest: old.objective_digest(),
        authority_epoch: old.authority_epoch(),
        body_generation: old.body_generation(),
        configuration_digest: AgentdIntelligenceInvocationV1::configuration_digest(&record),
        revocation_frontier_digest: old.revocation_frontier_digest(),
        owner_bindings: value.owners.clone(),
    })
    .unwrap();
    value.inputs.context_request.run_snapshot_digest = value.request.snapshot.digest();
    let context = compile(value.inputs.context_request.clone()).unwrap();
    let legal = build_legal_candidates(value.request.legal_candidates.clone()).unwrap();
    let binding = AgentdEvaluationBindingV1 {
        run_id: record_id,
        objective_digest: value.request.snapshot.objective_digest(),
        snapshot_digest: value.request.snapshot.digest(),
        context_receipt_digest: context.context_digest,
        candidate_set_digest: legal.candidate_set_digest,
        selected_candidate_id: id("action.read"),
    };
    let (trust, signed) = evidence_fixture(&binding, wall_clock_ms().unwrap());
    value.inputs.signed_evaluation = Some(signed);
    write_authority_file(
        &authority,
        &value.owners,
        value.request.snapshot.revocation_frontier_digest(),
    );
    let runner = product_runner(authority, &value)
        .with_evaluation_trust(trust)
        .unwrap();
    (value, record, composition, directory, runner)
}

async fn durable_preparation() -> (
    PreparedAgentdIntelligenceRunV1,
    RunStartRecordV1,
    RuntimeComposition,
) {
    let (value, record, composition, _directory, runner) = durable_inputs();
    let outcome = runner
        .prepare_for_composition(&composition, value.request, value.inputs)
        .await
        .unwrap();
    let AgentdIntelligenceProductOutcomeV1::Ready(prepared) = outcome else {
        panic!("seven real owner stages");
    };
    (*prepared, record, composition)
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn canonical_admission_preserves_durable_identity_and_original_deadline() {
    let (mut prepared, record, composition) = durable_preparation().await;
    let now = NOW_MICROS / 1000;
    prepared.bind_revalidated_run_start(&record, now).unwrap();
    let expected = crate::RunSnapshot::from_revalidated_run_start(&record).unwrap();
    assert_eq!(crate::RunSnapshot::from(prepared.run_snapshot()), expected);
    let bound = prepared.clone();
    prepared.bind_revalidated_run_start(&record, now).unwrap();
    assert_eq!(prepared, bound, "binding the same record is idempotent");
    let attachment = prepared.context_attachment();
    assert_eq!(attachment.body_digest, expected.body_digest);
    assert_eq!(attachment.request_digest, expected.request_digest);
    assert_eq!(attachment.artifact_set_digest, expected.artifact_set_digest);
    assert_eq!(attachment.deadline_ms, expected.deadline_ms);
    let mut coordinator = AgentRunCoordinator::compose_runtime(composition).unwrap();
    let admission = coordinator
        .start_revalidated_run_start(now, &record)
        .unwrap();
    let attached = coordinator
        .attach_context(now, admission.revision, attachment.into())
        .unwrap();
    assert_eq!(attached.phase, crate::RunPhase::ContextAttached);
    assert_eq!(attached.deadline_ms, expected.deadline_ms);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn changed_run_start_or_expired_horizon_cannot_rebind_a_prepared_result() {
    let (prepared, record, _) = durable_preparation().await;
    let mut variants = Vec::new();
    let mut changed = record.clone();
    changed.runtime_body_digest = digest("different-body");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.artifact_set_digest = digest("different-artifacts");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.model_tuple_digest = digest("different-model-tuple");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.preference_state_digest = digest("different-preferences");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.prompt_registry_digest = digest("different-registry");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.run_id = id("different-run");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.authority_epoch += 1;
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.generation += 1;
    variants.push(changed);
    let mut changed = record.clone();
    changed.admission.deadline_unix_micros += 1000;
    variants.push(changed);
    let mut changed = record.clone();
    changed.authentication.expires_at_ms += 1;
    variants.push(changed);
    let mut changed = record.clone();
    changed.authentication.signed_body_digest = digest("different-signed-body");
    variants.push(changed);
    let mut changed = record.clone();
    changed.admission.profile_digest = digest("different-profile");
    variants.push(changed);
    let mut changed = record.clone();
    changed.snapshot.fence_digest = digest("different-fence");
    variants.push(changed);
    for changed in variants {
        let mut candidate = prepared.clone();
        assert!(
            candidate
                .bind_revalidated_run_start(&changed, NOW_MICROS / 1000)
                .is_err()
        );
        assert_eq!(
            candidate, prepared,
            "reject before changing live run/context identity"
        );
    }
    let mut candidate = prepared.clone();
    let expired = crate::RunSnapshot::from_revalidated_run_start(&record)
        .unwrap()
        .deadline_ms;
    assert!(
        candidate
            .bind_revalidated_run_start(&record, expired)
            .is_err()
    );
    assert_eq!(candidate, prepared);
}

#[path = "intelligence_invocation_owner_tests.rs"]
mod intelligence_ingress;
