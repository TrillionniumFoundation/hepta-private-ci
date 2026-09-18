use std::collections::BTreeMap;

use codex_hepta_objective::RunStartSnapshotV1;
use codex_hepta_objective::objective_run_publication_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use tempfile::TempDir;

use super::*;

fn digest(value: &str) -> String {
    Digest32::of_bytes(value.as_bytes()).to_string()
}

fn coordinator() -> AgentRunCoordinator {
    AgentRunCoordinator::compose_runtime(RuntimeComposition {
        agent_id: "agent.test".to_string(),
        supervisor_generation: 1,
        agentd_generation: 1,
        configuration_digest: digest("config"),
        ports_digest: digest("ports"),
    })
    .expect("coordinator")
}

fn record(run_id: &str, sequence: u64) -> StoredObjectiveRun {
    let objective_digest = Digest32::of_bytes(format!("objective:{run_id}").as_bytes());
    let hard_constraint_digest = Digest32::of_bytes(format!("hard:{run_id}").as_bytes());
    let preference_state_digest = Digest32::of_bytes(b"preference");
    let model_tuple_digest = Digest32::of_bytes(b"model");
    let prompt_registry_digest = Digest32::of_bytes(b"prompt");
    let artifact_set_digest = Digest32::of_bytes(b"artifact");
    let fence_digest = Digest32::of_bytes(b"fence");
    let snapshot = RunStartSnapshotV1 {
        run_id: StableId::new(run_id).expect("run id"),
        objective_digest,
        hard_constraint_digest,
        preference_state_digest,
        model_tuple_digest,
        prompt_registry_digest,
        artifact_set_digest,
        authority_epoch: 7,
        generation: 9,
        fence_digest,
    };
    let publication_json = format!("{{\"run\":\"{run_id}\"}}");
    StoredObjectiveRun {
        schema_version: STORE_SCHEMA_VERSION,
        issuer_id: "issuer.test".to_string(),
        key_epoch: 1,
        message_id: format!("message.{run_id}"),
        sequence,
        signed_body_digest: digest(&format!("signed:{run_id}")),
        run_id: run_id.to_string(),
        admitted_source_digest: digest(&format!("source:{run_id}")),
        objective_digest: objective_digest.to_string(),
        hard_constraint_digest: hard_constraint_digest.to_string(),
        preference_state_digest: preference_state_digest.to_string(),
        model_tuple_digest: model_tuple_digest.to_string(),
        prompt_registry_digest: prompt_registry_digest.to_string(),
        artifact_set_digest: artifact_set_digest.to_string(),
        authority_epoch: 7,
        generation: 9,
        fence_digest: fence_digest.to_string(),
        runtime_body_digest: digest(&format!("body:{run_id}")),
        deadline_ms: 100_000,
        disposition: "compiled".to_string(),
        run_start_digest: snapshot.semantic_digest().expect("snapshot digest").to_string(),
        publication_digest: objective_run_publication_digest_v1(publication_json.as_bytes()).to_string(),
        publication_json,
    }
}

fn state() -> ObjectiveHostState {
    ObjectiveHostState {
        coordinator: coordinator(),
        highest_sequences: BTreeMap::new(),
    }
}

#[test]
fn durable_objective_commit_is_exactly_idempotent_and_rejects_identity_drift() {
    let temp = TempDir::new().expect("temp");
    prepare_store(temp.path()).expect("store");
    let mut host = state();
    let first = record("run.1", 1);
    let receipt = commit_or_replay(temp.path(), &first, &mut host, 1_000).expect("first");
    assert!(!receipt.idempotent);
    let replay = commit_or_replay(temp.path(), &first, &mut host, 1_000).expect("replay");
    assert!(replay.idempotent);

    let mut changed = first.clone();
    changed.runtime_body_digest = digest("different-body");
    assert!(commit_or_replay(temp.path(), &changed, &mut host, 1_000).is_err());

    let other = record("run.2", 1);
    assert!(commit_or_replay(temp.path(), &other, &mut host, 1_000).is_err());
}

#[test]
fn restart_recovery_restores_replay_frontier_and_active_snapshot() {
    let temp = TempDir::new().expect("temp");
    prepare_store(temp.path()).expect("store");
    let first = record("run.1", 7);
    write_record_atomically(temp.path(), &record_path(temp.path(), &first.run_id), &first)
        .expect("write");

    let mut recovered = state();
    recover_store(temp.path(), 1_000, &mut recovered).expect("recover");
    assert_eq!(
        recovered
            .highest_sequences
            .get(&("issuer.test".to_string(), 1)),
        Some(&7)
    );
    let replay = commit_or_replay(temp.path(), &first, &mut recovered, 1_000).expect("exact replay");
    assert!(replay.idempotent);
    assert!(commit_or_replay(temp.path(), &record("run.2", 7), &mut recovered, 1_000).is_err());
}

#[test]
fn corrupted_publication_or_run_snapshot_is_rejected_on_recovery() {
    let temp = TempDir::new().expect("temp");
    prepare_store(temp.path()).expect("store");
    let mut broken = record("run.1", 1);
    broken.publication_digest = digest("wrong-publication");
    let path = record_path(temp.path(), &broken.run_id);
    let bytes = serde_json::to_vec(&broken).expect("json");
    std::fs::write(&path, bytes).expect("write corrupt fixture");
    let mut recovered = state();
    assert!(recover_store(temp.path(), 1_000, &mut recovered).is_err());
}
