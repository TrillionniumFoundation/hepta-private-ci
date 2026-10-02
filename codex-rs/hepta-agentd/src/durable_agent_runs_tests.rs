use super::*;
use tempfile::TempDir;

fn composition() -> RuntimeComposition {
    RuntimeComposition {
        agent_id: "agent.1".into(),
        supervisor_generation: 7,
        agentd_generation: 7,
        configuration_digest: "1".repeat(64),
        ports_digest: "2".repeat(64),
        max_active_runs: 4,
    }
}
fn snapshot() -> RunSnapshot {
    RunSnapshot {
        run_id: "run.1".into(),
        request_digest: "3".repeat(64),
        objective_digest: "4".repeat(64),
        body_digest: "5".repeat(64),
        artifact_set_digest: "6".repeat(64),
        authority_epoch: 1,
        generation: 8,
        fence_digest: "7".repeat(64),
        deadline_ms: 10_000,
    }
}
fn attach(s: &RunSnapshot) -> ContextAttachment {
    ContextAttachment {
        run_id: s.run_id.clone(),
        request_digest: s.request_digest.clone(),
        objective_digest: s.objective_digest.clone(),
        body_digest: s.body_digest.clone(),
        artifact_set_digest: s.artifact_set_digest.clone(),
        authority_epoch: s.authority_epoch,
        generation: s.generation,
        fence_digest: s.fence_digest.clone(),
        deadline_ms: s.deadline_ms,
        context_digest: "8".repeat(64),
        compilation_receipt_digest: "9".repeat(64),
    }
}
fn dispatch(owner: &mut DurableAgentRunCoordinator) -> RunReceipt {
    let s = snapshot();
    let admitted = owner.start_run(1, s.clone()).unwrap();
    let attached = owner
        .attach_context(2, admitted.revision, attach(&s))
        .unwrap();
    owner
        .mark_dispatched(3, &s.run_id, attached.revision)
        .unwrap()
}
#[test]
fn dispatched_reopen_becomes_indeterminate_and_cannot_redispatch() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    let prior = dispatch(&mut owner);
    drop(owner);
    let mut reopened = DurableAgentRunCoordinator::open(composition(), path).unwrap();
    let current = reopened.run("run.1").unwrap().unwrap();
    assert_eq!(current.phase, RunPhase::Indeterminate);
    assert_eq!(current.revision, prior.revision + 1);
    assert!(
        reopened
            .mark_dispatched(4, "run.1", current.revision)
            .is_err()
    );
}
#[test]
fn closed_identity_survives_release_and_reopen_without_resurrection() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    let sent = dispatch(&mut owner);
    let done = owner
        .observe_terminal("run.1", sent.revision, RunPhase::Succeeded, true)
        .unwrap();
    owner.remove_closed_run("run.1", done.revision).unwrap();
    drop(owner);
    let mut reopened = DurableAgentRunCoordinator::open(composition(), path).unwrap();
    let retried = reopened.start_run(5, snapshot()).unwrap();
    assert_eq!(retried.phase, RunPhase::Succeeded);
    assert!(retried.idempotent);
    let mut drift = snapshot();
    drift.body_digest = "a".repeat(64);
    assert_eq!(reopened.start_run(5, drift), Err(AgentRunError::Conflict));
}
#[test]
fn reducer_error_cannot_publish_partial_memory_or_disk_state() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    dispatch(&mut owner);
    let before = serde_json::to_vec(&owner.image).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    assert!(owner.begin_drain(u64::MAX, "overflow").is_err());
    assert_eq!(serde_json::to_vec(&owner.image).unwrap(), before);
    assert_eq!(std::fs::read(path).unwrap(), bytes);
}
#[test]
fn truncated_cached_ack_poison_survives_byte_restoration() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    owner.start_run(1, snapshot()).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    std::fs::write(&path, b"").unwrap();
    assert!(owner.start_run(2, snapshot()).is_err());
    std::fs::write(&path, bytes).unwrap();
    assert!(owner.start_run(2, snapshot()).is_err());
    drop(owner);
    assert!(DurableAgentRunCoordinator::open(composition(), path).is_ok());
}
#[test]
fn stable_lifetime_lock_prevents_a_second_writer() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    assert!(DurableAgentRunCoordinator::open(composition(), path.clone()).is_err());
    drop(owner);
    assert!(DurableAgentRunCoordinator::open(composition(), path).is_ok());
}
#[test]
fn changed_generation_requires_independent_restart_evidence() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    drop(DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap());
    let mut next = composition();
    next.agentd_generation += 1;
    next.supervisor_generation += 1;
    assert!(DurableAgentRunCoordinator::open(next, path).is_err());
}
#[cfg(unix)]
#[test]
fn identical_inode_replacement_is_not_a_retained_cut() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    let replacement = dir.path().join("replacement");
    std::fs::copy(&path, &replacement).unwrap();
    std::fs::rename(replacement, &path).unwrap();
    assert!(owner.start_run(1, snapshot()).is_err());
}
#[test]
fn malformed_semantic_snapshot_is_rejected_before_replay() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    dispatch(&mut owner);
    let mut invalid = owner.image.clone();
    invalid.state.runs.get_mut("run.1").unwrap().context_digest = None;
    drop(owner);
    std::fs::write(&path, serde_json::to_vec(&invalid).unwrap()).unwrap();
    assert!(DurableAgentRunCoordinator::open(composition(), path).is_err());
}

#[test]
fn process_loss_after_dispatch_recovers_without_a_send_permit() {
    const CHILD: &str = "HEPTA_RUN_STORE_CRASH_CHILD";
    if let Some(path) = std::env::var_os(CHILD) {
        let mut owner =
            DurableAgentRunCoordinator::open(composition(), PathBuf::from(path)).unwrap();
        dispatch(&mut owner);
        std::process::exit(33);
    }
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let result=std::process::Command::new(std::env::current_exe().unwrap())
        .args(["--exact","lane_b_runtime::durable::tests::process_loss_after_dispatch_recovers_without_a_send_permit","--nocapture"])
        .env(CHILD,&path).output().unwrap();
    assert_eq!(
        result.status.code(),
        Some(33),
        "child output: {}",
        String::from_utf8_lossy(&result.stderr)
    );
    let mut owner = DurableAgentRunCoordinator::open(composition(), path).unwrap();
    let status = owner.run("run.1").unwrap().unwrap();
    assert_eq!(status.phase, RunPhase::Indeterminate);
    assert!(owner.mark_dispatched(5, "run.1", status.revision).is_err());
}

#[cfg(unix)]
#[test]
fn permission_drift_invalidates_cached_status_and_acknowledgements() {
    use std::os::unix::fs::PermissionsExt;
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    owner.start_run(1, snapshot()).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(owner.run("run.1").is_err());
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600)).unwrap();
    assert!(owner.start_run(2, snapshot()).is_err());
}

#[test]
fn deleted_live_image_is_not_recreated_to_acknowledge_cached_state() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    owner.start_run(1, snapshot()).unwrap();
    std::fs::remove_file(&path).unwrap();
    assert!(owner.start_run(2, snapshot()).is_err());
    assert!(!path.exists());
}

const PERSISTENCE_CUTS: [&str; 8] = [
    "before_write",
    "after_write",
    "before_flush",
    "before_sync",
    "before_rename",
    "after_rename",
    "after_parent_sync",
    "after_install",
];

#[test]
fn every_persistence_error_denies_ack_and_keeps_memory_unpublished() {
    for cut in PERSISTENCE_CUTS {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("runs.json");
        let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
        let s = snapshot();
        let admitted = owner.start_run(1, s.clone()).unwrap();
        let attached = owner
            .attach_context(2, admitted.revision, attach(&s))
            .unwrap();
        let before = serde_json::to_vec(&owner.image).unwrap();
        owner.file.fail_at(cut, file::FaultAction::Error);
        assert!(
            owner
                .mark_dispatched(3, "run.1", attached.revision)
                .is_err(),
            "{cut}"
        );
        assert_eq!(serde_json::to_vec(&owner.image).unwrap(), before, "{cut}");
        assert!(owner.run("run.1").is_err(), "{cut}");
        assert!(
            owner
                .mark_dispatched(3, "run.1", attached.revision)
                .is_err(),
            "{cut}"
        );
        drop(owner);
        let mut recovered = DurableAgentRunCoordinator::open(composition(), path).unwrap();
        let phase = recovered.run("run.1").unwrap().unwrap().phase;
        let expected = if ["after_rename", "after_parent_sync", "after_install"].contains(&cut) {
            RunPhase::Indeterminate
        } else {
            RunPhase::ContextAttached
        };
        assert_eq!(phase, expected, "{cut}");
    }
}

#[test]
fn process_loss_at_each_pre_ack_persistence_cut_recovers_one_complete_state() {
    const CHILD: &str = "HEPTA_RUN_STORE_PRE_ACK_CHILD";
    if let Some(path) = std::env::var_os(CHILD) {
        let name = std::env::var("HEPTA_RUN_STORE_PRE_ACK_CUT").unwrap();
        let cut = PERSISTENCE_CUTS
            .into_iter()
            .find(|cut| *cut == name)
            .unwrap();
        let mut owner =
            DurableAgentRunCoordinator::open(composition(), PathBuf::from(path)).unwrap();
        let s = snapshot();
        let admitted = owner.start_run(1, s.clone()).unwrap();
        let attached = owner
            .attach_context(2, admitted.revision, attach(&s))
            .unwrap();
        owner.file.fail_at(cut, file::FaultAction::Crash);
        let _ = owner.mark_dispatched(3, "run.1", attached.revision);
        panic!("pre-ACK crash hook was not reached");
    }
    for cut in PERSISTENCE_CUTS {
        let dir = TempDir::new().unwrap();
        let path = dir.path().join("runs.json");
        let result=std::process::Command::new(std::env::current_exe().unwrap())
            .args(["--exact","lane_b_runtime::durable::tests::process_loss_at_each_pre_ack_persistence_cut_recovers_one_complete_state","--nocapture"])
            .env(CHILD,&path).env("HEPTA_RUN_STORE_PRE_ACK_CUT",cut).output().unwrap();
        assert_eq!(
            result.status.code(),
            Some(37),
            "{cut}: {}",
            String::from_utf8_lossy(&result.stderr)
        );
        let mut owner = DurableAgentRunCoordinator::open(composition(), path).unwrap();
        let phase = owner.run("run.1").unwrap().unwrap().phase;
        let expected = if ["after_rename", "after_parent_sync", "after_install"].contains(&cut) {
            RunPhase::Indeterminate
        } else {
            RunPhase::ContextAttached
        };
        assert_eq!(phase, expected, "{cut}");
    }
}

#[test]
fn missing_image_after_owner_exit_cannot_reset_acknowledged_history() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    owner.start_run(1, snapshot()).unwrap();
    drop(owner);
    std::fs::remove_file(&path).unwrap();
    assert!(DurableAgentRunCoordinator::open(composition(), path.clone()).is_err());
    assert!(!path.exists());
}

#[test]
fn one_uninspected_pending_slot_blocks_writes_without_storage_growth() {
    let dir = TempDir::new().unwrap();
    let path = dir.path().join("runs.json");
    let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
    let s = snapshot();
    let admitted = owner.start_run(1, s.clone()).unwrap();
    owner
        .file
        .fail_at("before_rename", file::FaultAction::Error);
    assert!(
        owner
            .attach_context(2, admitted.revision, attach(&s))
            .is_err()
    );
    drop(owner);
    let pending = path.with_extension("pending");
    let bytes = std::fs::read(&pending).unwrap();
    for _ in 0..3 {
        let mut owner = DurableAgentRunCoordinator::open(composition(), path.clone()).unwrap();
        assert_eq!(
            owner.run("run.1").unwrap().unwrap().phase,
            RunPhase::Admitted
        );
        assert!(
            owner
                .attach_context(2, admitted.revision, attach(&s))
                .is_err()
        );
        assert_eq!(std::fs::read(&pending).unwrap(), bytes);
        assert_eq!(std::fs::read_dir(dir.path()).unwrap().count(), 3);
    }
}
