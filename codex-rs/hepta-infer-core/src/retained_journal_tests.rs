use super::*;
use native::NativeMaintenanceStage;
use native::NativeRequest;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

struct Fixture {
    directory: PathBuf,
    journal: PathBuf,
}

#[allow(
    clippy::expect_used,
    reason = "Fixture setup must fail the test on invalid state"
)]
impl Fixture {
    fn new() -> Self {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system time follows Unix epoch")
            .as_nanos();
        let directory = std::env::temp_dir().join(format!(
            "hepta-retained-journal-{}-{nonce}",
            std::process::id()
        ));
        fs::create_dir_all(&directory).expect("create test owner directory");
        Self {
            journal: directory.join("owner.journal"),
            directory,
        }
    }

    fn open(&self) -> DurableInferenceControl {
        DurableInferenceControl::open(&self.journal, /*capacity*/ 8).expect("open test owner")
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.directory);
    }
}

fn request(id: &str) -> NativeRequest {
    NativeRequest {
        request_id: id.to_string(),
        principal_id: "principal".to_string(),
        worker_generation: 1,
        model: "model".to_string(),
        payload_digest: "1".repeat(64),
    }
}

#[test]
fn truncation_denies_cached_ack_and_restoring_bytes_does_not_clear_poison() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let admitted = owner.reserve_native(request("request-1"), 2).unwrap();
    let original = fs::read(&fixture.journal).unwrap();
    fs::OpenOptions::new()
        .write(true)
        .open(&fixture.journal)
        .unwrap()
        .set_len(0)
        .unwrap();
    assert!(matches!(
        owner.reserve_native(request("request-1"), 2),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(owner.native_record("request-1"), Some(&admitted));
    assert!(fs::read(&fixture.journal).unwrap().is_empty());
    fs::write(&fixture.journal, &original).unwrap();
    assert_eq!(
        owner.reserve_native(request("request-1"), 2),
        Err(Error::WriterUnavailable)
    );
    assert_eq!(
        owner.reserve_native(request("request-2"), 2),
        Err(Error::WriterUnavailable)
    );
    assert_eq!(fs::read(&fixture.journal).unwrap(), original);
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(
        reopened.reserve_native(request("request-1"), 2).unwrap(),
        admitted
    );
    reopened.reserve_native(request("request-2"), 2).unwrap();
}

#[test]
fn same_length_valid_history_substitution_denies_new_write_without_repair() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("request-1"), 2).unwrap();
    let released = owner
        .stop_native_before_dispatch("request-1", "not sent".to_string())
        .unwrap();
    let original = fs::read_to_string(&fixture.journal).unwrap();
    let replaced = original.replace("request-1", "request-2");
    assert_eq!(original.len(), replaced.len());
    fs::write(&fixture.journal, &replaced).unwrap();
    assert!(matches!(
        owner.reserve_native(request("request-3"), 2),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(owner.native_record("request-1"), Some(&released));
    assert_eq!(owner.native_record("request-3"), None);
    assert_eq!(fs::read_to_string(&fixture.journal).unwrap(), replaced);
    drop(owner);
    // This valid substitution cannot be detected by a plain reopen without an
    // independent retained witness. The live-owner check does not claim that.
    let reopened = fixture.open();
    assert_eq!(reopened.native_record("request-1"), None);
    assert!(reopened.native_record("request-2").is_some());
    assert_eq!(reopened.native_record("request-3"), None);
}

#[cfg(unix)]
#[test]
fn byte_identical_path_replacement_fences_the_original_open_writer() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("request-1"), 2).unwrap();
    let original = fs::read(&fixture.journal).unwrap();
    let replacement = fixture.directory.join("replacement");
    fs::copy(&fixture.journal, &replacement).unwrap();
    fs::rename(&replacement, &fixture.journal).unwrap();
    assert!(matches!(
        owner.reserve_native(request("request-1"), 2),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(fs::read(&fixture.journal).unwrap(), original);
    assert_eq!(
        owner.reserve_native(request("request-2"), 2),
        Err(Error::WriterUnavailable)
    );
}

#[test]
fn lost_journal_access_denies_ack_and_write_until_explicit_reopen() {
    use std::os::unix::fs::PermissionsExt;
    for mode in [0o400, 0o000, 0o644] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let admitted = owner.reserve_native(request("request-1"), 2).unwrap();
        let original = fs::read(&fixture.journal).unwrap();
        fs::set_permissions(&fixture.journal, fs::Permissions::from_mode(mode)).unwrap();
        assert!(owner.reserve_native(request("request-1"), 2).is_err());
        assert_eq!(owner.native_record("request-1"), Some(&admitted));
        fs::set_permissions(&fixture.journal, fs::Permissions::from_mode(0o600)).unwrap();
        assert_eq!(
            owner.reserve_native(request("request-2"), 2),
            Err(Error::WriterUnavailable)
        );
        assert_eq!(fs::read(&fixture.journal).unwrap(), original);
        drop(owner);
        let mut reopened = fixture.open();
        assert_eq!(
            reopened.reserve_native(request("request-1"), 2).unwrap(),
            admitted
        );
    }
}

#[test]
fn malformed_admission_is_rejected_without_an_expensive_retention_scan() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    fs::remove_file(&fixture.journal).unwrap();
    assert!(matches!(
        owner.reserve_native(request(""), 2),
        Err(Error::InvalidIdentity(_))
    ));
    assert!(!owner.poisoned);
    assert!(owner.reserve_native(request("request-1"), 2).is_err());
    assert!(owner.poisoned);
}

#[test]
fn compaction_rechecks_predecessor_after_generation_sync_before_rename() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("request-1"), 2).unwrap();
    let original = fs::read_to_string(&fixture.journal).unwrap();
    let replacement = original.replace("request-1", "request-2");
    let mut fault = |stage| {
        if stage == NativeMaintenanceStage::AfterGenerationSync {
            fs::write(&fixture.journal, &replacement).unwrap();
        }
        Ok(())
    };
    assert!(matches!(
        owner.compact_native_journal_with_failpoint(1, &mut fault),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(owner.native_metrics(1).checkpoint_generation, 0);
    assert_eq!(fs::read_to_string(&fixture.journal).unwrap(), replacement);
    fs::write(&fixture.journal, original).unwrap();
    assert_eq!(
        owner.compact_native_journal(),
        Err(Error::WriterUnavailable)
    );
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(reopened.compact_native_journal().unwrap().generation, 1);
}

#[test]
fn compaction_does_not_publish_damaged_replacement_after_directory_sync() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let original = owner.reserve_native(request("request-1"), 2).unwrap();
    let mut fault = |stage| {
        if stage == NativeMaintenanceStage::AfterParentSync {
            fs::write(&fixture.journal, b"damaged\n").unwrap();
        }
        Ok(())
    };
    assert!(matches!(
        owner.compact_native_journal_with_failpoint(1, &mut fault),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(owner.native_record("request-1"), Some(&original));
    assert_eq!(owner.native_metrics(1).checkpoint_generation, 0);
    assert_eq!(fs::read(&fixture.journal).unwrap(), b"damaged\n");
    assert_eq!(
        owner.reserve_native(request("request-2"), 2),
        Err(Error::WriterUnavailable)
    );
    drop(owner);
    assert!(DurableInferenceControl::open(&fixture.journal, 8).is_err());
}

#[test]
fn compaction_and_reopen_adopt_only_the_verified_new_prefix() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    owner.reserve_native(request("request-1"), 2).unwrap();
    owner.compact_native_journal().unwrap();
    let second = owner.reserve_native(request("request-2"), 2).unwrap();
    drop(owner);
    let mut reopened = fixture.open();
    assert_eq!(
        reopened.reserve_native(request("request-2"), 2).unwrap(),
        second
    );
    reopened
        .stop_native_before_dispatch("request-1", "not sent".to_string())
        .unwrap();
    reopened.compact_native_journal().unwrap();
    reopened.reserve_native(request("request-3"), 2).unwrap();
}

#[test]
fn checkpoint_damage_denies_cached_ack_and_restore_does_not_clear_poison() {
    for damage in ["truncate", "replace", "delete", "permissions", "unreadable"] {
        let fixture = Fixture::new();
        let mut owner = fixture.open();
        let admitted = owner.reserve_native(request("request-1"), 2).unwrap();
        let receipt = owner.compact_native_journal().unwrap();
        let checkpoint = fixture
            .directory
            .join("owner.journal.checkpoints")
            .join(format!("{}.json", receipt.checkpoint_digest));
        let permissions = fs::metadata(&checkpoint).unwrap().permissions();
        let original = fs::read_to_string(&checkpoint).unwrap();
        let journal_before = fs::read(&fixture.journal).unwrap();
        match damage {
            "truncate" => fs::write(&checkpoint, b"").unwrap(),
            "replace" => {
                let replaced = original.replace("request-1", "request-2");
                assert_eq!(replaced.len(), original.len());
                serde_json::from_str::<serde_json::Value>(&replaced).unwrap();
                fs::write(&checkpoint, replaced).unwrap();
            }
            "delete" => fs::remove_file(&checkpoint).unwrap(),
            "permissions" | "unreadable" => {
                #[cfg(unix)]
                {
                    use std::os::unix::fs::PermissionsExt;
                    let mode = if damage == "permissions" {
                        0o644
                    } else {
                        0o000
                    };
                    fs::set_permissions(&checkpoint, fs::Permissions::from_mode(mode)).unwrap();
                }
                #[cfg(not(unix))]
                continue;
            }
            _ => unreachable!(),
        }
        assert!(
            owner.reserve_native(request("request-1"), 2).is_err(),
            "{damage}"
        );
        assert_eq!(owner.native_record("request-1"), Some(&admitted));
        assert_eq!(fs::read(&fixture.journal).unwrap(), journal_before);
        if checkpoint.exists() {
            fs::set_permissions(&checkpoint, permissions.clone()).unwrap();
        }
        fs::write(&checkpoint, original).unwrap();
        fs::set_permissions(&checkpoint, permissions).unwrap();
        assert_eq!(
            owner.reserve_native(request("request-2"), 2),
            Err(Error::WriterUnavailable)
        );
        drop(owner);
        let mut reopened = fixture.open();
        assert_eq!(
            reopened.reserve_native(request("request-1"), 2).unwrap(),
            admitted
        );
    }
}

#[test]
fn damaged_new_checkpoint_cannot_be_adopted_after_directory_sync() {
    let fixture = Fixture::new();
    let mut owner = fixture.open();
    let admitted = owner.reserve_native(request("request-1"), 2).unwrap();
    let mut fault = |stage| {
        if stage == NativeMaintenanceStage::AfterParentSync {
            let entry = fs::read_dir(fixture.directory.join("owner.journal.checkpoints"))
                .unwrap()
                .next()
                .unwrap()
                .unwrap();
            fs::write(entry.path(), b"{}").unwrap();
        }
        Ok(())
    };
    assert!(matches!(
        owner.compact_native_journal_with_failpoint(1, &mut fault),
        Err(Error::CorruptJournal(_))
    ));
    assert_eq!(owner.native_record("request-1"), Some(&admitted));
    assert_eq!(owner.native_metrics(1).checkpoint_generation, 0);
    assert_eq!(
        owner.reserve_native(request("request-2"), 2),
        Err(Error::WriterUnavailable)
    );
    drop(owner);
    assert!(DurableInferenceControl::open(&fixture.journal, 8).is_err());
}

#[test]
fn retained_prefix_cost_is_bounded_at_small_and_near_capacity_sizes() {
    for bytes in [1024, 63 * 1024 * 1024] {
        let fixture = Fixture::new();
        let mut options = OpenOptions::new();
        options.create_new(true).write(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let mut file = options.open(&fixture.journal).unwrap();
        // Blank journal lines are valid replay input and isolate retained-byte
        // cost without creating millions of authoritative request identities.
        let block = vec![b'\n'; 64 * 1024];
        let mut left = bytes;
        while left != 0 {
            let count = left.min(block.len());
            file.write_all(&block[..count]).unwrap();
            left -= count;
        }
        drop(file);
        let mut owner = fixture.open();
        let start = Instant::now();
        owner
            .submit(
                1,
                InferenceRequest {
                    request_id: "request-1".to_string(),
                    principal_id: "principal".to_string(),
                    model_digest: "1".repeat(64),
                    payload_digest: "2".repeat(64),
                    maximum_tokens: 1,
                    deadline_ms: 1000,
                    semantic_digest: "3".repeat(64),
                },
            )
            .unwrap();
        let admitted = start.elapsed();
        let start = Instant::now();
        owner.cancel("request-1", 1).unwrap();
        let released = start.elapsed();
        eprintln!("retained-prefix bytes={bytes} admission={admitted:?} release={released:?}");
    }
}
