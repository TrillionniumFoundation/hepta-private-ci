use super::*;
use std::fs::OpenOptions;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

static NEXT_TEST_FILE: AtomicU64 = AtomicU64::new(0);

fn test_scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

#[cfg(unix)]
fn fixture_file() -> (std::path::PathBuf, File) {
    use std::os::unix::fs::OpenOptionsExt;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    let suffix = NEXT_TEST_FILE.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!(
        "hepta-effect-intent-{}-{nonce}-{suffix}.bin",
        std::process::id()
    ));
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(&path)
        .expect("exclusive fixture");
    (path, file)
}

#[cfg(unix)]
fn reopen(path: &std::path::Path) -> File {
    OpenOptions::new()
        .read(true)
        .write(true)
        .open(path)
        .expect("reopen")
}

#[cfg(unix)]
#[test]
fn durable_prepare_quarantines_recovery_and_reissued_nonce() {
    let (path, file) = fixture_file();
    let tick = Digest32::of_bytes(b"semantic-tick-one");
    {
        let mut owner = DurableNeuronEffectIntentV1::open(
            file, test_scope(), Generation::new(2).unwrap(), 8,
        ).unwrap();
        owner.prepare(tick, Digest32::ZERO).unwrap();
        assert_eq!(owner.status().unresolved_tick, Some(tick));
        assert_eq!(
            owner.can_prepare(Digest32::of_bytes(b"later-signed-tick")),
            Err(NeuronEffectIntentErrorV1::PendingReconciliation)
        );
    }
    {
        let recovered = DurableNeuronEffectIntentV1::open(
            reopen(&path), test_scope(), Generation::new(2).unwrap(), 8,
        ).unwrap();
        assert_eq!(recovered.status().unresolved_tick, Some(tick));
        assert_eq!(
            recovered.can_prepare(tick),
            Err(NeuronEffectIntentErrorV1::PendingReconciliation)
        );
    }
    std::fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[test]
fn committed_tick_is_deduplicated_across_new_authorization_and_restart() {
    let (path, file) = fixture_file();
    let tick = Digest32::of_bytes(b"semantic-tick-one");
    {
        let mut owner = DurableNeuronEffectIntentV1::open(
            file, test_scope(), Generation::new(2).unwrap(), 8,
        ).unwrap();
        owner.prepare(tick, Digest32::ZERO).unwrap();
        owner.resolve(tick, Digest32::of_bytes(b"checkpoint-one")).unwrap();
        assert_eq!(owner.status().unresolved_tick, None);
        assert_eq!(owner.status().durable_records, 2);
    }
    {
        let mut reopened = DurableNeuronEffectIntentV1::open(
            reopen(&path), test_scope(), Generation::new(2).unwrap(), 8,
        ).unwrap();
        assert_eq!(
            reopened.can_prepare(tick),
            Err(NeuronEffectIntentErrorV1::DuplicateTick)
        );
        let second = Digest32::of_bytes(b"semantic-tick-two");
        reopened.prepare(second, Digest32::of_bytes(b"checkpoint-one")).unwrap();
        reopened.resolve(second, Digest32::of_bytes(b"checkpoint-two")).unwrap();
        assert_eq!(reopened.status().attempted_ticks, 2);
    }
    std::fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[test]
fn file_scope_generation_and_exclusive_owner_are_fenced() {
    let (path, file) = fixture_file();
    let owner = DurableNeuronEffectIntentV1::open(
        file, test_scope(), Generation::new(2).unwrap(), 8,
    ).unwrap();
    assert!(matches!(
        DurableNeuronEffectIntentV1::open(
            reopen(&path), test_scope(), Generation::new(2).unwrap(), 8
        ),
        Err(NeuronEffectIntentErrorV1::Busy)
    ));
    drop(owner);
    assert!(matches!(
        DurableNeuronEffectIntentV1::open(
            reopen(&path), test_scope(), Generation::new(3).unwrap(), 8
        ),
        Err(NeuronEffectIntentErrorV1::Corrupt)
    ));
    std::fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[test]
fn torn_record_is_detected_and_denied_without_rollback() {
    let (path, file) = fixture_file();
    let mut owner = DurableNeuronEffectIntentV1::open(
        file, test_scope(), Generation::new(2).unwrap(), 8,
    ).unwrap();
    owner
        .prepare(Digest32::of_bytes(b"tick"), Digest32::ZERO)
        .unwrap();
    drop(owner);
    OpenOptions::new()
        .append(true)
        .open(&path)
        .unwrap()
        .write_all(b"torn")
        .unwrap();
    assert!(matches!(
        DurableNeuronEffectIntentV1::open(
            reopen(&path), test_scope(), Generation::new(2).unwrap(), 8
        ),
        Err(NeuronEffectIntentErrorV1::Corrupt)
    ));
    std::fs::remove_file(path).unwrap();
}

#[cfg(unix)]
#[test]
fn capacity_reserves_resolution_slot_before_effect() {
    let (path, file) = fixture_file();
    let mut owner = DurableNeuronEffectIntentV1::open(
        file, test_scope(), Generation::new(2).unwrap(), 2,
    ).unwrap();
    let tick = Digest32::of_bytes(b"tick");
    owner.prepare(tick, Digest32::ZERO).unwrap();
    owner.resolve(tick, Digest32::of_bytes(b"checkpoint")).unwrap();
    assert_eq!(
        owner.can_prepare(Digest32::of_bytes(b"another")),
        Err(NeuronEffectIntentErrorV1::Capacity)
    );
    drop(owner);
    std::fs::remove_file(path).unwrap();
}
