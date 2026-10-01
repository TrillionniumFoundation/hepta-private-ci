//! Current-cut recovery rejects valid rollbacks and forks before any repair.

use std::cell::Cell;
use std::io::Write;
use std::os::unix::fs::DirBuilderExt;
use std::os::unix::fs::MetadataExt;

use super::*;
use crate::Digest32;
use crate::FactorSource;
use crate::Lifecycle;
use crate::PromptFactor;
use crate::StableId;
use crate::TestMust;
use crate::durable::Access;
use crate::durable::open_private;
use crate::durable::payload_tests::add_payload;
use crate::durable::payloads;
use crate::durable::prepare_directory;
use crate::durable::prepare_directory_with_parent_sync;
use crate::durable::stored_v2;

fn id(value: &str) -> StableId {
    StableId::new(value).must("test identity")
}

fn factor(index: usize) -> PromptFactor {
    PromptFactor {
        factor_id: id(&format!("factor:recovery:{index}")),
        proposer_id: id("proposer:recovery"),
        semantic_version: id("v1"),
        semantic_purpose: "independent recovery cut".into(),
        authority_class: "registered_prompt_factor".into(),
        eligible_objective_dimensions: Vec::new(),
        content_digest: Digest32::of_bytes(format!("recovery-factor:{index}").as_bytes()),
        source: FactorSource::GovernedInternal,
        lifecycle: Lifecycle::Draft,
    }
}

#[test]
fn invalid_recovery_anchor_and_capacity_are_rejected_before_filesystem_access() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("absent-owner");
    let valid = PromptRegistryRecoveryAnchor::from_registry(&PromptRegistry::new(64).must("core"));
    for fault in [
        "zero-revision",
        "zero-digest",
        "revocation",
        "lifecycle",
        "incomplete-frontier",
    ] {
        let mut invalid = valid;
        match fault {
            "zero-revision" => invalid.revision = 0,
            "zero-digest" => invalid.registry_digest = [0; 32],
            "revocation" => invalid.revocation_frontier = 1,
            "lifecycle" => invalid.lifecycle_frontier = 2,
            "incomplete-frontier" => invalid.revision = 2,
            _ => unreachable!(),
        }
        assert!(
            matches!(
                DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &invalid),
                Err(DurableRegistryError::InvalidRecoveryAnchor)
            ),
            "{fault}"
        );
        assert!(!path.exists());
    }
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 0, &valid),
        Err(DurableRegistryError::Core(_))
    ));
    assert!(!path.exists());
}

#[test]
fn anchored_recovery_requires_existing_state_without_bootstrap_or_new_marker() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let anchor = PromptRegistryRecoveryAnchor::from_registry(&PromptRegistry::new(64).must("core"));
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &anchor),
        Err(DurableRegistryError::RecoveryStateMissing)
    ));
    assert!(!path.exists());
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&path)
        .must("private directory");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &anchor),
        Err(DurableRegistryError::RecoveryStateMissing)
    ));
    assert_eq!(std::fs::read_dir(&path).must("entries").count(), 0);
    let directory = prepare_directory(&path).must("directory");
    drop(open_private(&directory, "registry.lock", Access::CreateNew).must("old marker"));
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &anchor),
        Err(DurableRegistryError::RecoveryStateMissing)
    ));
    assert_eq!(std::fs::read_dir(&path).must("entries").count(), 1);
    assert!(path.join("registry.lock").is_file());
}

#[test]
fn valid_old_backup_is_rejected_against_the_independent_post_revocation_cut() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let backup = temp.path().join("old-backup");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&backup)
        .must("backup directory");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.commit(|core| add_payload(core, 0)).must("payload");
    let old = owner.recovery_anchor().must("old cut");
    for name in ["registry.json", payloads::FILE_NAME] {
        std::fs::copy(path.join(name), backup.join(name)).must("backup file");
    }
    owner
        .revoke_factor(
            &id("factor:0"),
            &id("operator"),
            Digest32::of_bytes(b"revoked"),
            7,
        )
        .must("revoke");
    let current = owner.recovery_anchor().must("independent current cut");
    assert_ne!(old, current);
    drop(owner);
    // An old acknowledged cut is not a floor: complete mutation extension is
    // not retained here, so a later current image also needs its exact witness.
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &old),
        Err(DurableRegistryError::RecoveryAnchorMismatch)
    ));
    for name in ["registry.json", payloads::FILE_NAME] {
        std::fs::copy(backup.join(name), path.join(name)).must("restore valid old backup");
    }
    let selected = std::fs::read(path.join("registry.json")).must("old manifest");
    let payloads = std::fs::read(path.join(payloads::FILE_NAME)).must("old payloads");
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &current),
        Err(DurableRegistryError::RecoveryAnchorMismatch)
    ));
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        selected
    );
    assert_eq!(
        std::fs::read(path.join(payloads::FILE_NAME)).must("payloads"),
        payloads
    );
    // Internal integrity alone cannot distinguish this valid predecessor.
    let unanchored =
        DurablePromptRegistry::open_state_dir(&path, 64).must("internally valid backup");
    assert_eq!(unanchored.recovery_anchor().must("cut"), old);
    assert_eq!(
        unanchored
            .registry()
            .must("registry")
            .factor(&id("factor:0"))
            .must("factor")
            .lifecycle,
        Lifecycle::Admitted
    );
}

#[test]
fn independently_retained_cut_rejects_a_valid_equal_revision_fork() {
    let temp = tempfile::tempdir().must("temp");
    let first_path = temp.path().join("first");
    let second_path = temp.path().join("second");
    let mut first = DurablePromptRegistry::open_state_dir(&first_path, 64).must("first");
    let mut second = DurablePromptRegistry::open_state_dir(&second_path, 64).must("second");
    first.register_factor(factor(0)).must("first factor");
    second.register_factor(factor(1)).must("second factor");
    let expected = first.recovery_anchor().must("current cut");
    let fork = second.recovery_anchor().must("fork cut");
    assert_eq!(
        (
            expected.revision,
            expected.lifecycle_frontier,
            expected.revocation_frontier
        ),
        (
            fork.revision,
            fork.lifecycle_frontier,
            fork.revocation_frontier
        )
    );
    assert_ne!(expected.registry_digest, fork.registry_digest);
    drop(second);
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&second_path, 64, &expected),
        Err(DurableRegistryError::RecoveryAnchorMismatch)
    ));
}

#[test]
fn rejected_current_cut_never_trims_an_unselected_payload_tail() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.commit(|core| add_payload(core, 0)).must("payload");
    let expected = owner.recovery_anchor().must("independent cut");
    let file_path = path.join(payloads::FILE_NAME);
    let committed = std::fs::read(&file_path).must("committed extents");
    std::fs::OpenOptions::new()
        .append(true)
        .open(&file_path)
        .must("extents")
        .write_all(b"unselected payload tail")
        .must("tail");
    drop(owner);
    let unselected = std::fs::read(&file_path).must("unselected extents");
    let manifest = std::fs::read(path.join("registry.json")).must("manifest");
    let mut wrong = expected;
    wrong.registry_digest = Digest32::of_bytes(b"different current cut").into_array();
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &wrong),
        Err(DurableRegistryError::RecoveryAnchorMismatch)
    ));
    assert_eq!(std::fs::read(&file_path).must("extents"), unselected);
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("manifest"),
        manifest
    );
    let recovered =
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &expected)
            .must("matching recovery");
    assert_eq!(recovered.recovery_anchor().must("cut"), expected);
    assert_eq!(std::fs::read(&file_path).must("trimmed extents"), committed);
}

#[test]
fn current_cut_comparison_precedes_legacy_migration_and_allows_a_matching_v2_image() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let directory = prepare_directory(&path).must("private owner directory");
    let mut core = PromptRegistry::new(64).must("core");
    add_payload(&mut core, 0).must("payload fixture");
    let expected = PromptRegistryRecoveryAnchor::from_registry(&core);
    let bytes = serde_json::to_vec(&stored_v2(&core)).must("legacy image");
    let mut file = open_private(&directory, "registry.json", Access::Create).must("legacy file");
    file.write_all(&bytes).must("legacy bytes");
    file.sync_all().must("legacy sync");
    let mut wrong = expected;
    wrong.registry_digest = Digest32::of_bytes(b"wrong legacy cut").into_array();
    assert!(matches!(
        DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &wrong),
        Err(DurableRegistryError::RecoveryAnchorMismatch)
    ));
    assert_eq!(
        std::fs::read(path.join("registry.json")).must("legacy image"),
        bytes
    );
    assert!(!path.join(payloads::FILE_NAME).exists());
    assert!(!path.join("registry.next").exists());
    let owner = DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &expected)
        .must("matching migrated owner");
    assert_eq!(owner.registry().must("registry"), &core);
    assert_eq!(owner.recovery_anchor().must("semantic cut"), expected);
    let selected: serde_json::Value =
        serde_json::from_slice(&std::fs::read(path.join("registry.json")).must("selected image"))
            .must("JSON");
    assert_eq!(selected["schema"], 3);
    assert!(path.join(payloads::FILE_NAME).is_file());
}

#[test]
fn matching_v1_semantic_cut_migrates_without_changing_its_recovery_anchor() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let directory = prepare_directory(&path).must("private owner directory");
    let legacy = crate::durable::StoredV1 {
        schema: 1,
        revision: 1,
        lifecycle_frontier: 0,
        revocation_frontier: 0,
        maximum_records: 64,
        factors: Vec::new(),
        realizations: Vec::new(),
        bindings: Vec::new(),
    };
    let core = PromptRegistry::new(64).must("empty semantic image");
    let expected = PromptRegistryRecoveryAnchor::from_registry(&core);
    let mut file = open_private(&directory, "registry.json", Access::Create).must("legacy file");
    file.write_all(&serde_json::to_vec(&legacy).must("legacy bytes"))
        .must("write legacy");
    file.sync_all().must("sync legacy");
    let owner = DurablePromptRegistry::open_state_dir_with_recovery_anchor(&path, 64, &expected)
        .must("matching V1 semantic cut");
    assert_eq!(owner.registry().must("registry"), &core);
    assert_eq!(owner.recovery_anchor().must("migrated cut"), expected);
    assert!(path.join(payloads::FILE_NAME).is_file());
}

#[test]
fn poisoned_owner_cannot_publish_a_recovery_anchor() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let mut owner = DurablePromptRegistry::open_state_dir(&path, 64).must("owner");
    owner.fail_directory_sync_after_rename_once();
    assert!(matches!(
        owner.register_factor(factor(0)),
        Err(DurableRegistryError::IndeterminateDurability)
    ));
    assert!(matches!(
        owner.recovery_anchor(),
        Err(DurableRegistryError::ReopenRequired)
    ));
}

#[test]
fn failed_parent_directory_sync_is_retried_even_after_the_directory_exists() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let attempts = Cell::new(0);
    assert!(matches!(
        prepare_directory_with_parent_sync(&path, OpenPolicy::BootstrapAllowed, |_parent| {
            attempts.set(attempts.get() + 1);
            Err(std::io::Error::from_raw_os_error(5))
        }),
        Err(DurableRegistryError::Unavailable)
    ));
    assert!(path.is_dir());
    assert!(!path.join("registry.lock").exists());
    let directory =
        prepare_directory_with_parent_sync(&path, OpenPolicy::BootstrapAllowed, |parent| {
            attempts.set(attempts.get() + 1);
            parent.sync_all()
        })
        .must("retry fence on existing directory");
    assert_eq!(attempts.get(), 2);
    drop(directory);
    DurablePromptRegistry::open_state_dir(&path, 64).must("durable initialization after retry");
}

#[test]
fn owner_alias_path_syncs_its_actual_parent_directory() {
    let temp = tempfile::tempdir().must("temp");
    let path = temp.path().join("owner");
    let owner = prepare_directory(&path).must("private owner");
    let child = path.join("child");
    std::fs::DirBuilder::new()
        .mode(0o700)
        .create(&child)
        .must("private child");
    let expected_parent = std::fs::metadata(temp.path()).must("actual parent");
    let expected_owner = owner.metadata().must("owner metadata");
    let attempts = Cell::new(0);
    let aliased = prepare_directory_with_parent_sync(
        &child.join(".."),
        OpenPolicy::BootstrapAllowed,
        |parent| {
            attempts.set(attempts.get() + 1);
            let actual = parent.metadata()?;
            assert_eq!(
                (actual.dev(), actual.ino()),
                (expected_parent.dev(), expected_parent.ino())
            );
            parent.sync_all()
        },
    )
    .must("owner parent fence through alias");
    assert_eq!(attempts.get(), 1);
    let actual_owner = aliased.metadata().must("aliased owner metadata");
    assert_eq!(
        (actual_owner.dev(), actual_owner.ino()),
        (expected_owner.dev(), expected_owner.ino())
    );
}
