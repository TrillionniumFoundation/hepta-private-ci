#![cfg(target_os = "linux")]
//! Real child-process crashes/OS locks on one host; NOT a multi-host qualification.
#[path = "../examples/memory_cell_lab/faults.rs"]
mod faults;
use faults::Crash;
use faults::LabNode;
use faults::Operation;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::process::ExitStatus;
use std::process::Stdio;

struct Fixture(PathBuf);
impl Fixture {
    fn new(name: &str) -> Self {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hepta-cell-{name}-{}-{nonce}", std::process::id()));
        LabNode::bootstrap(&root)
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
        Self(root)
    }
    fn node(&self) -> LabNode {
        LabNode::open(&self.0)
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn worker(root: &Path, operation: &str, fault: &str) -> Command {
    let mut cmd = Command::new("flock");
    cmd.arg("-w")
        .arg("10")
        .arg(root.join("writer.lock"))
        .arg(
            std::env::current_exe()
                .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}")),
        )
        .args(["--exact", "node_worker", "--ignored", "--nocapture"])
        .env("MCELL_NODE", root)
        .env("MCELL_OPERATION", operation)
        .env("MCELL_FAULT", fault)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    cmd
}
fn run(root: &Path, operation: &str, fault: &str) -> ExitStatus {
    worker(root, operation, fault)
        .status()
        .unwrap_or_else(|error| panic!("Linux flock and child-process execution required: {error}"))
}

#[test]
fn duplicate_delivery_and_conflicting_payload_survive_reopen() {
    let f = Fixture::new("dedup");
    let first = "publish~op1~1~0~a~r1~-";
    assert!(run(&f.0, first, "never").success());
    let before = f
        .node()
        .read()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(run(&f.0, first, "never").success());
    assert_eq!(
        before,
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
    );
    assert!(!run(&f.0, "publish~op1~1~0~different~r1~-", "never").success());
    assert_eq!(
        before,
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
    );
}

#[test]
fn two_processes_cannot_commit_one_checkpoint_twice() {
    let f = Fixture::new("cas");
    let mut a = worker(&f.0, "publish~op1~1~0~a~r1~-", "never")
        .spawn()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    let mut b = worker(&f.0, "publish~op2~1~0~b~r2~-", "never")
        .spawn()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    let successes = usize::from(
        a.wait()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
            .success(),
    ) + usize::from(
        b.wait()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
            .success(),
    );
    assert_eq!(successes, 1);
    let state = f
        .node()
        .read()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert_eq!(
        (
            state.revision,
            state.operations.len(),
            state.artifacts.len()
        ),
        (1, 1, 1)
    );
}

#[test]
fn split_crashes_leave_old_or_complete_new_graph_and_ack_loss_is_idempotent() {
    let f = Fixture::new("split");
    assert!(run(&f.0, "publish~op1~1~0~parent~r1~-", "never").success());
    let old = f
        .node()
        .read()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    let prepare = "prepare-split~op2~1~1~left,right~-~parent";
    assert_eq!(run(&f.0, prepare, "before").code(), Some(86));
    assert_eq!(
        old,
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
    );
    assert_eq!(run(&f.0, prepare, "after").code(), Some(87));
    let prepared = f
        .node()
        .read()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert_eq!(prepared.active, old.active);
    assert_eq!(prepared.graph_generation, old.graph_generation);
    let commit = "commit-split~op3~1~2~-~-~-";
    assert_eq!(run(&f.0, commit, "after").code(), Some(87));
    let complete = f
        .node()
        .read()
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert_eq!(
        complete.active,
        ["left".into(), "right".into()].into_iter().collect()
    );
    assert_eq!(complete.graph_generation, 2);
    assert!(run(&f.0, commit, "never").success());
    assert_eq!(
        complete,
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
    );
}

#[test]
fn revocation_between_prepare_and_commit_blocks_update_and_stale_restore() {
    let f = Fixture::new("revoke");
    assert!(run(&f.0, "publish~op1~1~0~parent~r1~-", "never").success());
    assert!(run(&f.0, "prepare-split~op2~1~1~left,right~r2~parent", "never").success());
    let backup = fs::read(f.0.join("snapshot"))
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    f.node()
        .revoke(1, "r1")
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(!run(&f.0, "commit-split~op3~1~2~-~-~-", "never").success());
    assert!(f.node().read().is_err());
    fs::write(f.0.join("snapshot"), backup)
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(f.node().read().is_err());
    assert!(!run(&f.0, "publish~op4~1~2~distilled~r3~left", "never").success());
}

#[test]
fn descendant_union_prevents_distillation_from_severing_revocation() {
    let f = Fixture::new("lineage");
    assert!(run(&f.0, "publish~op1~1~0~a~r1~-", "never").success());
    assert!(run(&f.0, "publish~op2~1~1~b~r2~a", "never").success());
    assert!(run(&f.0, "publish~op3~1~2~c~r3~b", "never").success());
    assert_eq!(
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
            .artifacts["c"]
            .roots
            .len(),
        3
    );
    f.node()
        .revoke(1, "r1")
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(f.node().read().is_err());
}

#[test]
fn migration_fences_offline_writer_and_interrupted_handoff_fails_closed() {
    let f = Fixture::new("migrate");
    assert!(run(&f.0, "publish~op1~1~0~a~r1~-", "never").success());
    let backup = fs::read(f.0.join("snapshot"))
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    f.node()
        .migrate(1)
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(!run(&f.0, "publish~op2~1~1~b~r2~-", "never").success());
    fs::write(f.0.join("snapshot"), backup)
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(f.node().read().is_err());
    f.node()
        .reconcile_migration(2)
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(run(&f.0, "publish~op2~2~1~b~r2~-", "never").success());
    assert_eq!(
        f.node()
            .read()
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
            .epoch,
        2
    );
}

#[test]
fn corrupt_snapshot_and_unknown_commands_fail_closed() {
    let f = Fixture::new("corrupt");
    fs::write(f.0.join("snapshot"), "partial\n")
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    assert!(f.node().read().is_err());
    assert!(Operation::parse("execute~op~1~0~a~r~-").is_err());
    assert!(Operation::parse("publish~op~1~0~../escape~r~-").is_err());
}

#[test]
#[ignore = "executed by parent tests under a real OS flock in child processes"]
fn node_worker() {
    let root = PathBuf::from(
        std::env::var("MCELL_NODE")
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}")),
    );
    let operation = Operation::parse(
        &std::env::var("MCELL_OPERATION")
            .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}")),
    )
    .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"));
    let crash = match std::env::var("MCELL_FAULT")
        .unwrap_or_else(|error| panic!("memory-cell fixture failed: {error}"))
        .as_str()
    {
        "never" => Crash::Never,
        "before" => Crash::BeforePublish,
        "after" => Crash::AfterPublish,
        _ => panic!("unknown fault"),
    };
    if LabNode::open(&root).apply(&operation, crash).is_err() {
        std::process::exit(3);
    }
}
