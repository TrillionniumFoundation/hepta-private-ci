//! Physical storage regression tests; fixture admissions are not product authority.
use std::io::Seek;
use std::io::SeekFrom;
use std::os::unix::fs::MetadataExt;

use super::*;
use crate::TestMust;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn factor(index: usize) -> PromptFactor {
    PromptFactor {
        factor_id: id(&format!("factor:{index}")),
        proposer_id: id("proposer:test"),
        semantic_version: id("v1"),
        semantic_purpose: "payload storage test".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: vec![id("dimension:quality")],
        content_digest: digest(&format!("factor-content:{index}")),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

fn add_payload(core: &mut PromptRegistry, index: usize) -> Result<RegistryReceipt, Error> {
    let factor = factor(index);
    let factor_id = factor.factor_id.clone();
    core.register_factor(factor)?;
    core.admit_factor(&factor_id, &id("reviewer:test"), digest("review-evidence"))?;
    let payload = vec![65 + (index % 26) as u8; 16 * 1024];
    core.register_realization_payload_v2(
        PromptRealizationBindingV2 {
            realization_id: id(&format!("realization:{index}")),
            factor_id,
            model_id: id("model:test"),
            model_version: "v1".into(),
            model_digest: digest("model"),
            tokenizer_digest: digest("tokenizer"),
            template_digest: digest("template"),
            tool_schema_digest: digest("tools"),
            context_profile_digest: digest("context"),
            locale_id: id("en-US"),
            role: PromptRoleV2::DeveloperInstruction,
            payload_digest: Digest32::of_bytes(&payload),
            token_cost: 4096,
            expires_unix_ms: None,
        },
        payload,
        None,
    )
}

#[test]
fn metadata_changes_never_rewrite_old_payloads_and_reopen_never_rewrites_manifest() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 512).must("owner");
    owner
        .commit(|core| {
            for index in 0..64 {
                add_payload(core, index)?;
            }
            Ok(core.receipt(crate::MutationDisposition::Inserted))
        })
        .must("seed actual payload bytes");
    let payload_file = path.join(payloads::FILE_NAME);
    let before = std::fs::metadata(&payload_file).must("payload metadata");
    let legacy_bytes = serde_json::to_vec(&stored_v2(owner.registry().must("registry")))
        .must("legacy serialization")
        .len();
    owner
        .register_factor(factor(65))
        .must("small metadata mutation");
    owner
        .retire_factor(&id("factor:0"), &id("operator:test"), digest("retirement"))
        .must("metadata-only retirement preserves historical payloads");
    let after = std::fs::metadata(&payload_file).must("payload metadata");
    assert_eq!(
        (
            before.len(),
            before.ino(),
            before.mtime(),
            before.mtime_nsec()
        ),
        (after.len(), after.ino(), after.mtime(), after.mtime_nsec())
    );
    let manifest = path.join("registry.json");
    let metadata_bytes = std::fs::metadata(&manifest).must("manifest").len();
    assert!(metadata_bytes < legacy_bytes as u64 / 4);
    let expected = owner.registry().must("registry").clone();
    let payload_id = id("realization:0");
    assert!(std::sync::Arc::ptr_eq(
        expected
            .realization_payloads
            .get(&payload_id)
            .must("snapshot payload"),
        owner
            .registry()
            .must("registry")
            .realization_payloads
            .get(&payload_id)
            .must("owner payload"),
    ));
    let manifest_inode = std::fs::metadata(&manifest).must("manifest").ino();
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 512).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
    assert_eq!(
        std::fs::metadata(&manifest).must("manifest").ino(),
        manifest_inode
    );
    eprintln!(
        "PREG_V3_GROWTH payloads=64 raw_bytes={} legacy_snapshot_bytes={legacy_bytes} metadata_commit_bytes={metadata_bytes} old_payload_bytes_rewritten=0",
        64 * 16 * 1024
    );
}

#[test]
fn incomplete_unselected_payload_tail_is_discarded_only_after_semantic_validation() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("initial payload");
    let expected = owner.registry().must("registry").clone();
    let file_path = path.join(payloads::FILE_NAME);
    let committed_length = std::fs::metadata(&file_path).must("metadata").len();
    // Simulate bytes written before any selecting metadata rename.
    let mut file =
        open_private(&owner.store.root, payloads::FILE_NAME, Access::Create).must("payload");
    file.seek(SeekFrom::End(0)).must("tail");
    file.write_all(b"unselected incomplete next payload")
        .must("orphan tail");
    file.sync_all().must("tail sync");
    drop(owner);
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 65),
        Err(DurableRegistryError::ConfigurationMismatch)
    ));
    assert!(std::fs::metadata(&file_path).must("metadata").len() > committed_length);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
    assert_eq!(
        std::fs::metadata(file_path).must("metadata").len(),
        committed_length
    );
}

#[test]
fn post_rename_unknown_commit_keeps_new_payload_and_requires_reopen() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.commit(|core| add_payload(core, 1)),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    drop(owner);
    let reopened =
        DurablePromptRegistry::open_state_dir(&path, 64).must("reconcile selected snapshot");
    assert!(
        reopened
            .registry()
            .must("registry")
            .realization_payloads
            .contains_key(&id("realization:1"))
    );
}

#[test]
fn missing_truncated_or_modified_committed_payload_is_never_repaired() {
    for fault in ["missing", "truncated", "modified"] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
        owner.commit(|core| add_payload(core, 1)).must("payload");
        let file_path = path.join(payloads::FILE_NAME);
        let metadata = std::fs::read(path.join("registry.json")).must("snapshot");
        drop(owner);
        match fault {
            "missing" => std::fs::remove_file(&file_path).must("remove"),
            "truncated" => std::fs::OpenOptions::new()
                .write(true)
                .open(&file_path)
                .must("payload")
                .set_len(32)
                .must("truncate"),
            "modified" => {
                let mut file = std::fs::OpenOptions::new()
                    .write(true)
                    .open(&file_path)
                    .must("payload");
                file.seek(SeekFrom::Start(64)).must("position");
                file.write_all(b"corrupted").must("modify");
            }
            _ => unreachable!(),
        }
        assert!(
            DurablePromptRegistry::open_state_dir(&path, 64).is_err(),
            "{fault}"
        );
        assert_eq!(
            std::fs::read(path.join("registry.json")).must("snapshot"),
            metadata
        );
    }
}

#[test]
fn v2_migration_preserves_payloads_frontiers_and_semantic_identity() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let directory = prepare_directory(&path).must("directory");
    let mut core = PromptRegistry::new(64).must("core");
    add_payload(&mut core, 0).must("legacy payload");
    let bytes = serde_json::to_vec(&stored_v2(&core)).must("legacy snapshot");
    let mut file = open_private(&directory, "registry.json", Access::Create).must("legacy file");
    file.write_all(&bytes).must("legacy bytes");
    file.sync_all().must("legacy sync");
    directory.sync_all().must("legacy directory sync");
    let owner = DurablePromptRegistry::open_state_dir(&path, 64).must("migration");
    assert_eq!(owner.registry().must("registry"), &core);
    let manifest: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path.join("registry.json")).must("manifest"))
            .must("json");
    assert_eq!(manifest["schema"], 3);
    assert_eq!(manifest["state"]["payloads"], serde_json::json!([]));
    assert!(path.join(payloads::FILE_NAME).is_file());
}

#[test]
fn failed_manifest_publication_never_selects_new_payload_bytes() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.commit(|core| add_payload(core, 0)).must("initial");
    let expected = owner.registry().must("registry").clone();
    let payload_file = path.join(payloads::FILE_NAME);
    let committed_end = std::fs::metadata(&payload_file).must("metadata").len();
    std::fs::create_dir(path.join("registry.next")).must("block manifest staging");
    assert!(owner.commit(|core| add_payload(core, 1)).is_err());
    assert_eq!(owner.registry().must("unchanged registry"), &expected);
    assert!(std::fs::metadata(&payload_file).must("metadata").len() > committed_end);
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen predecessor");
    assert_eq!(reopened.registry().must("registry"), &expected);
    assert_eq!(
        std::fs::metadata(payload_file).must("metadata").len(),
        committed_end
    );
}

#[test]
fn metadata_mutation_rejects_a_missing_committed_extent_file() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    let before = std::fs::read(path.join("registry.json")).must("snapshot");
    std::fs::remove_file(path.join(payloads::FILE_NAME)).must("remove extent file");
    assert!(owner.register_factor(factor(0)).is_err());
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("snapshot"),
        before
    );
}

#[test]
fn malformed_extent_manifests_cannot_reinterpret_or_trim_committed_bytes() {
    for fault in [
        "overlap",
        "oversize",
        "duplicate",
        "inline-payload",
        "schema",
    ] {
        let temp = tempfile::tempdir().must("temp");
        let path = temp.path().join("owner");
        let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
        owner.commit(|core| add_payload(core, 0)).must("payload");
        drop(owner);
        let manifest = path.join("registry.json");
        let mut value: serde_json::Value =
            serde_json::from_slice(&std::fs::read(&manifest).must("manifest")).must("JSON");
        match fault {
            "overlap" => value["payload_references"][0]["offset"] = 0.into(),
            "oversize" => value["payload_references"][0]["length"] = u64::MAX.into(),
            "duplicate" => {
                let repeated = value["payload_references"][0].clone();
                value["payload_references"]
                    .as_array_mut()
                    .must("references")
                    .push(repeated);
            }
            "inline-payload" => {
                value["state"]["payloads"] = serde_json::json!([
                    {"realization_id": "realization:0", "payload": [1]}
                ])
            }
            "schema" => value["schema"] = 4.into(),
            _ => unreachable!(),
        }
        std::fs::write(&manifest, serde_json::to_vec(&value).must("encode")).must("mutate");
        let payload_path = path.join(payloads::FILE_NAME);
        let before = std::fs::read(&payload_path).must("payload file");
        assert!(
            DurablePromptRegistry::open_state_dir(&path, 64).is_err(),
            "{fault}"
        );
        assert_eq!(
            std::fs::read(&payload_path).must("unchanged payload"),
            before
        );
    }
}

#[test]
fn distinct_model_versions_remain_reopenable() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("first profile");

    let current = owner.registry().must("current");
    let mut second = current
        .realization_bindings
        .get(&id("realization:0"))
        .must("first binding")
        .clone();
    let payload = current
        .realization_payloads
        .get(&id("realization:0"))
        .must("first payload")
        .to_vec();
    second.realization_id = id("realization:second-version");
    second.model_version = "v2".into();
    owner
        .register_realization_payload_v2(second, payload, None)
        .must("second model version");
    let expected = owner.registry().must("registry").clone();
    drop(owner);

    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
}

#[test]
fn rejected_first_configuration_leaves_directory_retryable() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&path, 0),
        Err(DurableRegistryError::Core(Error::ZeroCapacity))
    ));
    assert!(!path.join("registry.lock").exists());
    assert!(!path.join("registry.json").exists());

    let owner = DurablePromptRegistry::open_state_dir(&path, 64).must("corrected retry");
    assert_eq!(owner.registry().must("registry").revision().get(), 1);
}

#[test]
fn guarded_reopen_rejects_valid_pre_revocation_backup() {
    let temp = tempfile::tempdir().must("temp");
    let registry_path = temp.path().join("owner");
    let checkpoint_path = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("seed active payload");
    let old_manifest = std::fs::read(registry_path.join("registry.json")).must("old manifest");
    let old_payloads = std::fs::read(registry_path.join(payloads::FILE_NAME)).must("old payloads");
    owner
        .revoke_factor(
            &id("factor:0"),
            &id("operator:test"),
            digest("revoked after backup"),
            1,
        )
        .must("durable revocation");
    drop(owner);

    std::fs::write(registry_path.join("registry.json"), old_manifest).must("restore manifest");
    std::fs::write(registry_path.join(payloads::FILE_NAME), old_payloads).must("restore payloads");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &registry_path,
            &checkpoint_path,
            "agent:test:prompt.registry",
            64,
        ),
        Err(DurableRegistryError::RollbackDetected)
    ));
}

#[test]
fn checkpoint_bound_registry_cannot_reopen_unguarded() {
    let temp = tempfile::tempdir().must("temp");
    let registry_path = temp.path().join("owner");
    let checkpoint_path = temp.path().join("witness").join("checkpoint.json");
    drop(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &registry_path,
            &checkpoint_path,
            "agent:test:prompt.registry",
            64,
        )
        .must("guarded owner"),
    );
    assert!(matches!(
        DurablePromptRegistry::open_state_dir(&registry_path, 64),
        Err(DurableRegistryError::RecoveryCheckpointRequired)
    ));
}

#[test]
fn guarded_indeterminate_commit_promotes_exact_pending_successor_on_reopen() {
    let temp = tempfile::tempdir().must("temp");
    let registry_path = temp.path().join("owner");
    let checkpoint_path = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    let expected = factor(7);
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(expected.clone()),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    drop(owner);

    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("reconcile pending successor");
    assert_eq!(
        reopened
            .registry()
            .must("registry")
            .factor(&expected.factor_id),
        Some(&expected)
    );
}

#[test]
fn guarded_precommit_failure_aborts_pending_checkpoint() {
    let temp = tempfile::tempdir().must("temp");
    let registry_path = temp.path().join("owner");
    let checkpoint_path = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    let rejected = factor(8);
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.register_factor(rejected.clone()),
        Err(DurableRegistryError::StorageFull)
    ));
    drop(owner);

    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("reopen predecessor");
    assert!(
        reopened
            .registry()
            .must("registry")
            .factor(&rejected.factor_id)
            .is_none()
    );
}

#[test]
fn rejected_rollback_does_not_trim_newer_committed_payloads() {
    let temp = tempfile::tempdir().must("temp");
    let registry_path = temp.path().join("owner");
    let checkpoint_path = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("first committed payload");
    let old_manifest = std::fs::read(registry_path.join("registry.json")).must("old manifest");
    owner
        .commit(|core| add_payload(core, 1))
        .must("second committed payload");
    let current_manifest =
        std::fs::read(registry_path.join("registry.json")).must("current manifest");
    let current_payloads =
        std::fs::read(registry_path.join(payloads::FILE_NAME)).must("current payloads");
    let current_witness = std::fs::read(&checkpoint_path).must("current witness");
    drop(owner);
    std::fs::write(registry_path.join("registry.json"), &old_manifest)
        .must("restore old manifest only");
    for guarded in [false, true] {
        let result = if guarded {
            DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
                &registry_path,
                &checkpoint_path,
                "agent:test:prompt.registry",
                64,
            )
        } else {
            DurablePromptRegistry::open_state_dir(&registry_path, 64)
        };
        assert!(result.is_err(), "rejected rollback must not open");
        assert_eq!(
            std::fs::read(registry_path.join(payloads::FILE_NAME)).must("untouched payloads"),
            current_payloads
        );
        assert_eq!(
            std::fs::read(registry_path.join("registry.json")).must("untouched manifest"),
            old_manifest
        );
        assert_eq!(
            std::fs::read(&checkpoint_path).must("untouched witness"),
            current_witness
        );
    }
    std::fs::write(registry_path.join("registry.json"), current_manifest)
        .must("restore current manifest");
    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &registry_path,
        &checkpoint_path,
        "agent:test:prompt.registry",
        64,
    )
    .must("newer committed extents remain recoverable");
    assert!(
        reopened
            .registry()
            .must("registry")
            .factor(&id("factor:1"))
            .is_some()
    );
}

#[test]
fn damaged_independent_witness_poison_writer_before_further_reads_or_writes() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test:prompt.registry",
        64,
    )
    .must("guarded owner");
    owner.register_factor(factor(0)).must("first factor");
    let before = std::fs::read(path.join("registry.json")).must("old manifest");
    let witness = std::fs::read(&checkpoint).must("retained witness");
    std::fs::write(&checkpoint, b"damaged witness").must("simulate witness corruption");
    assert!(owner.register_factor(factor(1)).is_err());
    assert!(owner.requires_reopen());
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    assert!(matches!(
        owner.register_factor(factor(2)),
        Err(DurableRegistryError::ReopenRequired)
    ));
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest unchanged"),
        before
    );
    drop(owner);
    std::fs::write(&checkpoint, witness).must("restore independently retained exact witness");
    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test:prompt.registry",
        64,
    )
    .must("reconcile exact predecessor");
    assert!(
        reopened
            .registry()
            .must("registry")
            .factor(&id("factor:1"))
            .is_none()
    );
}

#[test]
fn new_factor_cannot_consume_capacity_reserved_for_retirement_and_revocation() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner
        .commit(|core| add_payload(core, 0))
        .must("seed active realization");
    let before = std::fs::read(path.join("registry.json")).must("manifest");
    let limit = before.len() as u64 + capacity::reserved_bytes(owner.registry().must("registry"));
    owner.store.metadata_limit.set(limit);
    assert!(matches!(
        owner.register_factor(factor(1)),
        Err(DurableRegistryError::CapacityExceeded)
    ));
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("unchanged"),
        before
    );
    owner
        .retire_factor(
            &id("factor:0"),
            &id("operator:test"),
            digest("retire at capacity"),
        )
        .must("reserved retirement");
    owner
        .revoke_factor(
            &id("factor:0"),
            &id("operator:test"),
            digest("revoke at capacity"),
            1,
        )
        .must("reserved revocation");
    assert!(
        std::fs::metadata(path.join("registry.json"))
            .must("manifest size")
            .len()
            <= limit
    );
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen revoked owner");
    assert_eq!(
        reopened
            .registry()
            .must("registry")
            .factor(&id("factor:0"))
            .must("factor")
            .lifecycle,
        Lifecycle::Revoked
    );
}

#[test]
fn invalid_guarded_initial_configuration_is_side_effect_free_and_retryable() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("checkpoint.json");
    for (witness, owner_id) in [
        (
            std::path::PathBuf::from("relative-checkpoint.json"),
            "agent:test",
        ),
        (path.join("checkpoint.json"), "agent:test"),
        (checkpoint.clone(), ""),
    ] {
        assert!(
            DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
                &path, &witness, owner_id, 64
            )
            .is_err()
        );
        assert!(
            !path.exists(),
            "bad arguments must not create registry.lock"
        );
    }
    DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test",
        64,
    )
    .must("corrected initial configuration");
}

#[test]
fn guarded_post_rename_uncertainty_reconciles_exact_pending_successor() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test",
        64,
    )
    .must("owner");
    owner.register_factor(factor(0)).must("predecessor");
    let old_manifest = std::fs::read(path.join("registry.json")).must("old manifest");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(factor(1)),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(owner.requires_reopen());
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test",
        64,
    )
    .must("pending successor reconciliation");
    assert!(
        reopened
            .registry()
            .must("registry")
            .factor(&id("factor:1"))
            .is_some()
    );
    drop(reopened);
    std::fs::write(path.join("registry.json"), old_manifest)
        .must("attempt predecessor rollback after promotion");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &path,
            &checkpoint,
            "agent:test",
            64
        ),
        Err(DurableRegistryError::RollbackDetected)
    ));
}

#[test]
fn guarded_precommit_storage_full_aborts_pending_without_changing_predecessor() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let checkpoint = temp.path().join("witness").join("checkpoint.json");
    let mut owner = DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &path,
        &checkpoint,
        "agent:test",
        64,
    )
    .must("owner");
    owner.register_factor(factor(0)).must("predecessor");
    let old_manifest = std::fs::read(path.join("registry.json")).must("old manifest");
    let old_witness = std::fs::read(&checkpoint).must("old witness");
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.register_factor(factor(1)),
        Err(DurableRegistryError::StorageFull)
    ));
    assert!(!owner.requires_reopen());
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        old_manifest
    );
    assert_eq!(std::fs::read(&checkpoint).must("witness"), old_witness);
    owner
        .register_factor(factor(1))
        .must("retry after proven precommit failure");
}

#[test]
fn unsafe_checkpoint_parent_is_rejected_before_initial_registry_creation() {
    use std::os::unix::fs::PermissionsExt;
    let temp = tempfile::tempdir().must("temp");
    let root = temp.path().join("registry");
    let shared = temp.path().join("shared-checkpoints");
    std::fs::create_dir(&shared).must("shared parent");
    std::fs::set_permissions(&shared, std::fs::Permissions::from_mode(0o755))
        .must("non-private checkpoint parent");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &root,
            &shared.join("checkpoint.json"),
            "agent:test",
            64,
        ),
        Err(DurableRegistryError::UnsafeRecoveryCheckpoint)
    ));
    assert!(
        !root.exists(),
        "invalid parent must not strand a writer lock"
    );
    let checkpoint = temp
        .path()
        .join("private-checkpoints")
        .join("checkpoint.json");
    drop(
        DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
            &root,
            &checkpoint,
            "agent:test",
            64,
        )
        .must("corrected initial open"),
    );
    DurablePromptRegistry::open_state_dir_with_recovery_checkpoint(
        &root,
        &checkpoint,
        "agent:test",
        64,
    )
    .must("reopen corrected registry");
}
