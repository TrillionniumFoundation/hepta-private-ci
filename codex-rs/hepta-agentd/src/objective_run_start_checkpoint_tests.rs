use std::fs::OpenOptions;
#[cfg(unix)]
use std::path::Path;
#[cfg(unix)]
use std::path::PathBuf;

use codex_hepta_learning_ledger::RunStartAnchor;
use codex_hepta_learning_ledger::RunStartCheckpointOwnerV1;
use codex_hepta_learning_ledger::RunStartCheckpointV1;
use codex_hepta_learning_ledger::RunStartStoreError;
use codex_hepta_types::Digest32;

use super::ObjectiveRunStartCheckpointFile;
use super::checkpoint_lock_path;
use super::write_private_atomic;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[cfg(unix)]
#[test]
fn checkpoint_cas_binds_append_and_compaction_transitions() {
    let temp = tempfile::tempdir().expect("tempdir");
    let path = temp.path().join("objective-checkpoint.json");
    let binding = digest("binding");
    write_private_atomic(&path, "agent.test", binding, RunStartCheckpointV1::ZERO)
        .expect("initialize checkpoint");
    let lock = OpenOptions::new()
        .create_new(true)
        .read(true)
        .write(true)
        .open(temp.path().join("checkpoint.lock"))
        .expect("lock");
    let file = ObjectiveRunStartCheckpointFile {
        path,
        agent_id: "agent.test".to_string(),
        binding,
        _lock: lock,
    };
    assert_eq!(
        file.current_checkpoint().expect("initial checkpoint"),
        RunStartCheckpointV1::ZERO
    );

    let first_anchor = RunStartAnchor {
        sequence: 1,
        chain_digest: digest("chain.1"),
    };
    let appended = RunStartCheckpointV1 {
        anchor: first_anchor,
        compacted_prefix: RunStartAnchor::ZERO,
        compacted_digest: Digest32::ZERO,
    };
    file.compare_and_swap(RunStartCheckpointV1::ZERO, appended)
        .expect("append checkpoint");

    let compacted = RunStartCheckpointV1 {
        anchor: first_anchor,
        compacted_prefix: first_anchor,
        compacted_digest: digest("compacted.1"),
    };
    file.compare_and_swap(appended, compacted)
        .expect("compaction checkpoint");
    file.compare_and_swap(appended, compacted)
        .expect("lost acknowledgement replay");
    assert_eq!(file.current_checkpoint().expect("current"), compacted);

    let stale_next = RunStartCheckpointV1 {
        anchor: first_anchor,
        compacted_prefix: RunStartAnchor::ZERO,
        compacted_digest: Digest32::ZERO,
    };
    assert_eq!(
        file.compare_and_swap(RunStartCheckpointV1::ZERO, stale_next),
        Err(RunStartStoreError::RollbackDetected)
    );
}

#[cfg(unix)]
fn test_identity(root: &Path) -> crate::AgentdIdentity {
    use std::os::unix::fs::PermissionsExt;

    use codex_hepta_contracts::AgentId;
    use codex_hepta_fleet::AgentManifest;
    use codex_hepta_fleet::FleetRegistry;
    use codex_hepta_fleet::ResourceBudget;
    use codex_hepta_fleet::WorkspaceBinding;
    use codex_hepta_paths::HeptaFleetRoot;

    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id");
    let manifest = AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
        ResourceBudget::local_default(),
    )
    .expect("manifest");
    let registered = registry.register(manifest).expect("register");
    let identity = crate::AgentdIdentity {
        agent_id: agent,
        spawn_generation: 1,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
        layout: registered.layout,
    };
    std::fs::set_permissions(&identity.home_root, std::fs::Permissions::from_mode(0o700))
        .expect("private home");
    identity
}

#[cfg(unix)]
fn checkpoint_path(root: &Path) -> PathBuf {
    use std::os::unix::fs::PermissionsExt;

    let directory = root.join("objective-checkpoint-owner");
    std::fs::create_dir(&directory).expect("checkpoint directory");
    std::fs::set_permissions(&directory, std::fs::Permissions::from_mode(0o700))
        .expect("private checkpoint directory");
    directory
        .canonicalize()
        .expect("canonical checkpoint directory")
        .join("checkpoint.json")
}

#[cfg(unix)]
#[test]
fn checkpoint_open_initializes_private_state_and_reopens_exact_identity() {
    use std::os::unix::fs::MetadataExt;

    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let identity = test_identity(&root);
    let path = checkpoint_path(&root);
    let binding = digest("binding.open");

    let first = ObjectiveRunStartCheckpointFile::open(path.clone(), &identity, binding, true)
        .expect("initialize checkpoint");
    assert_eq!(
        first.current_checkpoint().expect("initial checkpoint"),
        RunStartCheckpointV1::ZERO
    );
    let metadata = std::fs::symlink_metadata(&path).expect("checkpoint metadata");
    assert!(metadata.is_file());
    assert_eq!(metadata.nlink(), 1);
    assert_eq!(metadata.mode() & 0o077, 0);
    let lock_path = checkpoint_lock_path(&path).expect("lock path");
    assert!(lock_path.is_file());
    drop(first);

    let reopened = ObjectiveRunStartCheckpointFile::open(path, &identity, binding, false)
        .expect("reopen checkpoint");
    assert_eq!(
        reopened.current_checkpoint().expect("reopened checkpoint"),
        RunStartCheckpointV1::ZERO
    );
}

#[cfg(unix)]
#[test]
fn missing_checkpoint_for_existing_history_fails_closed() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let identity = test_identity(&root);
    let path = checkpoint_path(&root);
    let result =
        ObjectiveRunStartCheckpointFile::open(path, &identity, digest("binding.missing"), false);
    let error = match result {
        Ok(_) => panic!("missing checkpoint must not be recreated for existing history"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("RollbackDetected"));
}

#[cfg(unix)]
#[test]
fn checkpoint_lock_excludes_a_second_live_writer() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let identity = test_identity(&root);
    let path = checkpoint_path(&root);
    let binding = digest("binding.lock");
    let first = ObjectiveRunStartCheckpointFile::open(path.clone(), &identity, binding, true)
        .expect("first writer");
    let second = ObjectiveRunStartCheckpointFile::open(path.clone(), &identity, binding, false);
    let error = match second {
        Ok(_) => panic!("second live checkpoint writer must be rejected"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("Busy"));
    drop(first);
    ObjectiveRunStartCheckpointFile::open(path, &identity, binding, false)
        .expect("writer can reopen after lock release");
}

#[cfg(unix)]
#[test]
fn checkpoint_rejects_wrong_binding_and_agent_home_placement() {
    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let identity = test_identity(&root);
    let path = checkpoint_path(&root);
    let binding = digest("binding.correct");
    drop(
        ObjectiveRunStartCheckpointFile::open(path.clone(), &identity, binding, true)
            .expect("initialize checkpoint"),
    );

    let wrong =
        ObjectiveRunStartCheckpointFile::open(path, &identity, digest("binding.wrong"), false);
    let error = match wrong {
        Ok(_) => panic!("wrong checkpoint binding must fail"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("BindingMismatch"));

    let inside_home = identity.home_root.join("objective-checkpoint.json");
    let misplaced = ObjectiveRunStartCheckpointFile::open(inside_home, &identity, binding, true);
    let error = match misplaced {
        Ok(_) => panic!("checkpoint inside Agent home must fail"),
        Err(error) => error,
    };
    assert!(error.to_string().contains("outside Agent home"));
}

#[cfg(unix)]
#[test]
fn checkpoint_and_writer_lock_reject_symbolic_links() {
    use std::os::unix::fs::symlink;

    let temp = tempfile::tempdir().expect("tempdir");
    let root = temp.path().canonicalize().expect("canonical root");
    let identity = test_identity(&root);
    let path = checkpoint_path(&root);
    let target = path.with_file_name("target.json");
    std::fs::write(&target, b"not a checkpoint").expect("target");
    symlink(&target, &path).expect("checkpoint symlink");
    let checkpoint_result = ObjectiveRunStartCheckpointFile::open(
        path.clone(),
        &identity,
        digest("binding.symlink"),
        false,
    );
    assert!(checkpoint_result.is_err());
    std::fs::remove_file(&path).expect("remove checkpoint symlink");

    let lock_path = checkpoint_lock_path(&path).expect("lock path");
    std::fs::remove_file(&lock_path).expect("remove legitimate lock artifact");
    symlink(&target, &lock_path).expect("lock symlink");
    let lock_result =
        ObjectiveRunStartCheckpointFile::open(path, &identity, digest("binding.symlink"), true);
    assert!(lock_result.is_err());
    assert_eq!(
        std::fs::read(&target).expect("target remains readable"),
        b"not a checkpoint"
    );
}
