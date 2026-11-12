//! Descriptor and exact-record component tests. Synthetic record metadata here
//! is not an A lifetime, a registered Initial owner or a historical grant.

use std::io::Write;
use std::os::unix::fs::PermissionsExt;

use pretty_assertions::assert_eq;

use super::*;
use crate::circuit_cell::tests::support as cell;

fn target() -> anyhow::Result<(
    CellGenerationOwnerBindingV1,
    CellDefinitionV1,
    CircuitTaskSourceInputV1,
)> {
    let input = cell::input("A");
    let source = CircuitTaskSourceInputV1 {
        scope: input.scope,
        source_frontier: input.source_frontier,
        objective_digest: input.objective_digest,
        ndu_snapshot_digest: input.ndu_snapshot_digest,
        monotonic_micros: input.monotonic_micros,
        deadline_micros: input.deadline_micros,
        observation: input.observation,
        candidates: input.candidates,
        lease_duration_ms: 2_000,
    };
    let definition = cell::definition();
    let target = serde_json::from_value(serde_json::json!({
        "scope": {"agent_id": source.scope.agent_id.as_str(), "cell_id": source.scope.cell_id.as_str(),
            "run_id": source.scope.run_id.as_str(), "principal_digest": source.scope.principal_digest.into_array()},
        "manifest_digest": vec![1; 32], "source_frontier": source.source_frontier.into_array(),
        "task_digest": crate::circuit_feature_task_digest_v1(&definition, &source)?.into_array(),
        "initial_snapshot_digest": vec![2; 32], "config_digest": vec![3; 32], "generation": 1, "writer_epoch": 1
    }))?;
    Ok((target, definition, source))
}

#[test]
fn source_pin_checks_private_original_descriptors_without_borrowing_writer_lock()
-> anyhow::Result<()> {
    let file = tempfile::NamedTempFile::new()?;
    file.as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    let metadata = file.as_file().metadata()?;
    let (mut reader, pin) = FilePin::readonly(file.as_file(), metadata.uid(), metadata.gid())?;
    assert_eq!(FilePin::read(&reader, metadata.uid(), metadata.gid())?, pin);
    assert!(reader.write_all(b"cannot write").is_err());
    file.as_file().try_lock()?;
    assert!(matches!(
        reader.try_lock_shared(),
        Err(std::fs::TryLockError::WouldBlock)
    ));
    file.as_file().unlock()?;
    file.as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o640))?;
    assert!(FilePin::read(&reader, metadata.uid(), metadata.gid()).is_err());
    file.as_file()
        .set_permissions(std::fs::Permissions::from_mode(0o600))?;
    let directory = tempfile::tempdir()?;
    let link = directory.path().join("extra-link");
    std::fs::hard_link(file.path(), &link)?;
    assert!(FilePin::read(&reader, metadata.uid(), metadata.gid()).is_err());
    std::fs::remove_file(link)?;
    Ok(())
}

#[test]
fn source_pin_recomputes_the_published_task_instead_of_accepting_matching_scope()
-> anyhow::Result<()> {
    let (target, definition, source) = target()?;
    require_target(&target, &definition, &source)?;
    let mut changed = source.clone();
    changed.observation.push(0);
    assert!(require_target(&target, &definition, &changed).is_err());
    let mut changed = source;
    changed.lease_duration_ms += 1;
    assert!(require_target(&target, &definition, &changed).is_err());
    Ok(())
}

#[test]
#[ignore = "actual UID0 and original Root-owned directory custody"]
fn root_source_pin_preserves_exact_registration_and_never_initializes_recovery()
-> anyhow::Result<()> {
    original_root()?;
    let directory = tempfile::Builder::new()
        .prefix("source-pin-")
        .tempdir_in("/run")?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700))?;
    let root = RootAuthorityDirectory::open(directory.path())?;
    let (target, _, _) = target()?;
    assert!(RootHistoricalSourcePinV1::open_existing(root.clone(), &target).is_err());
    let named = tempfile::NamedTempFile::new()?;
    let file = named.as_file();
    file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
    let file_pin = FilePin::read(file, /*uid*/ 0, /*gid*/ 0)?;
    let pin = SourcePin {
        schema: 1,
        purpose: PIN_PURPOSE.into(),
        initial_profile: "component-profile".into(),
        identity: "component-identity".into(),
        spawn_generation: 1,
        publisher_epoch: 1,
        publisher: CognitiveCheckpointPeerLifetime {
            uid: 60001,
            pid: 101,
            boot_id: "component-boot".into(),
            process_start_ticks: 1,
        },
        writer: "component-writer".into(),
        target: target.clone(),
        target_files: "component-target-files".into(),
        source_files: [file_pin.clone(), file_pin],
        source_configuration: "component-configuration".into(),
        witness_context: "component-witness".into(),
        source_sequence: 7,
        source_checkpoint: "component-anchor".into(),
        publication: "component-publication".into(),
        completed_task: "component-completion".into(),
        fence_digest: Digest32::of_bytes(b"component-fence-digest").to_string(),
    };
    let retained = RootHistoricalSourcePinV1::retain(root.clone(), pin.clone())?;
    let digest = retained.readback_digest()?;
    assert_eq!(
        RootHistoricalSourcePinV1::retain(root.clone(), pin.clone())?.readback_digest()?,
        digest
    );
    let mut changed = pin;
    changed.publication = "different-publication".into();
    assert!(RootHistoricalSourcePinV1::retain(root.clone(), changed).is_err());
    assert_eq!(
        RootHistoricalSourcePinV1::open_existing(root.clone(), &target)?.readback_digest()?,
        digest
    );
    retained.fence()?;
    retained.fence()?;
    assert!(retained.readback_digest().is_err());
    assert!(
        RootHistoricalSourcePinV1::retain(root.clone(), retained.expected.pin.clone()).is_err()
    );
    assert!(RootHistoricalSourcePinV1::open_existing(root, &target).is_err());
    Ok(())
}
