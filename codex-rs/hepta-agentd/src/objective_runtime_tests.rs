use std::fs::OpenOptions;

use codex_hepta_learning_ledger::RunStartAdmissionBindingV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use tempfile::TempDir;

use super::*;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn record(
    run_id: &str,
    sequence: u64,
    disposition: RunStartObjectiveDispositionV1,
) -> RunStartRecordV1 {
    let objective = format!("objective:{run_id}").into_bytes();
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            issuer_id: id("issuer.objective"),
            key_epoch: 1,
            message_id: id(&format!("message.{run_id}")),
            sequence,
            expires_at_ms: 9_999_999,
            scope_digest: digest("scope"),
            signed_body_digest: digest(&format!("signed:{run_id}")),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_digest: digest("profile"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest(&format!("source:{run_id}")),
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 100_000_000,
        },
        disposition,
        snapshot: RunStartSnapshotV1 {
            run_id: id(run_id),
            objective_digest: Digest32::of_bytes(&objective),
            hard_constraint_digest: digest(&format!("hard:{run_id}")),
            preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model"),
            prompt_registry_digest: digest("prompt"),
            artifact_set_digest: digest("artifact"),
            authority_epoch: 7,
            generation: 3,
            fence_digest: digest("fence"),
        },
        runtime_body_digest: digest(&format!("body:{run_id}")),
        objective_semantic_bytes: objective,
    }
}

fn state_with(record: RunStartRecordV1) -> (TempDir, ObjectiveHostState) {
    let temp = TempDir::new().expect("temp");
    let path = temp.path().join("journal");
    let file = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(path)
        .expect("journal");
    let mut journal =
        DurableRunStartJournal::create(file, digest("binding"), 16).expect("create journal");
    journal
        .append(Digest32::ZERO, record)
        .expect("append record");
    let highest_sequences = replay_frontier(&journal).expect("frontier");
    (
        temp,
        ObjectiveHostState {
            journal,
            coordinator_generation: None,
            coordinator: None,
            highest_sequences,
        },
    )
}

#[test]
fn durable_authentication_frontier_allows_only_exact_replay() {
    let first = record("run.1", 7, RunStartObjectiveDispositionV1::Compiled);
    let (_temp, state) = state_with(first.clone());
    assert!(
        require_replay_admission(&state, &first.authentication, &first.snapshot.run_id).is_ok()
    );

    let other = record("run.2", 7, RunStartObjectiveDispositionV1::Compiled);
    assert!(
        require_replay_admission(&state, &other.authentication, &other.snapshot.run_id).is_err()
    );

    let newer = record("run.2", 8, RunStartObjectiveDispositionV1::Compiled);
    assert!(
        require_replay_admission(&state, &newer.authentication, &newer.snapshot.run_id).is_ok()
    );
}

#[test]
fn runtime_consumes_compiled_record_but_not_explicit_abstain() {
    let fence = digest("fence");
    let mut coordinator = AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 3,
        agentd_generation: 3,
        configuration_digest: digest("config").to_string(),
        ports_digest: digest("ports").to_string(),
        fence_digest: fence.to_string(),
    })
    .expect("coordinator");

    let compiled = record("run.1", 1, RunStartObjectiveDispositionV1::Compiled);
    ensure_runtime_record(&mut coordinator, &compiled, 1).expect("compiled run");
    assert!(coordinator.run("run.1").is_some());

    let abstain = record("run.2", 2, RunStartObjectiveDispositionV1::ExplicitAbstain);
    ensure_runtime_record(&mut coordinator, &abstain, 1).expect("abstain");
    assert!(coordinator.run("run.2").is_none());
}