use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn must<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn binding() -> Digest32 {
    digest("run-start-owner-scope")
}

fn record(run_id: &str, objective: &[u8]) -> RunStartRecordV1 {
    RunStartRecordV1 {
        authentication: RunStartAuthenticationV1 {
            signed_body_bytes: Vec::new(),
            issuer_id: id("issuer.objective"),
            key_epoch: 3,
            message_id: id(&format!("message.{run_id}")),
            sequence: 5,
            expires_at_ms: 9_999_999,
            scope_digest: digest("objective-scope"),
            signed_body_digest: digest("signed-body"),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.objective"),
            profile_revision: 4,
            profile_digest: digest("profile"),
            supplied_source_digest: digest("supplied-source"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest("admitted-source"),
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 2_000_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        disposition: RunStartObjectiveDispositionV1::Compiled,
        snapshot: RunStartSnapshotV1 {
            run_id: id(run_id),
            objective_digest: Digest32::of_bytes(objective),
            hard_constraint_digest: digest("hard"),
            preference_state_digest: digest("preference"),
            model_tuple_digest: digest("model-tuple"),
            prompt_registry_digest: digest("prompt-registry"),
            artifact_set_digest: digest("artifact-set"),
            authority_epoch: 7,
            generation: 11,
            fence_digest: digest("fence"),
        },
        runtime_body_digest: digest("runtime-body"),
        objective_semantic_bytes: objective.to_vec(),
        objective_function_v1_digest: Digest32::of_bytes(b"{\"objectiveId\":\"fixture\"}"),
        objective_function_v1_bytes: b"{\"objectiveId\":\"fixture\"}".to_vec(),
    }
}

fn conflict_record(run_id: &str, receipt: &[u8]) -> RunStartConflictRecordV1 {
    RunStartConflictRecordV1 {
        authentication: RunStartAuthenticationV1 {
            signed_body_bytes: Vec::new(),
            issuer_id: id("issuer.objective"),
            key_epoch: 3,
            message_id: id(&format!("message.{run_id}")),
            sequence: 5,
            expires_at_ms: 9_999_999,
            scope_digest: digest("objective-scope"),
            signed_body_digest: digest("signed-body"),
            signature: [7; 64],
        },
        admission: RunStartAdmissionBindingV1 {
            profile_id: id("profile.objective"),
            profile_revision: 4,
            profile_digest: digest("profile"),
            supplied_source_digest: digest("supplied-source"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest("admitted-source"),
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 2_000_000,
            authority: AuthorityPosture::DENY_ALL,
        },
        run_id: id(run_id),
        runtime_body_digest: digest("runtime-body"),
        conflict_digest: Digest32::of_bytes(receipt),
        conflict_receipt_bytes: receipt.to_vec(),
    }
}

struct Fixture {
    root: PathBuf,
}

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-run-start-journal-{}-{serial}",
            std::process::id()
        ));
        must(fs::create_dir(&root));
        must(
            OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(root.join("journal")),
        );
        Self { root }
    }

    fn path(&self) -> PathBuf {
        self.root.join("journal")
    }

    fn file(&self) -> File {
        must(OpenOptions::new().read(true).write(true).open(self.path()))
    }

    fn create(&self) -> DurableRunStartJournal {
        must(DurableRunStartJournal::create(
            self.file(),
            binding(),
            /*max_records*/ 16,
        ))
    }

    fn recover(
        &self,
        recovery: RunStartRecovery,
    ) -> Result<DurableRunStartJournal, RunStartStoreError> {
        DurableRunStartJournal::recover(self.file(), binding(), /*max_records*/ 16, recovery)
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

#[test]
fn durable_run_start_roundtrip_replays_exact_objective_bytes() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = record("run-1", b"objective-semantic-one");
    let receipt = must(journal.append(Digest32::ZERO, first.clone()));
    assert_eq!(receipt.disposition, RunStartAppendDisposition::Appended);
    let anchor = RunStartAnchor {
        sequence: receipt.sequence,
        chain_digest: receipt.chain_digest,
    };
    drop(journal);

    let reopened = must(fixture.recover(RunStartRecovery::Acknowledged(anchor)));
    assert_eq!(must(reopened.get(&id("run-1"))), Some(&first));
    assert_eq!(
        Digest32::of_bytes(&first.objective_semantic_bytes),
        first.snapshot.objective_digest
    );
}

#[test]
fn exact_retry_is_idempotent_but_run_id_drift_conflicts() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = record("run-1", b"objective-semantic-one");
    let receipt = must(journal.append(Digest32::ZERO, first.clone()));
    let before = must(fs::read(fixture.path()));

    let replay = must(journal.append(Digest32::ZERO, first.clone()));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.chain_digest, receipt.chain_digest);
    assert_eq!(must(fs::read(fixture.path())), before);

    let second = must(journal.append(
        receipt.chain_digest,
        record("run-2", b"objective-semantic-second"),
    ));
    let after_second = must(fs::read(fixture.path()));
    let late_replay = must(journal.append(second.chain_digest, first));
    assert_eq!(
        late_replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(late_replay.record_digest, receipt.record_digest);
    assert_eq!(must(fs::read(fixture.path())), after_second);

    let changed = record("run-1", b"objective-semantic-two");
    assert_eq!(
        journal.append(Digest32::ZERO, changed),
        Err(RunStartStoreError::Conflict)
    );
    assert_eq!(must(fs::read(fixture.path())), after_second);
}

#[test]
fn durable_conflict_roundtrip_replays_exact_receipt_without_runtime_snapshot() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let conflict = conflict_record("run-conflict", b"canonical-conflict-receipt");
    let receipt = must(journal.append_conflict(Digest32::ZERO, conflict.clone()));
    assert_eq!(receipt.disposition, RunStartAppendDisposition::Appended);
    assert!(must(journal.records()).is_empty());
    assert_eq!(must(journal.conflicts()), vec![&conflict]);
    assert_eq!(
        must(journal.authentication_records()).len(),
        1,
        "conflict consumes the signed replay identity"
    );

    let replay = must(journal.append_conflict(Digest32::ZERO, conflict.clone()));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.chain_digest, receipt.chain_digest);

    let mut changed = conflict.clone();
    changed.conflict_receipt_bytes = b"different-conflict-receipt".to_vec();
    changed.conflict_digest = Digest32::of_bytes(&changed.conflict_receipt_bytes);
    assert_eq!(
        journal.append_conflict(Digest32::ZERO, changed),
        Err(RunStartStoreError::Conflict)
    );

    let anchor = RunStartAnchor {
        sequence: receipt.sequence,
        chain_digest: receipt.chain_digest,
    };
    drop(journal);
    let reopened = must(fixture.recover(RunStartRecovery::Acknowledged(anchor)));
    assert_eq!(
        must(reopened.get_conflict(&id("run-conflict"))),
        Some(&conflict)
    );
    assert!(must(reopened.records()).is_empty());
}

#[test]
fn objective_payload_digest_mismatch_rejects_before_io() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let mut invalid = record("run-1", b"objective-semantic-one");
    invalid.snapshot.objective_digest = digest("forged");
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        journal.append(Digest32::ZERO, invalid),
        Err(RunStartStoreError::ObjectiveDigestMismatch)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
}

#[test]
fn predecessor_and_binding_are_fenced() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    assert_eq!(
        journal.append(digest("wrong-predecessor"), record("run-1", b"one")),
        Err(RunStartStoreError::Conflict)
    );
    let first = must(journal.append(Digest32::ZERO, record("run-1", b"one")));
    drop(journal);

    assert_eq!(
        DurableRunStartJournal::recover(
            fixture.file(),
            digest("wrong-binding"),
            16,
            RunStartRecovery::Acknowledged(RunStartAnchor {
                sequence: 1,
                chain_digest: first.chain_digest,
            })
        )
        .err(),
        Some(RunStartStoreError::BindingMismatch)
    );
}

#[test]
fn incomplete_unacknowledged_tail_recovers_to_last_synced_frame() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = must(journal.append(Digest32::ZERO, record("run-1", b"one")));
    let second = must(journal.append(first.chain_digest, record("run-2", b"two")));
    drop(journal);

    let full = must(fs::read(fixture.path()));
    let second_record = record("run-2", b"two");
    let second_stored = StoredRunStart {
        sequence: second.sequence,
        predecessor_chain_digest: first.chain_digest,
        record_digest: second.record_digest,
        chain_digest: second.chain_digest,
        record: StoredRunStartRecord::Run(Box::new(second_record)),
    };
    let second_size = must(encode_frame(&second_stored)).len();
    let first_end = full.len() - second_size;

    must(fs::write(
        fixture.path(),
        &full[..first_end + second_size / 2],
    ));
    let recovered = must(
        fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: first.sequence,
            chain_digest: first.chain_digest,
        })),
    );
    assert_eq!(must(recovered.records()).len(), 1);
    assert_eq!(must(fs::metadata(fixture.path())).len(), first_end as u64);
}

#[test]
fn acknowledged_missing_history_never_repairs_as_success() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first = must(journal.append(Digest32::ZERO, record("run-1", b"one")));
    let second = must(journal.append(first.chain_digest, record("run-2", b"two")));
    drop(journal);

    let full = must(fs::read(fixture.path()));
    let second_record = record("run-2", b"two");
    let second_stored = StoredRunStart {
        sequence: second.sequence,
        predecessor_chain_digest: first.chain_digest,
        record_digest: second.record_digest,
        chain_digest: second.chain_digest,
        record: StoredRunStartRecord::Run(Box::new(second_record)),
    };
    let second_size = must(encode_frame(&second_stored)).len();
    let first_end = full.len() - second_size;
    let damaged = &full[..first_end + second_size / 2];
    must(fs::write(fixture.path(), damaged));

    assert_eq!(
        fixture
            .recover(RunStartRecovery::Acknowledged(RunStartAnchor {
                sequence: second.sequence,
                chain_digest: second.chain_digest,
            }))
            .err(),
        Some(RunStartStoreError::AcknowledgedHistoryMissing)
    );
    assert_eq!(must(fs::read(fixture.path())), damaged);
}

#[test]
fn objective_protocol_digest_mismatch_rejects_before_io() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let mut invalid = record("run-protocol", b"objective-semantic");
    invalid.objective_function_v1_digest = digest("forged-protocol");
    let before = must(fs::read(fixture.path()));
    assert_eq!(
        journal.append(Digest32::ZERO, invalid),
        Err(RunStartStoreError::ObjectiveProtocolDigestMismatch)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
}

#[test]
fn committed_record_reopens_and_ack_loss_retry_is_idempotent() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first_record = record("run-ack-loss", b"objective-semantic");
    let first = must(journal.append(Digest32::ZERO, first_record.clone()));
    drop(journal);

    let mut reopened = must(fixture.recover(RunStartRecovery::Unacknowledged));
    let replay = must(reopened.append(Digest32::ZERO, first_record));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.record_digest, first.record_digest);
    assert_eq!(replay.chain_digest, first.chain_digest);
}

#[test]
fn semantic_or_protocol_drift_after_reopen_conflicts() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let first_record = record("run-drift", b"objective-semantic");
    let first = must(journal.append(Digest32::ZERO, first_record));
    drop(journal);

    let mut reopened = must(
        fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: first.sequence,
            chain_digest: first.chain_digest,
        })),
    );
    let mut changed = record("run-drift", b"objective-semantic");
    changed.objective_function_v1_bytes = b"{\"objectiveId\":\"different\"}".to_vec();
    changed.objective_function_v1_digest = Digest32::of_bytes(&changed.objective_function_v1_bytes);
    assert_eq!(
        reopened.append(first.chain_digest, changed),
        Err(RunStartStoreError::Conflict)
    );
}

#[test]
fn mixed_legacy_and_signed_input_history_reopens_without_rewriting() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let legacy = record("legacy", b"old objective");
    let first = must(journal.append(Digest32::ZERO, legacy.clone()));
    let prefix = must(fs::read(fixture.path()));
    let mut current = record("signed-input", b"new objective");
    current.authentication.signed_body_bytes = br#"{"source":"exact input"}"#.to_vec();
    current.authentication.signed_body_digest =
        Digest32::of_bytes(&current.authentication.signed_body_bytes);
    let receipt = must(journal.append(first.chain_digest, current.clone()));
    let mut conflict = conflict_record("signed-conflict", b"conflict");
    conflict.authentication = current.authentication.clone();
    let last = must(journal.append_conflict(receipt.chain_digest, conflict.clone()));
    let bytes = must(fs::read(fixture.path()));
    assert_eq!(&bytes[..prefix.len()], prefix.as_slice());
    drop(journal);
    let mut reopened = must(
        fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: last.sequence,
            chain_digest: last.chain_digest,
        })),
    );
    assert_eq!(must(reopened.get(&id("legacy"))), Some(&legacy));
    assert_eq!(must(reopened.get(&id("signed-input"))), Some(&current));
    assert_eq!(
        must(reopened.get_conflict(&id("signed-conflict"))),
        Some(&conflict)
    );
    assert_eq!(
        must(reopened.append(Digest32::ZERO, current)).disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn signed_input_substitution_and_oversize_reject_before_write() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let bytes = must(fs::read(fixture.path()));
    let mut changed = record("signed-input", b"objective");
    changed.authentication.signed_body_bytes = b"substituted input".to_vec();
    assert!(journal.append(Digest32::ZERO, changed.clone()).is_err());
    changed.authentication.signed_body_bytes = vec![1; MAX_SIGNED_BODY_BYTES + 1];
    changed.authentication.signed_body_digest =
        Digest32::of_bytes(&changed.authentication.signed_body_bytes);
    assert!(journal.append(Digest32::ZERO, changed).is_err());
    assert_eq!(must(fs::read(fixture.path())), bytes);
    assert_eq!(journal.head_digest(), Digest32::ZERO);
}

#[test]
fn signed_input_codec_rejects_truncation_and_payload_tampering() {
    let mut value = record("signed-input", b"objective");
    value.authentication.signed_body_bytes = b"original signed source bytes".to_vec();
    value.authentication.signed_body_digest =
        Digest32::of_bytes(&value.authentication.signed_body_bytes);
    let bytes = encode_record(&value);
    assert_eq!(must(decode_record(&bytes)), value);
    for end in 0..bytes.len() {
        assert!(decode_record(&bytes[..end]).is_err());
    }
    let offset = bytes
        .windows(value.authentication.signed_body_bytes.len())
        .position(|window| window == value.authentication.signed_body_bytes)
        .unwrap();
    let mut tampered = bytes;
    tampered[offset] ^= 1;
    assert!(decode_record(&tampered).is_err());
}

#[test]
fn complete_recovery_requires_sync_before_exposing_idempotent_receipt() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let value = record("run.sync", b"original objective");
    let appended = must(journal.append(Digest32::ZERO, value.clone()));
    drop(journal);
    let bytes = must(fs::read(fixture.path()));
    let synchronized = std::cell::Cell::new(false);
    let mut recovered = must(DurableRunStartJournal::recover_synced(
        fixture.file(),
        binding(),
        16,
        RunStartRecovery::Unacknowledged,
        |file| {
            assert_eq!(must(file.metadata()).len(), bytes.len() as u64);
            file.sync_all()?;
            synchronized.set(true);
            Ok(())
        },
    ));
    assert!(synchronized.get());
    assert_eq!(
        must(recovered.append(Digest32::ZERO, value)),
        RunStartAppendReceipt {
            disposition: RunStartAppendDisposition::IdempotentReplay,
            ..appended
        }
    );
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

#[test]
fn complete_recovery_sync_failure_returns_no_writer_and_releases_lock() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let value = record("run.sync-failure", b"original objective");
    let appended = must(journal.append(Digest32::ZERO, value.clone()));
    drop(journal);
    let bytes = must(fs::read(fixture.path()));
    let result = DurableRunStartJournal::recover_synced(
        fixture.file(),
        binding(),
        16,
        RunStartRecovery::Unacknowledged,
        |_| Err(io::Error::other("injected recovery fsync failure")),
    );
    assert!(matches!(result, Err(RunStartStoreError::Indeterminate)));
    assert_eq!(must(fs::read(fixture.path())), bytes);
    let mut recovered = must(fixture.recover(RunStartRecovery::Unacknowledged));
    assert_eq!(
        must(recovered.append(Digest32::ZERO, value)),
        RunStartAppendReceipt {
            disposition: RunStartAppendDisposition::IdempotentReplay,
            ..appended
        }
    );
}

#[test]
fn invalid_anchor_is_rejected_before_recovery_sync_or_tail_repair() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let appended = must(journal.append(Digest32::ZERO, record("run.anchor", b"objective")));
    drop(journal);
    let mut file = fixture.file();
    must(file.seek(SeekFrom::End(0)));
    must(file.write_all(b"partial"));
    drop(file);
    let bytes = must(fs::read(fixture.path()));
    let synchronized = std::cell::Cell::new(false);
    let result = DurableRunStartJournal::recover_synced(
        fixture.file(),
        binding(),
        16,
        RunStartRecovery::Acknowledged(RunStartAnchor {
            sequence: appended.sequence,
            chain_digest: digest("wrong anchor"),
        }),
        |_| {
            synchronized.set(true);
            Ok(())
        },
    );
    assert!(matches!(result, Err(RunStartStoreError::AnchorMismatch)));
    assert!(!synchronized.get());
    assert_eq!(must(fs::read(fixture.path())), bytes);
}
