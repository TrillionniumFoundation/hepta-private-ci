//! Exercise the built binary, not a parser mock or a mutable owner accessor.
use codex_hepta_fleet::DurableFleetOwner;
use codex_hepta_fleet::SystemFleetClock;
use std::collections::BTreeMap;
use std::path::Path;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Arc;
use std::time::SystemTime;

type Image = BTreeMap<PathBuf, (Vec<u8>, SystemTime)>;

fn image(root: &Path) -> Image {
    let mut output = BTreeMap::new();
    for entry in std::fs::read_dir(root).expect("directory") {
        let entry = entry.expect("entry");
        let path = entry.path();
        let metadata = entry.metadata().expect("metadata");
        if metadata.is_dir() {
            output.extend(image(&path));
        } else {
            output.insert(
                path.clone(),
                (std::fs::read(path).expect("bytes"), metadata.modified().expect("mtime")),
            );
        }
    }
    output
}

fn command() -> Command {
    Command::new(env!("CARGO_BIN_EXE_hepta-fleet-status"))
}

#[test]
fn documented_command_and_compatibility_aliases_are_read_only() {
    let directory = tempfile::tempdir().expect("tempdir");
    let root = directory.path();
    DurableFleetOwner::open_supervisor_state_root(root, Arc::new(SystemFleetClock)).expect("owner");
    let before = image(root);
    for option in ["--supervisor-state-root", "--state-root", "--state-dir"] {
        let output = command()
            .arg("status")
            .arg(option)
            .arg(root)
            .args(["--format", "json", "--operation-id", "not-in-retained-window"])
            .output()
            .expect("status process");
        assert!(output.status.success(), "{}", String::from_utf8_lossy(&output.stderr));
        let value: serde_json::Value = serde_json::from_slice(&output.stdout).expect("json");
        assert_eq!(value["claim_boundary"]["read_only"], true);
        assert_eq!(value["metrics"]["fleet_grant_issue_total"]["available"], false);
        assert!(value["metrics"]["fleet_grant_issue_total"]["success"].is_null());
        assert!(value["metrics"]["fleet_registry_conflict_total"].is_null());
        assert!(value["sampled_at_ms"].as_u64().is_some());
        assert_eq!(image(root), before);
    }
}

#[test]
fn missing_or_damaged_state_is_failure_without_creation_or_repair() {
    let directory = tempfile::tempdir().expect("tempdir");
    let missing = directory.path().join("missing");
    let output = command().arg("--supervisor-state-root").arg(&missing).output().expect("process");
    assert!(!output.status.success());
    assert!(!missing.exists());
    let root = directory.path().join("state");
    std::fs::create_dir(&root).expect("root");
    DurableFleetOwner::open_supervisor_state_root(&root, Arc::new(SystemFleetClock)).expect("owner");
    for name in ["owner.lock", "latest-frontier-v1.json"] {
        let path = root.join("fleet-allocation-v1").join(name);
        let original = std::fs::read(&path).expect("existing file");
        std::fs::remove_file(&path).expect("remove fixture");
        let before = image(&root);
        let output = command().arg("--supervisor-state-root").arg(&root).output().expect("process");
        assert!(!output.status.success());
        assert_eq!(image(&root), before);
        assert!(!path.exists());
        std::fs::write(path, original).expect("restore fixture");
    }
}

#[test]
fn malformed_commands_never_open_authority_state() {
    let directory = tempfile::tempdir().expect("tempdir");
    let root = directory.path().join("must-not-exist");
    for extra in [
        vec!["--format", "yaml"],
        vec!["--operation-id", "--fail-on-alert"],
        vec!["--fail-on-alert", "--fail-on-alert"],
        vec!["--format", "json", "--format", "json"],
        vec!["preflight"],
        vec!["open", "--allow-create"],
    ] {
        let output = command().arg("--supervisor-state-root").arg(&root).args(extra).output().expect("process");
        assert!(!output.status.success());
        assert!(!root.exists());
    }
    let output = command().args(["--help"]).output().expect("help");
    assert!(output.status.success());
    assert!(!root.exists());
}

#[test]
fn writer_contention_is_a_diagnostic_error_not_a_healthy_empty_fleet() {
    let directory = tempfile::tempdir().expect("tempdir");
    let root = directory.path();
    DurableFleetOwner::open_supervisor_state_root(root, Arc::new(SystemFleetClock)).expect("owner");
    let file = std::fs::File::open(root.join("fleet-allocation-v1/owner.lock")).expect("lock");
    file.lock().expect("writer");
    let before = image(root);
    let output = command().arg("--supervisor-state-root").arg(root).output().expect("process");
    assert!(!output.status.success());
    assert!(output.stdout.is_empty());
    assert_eq!(image(root), before);
}
