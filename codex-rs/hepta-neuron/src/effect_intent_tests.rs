use super::*;
#[cfg(unix)]
use std::fs::OpenOptions;
#[cfg(unix)]
use std::io::Write;
#[cfg(unix)]
use std::sync::atomic::AtomicU64;
#[cfg(unix)]
use std::sync::atomic::Ordering;
#[cfg(unix)]
use std::time::SystemTime;
#[cfg(unix)]
use std::time::UNIX_EPOCH;

#[cfg(unix)]
static NEXT_TEST_FILE: AtomicU64 = AtomicU64::new(0);

#[cfg(unix)]
fn test_scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

#[cfg(unix)]
fn fixture_file() -> Result<(std::path::PathBuf, File), Box<dyn std::error::Error>> {
    use std::os::unix::fs::OpenOptionsExt;
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH)?.as_nanos();
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
        .open(&path)?;
    Ok((path, file))
}

#[cfg(unix)]
fn reopen(path: &std::path::Path) -> std::io::Result<File> {
    OpenOptions::new().read(true).write(true).open(path)
}

#[cfg(unix)]
#[test]
fn tick_scope_binding_cannot_cross_objective_subject_or_generation() -> Result<(), Box<dyn std::error::Error>> {
    let subject = StableId::new("subject").unwrap();
    let (path, file) = fixture_file()?;
    let objective = Digest32::of_bytes(b"objective");
    let scope = JournalScope {
        scope_digest: crate::runtime_types::subject_scope_digest(&subject).unwrap(),
        objective_digest: objective,
    };
    let owner =
        DurableNeuronEffectIntentV1::open(file, scope, Generation::new(2).unwrap(), 8).unwrap();
    assert!(owner.matches_tick_scope(&subject, objective, Generation::new(2).unwrap()));
    assert!(!owner.matches_tick_scope(
        &StableId::new("another").unwrap(),
        objective,
        Generation::new(2).unwrap()
    ));
    assert!(!owner.matches_tick_scope(
        &subject,
        Digest32::of_bytes(b"other-objective"),
        Generation::new(2).unwrap()
    ));
    assert!(!owner.matches_tick_scope(&subject, objective, Generation::new(3).unwrap()));
    drop(owner);
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn durable_prepare_quarantines_recovery_and_reissued_nonce() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let tick = Digest32::of_bytes(b"semantic-tick-one");
    {
        let mut owner =
            DurableNeuronEffectIntentV1::open(file, test_scope(), Generation::new(2).unwrap(), 8)
                .unwrap();
        owner.prepare(tick, Digest32::ZERO).unwrap();
        assert_eq!(owner.status().unresolved_tick, Some(tick));
        assert_eq!(
            owner.can_prepare(Digest32::of_bytes(b"later-signed-tick")),
            Err(NeuronEffectIntentErrorV1::PendingReconciliation)
        );
    }
    {
        let mut recovered = DurableNeuronEffectIntentV1::open(
            reopen(&path)?,
            test_scope(),
            Generation::new(2).unwrap(),
            8,
        )
        .unwrap();
        assert_eq!(recovered.status().unresolved_tick, Some(tick));
        assert_eq!(
            recovered.can_prepare(tick),
            Err(NeuronEffectIntentErrorV1::PendingReconciliation)
        );
        // An arbitrary new checkpoint digest is not an independent signed
        // reconciliation receipt; it cannot clear an in-doubt crash intent.
        assert_eq!(
            recovered.resolve(tick, Digest32::of_bytes(b"forged-after-crash")),
            Err(NeuronEffectIntentErrorV1::PendingReconciliation)
        );
    }
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn committed_tick_is_deduplicated_across_new_authorization_and_restart() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let tick = Digest32::of_bytes(b"semantic-tick-one");
    {
        let mut owner =
            DurableNeuronEffectIntentV1::open(file, test_scope(), Generation::new(2).unwrap(), 8)
                .unwrap();
        owner.prepare(tick, Digest32::ZERO).unwrap();
        owner
            .resolve(tick, Digest32::of_bytes(b"checkpoint-one"))
            .unwrap();
        assert_eq!(owner.status().unresolved_tick, None);
        assert_eq!(owner.status().durable_records, 2);
    }
    {
        let mut reopened = DurableNeuronEffectIntentV1::open(
            reopen(&path)?,
            test_scope(),
            Generation::new(2).unwrap(),
            8,
        )
        .unwrap();
        assert_eq!(
            reopened.can_prepare(tick),
            Err(NeuronEffectIntentErrorV1::DuplicateTick)
        );
        let second = Digest32::of_bytes(b"semantic-tick-two");
        reopened
            .prepare(second, Digest32::of_bytes(b"checkpoint-one"))
            .unwrap();
        reopened
            .resolve(second, Digest32::of_bytes(b"checkpoint-two"))
            .unwrap();
        assert_eq!(reopened.status().attempted_ticks, 2);
    }
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn file_scope_generation_and_exclusive_owner_are_fenced() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let owner =
        DurableNeuronEffectIntentV1::open(file, test_scope(), Generation::new(2).unwrap(), 8)
            .unwrap();
    assert!(matches!(
        DurableNeuronEffectIntentV1::open(
            reopen(&path)?,
            test_scope(),
            Generation::new(2).unwrap(),
            8
        ),
        Err(NeuronEffectIntentErrorV1::Busy)
    ));
    drop(owner);
    assert!(matches!(
        DurableNeuronEffectIntentV1::open(
            reopen(&path)?,
            test_scope(),
            Generation::new(3).unwrap(),
            8
        ),
        Err(NeuronEffectIntentErrorV1::Corrupt)
    ));
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn torn_record_is_detected_and_denied_without_rollback() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let mut owner =
        DurableNeuronEffectIntentV1::open(file, test_scope(), Generation::new(2).unwrap(), 8)
            .unwrap();
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
            reopen(&path)?,
            test_scope(),
            Generation::new(2).unwrap(),
            8
        ),
        Err(NeuronEffectIntentErrorV1::Corrupt)
    ));
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn capacity_reserves_resolution_slot_before_effect() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let mut owner =
        DurableNeuronEffectIntentV1::open(file, test_scope(), Generation::new(2).unwrap(), 2)
            .unwrap();
    let tick = Digest32::of_bytes(b"tick");
    owner.prepare(tick, Digest32::ZERO).unwrap();
    owner
        .resolve(tick, Digest32::of_bytes(b"checkpoint"))
        .unwrap();
    assert_eq!(
        owner.can_prepare(Digest32::of_bytes(b"another")),
        Err(NeuronEffectIntentErrorV1::Capacity)
    );
    drop(owner);
    std::fs::remove_file(path)?;
    Ok(())
}

#[cfg(unix)]
#[test]
fn raw_unbound_journal_cannot_claim_bootstrap_path_identity() -> Result<(), Box<dyn std::error::Error>> {
    let (path, file) = fixture_file()?;
    let owner = DurableNeuronEffectIntentV1::open(
        file,
        test_scope(),
        Generation::new(2)?,
        8,
    )
    ?;
    assert_eq!(
        owner.verify_bound_owner_path(),
        Err(NeuronEffectIntentErrorV1::UnsafeFile),
    );
    // Raw-journal tests still exercise the low-level WAL, but an unbound
    // descriptor cannot be presented as an Agentd owner-path witness.
    assert!(
        owner
            .can_prepare(Digest32::of_bytes(b"unbound-test-tick"))
            .is_ok(),
    );
    drop(owner);
    std::fs::remove_file(path)?;
    Ok(())
}
