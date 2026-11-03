use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

#[test]
fn prepared_handoff_reopens_exact_original_journal_without_consuming_ingress_again() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("prepared-run", b"original-objective");
    let start = must(journal.append(Digest32::ZERO, original.clone()));
    let payload = b"exact sealed owner handoff bytes".to_vec();
    let prepared = RunPreparedRecordV1 { run_id: original.snapshot.run_id.clone(),
        run_start_record_digest: start.record_digest, payload_digest: Digest32::of_bytes(&payload), payload };
    let appended = must(journal.append_prepared(start.chain_digest, prepared.clone()));
    let before = locked_bytes(&journal.file.0);
    drop(journal);
    let mut cold = must(fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
        sequence: appended.sequence, chain_digest: appended.chain_digest })));
    let loaded = must(cold.prepared(&original.snapshot.run_id)).expect("committed handoff");
    assert_eq!(loaded.record(), &prepared);
    assert_eq!(loaded.receipt().record_digest, appended.record_digest);
    assert_eq!(must(cold.records()), vec![&original]);
    assert_eq!(must(cold.authentication_records()), vec![(&original.authentication, &original.snapshot.run_id)]);
    assert_eq!(must(cold.append(Digest32::ZERO, original)).record_digest, start.record_digest);
    let replay = must(cold.append_prepared(Digest32::ZERO, prepared));
    assert_eq!(replay, RunStartAppendReceipt { disposition: RunStartAppendDisposition::IdempotentReplay, ..appended });
    assert_eq!(locked_bytes(&cold.file.0), before);
}

#[test]
fn prepared_handoff_requires_original_compiled_record_and_exact_payload() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("bound-prepared", b"objective");
    let start = must(journal.append(Digest32::ZERO, original.clone()));
    let make = |payload: &[u8]| RunPreparedRecordV1 { run_id: original.snapshot.run_id.clone(),
        run_start_record_digest: start.record_digest, payload_digest: Digest32::of_bytes(payload), payload: payload.to_vec() };
    let initial = locked_bytes(&journal.file.0);
    let mut changed = make(b"prepared");
    changed.run_start_record_digest = digest("other-start");
    assert_eq!(journal.append_prepared(start.chain_digest, changed), Err(RunStartStoreError::Conflict));
    let mut missing = make(b"prepared");
    missing.run_id = id("missing-run");
    assert_eq!(journal.append_prepared(start.chain_digest, missing), Err(RunStartStoreError::Conflict));
    let mut altered = make(b"prepared");
    altered.payload.push(1);
    assert!(journal.append_prepared(start.chain_digest, altered).is_err());
    assert!(journal.append_prepared(start.chain_digest, make(&vec![1; MAX_RUN_PREPARED_BYTES + 1])).is_err());
    assert_eq!(locked_bytes(&journal.file.0), initial);
    must(journal.append_prepared(start.chain_digest, make(b"prepared")));
    let committed = locked_bytes(&journal.file.0);
    assert_eq!(journal.append_prepared(journal.head_digest(), make(b"replacement")), Err(RunStartStoreError::Conflict));
    assert_eq!(locked_bytes(&journal.file.0), committed);
}

#[test]
fn run_start_only_is_unknown_and_prepared_shares_original_frame_capacity() {
    let fixture = Fixture::new();
    let mut journal = must(DurableRunStartJournal::create(fixture.file(), binding(), /*max_records*/ 2));
    let original = record("capacity-prepared", b"objective");
    let start = must(journal.append(Digest32::ZERO, original.clone()));
    assert_eq!(must(journal.prepared(&original.snapshot.run_id)), None);
    let payload = b"completed preparation".to_vec();
    must(journal.append_prepared(start.chain_digest, RunPreparedRecordV1 {
        run_id: original.snapshot.run_id, run_start_record_digest: start.record_digest,
        payload_digest: Digest32::of_bytes(&payload), payload }));
    let before = locked_bytes(&journal.file.0);
    assert_eq!(journal.append(journal.head_digest(), record("new-run", b"other")), Err(RunStartStoreError::Capacity));
    assert_eq!(locked_bytes(&journal.file.0), before);
}

#[test]
fn corrupted_committed_handoff_never_recovers_as_a_new_preparation() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let original = record("corrupt-prepared", b"objective");
    let start = must(journal.append(Digest32::ZERO, original.clone()));
    let payload = b"original prepared state".to_vec();
    must(journal.append_prepared(start.chain_digest, RunPreparedRecordV1 {
        run_id: original.snapshot.run_id, run_start_record_digest: start.record_digest,
        payload_digest: Digest32::of_bytes(&payload), payload }));
    let mut bytes = locked_bytes(&journal.file.0);
    drop(journal);
    let end = bytes.len();
    bytes[end - FRAME_OVERHEAD] ^= 1;
    must(fs::write(fixture.path(), &bytes));
    assert!(matches!(fixture.recover(RunStartRecovery::Unacknowledged), Err(RunStartStoreError::Corrupt)));
    assert_eq!(must(fs::read(fixture.path())), bytes);
}

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
        authenticated_payload: None,
        authentication: RunStartAuthenticationV1 {
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

// Inspect the original lock-owning handle: Windows locks also exclude other
// handles in this process. Restore its cursor before the next journal operation.
fn locked_bytes(mut file: &File) -> Vec<u8> {
    let position = must(file.stream_position());
    must(file.seek(SeekFrom::Start(0)));
    let mut bytes = Vec::new();
    must(file.read_to_end(&mut bytes));
    must(file.seek(SeekFrom::Start(position)));
    bytes
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
    let before = locked_bytes(&journal.file.0);

    let replay = must(journal.append(Digest32::ZERO, first.clone()));
    assert_eq!(
        replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(replay.chain_digest, receipt.chain_digest);
    assert_eq!(locked_bytes(&journal.file.0), before);

    let second = must(journal.append(
        receipt.chain_digest,
        record("run-2", b"objective-semantic-second"),
    ));
    let after_second = locked_bytes(&journal.file.0);
    let late_replay = must(journal.append(second.chain_digest, first));
    assert_eq!(
        late_replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(late_replay.record_digest, receipt.record_digest);
    assert_eq!(locked_bytes(&journal.file.0), after_second);

    let changed = record("run-1", b"objective-semantic-two");
    assert_eq!(
        journal.append(Digest32::ZERO, changed),
        Err(RunStartStoreError::Conflict)
    );
    assert_eq!(locked_bytes(&journal.file.0), after_second);
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
    let before = locked_bytes(&journal.file.0);
    assert_eq!(
        journal.append(Digest32::ZERO, invalid),
        Err(RunStartStoreError::ObjectiveDigestMismatch)
    );
    assert_eq!(locked_bytes(&journal.file.0), before);
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
    let before = locked_bytes(&journal.file.0);
    assert_eq!(
        journal.append(Digest32::ZERO, invalid),
        Err(RunStartStoreError::ObjectiveProtocolDigestMismatch)
    );
    assert_eq!(locked_bytes(&journal.file.0), before);
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
fn authenticated_payload_v3_recovers_exact_bytes_and_replays_without_a_second_append() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let mut first = record("run-authenticated", b"objective-semantic");
    let payload = br#"{"queuedInput":{"threadId":"original-thread","text":"original signed input"}}"#.to_vec();
    first.authentication.signed_body_digest = Digest32::of_bytes(&payload);
    first.authenticated_payload = Some(payload);
    let receipt = must(journal.append(Digest32::ZERO, first.clone()));
    let before = locked_bytes(&journal.file.0);
    assert!(before.windows(RECORD_DOMAIN_V3.len()).any(|part| part == RECORD_DOMAIN_V3));
    drop(journal);

    let mut recovered = must(fixture.recover(RunStartRecovery::Acknowledged(RunStartAnchor {
        sequence: receipt.sequence,
        chain_digest: receipt.chain_digest,
    })));
    assert_eq!(must(recovered.get(&first.snapshot.run_id)), Some(&first));
    let replay = must(recovered.append(Digest32::ZERO, first));
    assert_eq!(replay, RunStartAppendReceipt {
        disposition: RunStartAppendDisposition::IdempotentReplay,
        ..receipt
    });
    assert_eq!(locked_bytes(&recovered.file.0), before);
}

#[test]
fn legacy_v1_v2_decode_without_inventing_authenticated_payload_and_v2_replays_exactly() {
    let legacy = record("run-legacy", b"objective-semantic");
    let v2 = encode_record(&legacy);
    assert!(v2.starts_with(b"hepta.run-start-record.v2"));
    assert_eq!(must(decode_record(&v2)), legacy);
    let protocol_bytes = 32 + 4 + legacy.objective_function_v1_bytes.len();
    let mut v1 = v2[..v2.len() - protocol_bytes].to_vec();
    v1[..RECORD_DOMAIN_V1.len()].copy_from_slice(RECORD_DOMAIN_V1);
    let decoded_v1 = must(decode_record(&v1));
    assert_eq!(decoded_v1, RunStartRecordV1 {
        objective_function_v1_digest: Digest32::ZERO,
        objective_function_v1_bytes: Vec::new(),
        ..legacy.clone()
    });

    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let receipt = must(journal.append(Digest32::ZERO, legacy.clone()));
    assert_eq!(receipt.record_digest, Digest32::of_bytes(&v2));
    let before = locked_bytes(&journal.file.0);
    drop(journal);
    let mut recovered = must(fixture.recover(RunStartRecovery::Unacknowledged));
    assert_eq!(must(recovered.append(Digest32::ZERO, legacy)).disposition,
        RunStartAppendDisposition::IdempotentReplay);
    assert_eq!(locked_bytes(&recovered.file.0), before);
}

#[test]
fn authenticated_payload_mismatch_invalid_json_and_size_reject_before_journal_io() {
    let fixture = Fixture::new();
    let mut journal = fixture.create();
    let before = locked_bytes(&journal.file.0);
    for payload in [Vec::new(), b"not-json".to_vec(), b"[]".to_vec(),
        vec![b'x'; MAX_AUTHENTICATED_PAYLOAD_BYTES + 1]] {
        let mut invalid = record("run-invalid-authenticated", b"objective-semantic");
        invalid.authentication.signed_body_digest = Digest32::of_bytes(&payload);
        invalid.authenticated_payload = Some(payload);
        assert!(matches!(journal.append(Digest32::ZERO, invalid),
            Err(RunStartStoreError::InvalidSnapshot(_))));
        assert_eq!(locked_bytes(&journal.file.0), before);
    }
    let mut wrong_digest = record("run-forged-authenticated", b"objective-semantic");
    wrong_digest.authenticated_payload = Some(br#"{"text":"not the signed input"}"#.to_vec());
    assert_eq!(journal.append(Digest32::ZERO, wrong_digest),
        Err(RunStartStoreError::InvalidSnapshot("authenticatedPayloadDigest")));
    assert_eq!(locked_bytes(&journal.file.0), before);
}

#[test]
fn authenticated_payload_v3_rejects_truncated_changed_and_unbounded_tail() {
    let mut original = record("run-authenticated-tail", b"objective-semantic");
    let payload = br#"{"text":"original"}"#.to_vec();
    original.authentication.signed_body_digest = Digest32::of_bytes(&payload);
    original.authenticated_payload = Some(payload.clone());
    let encoded = encode_record(&original);
    for end in [encoded.len() - 1, encoded.len() - payload.len(), encoded.len() - payload.len() - 4] {
        assert_eq!(decode_record(&encoded[..end]), Err(RunStartStoreError::Corrupt));
    }
    let mut changed = encoded.clone();
    let payload_start = encoded.len() - payload.len();
    changed[payload_start + 10] = b'x';
    assert_eq!(decode_record(&changed), Err(RunStartStoreError::Corrupt));
    let mut oversized = encoded;
    oversized[payload_start - 4..payload_start]
        .copy_from_slice(&((MAX_AUTHENTICATED_PAYLOAD_BYTES + 1) as u32).to_be_bytes());
    assert_eq!(decode_record(&oversized), Err(RunStartStoreError::Corrupt));
}

#[path = "run_lifecycle_tests.rs"]
mod lifecycle_records;
