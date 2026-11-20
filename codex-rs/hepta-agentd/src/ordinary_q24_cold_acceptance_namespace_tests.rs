//! Cross the DATA observer with real Root refusal registration and CAS files.
//! The target is synthetic fixture data; no A run, terminal fact, or completed
//! learning authority is created or claimed by this component.

use std::io;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;

use codex_hepta_contracts::RootAuthorityDirectory;
use pretty_assertions::assert_eq;

use super::Kind;
use super::Phase;
use super::Refusal;
use super::completed_learning_refusal_owner;
use super::observe_original_record;
use super::record_paths;
use crate::authority_host_service::generation_initial::RootCompletedLearningRefusalV1;
use crate::authority_host_service::generation_initial::original_root;

fn read_expected(
    directory: &std::path::Path,
    owner: &str,
    expected: &Refusal,
) -> anyhow::Result<Refusal> {
    observe_original_record::<Refusal>(directory, owner, |actual| {
        anyhow::ensure!(actual == expected, "complete original refusal differs");
        Ok(())
    })?
    .ok_or_else(|| anyhow::anyhow!("quiescent original refusal was replaced"))
}

fn require_missing_error(directory: &std::path::Path, owner: &str) -> anyhow::Result<()> {
    let error = observe_original_record::<Refusal>(directory, owner, |_| Ok(()))
        .expect_err("missing original refusal must fail, never become a retryable None");
    anyhow::ensure!(
        error
            .downcast_ref::<io::Error>()
            .is_some_and(|error| error.kind() == io::ErrorKind::NotFound),
        "missing original refusal returned a different error: {error:#}"
    );
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_completed_refusal_observer_matches_registered_owner() -> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("completed-refusal-observer-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let target: codex_hepta_neuron::CellGenerationOwnerBindingV1 =
        serde_json::from_value(serde_json::json!({
            "scope": {"agent_id": "refusal-agent", "cell_id": "refusal-cell",
                "run_id": "refusal-run", "principal_digest": vec![1; 32]},
            "manifest_digest": vec![2; 32], "source_frontier": vec![3; 32],
            "task_digest": vec![4; 32], "initial_snapshot_digest": vec![5; 32],
            "config_digest": vec![6; 32], "generation": 1, "writer_epoch": 1
        }))?;
    let initial = codex_hepta_types::Digest32::from_array([11; 32]);
    // Product registration chooses and physically publishes its own owner.
    // The observer is not given that owner's string or a forged envelope.
    let (registered, ()) =
        RootCompletedLearningRefusalV1::retain_fresh(Arc::clone(&root), &target, initial, || {
            Ok(())
        })?;
    let owner = completed_learning_refusal_owner(initial, &target)?;
    let expected = Refusal {
        schema: 1,
        purpose: "runtime.initial-data-refusal.v1".into(),
        kind: Kind::CompletedLearning {
            initial: initial.into_array(),
        },
        target: target.clone(),
        attempt: 1,
        phase: Phase::Ready,
    };
    assert_eq!(
        read_expected(directory.path(), &owner, &expected)?,
        expected
    );
    let paths = record_paths(directory.path(), &owner);
    let original_bytes = paths
        .iter()
        .map(std::fs::read)
        .collect::<io::Result<Vec<_>>>()?;
    let original_entries = std::fs::read_dir(directory.path())?.count();

    let scope = crate::neuron_generation_current::types::scope_digest(target.scope())?;
    let old_owner = format!("initial-data-refusal/completed-learning/{initial}/{scope}");
    require_missing_error(directory.path(), &old_owner)?;
    let other_initial = codex_hepta_types::Digest32::from_array([12; 32]);
    require_missing_error(
        directory.path(),
        &completed_learning_refusal_owner(other_initial, &target)?,
    )?;
    let mut other_scope = serde_json::to_value(&target)?;
    other_scope["scope"]["run_id"] = serde_json::json!("other-refusal-run");
    let other_scope = serde_json::from_value(other_scope)?;
    require_missing_error(
        directory.path(),
        &completed_learning_refusal_owner(initial, &other_scope)?,
    )?;

    // Full target changes stay in the same scope slot and must not be accepted
    // merely because the physical record was found at the canonical pathname.
    let mut changed_target = serde_json::to_value(&target)?;
    changed_target["writer_epoch"] = serde_json::json!(2);
    let changed_target = serde_json::from_value(changed_target)?;
    assert_eq!(
        completed_learning_refusal_owner(initial, &changed_target)?,
        owner
    );
    let mut wrong_binding = expected.clone();
    wrong_binding.target = changed_target;
    assert!(read_expected(directory.path(), &owner, &wrong_binding).is_err());

    // An actually missing canonical record remains a hard error. Restore the
    // exact fixture bytes before any further original product operation.
    let saved = directory.path().join("saved-canonical-refusal.json");
    std::fs::rename(&paths[0], &saved)?;
    let missing = require_missing_error(directory.path(), &owner);
    std::fs::rename(&saved, &paths[0])?;
    missing?;
    assert_eq!(
        paths
            .iter()
            .map(std::fs::read)
            .collect::<io::Result<Vec<_>>>()?,
        original_bytes
    );
    assert_eq!(
        std::fs::read_dir(directory.path())?.count(),
        original_entries
    );
    assert_eq!(
        read_expected(directory.path(), &owner, &expected)?,
        expected
    );

    // Observe the real product's Armed/Ready transition; do not manufacture a
    // record in the observer to make the namespace comparison pass.
    let mut armed = expected.clone();
    armed.attempt = 2;
    armed.phase = Phase::Armed;
    registered.accept_registered(|| {
        read_expected(directory.path(), &owner, &armed).map_err(io::Error::other)?;
        assert!(read_expected(directory.path(), &owner, &expected).is_err());
        Ok(())
    })?;
    let mut ready = armed;
    ready.phase = Phase::Ready;
    assert_eq!(read_expected(directory.path(), &owner, &ready)?, ready);

    // A failed original verification stays Armed. The namespace fix cannot
    // turn this real unfinished attempt into the prior Ready observation.
    assert!(
        registered
            .accept_registered::<()>(|| Err(io::Error::other("original verification refused")))
            .is_err()
    );
    let mut unfinished = ready.clone();
    unfinished.attempt += 1;
    unfinished.phase = Phase::Armed;
    assert_eq!(
        read_expected(directory.path(), &owner, &unfinished)?,
        unfinished
    );
    assert!(read_expected(directory.path(), &owner, &ready).is_err());
    assert!(
        RootCompletedLearningRefusalV1::read_original(root, &target, initial, || Ok(())).is_err()
    );
    Ok(())
}
