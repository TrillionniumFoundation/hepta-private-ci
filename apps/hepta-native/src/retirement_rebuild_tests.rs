use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::io::Write as _;

use super::RebuildBoundary;
use super::publish_bucket_batch;
use super::rebuild_buckets;
use super::spool_nonce;
use crate::error::ShellError;
use crate::journal::OperationPhase;
use crate::journal::OperationRecord;
use crate::journal::retirement_digest;
use crate::model::OperationKey;
use crate::model::PlatformAction;
use crate::model::TerminalStatus;
use crate::model::sha256_hex;
use crate::private_state::PrivateStateRoot;
use crate::retirement::BUCKET_SCHEMA;
use crate::retirement::Checkpoint;
use crate::retirement::Head;
use crate::retirement::IndexBucket;
use crate::retirement::RetirementStore;
use crate::retirement::SEGMENT_BYTES;
use crate::retirement::SEGMENT_SCHEMA;
use crate::retirement::Segment;
use crate::retirement::directory;
use crate::retirement::write_content_addressed;

fn seed_legacy(
    journal: &std::path::Path,
    groups: &[Vec<String>],
    records: &BTreeMap<String, String>,
) -> (PrivateStateRoot, Checkpoint, Vec<String>) {
    let root = PrivateStateRoot::open(directory(journal)).unwrap();
    let mut checkpoint = Checkpoint::default();
    let mut chain = Vec::new();
    for group in groups {
        let mut identities = group.clone();
        identities.sort_unstable();
        let record_digests = records
            .iter()
            .filter(|(identity, _)| identities.binary_search(identity).is_ok())
            .map(|(identity, digest)| (identity.clone(), digest.clone()))
            .collect();
        let segment = Segment {
            schema: SEGMENT_SCHEMA.to_owned(),
            previous: checkpoint.clone(),
            digests: identities,
            record_digests,
        };
        let digest = write_content_addressed(
            &root,
            "segment",
            &serde_json::to_vec(&segment).unwrap(),
            SEGMENT_BYTES,
        )
        .unwrap();
        checkpoint.head = Some(digest.clone());
        checkpoint.count += group.len();
        chain.push(digest);
    }
    crate::journal_storage::write_private(
        &root,
        &root.path().join("head.json"),
        &serde_json::to_vec(&Head {
            schema: SEGMENT_SCHEMA.to_owned(),
            checkpoint: checkpoint.clone(),
            index_manifest: None,
        })
        .unwrap(),
    )
    .unwrap();
    chain.reverse();
    (root, checkpoint, chain)
}

fn mixed_groups() -> Vec<Vec<String>> {
    (0..12)
        .map(|batch| {
            (0..256)
                .map(|item| sha256_hex(format!("mixed.{batch}.{item}")))
                .collect()
        })
        .collect()
}

fn scratch_paths(root: &PrivateStateRoot) -> Vec<std::path::PathBuf> {
    std::fs::read_dir(root.path())
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with(".retirement-rebuild-")
        })
        .collect()
}

#[test]
fn mixed_history_builds_only_final_buckets_and_restarts_with_every_identity() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let groups = mixed_groups();
    let prefixes: BTreeSet<_> = groups
        .iter()
        .flatten()
        .map(|identity| &identity[..2])
        .collect();
    let (root, checkpoint, _) = seed_legacy(&journal, &groups, &BTreeMap::new());
    let store = RetirementStore::open(&journal, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert!(groups.iter().flatten().all(|id| store.contains(id)));
    assert!(scratch_paths(&root).is_empty());
    let buckets = std::fs::read_dir(root.path())
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .filter(|name| name.to_string_lossy().starts_with("bucket-"))
        .count();
    assert_eq!(
        buckets,
        prefixes.len(),
        "mixed segments must not leave intermediate index versions"
    );
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    drop(store);
    let reopened = RetirementStore::open(&journal, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert_eq!(reopened.len(), checkpoint.count);
    assert!(groups.iter().flatten().all(|id| reopened.contains(id)));
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
}

#[test]
fn duplicate_identity_across_valid_segments_prevents_promotion_and_cleans_spools() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let id = sha256_hex("duplicate.identity");
    let (root, checkpoint, _) =
        seed_legacy(&journal, &[vec![id.clone()], vec![id]], &BTreeMap::new());
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    assert!(RetirementStore::open(&journal, Some(&checkpoint)).is_err());
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
    assert!(scratch_paths(&root).is_empty());
}

#[test]
fn changed_spool_bytes_are_rejected_before_promotion_and_exact_owned_files_cleaned() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let (root, _, chain) = seed_legacy(&journal, &mixed_groups(), &BTreeMap::new());
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let result = rebuild_buckets(&root, &chain, |boundary| {
        if matches!(boundary, RebuildBoundary::SegmentsSpooled) {
            let path = scratch_paths(&root).pop().unwrap();
            let mut file = crate::journal_storage::open_private_file_in(
                &root,
                &path,
                crate::journal_storage::FileAccess::Write,
                /*preexisting*/ true,
            )?;
            file.write_all(b"x")?;
        }
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
    assert!(scratch_paths(&root).is_empty());
}

#[test]
fn error_after_a_bucket_write_keeps_legacy_head_and_retry_has_exact_membership() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let groups = mixed_groups();
    let (root, checkpoint, chain) = seed_legacy(&journal, &groups, &BTreeMap::new());
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let result = rebuild_buckets(&root, &chain, |boundary| match boundary {
        RebuildBoundary::SegmentsSpooled => Ok(()),
        RebuildBoundary::BucketPublished => Err(ShellError::State(
            "injected prepublication failure".to_owned(),
        )),
    });
    assert!(result.is_err());
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
    assert!(scratch_paths(&root).is_empty());
    let reopened = RetirementStore::open(&journal, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert!(groups.iter().flatten().all(|id| reopened.contains(id)));
}

#[test]
fn first_bucket_notification_follows_a_joined_bounded_batch() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let identities: Vec<_> = (0..6)
        .map(|prefix| format!("{prefix:02x}{}", "a".repeat(62)))
        .collect();
    let (root, checkpoint, chain) = seed_legacy(
        &journal,
        std::slice::from_ref(&identities),
        &BTreeMap::new(),
    );
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let result = rebuild_buckets(&root, &chain, |boundary| {
        if matches!(boundary, RebuildBoundary::BucketPublished) {
            let published = std::fs::read_dir(root.path())?
                .collect::<Result<Vec<_>, _>>()?
                .iter()
                .filter(|entry| entry.file_name().to_string_lossy().starts_with("bucket-"))
                .count();
            assert_eq!(
                published, 4,
                "first batch is complete; the next has not started"
            );
            return Err(ShellError::State(
                "stop at the first joined batch".to_owned(),
            ));
        }
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
    assert!(scratch_paths(&root).is_empty());
    let reopened = RetirementStore::open(&journal, Some(&checkpoint))
        .unwrap()
        .unwrap();
    assert_eq!(reopened.len(), identities.len());
    assert!(identities.iter().all(|id| reopened.contains(id)));
}

#[test]
fn failed_publisher_joins_every_other_durable_writer_before_returning() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let identities: Vec<_> = (0..4)
        .map(|prefix| format!("{prefix:02x}{}", "a".repeat(62)))
        .collect();
    let (root, _, _) = seed_legacy(
        &journal,
        std::slice::from_ref(&identities),
        &BTreeMap::new(),
    );
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let batch: Vec<_> = identities
        .iter()
        .map(|identity| {
            let prefix = identity[..2].to_owned();
            let bucket = IndexBucket {
                schema: BUCKET_SCHEMA.to_owned(),
                prefix: prefix.clone(),
                entries: BTreeMap::from([(identity.clone(), None)]),
            };
            (prefix, serde_json::to_vec(&bucket).unwrap())
        })
        .collect();
    let expected: Vec<_> = batch
        .iter()
        .map(|(_, bytes)| {
            (
                root.path()
                    .join(format!("bucket-{}.json", sha256_hex(bytes))),
                bytes.clone(),
            )
        })
        .collect();
    crate::journal_storage::write_private(&root, &expected[0].0, b"foreign CAS content").unwrap();
    assert!(publish_bucket_batch(&root, batch).is_err());
    assert_eq!(
        std::fs::read(&expected[0].0).unwrap(),
        b"foreign CAS content"
    );
    for (path, bytes) in &expected[1..] {
        assert_eq!(std::fs::read(path).unwrap(), *bytes);
    }
    assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
}

#[test]
fn repeated_orphan_collision_preserves_foreign_file_and_does_not_grow_scratch() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let groups = mixed_groups();
    let (root, checkpoint, chain) = seed_legacy(&journal, &groups, &BTreeMap::new());
    let prefix = &groups[0].iter().max().unwrap()[..2];
    let foreign = root.path().join(format!(
        ".retirement-rebuild-{}-{prefix}.tmp",
        spool_nonce(&chain)
    ));
    crate::journal_storage::write_private(
        &root,
        &foreign,
        b"unproven foreign or crashed-attempt bytes",
    )
    .unwrap();
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let before = std::fs::read_dir(root.path()).unwrap().count();
    for _ in 0..2 {
        assert!(RetirementStore::open(&journal, Some(&checkpoint)).is_err());
        assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
        assert_eq!(std::fs::read_dir(root.path()).unwrap().count(), before);
        assert_eq!(
            std::fs::read(&foreign).unwrap(),
            b"unproven foreign or crashed-attempt bytes"
        );
    }
}

#[test]
fn missing_corrupt_or_falsely_bound_archives_cannot_promote_a_legacy_head() {
    for invalid in ["valid", "missing", "hash", "identity", "phase"] {
        let temp = tempfile::tempdir().unwrap();
        let journal = temp.path().join("operations.json");
        let mut record = OperationRecord {
            endpoint_id: "runtime.archive".to_owned(),
            key: OperationKey {
                session_id: "session.archive".to_owned(),
                session_generation: 1,
                operation_id: "operation.archive".to_owned(),
            },
            subject_id: "operator.archive".to_owned(),
            displayed_revision: 1,
            action: PlatformAction::CopyText,
            payload_digest: "1".repeat(64),
            binding_digest: "2".repeat(64),
            grant_digest: "3".repeat(64),
            phase: OperationPhase::Terminal,
            terminal_status: Some(TerminalStatus::Succeeded),
            outcome_digest: Some("4".repeat(64)),
        };
        let id = retirement_digest(&record.endpoint_id, &record.key).unwrap();
        if invalid == "identity" {
            record.key.operation_id = "operation.other".to_owned();
        }
        if invalid == "phase" {
            record.phase = OperationPhase::Prepared;
            record.terminal_status = None;
            record.outcome_digest = None;
        }
        let bytes = serde_json::to_vec(&record).unwrap();
        let digest = sha256_hex(&bytes);
        let (root, checkpoint, _) = seed_legacy(
            &journal,
            &[vec![id.clone()]],
            &BTreeMap::from([(id.clone(), digest.clone())]),
        );
        if invalid != "missing" {
            crate::journal_storage::write_private(
                &root,
                &root.path().join(format!("record-{digest}.json")),
                if invalid == "hash" { b"{}" } else { &bytes },
            )
            .unwrap();
        }
        let head = std::fs::read(root.path().join("head.json")).unwrap();
        if invalid == "valid" {
            let rebuilt = RetirementStore::open(&journal, Some(&checkpoint))
                .unwrap()
                .unwrap();
            assert_eq!(rebuilt.read_record(&id).unwrap(), Some(record));
            assert!(scratch_paths(&root).is_empty());
            continue;
        }
        assert!(
            RetirementStore::open(&journal, Some(&checkpoint)).is_err(),
            "invalid archive {invalid} must fail promotion"
        );
        assert_eq!(std::fs::read(root.path().join("head.json")).unwrap(), head);
        assert!(scratch_paths(&root).is_empty());
    }
}

#[cfg(unix)]
#[test]
fn replaced_root_fails_before_publication_and_cleanup_stays_in_original_directory() {
    let temp = tempfile::tempdir().unwrap();
    let journal = temp.path().join("operations.json");
    let (root, _, chain) = seed_legacy(&journal, &mixed_groups(), &BTreeMap::new());
    let head = std::fs::read(root.path().join("head.json")).unwrap();
    let original = temp.path().join("original-retirement");
    let mut replacement_file = None;
    let result = rebuild_buckets(&root, &chain, |boundary| {
        if matches!(boundary, RebuildBoundary::SegmentsSpooled) {
            let name = scratch_paths(&root)
                .pop()
                .unwrap()
                .file_name()
                .unwrap()
                .to_owned();
            std::fs::rename(root.path(), &original)?;
            let replacement = PrivateStateRoot::open(root.path().to_path_buf())?;
            let path = replacement.path().join(name);
            crate::journal_storage::write_private(&replacement, &path, b"replacement sentinel")?;
            replacement_file = Some(path);
        }
        Ok(())
    });
    assert!(result.is_err());
    assert_eq!(
        std::fs::read(replacement_file.unwrap()).unwrap(),
        b"replacement sentinel"
    );
    assert_eq!(std::fs::read(original.join("head.json")).unwrap(), head);
    assert!(scratch_paths(&PrivateStateRoot::open_existing(original).unwrap()).is_empty());
}
