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
            profile_digest: digest("profile"),
            intent_digest: digest("intent"),
            admitted_source_digest: digest("admitted-source"),
            observed_at_unix_micros: 1_000_000,
            deadline_unix_micros: 2_000_000,
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
    let late_replay = must(journal.append(second.chain_digest, first.clone()));
    assert_eq!(
        late_replay.disposition,
        RunStartAppendDisposition::IdempotentReplay
    );
    assert_eq!(late_replay.record_digest, receipt.record_digest);

    let changed = record("run-1", b"objective-semantic-two");
    assert_eq!(
        journal.append(Digest32::ZERO, changed),
        Err(RunStartStoreError::Conflict)
    );
    assert_eq!(must(fs::read(fixture.path())), before);
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
        record: second_record,
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
        record: second_record,
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
