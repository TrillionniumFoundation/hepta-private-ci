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
    fn new(name: &str) -> Result<Self, String> {
        let nonce = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|error| error.to_string())?
            .as_nanos();
        let root =
            std::env::temp_dir().join(format!("hepta-cell-{name}-{}-{nonce}", std::process::id()));
        LabNode::bootstrap(&root)?;
        Ok(Self(root))
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

fn worker(root: &Path, operation: &str, fault: &str) -> Result<Command, String> {
    let mut cmd = Command::new("flock");
    cmd.arg("-w")
        .arg("10")
        .arg(root.join("writer.lock"))
        .arg(std::env::current_exe().map_err(|error| error.to_string())?)
        .args(["--exact", "node_worker", "--ignored", "--nocapture"])
        .env("MCELL_NODE", root)
        .env("MCELL_OPERATION", operation)
        .env("MCELL_FAULT", fault)
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    Ok(cmd)
}
fn run(root: &Path, operation: &str, fault: &str) -> Result<ExitStatus, String> {
    worker(root, operation, fault)?
        .status()
        .map_err(|error| error.to_string())
}

#[test]
fn duplicate_delivery_and_conflicting_payload_survive_reopen() -> Result<(), String> {
    let f = Fixture::new("dedup")?;
    let first = "publish~op1~1~0~a~r1~-";
    assert!(run(&f.0, first, "never")?.success());
    let before = f.node().read().unwrap();
    assert!(run(&f.0, first, "never")?.success());
    assert_eq!(before, f.node().read().unwrap());
    assert!(!run(&f.0, "publish~op1~1~0~different~r1~-", "never")?.success());
    assert_eq!(before, f.node().read().unwrap());
    Ok(())
}

#[test]
fn two_processes_cannot_commit_one_checkpoint_twice() -> Result<(), String> {
    let f = Fixture::new("cas")?;
    let mut a = worker(&f.0, "publish~op1~1~0~a~r1~-", "never")?
        .spawn()
        .map_err(|error| error.to_string())?;
    let mut b = match worker(&f.0, "publish~op2~1~0~b~r2~-", "never")
        .and_then(|mut command| command.spawn().map_err(|error| error.to_string()))
    {
        Ok(child) => child,
        Err(error) => {
            let _ = a.kill();
            let _ = a.wait();
            return Err(error);
        }
    };
    let a_status = a.wait();
    let b_status = b.wait();
    let successes = usize::from(a_status.map_err(|error| error.to_string())?.success())
        + usize::from(b_status.map_err(|error| error.to_string())?.success());
    assert_eq!(successes, 1);
    let state = f.node().read().unwrap();
    assert_eq!(
        (
            state.revision,
            state.operations.len(),
            state.artifacts.len()
        ),
        (1, 1, 1)
    );
    Ok(())
}

#[test]
fn split_crashes_leave_old_or_complete_new_graph_and_ack_loss_is_idempotent() -> Result<(), String>
{
    let f = Fixture::new("split")?;
    assert!(run(&f.0, "publish~op1~1~0~parent~r1~-", "never")?.success());
    let old = f.node().read().unwrap();
    let prepare = "prepare-split~op2~1~1~left,right~-~parent";
    assert_eq!(run(&f.0, prepare, "before")?.code(), Some(86));
    assert_eq!(old, f.node().read().unwrap());
    assert_eq!(run(&f.0, prepare, "after")?.code(), Some(87));
    let prepared = f.node().read().unwrap();
    assert_eq!(prepared.active, old.active);
    assert_eq!(prepared.graph_generation, old.graph_generation);
    let commit = "commit-split~op3~1~2~-~-~-";
    assert_eq!(run(&f.0, commit, "after")?.code(), Some(87));
    let complete = f.node().read().unwrap();
    assert_eq!(
        complete.active,
        ["left".into(), "right".into()].into_iter().collect()
    );
    assert_eq!(complete.graph_generation, 2);
    assert!(run(&f.0, commit, "never")?.success());
    assert_eq!(complete, f.node().read().unwrap());
    Ok(())
}

#[test]
fn revocation_between_prepare_and_commit_blocks_update_and_stale_restore() -> Result<(), String> {
    let f = Fixture::new("revoke")?;
    assert!(run(&f.0, "publish~op1~1~0~parent~r1~-", "never")?.success());
    assert!(run(&f.0, "prepare-split~op2~1~1~left,right~r2~parent", "never")?.success());
    let backup = fs::read(f.0.join("snapshot")).unwrap();
    f.node().revoke(1, "r1").unwrap();
    assert!(!run(&f.0, "commit-split~op3~1~2~-~-~-", "never")?.success());
    assert!(f.node().read().is_err());
    fs::write(f.0.join("snapshot"), backup).unwrap();
    assert!(f.node().read().is_err());
    assert!(!run(&f.0, "publish~op4~1~2~distilled~r3~left", "never")?.success());
    Ok(())
}

#[test]
fn descendant_union_prevents_distillation_from_severing_revocation() -> Result<(), String> {
    let f = Fixture::new("lineage")?;
    assert!(run(&f.0, "publish~op1~1~0~a~r1~-", "never")?.success());
    assert!(run(&f.0, "publish~op2~1~1~b~r2~a", "never")?.success());
    assert!(run(&f.0, "publish~op3~1~2~c~r3~b", "never")?.success());
    assert_eq!(f.node().read().unwrap().artifacts["c"].roots.len(), 3);
    f.node().revoke(1, "r1").unwrap();
    assert!(f.node().read().is_err());
    Ok(())
}

#[test]
fn migration_fences_offline_writer_and_interrupted_handoff_fails_closed() -> Result<(), String> {
    let f = Fixture::new("migrate")?;
    assert!(run(&f.0, "publish~op1~1~0~a~r1~-", "never")?.success());
    let backup = fs::read(f.0.join("snapshot")).unwrap();
    f.node().migrate(1).unwrap();
    assert!(!run(&f.0, "publish~op2~1~1~b~r2~-", "never")?.success());
    fs::write(f.0.join("snapshot"), backup).unwrap();
    assert!(f.node().read().is_err());
    f.node().reconcile_migration(2).unwrap();
    assert!(run(&f.0, "publish~op2~2~1~b~r2~-", "never")?.success());
    assert_eq!(f.node().read().unwrap().epoch, 2);
    Ok(())
}

#[test]
fn corrupt_snapshot_and_unknown_commands_fail_closed() -> Result<(), String> {
    let f = Fixture::new("corrupt")?;
    fs::write(f.0.join("snapshot"), "partial\n").unwrap();
    assert!(f.node().read().is_err());
    assert!(Operation::parse("execute~op~1~0~a~r~-").is_err());
    assert!(Operation::parse("publish~op~1~0~../escape~r~-").is_err());
    Ok(())
}

#[test]
#[ignore = "executed by parent tests under a real OS flock in child processes"]
fn node_worker() {
    let root = PathBuf::from(std::env::var("MCELL_NODE").unwrap());
    let operation = Operation::parse(&std::env::var("MCELL_OPERATION").unwrap()).unwrap();
    let crash = match std::env::var("MCELL_FAULT").unwrap().as_str() {
        "never" => Crash::Never,
        "before" => Crash::BeforePublish,
        "after" => Crash::AfterPublish,
        _ => panic!("unknown fault"),
    };
    if LabNode::open(&root).apply(&operation, crash).is_err() {
        std::process::exit(3);
    }
}
