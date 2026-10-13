use super::*;
use codex_hepta_types::Digest32;

#[cfg(unix)]
fn test_scope() -> JournalScope {
    JournalScope {
        scope_digest: Digest32::of_bytes(b"subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    }
}

#[cfg(unix)]
fn test_generation() -> Generation {
    // A constant valid generation; invalid values are not part of this
    // bootstrap's input contract.
    match Generation::new(2) {
        Ok(value) => value,
        Err(_) => panic!("invalid test generation"),
    }
}

#[cfg(unix)]
#[test]
fn secure_bootstrap_fsyncs_and_replays_duplicate_tick() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("subject.intent");
    let tick = Digest32::of_bytes(b"business-tick");
    {
        let mut owner =
            bootstrap_durable_neuron_effect_intent_v1(&path, test_scope(), test_generation(), 8)?;
        owner.prepare(tick, Digest32::ZERO)?;
        owner.resolve(tick, Digest32::of_bytes(b"checkpoint"))?;
    }
    let owner = bootstrap_durable_neuron_effect_intent_v1(
        &path,
        test_scope(),
        test_generation(),
        8,
    )?;
    assert_eq!(owner.status().attempted_ticks, 1);
    assert_eq!(owner.status().durable_records, 2);
    assert_eq!(owner.status().unresolved_tick, None);
    assert_eq!(owner.can_prepare(tick), Err(NeuronEffectIntentErrorV1::DuplicateTick));
    Ok(())
}

#[cfg(unix)]
#[test]
fn unresolved_crash_intent_stays_quarantined() -> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let path = directory.path().join("subject.intent");
    let tick = Digest32::of_bytes(b"effect-may-have-entered");
    {
        let mut owner =
            bootstrap_durable_neuron_effect_intent_v1(&path, test_scope(), test_generation(), 8)?;
        owner.prepare(tick, Digest32::ZERO)?;
    }
    let mut recovered = bootstrap_durable_neuron_effect_intent_v1(
        &path,
        test_scope(),
        test_generation(),
        8,
    )?;
    assert_eq!(recovered.status().unresolved_tick, Some(tick));
    assert_eq!(
        recovered.can_prepare(Digest32::of_bytes(b"fresh-authorized-tick")),
        Err(NeuronEffectIntentErrorV1::PendingReconciliation)
    );
    assert_eq!(
        recovered.resolve(tick, Digest32::of_bytes(b"unverified-new-checkpoint")),
        Err(NeuronEffectIntentErrorV1::PendingReconciliation)
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn symlink_hardlink_and_group_writable_directory_deny() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt;
    use std::os::unix::fs::symlink;

    let directory = tempfile::tempdir()?;
    let protected_path = directory.path().join("protected.intent");
    let owner =
        bootstrap_durable_neuron_effect_intent_v1(&protected_path, test_scope(), test_generation(), 8)?;
    drop(owner);

    let link = directory.path().join("alias.intent");
    symlink(&protected_path, &link)?;
    assert!(matches!(
        bootstrap_durable_neuron_effect_intent_v1(&link, test_scope(), test_generation(), 8),
        Err(NeuronEffectBootstrapErrorV1::UnsafeFile)
    ));
    let hardlink = directory.path().join("alias-hard.intent");
    std::fs::hard_link(&protected_path, &hardlink)?;
    assert!(matches!(
        bootstrap_durable_neuron_effect_intent_v1(
            &protected_path,
            test_scope(),
            test_generation(),
            8,
        ),
        Err(NeuronEffectBootstrapErrorV1::UnsafeFile)
    ));
    std::fs::remove_file(hardlink)?;
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o770))?;
    assert!(matches!(
        bootstrap_durable_neuron_effect_intent_v1(
            &protected_path,
            test_scope(),
            test_generation(),
            8,
        ),
        Err(NeuronEffectBootstrapErrorV1::UnsafeDirectory)
    ));
    Ok(())
}

#[test]
fn relative_path_can_never_be_a_production_effect_journal() {
    #[cfg(unix)]
    {
        assert!(matches!(
            bootstrap_durable_neuron_effect_intent_v1(
                Path::new("relative.intent"),
                test_scope(),
                test_generation(),
                8,
            ),
            Err(NeuronEffectBootstrapErrorV1::InvalidPath)
        ));
    }
    #[cfg(not(unix))]
    {
        assert!(matches!(
            bootstrap_durable_neuron_effect_intent_v1(
                Path::new("relative.intent"),
                JournalScope {
                    scope_digest: Digest32::of_bytes(b"scope"),
                    objective_digest: Digest32::of_bytes(b"objective"),
                },
                match Generation::new(2) {
                    Ok(value) => value,
                    Err(_) => panic!("invalid test generation"),
                },
                8,
            ),
            Err(NeuronEffectBootstrapErrorV1::UnsupportedPlatform)
        ));
    }
}

#[test]
fn mismatched_sparse_runtime_scope_is_denied_before_effect_intent_creation() {
    let actual = JournalScope {
        scope_digest: Digest32::of_bytes(b"actual-subject"),
        objective_digest: Digest32::of_bytes(b"objective"),
    };
    let wrong_subject = JournalScope {
        scope_digest: Digest32::of_bytes(b"other-subject"),
        ..actual
    };
    let wrong_objective = JournalScope {
        objective_digest: Digest32::of_bytes(b"other-objective"),
        ..actual
    };
    assert_eq!(verify_neuron_effect_scope_v1(actual, actual), Ok(()));
    assert_eq!(
        verify_neuron_effect_scope_v1(actual, wrong_subject),
        Err(NeuronEffectBootstrapErrorV1::ScopeMismatch)
    );
    assert_eq!(
        verify_neuron_effect_scope_v1(actual, wrong_objective),
        Err(NeuronEffectBootstrapErrorV1::ScopeMismatch)
    );
}


#[cfg(unix)]
#[test]
fn rejects_replaced_journal_inode() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt as _;

    let directory = tempfile::tempdir()?;
    let path = directory.path().join("subject.intent");
    let moved = directory.path().join("original.intent");
    let mut owner =
        bootstrap_durable_neuron_effect_intent_v1(&path, test_scope(), test_generation(), 8)?;
    let initial = Digest32::of_bytes(b"first-business-tick");
    owner.prepare(initial, Digest32::ZERO)?;
    owner.resolve(initial, Digest32::of_bytes(b"first-commit"))?;
    let bytes = std::fs::read(&path)?;

    // A second process replaces the exact pathname with a plausible journal
    // while this owner retains its lock on the original inode. Merely reading
    // a valid digest from the replacement must not authorize another effect.
    std::fs::rename(&path, &moved)?;
    std::fs::write(&path, &bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;

    let subsequent = Digest32::of_bytes(b"second-business-tick");
    assert_eq!(
        owner.can_prepare(subsequent),
        Err(NeuronEffectIntentErrorV1::UnsafeFile),
    );
    assert_eq!(
        owner.prepare(subsequent, Digest32::of_bytes(b"first-commit")),
        Err(NeuronEffectIntentErrorV1::UnsafeFile),
    );
    assert!(owner.status().poisoned);
    assert_eq!(std::fs::read(&path)?, bytes);
    assert_eq!(std::fs::read(&moved)?, bytes);
    Ok(())
}

#[cfg(unix)]
#[test]
fn pending_recovery_rejects_path_swap() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::unix::fs::PermissionsExt as _;

    let directory = tempfile::tempdir()?;
    let path = directory.path().join("subject.intent");
    let moved = directory.path().join("original.intent");
    let mut owner =
        bootstrap_durable_neuron_effect_intent_v1(&path, test_scope(), test_generation(), 8)?;
    let pending = Digest32::of_bytes(b"pending-business-tick");
    owner.prepare(pending, Digest32::ZERO)?;
    let bytes = std::fs::read(&path)?;

    std::fs::rename(&path, &moved)?;
    std::fs::write(&path, &bytes)?;
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600))?;
    assert_eq!(
        owner.resolve(pending, Digest32::of_bytes(b"committed-but-untrusted")),
        Err(NeuronEffectIntentErrorV1::UnsafeFile),
    );
    assert_eq!(owner.status().unresolved_tick, Some(pending));
    assert!(owner.status().poisoned);
    assert_eq!(std::fs::read(&moved)?, bytes);
    assert_eq!(std::fs::read(&path)?, bytes);
    Ok(())
}
