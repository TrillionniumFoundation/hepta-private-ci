use super::*;

use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(1);

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-neuron-manifest-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&path));
        Self(path)
    }

    fn manifest(&self) -> PathBuf {
        self.0.join("manifest.json")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: digest(&format!("checkpoint-{sequence}")),
    }
}

fn bootstrap() -> NeuronStoreManifestV1 {
    checked(NeuronStoreManifestV1::bootstrap(
        NeuronStoreBootstrapV1 {
            generation: checked(Generation::new(7)),
            scope: JournalScope {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
            },
            runtime_config_digest: digest("runtime-config"),
            key_epoch: 1,
            key_receipt_digest: None,
            deletion_epoch: 1,
            deletion_receipt_digest: None,
            predecessor_manifest_digest: None,
            journal_file_name: "journal-0000.bin".to_owned(),
            journal_header_digest: digest("journal-header-0"),
            journal_header_bytes: 136,
            witness_file_name: "witness-0000.bin".to_owned(),
            witness_header_digest: digest("witness-header-0"),
            witness_header_bytes: 112,
            operation_file_name: "operations.bin".to_owned(),
            operation_header_digest: digest("operation-header"),
            operation_header_bytes: 256,
        },
    ))
}

#[test]
fn atomic_manifest_round_trip_and_frontier_replacement_are_exact() {
    let fixture = Fixture::new();
    let manifest = bootstrap();
    checked(write_neuron_store_manifest_v1(
        &fixture.manifest(),
        &manifest,
    ));
    assert_eq!(
        checked(read_neuron_store_manifest_v1(&fixture.manifest())),
        manifest
    );

    let advanced = checked(manifest.advance_completed_frontier(
        None,
        anchor(1),
        520,
        224,
        4096,
    ));
    checked(write_neuron_store_manifest_v1(
        &fixture.manifest(),
        &advanced,
    ));
    assert_eq!(
        checked(read_neuron_store_manifest_v1(&fixture.manifest())),
        advanced
    );
    let entries = checked(fs::read_dir(&fixture.0)).collect::<Result<Vec<_>, _>>();
    assert_eq!(entries.len(), 1);
}

#[test]
fn paired_rollover_publishes_one_seeded_chain_and_bounded_replay_plan() {
    let first = checked(bootstrap().advance_completed_frontier(
        None,
        anchor(1),
        520,
        224,
        4096,
    ));
    let rolled = checked(first.rollover_pair(
        "journal-0001.bin".to_owned(),
        digest("journal-header-1"),
        176,
        "witness-0001.bin".to_owned(),
        digest("witness-header-1"),
        152,
    ));
    assert_eq!(rolled.current_journal_ordinal, 1);
    assert_eq!(rolled.current_witness_ordinal, 1);
    let journal = rolled
        .segments
        .iter()
        .find(|segment| {
            segment.kind == NeuronStoreSegmentKindV1::Journal && segment.ordinal == 1
        })
        .expect("journal successor");
    let witness = rolled
        .segments
        .iter()
        .find(|segment| {
            segment.kind == NeuronStoreSegmentKindV1::Witness && segment.ordinal == 1
        })
        .expect("witness successor");
    assert_eq!(journal.seed_anchor, Some(anchor(1)));
    assert_eq!(journal.frontier_anchor, Some(anchor(1)));
    assert_eq!(witness.seed_anchor, Some(anchor(1)));
    assert_eq!(witness.frontier_anchor, Some(anchor(1)));

    let plan = checked(rolled.bounded_replay_plan(2, 16 * 1024));
    assert_eq!(
        plan.journal_files,
        vec!["journal-0000.bin", "journal-0001.bin"]
    );
    assert_eq!(
        plan.witness_files,
        vec!["witness-0000.bin", "witness-0001.bin"]
    );
    assert_eq!(plan.operation_file, "operations.bin");
    assert_eq!(plan.manifest_digest, rolled.manifest_digest);
    assert_eq!(
        rolled.bounded_replay_plan(1, 16 * 1024),
        Err(NeuronStoreManifestError::ReplayBound)
    );
    assert_eq!(
        rolled.bounded_replay_plan(2, 1),
        Err(NeuronStoreManifestError::ReplayBound)
    );
}

#[test]
fn migration_is_explicit_and_never_reinterprets_v1_bytes() {
    let manifest = checked(bootstrap().advance_completed_frontier(
        None,
        anchor(1),
        520,
        224,
        4096,
    ));
    let target = digest("population-v2-config");
    let transformer = digest("transformer-receipt");
    let prepared = checked(manifest.prepare_v2_migration(target, transformer));
    assert_eq!(prepared.migration.durable_version(), 1);
    assert_eq!(
        prepared.advance_completed_frontier(
            Some(anchor(1)),
            anchor(2),
            904,
            336,
            8192,
        ),
        Err(NeuronStoreManifestError::MigrationState)
    );

    let committed = checked(prepared.commit_v2_migration(
        target,
        transformer,
        digest("migrated-checkpoint"),
        digest("commit-receipt"),
    ));
    assert_eq!(committed.migration.durable_version(), 2);
    assert_eq!(
        committed.abort_v2_migration(target, transformer, digest("late-abort")),
        Err(NeuronStoreManifestError::MigrationState)
    );

    let aborted = checked(
        manifest
            .prepare_v2_migration(target, transformer)
            .and_then(|value| {
                value.abort_v2_migration(target, transformer, digest("abort-receipt"))
            }),
    );
    assert_eq!(aborted.migration.durable_version(), 1);
    assert!(matches!(
        aborted.migration,
        NeuronStoreMigrationV1::V1ToV2Aborted { .. }
    ));
}

#[test]
fn restore_fences_deleted_or_old_key_backups() {
    let manifest = checked(NeuronStoreManifestV1::bootstrap(
        NeuronStoreBootstrapV1 {
            generation: checked(Generation::new(9)),
            scope: JournalScope {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
            },
            runtime_config_digest: digest("runtime-config"),
            key_epoch: 3,
            key_receipt_digest: Some(digest("key-rotation-receipt")),
            deletion_epoch: 4,
            deletion_receipt_digest: Some(digest("deletion-rebuild-receipt")),
            predecessor_manifest_digest: Some(digest("predecessor-manifest")),
            journal_file_name: "journal-0000.bin".to_owned(),
            journal_header_digest: digest("journal-header"),
            journal_header_bytes: 136,
            witness_file_name: "witness-0000.bin".to_owned(),
            witness_header_digest: digest("witness-header"),
            witness_header_bytes: 112,
            operation_file_name: "operations.bin".to_owned(),
            operation_header_digest: digest("operation-header"),
            operation_header_bytes: 256,
        },
    ));
    checked(manifest.verify_restore_frontier(4, 3, digest("runtime-config")));
    assert_eq!(
        manifest.verify_restore_frontier(5, 3, digest("runtime-config")),
        Err(NeuronStoreManifestError::Conflict)
    );
    assert_eq!(
        manifest.verify_restore_frontier(4, 4, digest("runtime-config")),
        Err(NeuronStoreManifestError::Conflict)
    );
    assert_eq!(
        manifest.verify_restore_frontier(4, 3, digest("different-config")),
        Err(NeuronStoreManifestError::Conflict)
    );
}

#[test]
fn tampered_digest_unknown_fields_and_path_escape_fail_closed() {
    let fixture = Fixture::new();
    let manifest = bootstrap();
    checked(write_neuron_store_manifest_v1(
        &fixture.manifest(),
        &manifest,
    ));

    let bytes = checked(fs::read(&fixture.manifest()));
    let mut json: serde_json::Value = checked(serde_json::from_slice(&bytes));
    json["manifestDigest"] = serde_json::Value::String(digest("tampered").to_string());
    checked(fs::write(
        fixture.manifest(),
        checked(serde_json::to_vec_pretty(&json)),
    ));
    assert_eq!(
        read_neuron_store_manifest_v1(&fixture.manifest()),
        Err(NeuronStoreManifestError::DigestMismatch)
    );

    json["manifestDigest"] = serde_json::Value::String(manifest.manifest_digest.to_string());
    json["unexpectedCriticalField"] = serde_json::Value::Bool(true);
    checked(fs::write(
        fixture.manifest(),
        checked(serde_json::to_vec_pretty(&json)),
    ));
    assert_eq!(
        read_neuron_store_manifest_v1(&fixture.manifest()),
        Err(NeuronStoreManifestError::Json)
    );

    let mut invalid = bootstrap();
    invalid.segments[0].file_name = "../journal".to_owned();
    assert_eq!(
        invalid.validate(),
        Err(NeuronStoreManifestError::Invalid("file name"))
    );
}
