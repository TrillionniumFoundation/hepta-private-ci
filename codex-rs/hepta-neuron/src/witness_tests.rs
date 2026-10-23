use super::*;

use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use pretty_assertions::assert_eq;

static NEXT: AtomicU64 = AtomicU64::new(0);

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

struct Fixture(PathBuf);

impl Fixture {
    fn new() -> Self {
        let serial = NEXT.fetch_add(1, Ordering::Relaxed);
        let root = std::env::temp_dir().join(format!(
            "hepta-neuron-witness-{}-{serial}",
            std::process::id()
        ));
        checked(fs::create_dir(&root));
        checked(
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(root.join("witness")),
        );
        Self(root)
    }

    fn path(&self) -> PathBuf {
        self.0.join("witness")
    }

    fn file(&self) -> File {
        checked(OpenOptions::new().read(true).write(true).open(self.path()))
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

fn generation() -> Generation {
    checked(Generation::new(1))
}

fn anchor(sequence: u64) -> JournalAnchor {
    JournalAnchor {
        sequence,
        checkpoint_digest: Digest32::of_bytes(format!("checkpoint-{sequence}").as_bytes()),
    }
}

#[test]
fn witness_history_survives_reopen_and_fences_stale_cas() {
    let fixture = Fixture::new();
    {
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
        checked(store.compare_and_swap(Some(anchor(1)), anchor(2)));
        assert_eq!(checked(store.current()), Some(anchor(2)));
    }
    let mut reopened = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
    ));
    assert_eq!(checked(reopened.current()), Some(anchor(2)));
    assert_eq!(
        reopened.compare_and_swap(Some(anchor(1)), anchor(2)),
        Err(WitnessStoreError::Conflict)
    );
    assert_eq!(checked(reopened.current()), Some(anchor(2)));
}

#[test]
fn wrong_scope_generation_and_corruption_never_reinitialize_history() {
    let fixture = Fixture::new();
    {
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
    }
    let original = checked(fs::read(fixture.path()));
    let mut changed_scope = scope();
    changed_scope.scope_digest = Digest32::of_bytes(b"other-subject");
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            changed_scope,
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), original);

    let generation_two = checked(Generation::new(2));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation_two,
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    let mut corrupt = original;
    let last = corrupt.len() - 1;
    corrupt[last] ^= 1;
    checked(fs::write(fixture.path(), &corrupt));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::Corrupt)
    );
    assert_eq!(checked(fs::read(fixture.path())), corrupt);
}

#[test]
fn witness_capacity_and_independent_writer_are_bounded() {
    let fixture = Fixture::new();
    let mut store = checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 1,
    ));
    assert_eq!(store.check_capacity(), Ok(()));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 1,
        )
        .err(),
        Some(WitnessStoreError::Busy)
    );
    checked(store.compare_and_swap(None, anchor(1)));
    assert_eq!(store.check_capacity(), Err(WitnessStoreError::Capacity));
    assert_eq!(checked(store.current()), Some(anchor(1)));
    assert_eq!(
        store.compare_and_swap(Some(anchor(1)), anchor(2)),
        Err(WitnessStoreError::Capacity)
    );
}

#[cfg(unix)]
#[test]
fn uncertain_witness_write_poison_is_visible_before_the_next_tick() {
    let fixture = Fixture::new();
    drop(checked(FileAnchorWitnessStore::open(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
    )));
    let original = checked(fs::read(fixture.path()));
    let read_only = checked(File::open(fixture.path()));
    let mut store = checked(FileAnchorWitnessStore::open(
        read_only,
        scope(),
        generation(),
        /*max_records*/ 8,
    ));
    assert_eq!(store.check_capacity(), Ok(()));
    assert_eq!(
        store.compare_and_swap(None, anchor(1)),
        Err(WitnessStoreError::Indeterminate)
    );
    assert_eq!(store.check_capacity(), Err(WitnessStoreError::Poisoned));
    assert_eq!(
        store.verify_context(scope(), generation()),
        Err(WitnessStoreError::Poisoned)
    );
    assert_eq!(store.current(), Err(WitnessStoreError::Poisoned));
    drop(store);
    assert_eq!(checked(fs::read(fixture.path())), original);
}

#[test]
fn oversized_witness_rejects_before_replaying_or_repairing_history() {
    let fixture = Fixture::new();
    let header = encode_header(scope(), generation(), WitnessBinding::Legacy);
    let mut bytes = header.to_vec();
    // Even invalid frames must not be read when the file exceeds the host quota.
    bytes.extend_from_slice(&[0; 2 * RECORD]);
    checked(fs::write(fixture.path(), &bytes));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 1,
        )
        .err(),
        Some(WitnessStoreError::Capacity)
    );
    assert_eq!(checked(fs::read(fixture.path())), bytes);
}

#[cfg(all(unix, target_pointer_width = "32"))]
#[test]
fn witness_record_count_cannot_wrap_to_an_empty_history() {
    let fixture = Fixture::new();
    checked(fs::write(
        fixture.path(),
        encode_header(scope(), generation(), WitnessBinding::Legacy),
    ));
    // set_len creates a sparse extent on this Unix fixture without allocating
    // record bytes. A premature usize cast would turn this count into zero.
    let records = u64::from(u32::MAX) + 1;
    let length = HEADER as u64 + records * RECORD as u64;
    checked(fixture.file().set_len(length));
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::Capacity)
    );
    assert_eq!(checked(fs::metadata(fixture.path())).len(), length);
}

#[test]
fn damaged_header_and_partial_witness_record_never_reset_history() {
    let fixture = Fixture::new();
    let header = encode_header(scope(), generation(), WitnessBinding::Legacy);
    for bytes in [
        {
            let mut bytes = header.to_vec();
            bytes[8] ^= 1;
            bytes
        },
        {
            let mut bytes = header.to_vec();
            bytes.extend_from_slice(&encode_record(None, anchor(1))[..RECORD - 1]);
            bytes
        },
    ] {
        checked(fs::write(fixture.path(), &bytes));
        assert_eq!(
            FileAnchorWitnessStore::open(
                fixture.file(),
                scope(),
                generation(),
                /*max_records*/ 8,
            )
            .err(),
            Some(WitnessStoreError::Corrupt)
        );
        assert_eq!(checked(fs::read(fixture.path())), bytes);
    }
}

#[cfg(target_os = "linux")]
#[test]
fn failed_witness_recovery_releases_lock_with_a_transient_duplicate_alive() {
    let fixture = Fixture::new();
    checked(fs::write(fixture.path(), b"broken"));
    let file = fixture.file();
    let transient = checked(file.try_clone());
    assert_eq!(
        FileAnchorWitnessStore::open(file, scope(), generation(), /*max_records*/ 8).err(),
        Some(WitnessStoreError::Corrupt)
    );
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::Corrupt)
    );
    drop(transient);
    assert_eq!(checked(fs::read(fixture.path())), b"broken");
}

#[test]
fn bound_witness_config_and_history_survive_reopen_and_append() {
    let fixture = Fixture::new();
    let config_digest = Digest32::of_bytes(b"complete runtime configuration");
    {
        let mut store = checked(FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            config_digest,
        ));
        assert_eq!(store.runtime_config_digest(), Ok(config_digest));
        checked(store.compare_and_swap(None, anchor(1)));
        checked(store.compare_and_swap(Some(anchor(1)), anchor(2)));
    }
    let original = checked(fs::read(fixture.path()));
    assert_eq!(original.len(), BOUND_HEADER + 2 * RECORD);
    {
        let mut reopened = checked(FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            config_digest,
        ));
        assert_eq!(reopened.runtime_config_digest(), Ok(config_digest));
        assert_eq!(reopened.current(), Ok(Some(anchor(2))));
        checked(reopened.compare_and_swap(Some(anchor(2)), anchor(3)));
    }
    let mut expected = original;
    expected.extend_from_slice(&encode_record(Some(anchor(2)), anchor(3)));
    assert_eq!(checked(fs::read(fixture.path())), expected);
}

#[test]
fn changed_runtime_config_and_legacy_open_cannot_rebind_bound_history() {
    let fixture = Fixture::new();
    let config_digest = Digest32::of_bytes(b"complete runtime configuration");
    {
        let mut store = checked(FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            config_digest,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
    }
    let original = checked(fs::read(fixture.path()));
    assert_eq!(
        FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            Digest32::of_bytes(b"changed complete runtime configuration"),
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(
        FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), original);
}

#[test]
fn legacy_witness_never_adopts_caller_supplied_runtime_config() {
    let fixture = Fixture::new();
    {
        let mut store = checked(FileAnchorWitnessStore::open(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
        ));
        checked(store.compare_and_swap(None, anchor(1)));
        assert_eq!(
            store.runtime_config_digest(),
            Err(WitnessStoreError::UnboundRuntimeConfig)
        );
    }
    let original = checked(fs::read(fixture.path()));
    assert_eq!(
        FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            Digest32::of_bytes(b"unverified caller configuration"),
        )
        .err(),
        Some(WitnessStoreError::UnboundRuntimeConfig)
    );
    assert_eq!(checked(fs::read(fixture.path())), original);
}

#[test]
fn invalid_bound_config_and_damaged_bound_header_do_not_initialize_or_repair() {
    let fixture = Fixture::new();
    assert_eq!(
        FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            Digest32::ZERO,
        )
        .err(),
        Some(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(checked(fs::read(fixture.path())), Vec::<u8>::new());
    let config_digest = Digest32::of_bytes(b"complete runtime configuration");
    let mut damaged = encode_header(
        scope(),
        generation(),
        WitnessBinding::RuntimeConfig(config_digest),
    );
    damaged[80] ^= 1;
    checked(fs::write(fixture.path(), &damaged));
    assert_eq!(
        FileAnchorWitnessStore::open_bound(
            fixture.file(),
            scope(),
            generation(),
            /*max_records*/ 8,
            config_digest,
        )
        .err(),
        Some(WitnessStoreError::Corrupt)
    );
    assert_eq!(checked(fs::read(fixture.path())), damaged);
}

#[test]
fn correct_runtime_config_does_not_authorize_another_scope_or_generation() {
    let fixture = Fixture::new();
    let config_digest = Digest32::of_bytes(b"complete runtime configuration");
    let store = checked(FileAnchorWitnessStore::open_bound(
        fixture.file(),
        scope(),
        generation(),
        /*max_records*/ 8,
        config_digest,
    ));
    assert_eq!(store.runtime_config_digest(), Ok(config_digest));
    assert_eq!(store.verify_context(scope(), generation()), Ok(()));
    let mut other_scope = scope();
    other_scope.scope_digest = Digest32::of_bytes(b"another subject");
    assert_eq!(
        store.verify_context(other_scope, generation()),
        Err(WitnessStoreError::ContextMismatch)
    );
    other_scope = scope();
    other_scope.objective_digest = Digest32::of_bytes(b"another objective");
    assert_eq!(
        store.verify_context(other_scope, generation()),
        Err(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(
        store.verify_context(scope(), checked(Generation::new(/*value*/ 2))),
        Err(WitnessStoreError::ContextMismatch)
    );
    assert_eq!(store.current(), Ok(None));
    drop(store);
    assert_eq!(
        checked(fs::read(fixture.path())),
        encode_header(
            scope(),
            generation(),
            WitnessBinding::RuntimeConfig(config_digest),
        )
    );
}
