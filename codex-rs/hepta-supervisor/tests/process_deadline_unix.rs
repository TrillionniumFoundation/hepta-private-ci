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
use codex_hepta_supervisor::enforce_process_deadline_v1;
use tempfile::TempDir;

fn owner() -> AgentId {
    AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2cde").expect("valid owner")
}

#[test]
fn real_hanging_child_is_killed_and_observed_exited() {
    let temp = TempDir::new().expect("tempdir");
    let workspace = temp.path().join("workspace");
    let home_root = temp.path().join("home");
    let run_root = temp.path().join("run");
    let logs_root = temp.path().join("logs");
    let fleet_root = temp.path().join("fleet");
    for path in [&workspace, &home_root, &run_root, &logs_root, &fleet_root] {
        std::fs::create_dir_all(path).expect("create process root");
    }

    let mut driver = UnixProcessDriver::new(8).expect("unix driver");
    let spawned = driver
        .spawn(&SpawnSpec {
            agent_id: owner(),
            generation: 1,
            fleet_root,
            workspace,
            home_root,
            run_root: run_root.clone(),
            control_socket: run_root.join("never-created-control.sock"),
            logs_root,
            command: AgentCommand::new("/bin/sleep", vec![OsString::from("60")])
                .expect("bounded command"),
        })
        .expect("spawn real child");
    let mut process = spawned.process;

    let outcome = enforce_process_deadline_v1(
        &mut process,
        ProcessDeadlinePolicyV1::new(Duration::from_millis(25), Duration::from_millis(2), 8)
            .expect("deadline policy"),
    )
    .expect("deadline enforcement");
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
        "SIGKILL must terminate the managed child within the bounded observation window"
    );
}
