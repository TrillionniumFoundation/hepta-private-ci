//! Strict wire data plus actual UID0 stores. Synthetic binding fixtures prove
//! storage refusal only; none stands in for live Root context or an executed A.

use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;
use sha2::Digest;

use super::*;
use crate::authority_host_service::generation_initial::Request;

fn publication(run: &str) -> OriginalRunStartPublicationDataV1 {
    OriginalRunStartPublicationDataV1 {
        run_id: run.into(),
        profile_digest: Digest32::of_bytes(b"profile").to_string(),
        sequence: 1,
        record_digest: Digest32::of_bytes(b"record").to_string(),
        chain_digest: Digest32::of_bytes(b"chain").to_string(),
    }
}

#[test]
fn original_run_start_retain_wire_rejects_paths_authority_and_unknown_fields() -> anyhow::Result<()>
{
    let valid = serde_json::json!({
        "schema": 1, "purpose": RUN_START_RETENTION_PURPOSE, "request_id": 4,
        "profile": "original-profile", "command": {
            "kind": "retain_run_start", "publication": publication("fixture-run"),
        },
    });
    let parsed: Request = serde_json::from_value(valid.clone())?;
    assert!(matches!(
        parsed.command,
        super::super::Command::RetainRunStart { .. }
    ));
    for field in ["path", "descriptor", "authority", "fresh", "recover"] {
        let mut injected = valid.clone();
        injected["command"][field] = serde_json::json!(true);
        assert!(serde_json::from_value::<Request>(injected).is_err());
        let mut injected = valid.clone();
        injected["command"]["publication"][field] = serde_json::json!(true);
        assert!(serde_json::from_value::<Request>(injected).is_err());
    }
    let mut unknown = valid.clone();
    unknown["authority"] = serde_json::json!(true);
    assert!(serde_json::from_value::<Request>(unknown).is_err());
    let mut absent = valid;
    absent["command"]["publication"]
        .as_object_mut()
        .ok_or_else(|| io::Error::other("fixture publication missing"))?
        .remove("chain_digest");
    assert!(serde_json::from_value::<Request>(absent).is_err());
    Ok(())
}

#[test]
fn original_run_start_retain_tuple_has_no_empty_or_unbounded_cut() -> anyhow::Result<()> {
    let valid = publication("fixture-run");
    valid.validate()?;
    for sequence in [0, 4_097] {
        let mut changed = valid.clone();
        changed.sequence = sequence;
        assert!(changed.validate().is_err());
    }
    for field in ["profile_digest", "record_digest", "chain_digest"] {
        let mut changed = serde_json::to_value(&valid)?;
        changed[field] = serde_json::json!(Digest32::ZERO.to_string());
        let changed: OriginalRunStartPublicationDataV1 = serde_json::from_value(changed)?;
        assert!(changed.validate().is_err());
    }
    Ok(())
}

fn original(run: &str) -> anyhow::Result<OriginalRunStartRegistration> {
    Ok(OriginalRunStartRegistration {
        schema: 1,
        purpose: RECORD_PURPOSE.into(),
        initial_profile: "component-initial".into(),
        identity: "component-identity".into(),
        spawn_generation: 1,
        writer: "component-writer".into(),
        publisher_epoch: 1,
        publisher: CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: 101,
            boot_id: "component-boot".into(),
            process_start_ticks: 7,
        },
        publisher_gid: 60001,
        target: serde_json::from_value(serde_json::json!({
            "scope": {"agent_id": "retained-agent", "cell_id": "retained-cell",
                "run_id": run, "principal_digest": vec![1; 32]},
            "manifest_digest": vec![2; 32], "source_frontier": vec![3; 32],
            "task_digest": vec![4; 32], "initial_snapshot_digest": vec![5; 32],
            "config_digest": vec![6; 32], "generation": 1, "writer_epoch": 1,
        }))?,
        target_files: "component-target-files".into(),
        inputs: serde_json::from_value(serde_json::json!({
            "files": [
                {"device": 1, "inode": 1, "uid": 0, "gid": 0, "mode": 0o100600},
                {"device": 1, "inode": 2, "uid": 0, "gid": 0, "mode": 0o100600},
                {"device": 1, "inode": 3, "uid": 0, "gid": 0, "mode": 0o100600},
            ],
            "profile_bytes": Digest32::of_bytes(b"profile-bytes").to_string(),
            "trust_bytes": Digest32::of_bytes(b"trust-bytes").to_string(),
            "profile_digest": publication(run).profile_digest,
            "journal_binding": Digest32::of_bytes(b"journal-binding").to_string(),
            "prefix_length": 72, "prefix_digest": Digest32::of_bytes(b"prefix").to_string(),
        }))?,
    })
}

fn observed(original: &OriginalRunStartRegistration) -> RunStartObservation {
    RunStartObservation {
        publication: publication(&original.target.scope().run_id),
        frame_start: 72,
        frame_end: 512,
        observed_length: 512,
        observed_unix_ms: 1_000,
        current: CurrentHead {
            schema_version: 1,
            current: original.target.clone(),
            prepared: None,
            published: None,
            initial: None,
        },
    }
}

fn root() -> anyhow::Result<(tempfile::TempDir, Arc<RootAuthorityDirectory>)> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("run-start-data-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    Ok((directory, root))
}

fn pending(
    root: Arc<RootAuthorityDirectory>,
    run: &str,
) -> anyhow::Result<(RootDataRefusalV1, RunStartRecordStore)> {
    let original = original(run)?;
    Ok(RootDataRefusalV1::create_fresh(
        Arc::clone(&root),
        RootDataKind::RunStart,
        &original.target,
        || RunStartRecordStore::initialize_unchecked(root, original.clone()),
    )?)
}

fn finalize_component(
    refusal: &RootDataRefusalV1,
    state: &mut RunStartRecordStore,
) -> io::Result<()> {
    let next = refusal.inspect(|| state.finalize_unchecked(observed(&state.expected.original)))?;
    state.expected = next;
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_run_start_data_never_promotes_pending_or_missing_refusal() -> anyhow::Result<()> {
    let (_directory, root) = root()?;
    let (refusal, mut success) = pending(Arc::clone(&root), "positive")?;
    finalize_component(&refusal, &mut success)?;
    let target = success.expected.original.target.clone();
    RootRetainedRunStartDataV1::open_finalized(Arc::clone(&root), &target)?.readback_digest()?;
    let (_refusal, state) = pending(Arc::clone(&root), "pending")?;
    let target = state.expected.original.target.clone();
    assert!(RootRetainedRunStartDataV1::open_finalized(Arc::clone(&root), &target).is_err());
    let old = original("old-primary-without-marker")?;
    let target = old.target.clone();
    let store = RunStartRecordStore::initialize_unchecked(Arc::clone(&root), old)?;
    assert!(RootRetainedRunStartDataV1::open_finalized(Arc::clone(&root), &target).is_err());
    assert!(pending(Arc::clone(&root), "old-primary-without-marker").is_err());
    assert!(RootDataRefusalV1::open_existing(root, RootDataKind::RunStart, &target).is_err());
    assert_eq!(store.store.load(&store.owner)?, store.expected);
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_run_start_finalized_primary_before_failed_postcheck_cannot_recover() -> anyhow::Result<()> {
    let (_directory, root) = root()?;
    let (refusal, state) = pending(Arc::clone(&root), "unfinished-finalization")?;
    let target = state.expected.original.target.clone();
    let result: io::Result<()> = refusal.inspect(|| {
        let next = state.finalize_unchecked(observed(&state.expected.original))?;
        assert_eq!(
            state.store.load(&state.owner).map_err(io::Error::other)?,
            next
        );
        Err(io::Error::new(
            io::ErrorKind::TimedOut,
            "component final absolute-end failure",
        ))
    });
    assert!(result.is_err());
    assert_eq!(
        state.store.load(&state.owner)?.phase,
        RetentionPhase::Finalized
    );
    drop(state);
    drop(refusal);
    assert!(RootRetainedRunStartDataV1::open_finalized(root, &target).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_run_start_corruption_then_restore_stays_refused_across_processes() -> anyhow::Result<()> {
    let (directory, root) = root()?;
    let (refusal, mut state) = pending(root, "cold-refusal")?;
    finalize_component(&refusal, &mut state)?;
    let target = state.expected.original.target.clone();
    let path = directory.path().join(format!(
        "frontier-v1-{:x}.json",
        sha2::Sha256::digest(state.owner.as_bytes())
    ));
    let original = std::fs::read(&path)?;
    drop(state);
    drop(refusal);
    for (bytes, phase) in [
        (original.as_slice(), "baseline"),
        (&b"{broken-run-start"[..], "observe_corruption"),
        (original.as_slice(), "restore_then_reopen"),
    ] {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .truncate(true)
            .open(&path)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        drop(file);
        let (_, child_name) = concat!(module_path!(), "::root_run_start_refusal_child")
            .split_once("::")
            .ok_or_else(|| io::Error::other("original child path missing"))?;
        let output = std::process::Command::new(std::env::current_exe()?)
            .args(["--exact", child_name, "--ignored", "--nocapture"])
            .env("HEPTA_RUN_START_DATA_TEST_ROOT", directory.path())
            .env(
                "HEPTA_RUN_START_DATA_TEST_TARGET",
                serde_json::to_string(&target)?,
            )
            .env("HEPTA_RUN_START_DATA_TEST_PHASE", phase)
            .output()?;
        let receipt = format!("hepta-root-run-start-child:{phase}");
        assert!(
            output.status.success()
                && String::from_utf8_lossy(&output.stdout).contains(receipt.as_str()),
            "Root RunStart child failed: {phase}; status={:?}; stdout={}; stderr={}",
            output.status,
            String::from_utf8_lossy(&output.stdout),
            String::from_utf8_lossy(&output.stderr)
        );
    }
    Ok(())
}

#[test]
#[ignore = "private subprocess of Root RunStart cold-refusal component tests"]
fn root_run_start_refusal_child() -> anyhow::Result<()> {
    original_root()?;
    let root = RootAuthorityDirectory::open(std::path::Path::new(&std::env::var(
        "HEPTA_RUN_START_DATA_TEST_ROOT",
    )?))?;
    let target = serde_json::from_str(&std::env::var("HEPTA_RUN_START_DATA_TEST_TARGET")?)?;
    let phase = std::env::var("HEPTA_RUN_START_DATA_TEST_PHASE")?;
    match phase.as_str() {
        "baseline" => {
            RootRetainedRunStartDataV1::open_finalized(root, &target)?.readback_digest()?;
        }
        "observe_corruption" | "restore_then_reopen" => {
            assert!(RootRetainedRunStartDataV1::open_finalized(root, &target).is_err());
        }
        _ => anyhow::bail!("unknown RunStart child phase: {phase}"),
    }
    println!("hepta-root-run-start-child:{phase}");
    std::io::stdout().flush()?;
    Ok(())
}
