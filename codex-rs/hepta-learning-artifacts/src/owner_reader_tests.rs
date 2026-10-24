//! Malformed-store controls through the actual original-owner reader.
use super::revocation_tests::published;
use super::*;
use crate::ArtifactOwnerCurrentReaderV1;
use crate::test_support::FixtureValue;
use std::fs;
use std::time::Instant;

#[test]
fn reader_requires_canonical_root_and_rejects_ancestor_aliases() {
    let (directory, config, service, _) = published();
    let anchor = service
        .host
        .discover_current_head(/*now*/ 20)
        .fixture("current")
        .fixture("anchor")
        .signed;
    let reader =
        ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust.clone(), anchor.clone())
            .fixture("canonical reader");
    pretty_assertions::assert_eq!(
        reader
            .current_registry_view(/*now*/ 20)
            .fixture("read")
            .receipt(),
        service
            .current_registry_view(/*now*/ 20)
            .fixture("owner read")
            .receipt()
    );

    let aliases = super::tests::TestDir::new();
    let root_alias = aliases.0.join("root-alias");
    std::os::unix::fs::symlink(&directory.0, &root_alias).fixture("root alias");
    let parent_alias = aliases.0.join("parent-alias");
    std::os::unix::fs::symlink(directory.0.parent().fixture("owner parent"), &parent_alias)
        .fixture("parent alias");
    let through_parent = parent_alias.join(directory.0.file_name().fixture("owner name"));
    for root in [root_alias, through_parent] {
        assert!(matches!(
            ArtifactOwnerCurrentReaderV1::open(root, config.trust.clone(), anchor.clone()),
            Err(ArtifactOwnerHostError::CurrentObservationFence)
        ));
    }
}

#[test]
fn reader_requires_existing_observation_inode_and_never_recreates_it() {
    let (directory, config, service, _) = published();
    let anchor = service
        .host
        .discover_current_head(/*now*/ 20)
        .fixture("current")
        .fixture("anchor")
        .signed;
    let reader =
        ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust.clone(), anchor.clone())
            .fixture("reader");
    let lock = directory.0.join("writer/current-observation.lock");
    let original = fs::read(&lock).fixture("retained lock bytes");
    fs::remove_file(&lock).fixture("remove lock");
    assert!(reader.current_registry_view(/*now*/ 20).is_err());
    assert!(ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust, anchor).is_err());
    assert!(!lock.exists(), "reader must not bootstrap a missing fence");
    fs::write(&lock, original).fixture("same bytes, different inode");
    assert!(matches!(
        reader.current_registry_view(/*now*/ 20),
        Err(ArtifactOwnerHostError::CurrentObservationFence)
    ));
    assert!(matches!(
        service.host.acquire_current_observation_exclusive(),
        Err(ArtifactOwnerHostError::CurrentObservationFence)
    ));
}

#[test]
fn reader_rejects_noncanonical_checkpoint_copies_and_unknown_entries() {
    for checkpoint_copy in [false, true] {
        let (directory, config, service, _) = published();
        let anchor = service
            .host
            .discover_current_head(/*now*/ 20)
            .fixture("current")
            .fixture("anchor")
            .signed;
        let reader = ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust, anchor)
            .fixture("reader");
        let transactions = directory.0.join("transactions");
        if checkpoint_copy {
            let ack = fs::read_dir(&transactions)
                .fixture("entries")
                .map(|entry| entry.fixture("entry").path())
                .find(|path| path.to_string_lossy().ends_with("-4.checkpoint"))
                .fixture("ACK path");
            fs::copy(ack, transactions.join("noncanonical.checkpoint"))
                .fixture("copied valid checkpoint");
        } else {
            fs::write(transactions.join("ignored.extension"), b"ignored").fixture("unknown entry");
        }
        assert!(matches!(
            reader.current_registry_view(/*now*/ 20),
            Err(ArtifactOwnerHostError::CheckpointMismatch)
        ));
    }
}

#[test]
fn current_directory_bounds_count_every_entry_before_decoding_unique_operations() {
    let (directory, config, service, _) = published();
    let anchor = service
        .host
        .discover_current_head(/*now*/ 20)
        .fixture("current")
        .fixture("anchor")
        .signed;
    let reader =
        ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust, anchor).fixture("reader");
    // Unknown names would previously evade the unique-operation set entirely.
    for index in 0..20_481 {
        fs::write(
            directory
                .0
                .join("transactions")
                .join(format!("extra-{index}.ignored")),
            b"",
        )
        .fixture("entry");
    }
    assert!(matches!(
        reader.current_registry_view(/*now*/ 20),
        Err(ArtifactOwnerHostError::Capacity)
    ));
    assert!(matches!(
        service.host.current_registry_view(/*now*/ 20),
        Err(ArtifactOwnerHostError::Capacity)
    ));
}

#[test]
fn signed_snapshot_replaced_by_fifo_rejects_before_blocking_open() {
    let (directory, config, service, _) = published();
    let anchor = service
        .host
        .discover_current_head(/*now*/ 20)
        .fixture("current")
        .fixture("anchor")
        .signed;
    let receipt = service
        .current_registry_view(/*now*/ 20)
        .fixture("original current")
        .receipt();
    let reader =
        ArtifactOwnerCurrentReaderV1::open(&directory.0, config.trust, anchor).fixture("reader");
    let snapshot = directory.0.join("registries").join(format!(
        "{}-{}.snapshot",
        receipt.head_digest, receipt.file_digest
    ));
    fs::remove_file(&snapshot).fixture("remove snapshot");
    let status = std::process::Command::new("mkfifo")
        .arg(&snapshot)
        .status()
        .fixture("mkfifo");
    assert!(status.success());
    let started = Instant::now();
    assert!(matches!(
        reader.current_registry_view(/*now*/ 20),
        Err(ArtifactOwnerHostError::CurrentObservationFence)
    ));
    assert!(
        started.elapsed().as_secs() < 1,
        "FIFO must fail before a blocking read"
    );
}
