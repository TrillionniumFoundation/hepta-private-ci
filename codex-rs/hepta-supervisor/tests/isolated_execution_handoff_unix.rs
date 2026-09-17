#![cfg(target_os = "linux")]

use std::ffi::OsString;
use std::thread;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDeadlineOutcomeV1;
use codex_hepta_supervisor::ProcessDeadlinePolicyV1;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::UnixProcessDriver;
use codex_hepta_supervisor::WriterHandoffCheckpointV1;
use codex_hepta_supervisor::WriterHandoffPhaseV1;
use codex_hepta_supervisor::WriterHandoffPlanV1;
use codex_hepta_supervisor::WriterResultFenceErrorV1;
use codex_hepta_supervisor::enforce_process_deadline_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use tempfile::TempDir;

fn owner() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cde").expect("valid owner")
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn checkpoint(phase: WriterHandoffPhaseV1) -> WriterHandoffCheckpointV1 {
    WriterHandoffCheckpointV1 {
        plan: WriterHandoffPlanV1 {
            operation_id: id("isolated.handoff"),
            domain_id: id("organ.isolated.domain"),
            source_writer: id("organ.writer.old"),
            target_writer: id("organ.writer.new"),
            old_generation: Generation::new(1).expect("old generation"),
            new_generation: Generation::new(2).expect("new generation"),
            authority_epoch: 11,
            migration_plan_digest: Digest32::of_bytes(b"migration"),
            schema_digest: Digest32::of_bytes(b"schema"),
            rollback_predecessor_digest: Digest32::of_bytes(b"rollback"),
        },
        revision: 1,
        phase,
        outbox_watermark: None,
        unknown_effect_count: 0,
        evidence_digest: Digest32::of_bytes(b"evidence"),
        previous_receipt_digest: Digest32::ZERO,
        receipt_digest: Digest32::of_bytes(b"receipt"),
    }
}

#[test]
fn repeated_hanging_isolated_generations_are_killed_and_old_results_stay_fenced() {
    let temp = TempDir::new().expect("tempdir");
    let workspace = temp.path().join("workspace");
    let home_root = temp.path().join("home");
    let run_root = temp.path().join("run");
    let logs_root = temp.path().join("logs");
    let fleet_root = temp.path().join("fleet");
    for path in [&workspace, &home_root, &run_root, &logs_root, &fleet_root] {
        std::fs::create_dir_all(path).expect("create process root");
    }

    let old_checkpoint = checkpoint(WriterHandoffPhaseV1::Prepared);
    let old_result = old_checkpoint
        .issue_old_result_fence()
        .expect("old generation admits work before drain");

    let policy =
        ProcessDeadlinePolicyV1::new(Duration::from_millis(25), Duration::from_millis(2), 8)
            .expect("deadline policy");
    let mut driver = UnixProcessDriver::new(8).expect("unix driver");

    for generation in 1..=3 {
        let generation_run_root = run_root.join(format!("generation-{generation}"));
        std::fs::create_dir_all(&generation_run_root).expect("create generation run root");
        let spawned = driver
            .spawn(&SpawnSpec {
                agent_id: owner(),
                generation,
                fleet_root: fleet_root.clone(),
                workspace: workspace.clone(),
                home_root: home_root.clone(),
                run_root: generation_run_root.clone(),
                control_socket: generation_run_root.join("never-created-control.sock"),
                logs_root: logs_root.clone(),
                command: AgentCommand::new("/bin/sleep", vec![OsString::from("60")])
                    .expect("bounded command"),
            })
            .expect("spawn isolated hanging child");
        let mut process = spawned.process;

        let outcome = enforce_process_deadline_v1(&mut process, policy.clone())
            .expect("enforce isolated deadline");
        assert_eq!(outcome, ProcessDeadlineOutcomeV1::KillRequestedAtDeadline);

        let mut exited = false;
        for _ in 0..100 {
            if matches!(
                process.poll(8).expect("poll after kill").state,
                ProcessState::Exited(_)
            ) {
                exited = true;
                break;
            }
            thread::sleep(Duration::from_millis(2));
        }
        assert!(
            exited,
            "a hanging isolated generation must terminate before the next generation is exercised"
        );
    }

    let drained = checkpoint(WriterHandoffPhaseV1::Drained);
    assert_eq!(
        drained.validate_result_fence(&old_result),
        Err(WriterResultFenceErrorV1::AdmissionClosed),
        "a late old-generation result cannot regain authority after drain"
    );

    let published = checkpoint(WriterHandoffPhaseV1::RoutePublished);
    let new_result = published
        .issue_new_result_fence()
        .expect("published successor admits work");
    published
        .validate_result_fence(&new_result)
        .expect("current generation result remains admissible");
}
