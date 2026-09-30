use super::*;
use crate::Lifecycle;
use crate::TestMust;
use crate::durable::maintenance::tests::add_payload;
use crate::durable::maintenance::tests::seeded;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use std::io::Write;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn retire(owner: &mut DurablePromptRegistry, index: usize) {
    owner
        .retire_factor(
            &id(&format!("factor:{index}")),
            &id("operator:test"),
            Digest32::of_bytes(b"retire"),
        )
        .must("retire");
}

#[test]
fn gc_reclaims_inactive_raw_bytes_but_preserves_audit_and_revocation_after_restart() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    owner
        .commit(|core| add_payload(core, 1))
        .must("second payload");
    owner
        .revoke_factor(
            &id("factor:0"),
            &id("operator:test"),
            Digest32::of_bytes(b"withdraw"),
            1,
        )
        .must("revoke");
    let before = owner.registry().must("registry").clone();
    let receipt = owner.collect_payload_garbage().must("collect");
    let after = owner.registry().must("registry");
    assert_eq!(receipt.collected_payload_records, 1);
    assert_eq!(receipt.collected_payload_bytes, 16 * 1024);
    assert_eq!(receipt.selected_revision, receipt.source_revision + 1);
    assert!(!receipt.cleanup_pending);
    assert!(!path.join("registry.payloads").exists());
    assert!(path.join("registry.payloads.alternate").is_file());
    assert_eq!(after.factors, before.factors);
    assert_eq!(after.relations, before.relations);
    assert_eq!(after.lifecycle_events, before.lifecycle_events);
    assert_eq!(
        after.realization_supersessions,
        before.realization_supersessions
    );
    assert_eq!(after.revocation_frontier, before.revocation_frontier);
    assert!(
        !after
            .realization_payloads
            .contains_key(&id("realization:0"))
    );
    assert_eq!(
        after.realization_payloads.get(&id("realization:1")),
        before.realization_payloads.get(&id("realization:1"))
    );
    let expected = after.clone();
    drop(owner);
    let reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen");
    assert_eq!(reopened.registry().must("registry"), &expected);
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
fn gc_identical_retry_is_noop_and_two_generations_reuse_bounded_slots() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    let first = owner.collect_payload_garbage().must("collect");
    let again = owner.collect_payload_garbage().must("retry");
    assert_eq!(again.collected_payload_records, 0);
    assert_eq!(again.selected_revision, first.selected_revision);
    assert_eq!(
        again.selected_registry_digest,
        first.selected_registry_digest
    );
    owner
        .commit(|core| add_payload(core, 1))
        .must("new payload");
    retire(&mut owner, 1);
    let second = owner.collect_payload_garbage().must("next collection");
    assert_eq!(second.collected_payload_records, 1);
    assert!(path.join("registry.payloads").is_file());
    assert!(!path.join("registry.payloads.alternate").exists());
    let json: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path.join("registry.json")).must("metadata"))
            .must("json");
    assert_eq!(json["schema"], 5);
    assert_eq!(json["payload_slot"], "primary");
    let expected = owner.registry().must("registry").clone();
    drop(owner);
    assert_eq!(
        DurablePromptRegistry::open_state_dir(&path, 64)
            .must("reopen")
            .registry()
            .must("registry"),
        &expected
    );
}

#[test]
fn gc_before_publication_failure_retains_selected_predecessor() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    let before = owner.registry().must("registry").clone();
    let metadata = std::fs::read(path.join("registry.json")).must("metadata");
    owner.fail_storage_full_before_rename_once();
    assert!(matches!(
        owner.collect_payload_garbage(),
        Err(DurableRegistryError::StorageFull)
    ));
    assert_eq!(owner.registry().must("available"), &before);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("metadata"),
        metadata
    );
    assert!(path.join("registry.payloads").is_file());
    assert_eq!(
        owner
            .operational_metrics()
            .must("metrics")
            .io
            .storage_full_rejections,
        1
    );
    assert_eq!(
        owner
            .collect_payload_garbage()
            .must("retry")
            .collected_payload_records,
        1
    );
}

#[test]
fn gc_indeterminate_publication_poison_preserves_both_slots_until_reopen() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    let revision = owner.registry().must("registry").revision().get();
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.collect_payload_garbage(),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(matches!(
        owner.registry(),
        Err(DurableRegistryError::ReopenRequired)
    ));
    assert!(path.join("registry.payloads").is_file());
    assert!(path.join("registry.payloads.alternate").is_file());
    assert_eq!(
        owner
            .operational_metrics()
            .must("diagnostics")
            .io
            .indeterminate_publications,
        1
    );
    drop(owner);
    let mut reopened = DurablePromptRegistry::open_state_dir(&path, 64).must("reconcile");
    assert_eq!(
        reopened.registry().must("registry").revision().get(),
        revision + 1
    );
    let retry = reopened.collect_payload_garbage().must("cleanup retry");
    assert_eq!(retry.collected_payload_records, 0);
    assert_eq!(retry.selected_revision, revision + 1);
    assert!(!retry.cleanup_pending);
    assert!(!path.join("registry.payloads").exists());
}

#[test]
fn gc_corrupt_selected_generation_never_falls_back_to_old_payloads() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    owner.commit(|core| add_payload(core, 1)).must("second");
    retire(&mut owner, 0);
    owner.fail_directory_sync_after_rename_once();
    assert!(owner.collect_payload_garbage().is_err());
    drop(owner);
    let selected = path.join("registry.payloads.alternate");
    let mut bytes = std::fs::read(&selected).must("selected");
    *bytes.last_mut().must("payload byte") ^= 1;
    std::fs::write(&selected, bytes).must("inject corruption");
    assert!(DurablePromptRegistry::open_state_dir(&path, 64).is_err());
    assert!(path.join("registry.payloads").is_file());
}

#[test]
fn gc_cleanup_never_follows_unselected_symlink() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    let outside = temp.path().join("outside");
    std::fs::write(&outside, b"keep").must("outside");
    let alternate = path.join("registry.payloads.alternate");
    std::os::unix::fs::symlink(&outside, &alternate).must("symlink");
    let receipt = owner.collect_payload_garbage().must("no-op collection");
    assert!(receipt.cleanup_pending);
    assert_eq!(std::fs::read(&outside).must("outside"), b"keep");
    assert!(
        std::fs::symlink_metadata(&alternate)
            .must("link")
            .file_type()
            .is_symlink()
    );
}

#[test]
fn gc_readonly_v5_restore_verifies_selected_slot_without_mutating_files() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    let gc = owner.collect_payload_garbage().must("collect");
    let metadata = std::fs::read(path.join("registry.json")).must("metadata");
    let payload = std::fs::read(path.join("registry.payloads.alternate")).must("payload");
    drop(owner);
    let verified = DurablePromptRegistry::verify_restore_checkpoint(
        &path,
        64,
        Some(gc.selected_revision),
        Some(gc.selected_registry_digest),
    )
    .must("verify");
    assert!(verified.verified);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("metadata"),
        metadata
    );
    assert_eq!(
        std::fs::read(path.join("registry.payloads.alternate")).must("payload"),
        payload
    );
    assert!(!path.join("registry.payloads").exists());
}

#[test]
fn gc_v5_manifest_rejects_unknown_slot_before_opening_an_arbitrary_path() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    owner.collect_payload_garbage().must("collect");
    drop(owner);
    let file = path.join("registry.json");
    let mut json: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&file).must("metadata")).must("json");
    json["payload_slot"] = serde_json::json!("../outside");
    std::fs::write(file, serde_json::to_vec(&json).must("encode")).must("inject");
    assert!(DurablePromptRegistry::open_state_dir(&path, 64).is_err());
    assert!(!temp.path().join("outside").exists());
}

#[test]
fn gc_orphan_slot_cleanup_does_not_change_authoritative_revision() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let mut owner = seeded(&path);
    let before = owner.registry().must("registry").clone();
    let mut file = open_private(
        &owner.store.root,
        "registry.payloads.alternate",
        Access::Create,
    )
    .must("orphan");
    file.write_all(b"aborted unselected write")
        .must("orphan bytes");
    file.sync_all().must("sync");
    drop(file);
    let receipt = owner.collect_payload_garbage().must("cleanup");
    assert_eq!(receipt.collected_payload_records, 0);
    assert_eq!(receipt.unlinked_file_bytes, 24);
    assert!(!receipt.cleanup_pending);
    assert_eq!(owner.registry().must("registry"), &before);
    let io = owner.operational_metrics().must("metrics").io;
    assert_eq!(io.publish_attempts, io.successful_publications);
    assert_eq!(io.successful_publications, io.metadata_sync_attempts);
    assert!(io.metadata_bytes_written > 0);
}

#[test]
#[ignore = "subprocess fixture; executed by gc_process_exit_after_unknown_commit_reconciles"]
fn gc_crash_child() {
    let Some(directory) = std::env::var_os("HEPTA_PROMPT_REGISTRY_GC_CRASH_TEST_DIR") else {
        panic!("GC crash helper requires its parent fixture");
    };
    let path = std::path::PathBuf::from(directory);
    let mut owner = seeded(&path);
    retire(&mut owner, 0);
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.collect_payload_garbage(),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    // No destructors or orderly owner shutdown: the parent starts a new owner.
    std::process::exit(73);
}

#[test]
fn gc_process_exit_after_unknown_commit_reconciles() {
    let temp = tempfile::tempdir().must("tempdir");
    let path = temp.path().join("owner");
    let output = std::process::Command::new(std::env::current_exe().must("test executable"))
        .args([
            "--exact",
            "durable::gc::tests::gc_crash_child",
            "--ignored",
            "--test-threads=1",
        ])
        .env("HEPTA_PROMPT_REGISTRY_GC_CRASH_TEST_DIR", &path)
        .output()
        .must("child process");
    assert_eq!(
        output.status.code(),
        Some(73),
        "{}",
        String::from_utf8_lossy(&output.stdout)
    );
    assert!(path.join("registry.payloads").exists());
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("reopen after exit");
    assert_eq!(
        owner
            .registry()
            .must("registry")
            .factor(&id("factor:0"))
            .must("factor")
            .lifecycle,
        Lifecycle::Retired
    );
    let receipt = owner.collect_payload_garbage().must("finish cleanup");
    assert_eq!(receipt.collected_payload_records, 0);
    assert!(!receipt.cleanup_pending);
    assert!(!path.join("registry.payloads").exists());
}
