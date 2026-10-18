use super::*;
use crate::DurableMutationPhaseV1;
use crate::SupervisordMutation;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

#[test]
fn before_spawn_resolution_preserves_the_original_receipt_and_blocks_replay() -> anyhow::Result<()>
{
    let directory = tempfile::tempdir()?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let digest = "a".repeat(64);
    let first = crate::prepare_mutation(
        directory.path(),
        41,
        &agent,
        "epoch",
        SupervisordMutation::Start,
        &digest,
        1,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &first.idempotency_key)?;
    let resolved = crate::mutation_journal::resolve_before_spawn(
        directory.path(),
        &first.idempotency_key,
        &digest,
        &Sha256Digest::for_bytes(b"native proof"),
    )?;
    assert_eq!(resolved.phase, DurableMutationPhaseV1::NoEffect);
    assert_eq!(resolved.applied_state_revision, None);
    crate::prepare_mutation(
        directory.path(),
        42,
        &agent,
        "new-epoch",
        SupervisordMutation::Start,
        &digest,
        2,
    )?;
    assert_eq!(
        crate::mutation_journal_slots::lookup(directory.path(), 41)?.map(|owned| owned.status),
        Some(resolved)
    );
    assert!(matches!(
        crate::prepare_mutation(
            directory.path(),
            41,
            &agent,
            "new-epoch",
            SupervisordMutation::Start,
            &digest,
            3
        ),
        Err(MutationJournalError::Unresolved)
    ));
    Ok(())
}

#[test]
fn archive_directory_cut_repairs_only_the_still_authoritative_hot_receipt() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let digest = "a".repeat(64);
    let first = crate::prepare_mutation(
        directory.path(),
        41,
        &agent,
        "epoch",
        SupervisordMutation::Start,
        &digest,
        1,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &first.idempotency_key)?;
    let terminal = crate::commit_mutation(directory.path(), &first.idempotency_key, 1, 1, &digest)?;
    preserve(directory.path(), &terminal)?;
    let (_, _, receipt) = paths(directory.path(), 41);
    std::fs::remove_file(receipt.join(crate::MUTATION_JOURNAL_FILE))?;
    assert!(lookup(directory.path(), 41).is_err());
    preserve(directory.path(), &terminal)?;
    assert_eq!(lookup(directory.path(), 41)?, Some(terminal));
    Ok(())
}

#[test]
fn stopped_or_killed_mutations_cannot_claim_the_before_spawn_resolution() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let digest = "a".repeat(64);
    let first = crate::prepare_mutation(
        directory.path(),
        41,
        &agent,
        "epoch",
        SupervisordMutation::Stop,
        &digest,
        1,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &first.idempotency_key)?;
    assert!(
        crate::mutation_journal::resolve_before_spawn(
            directory.path(),
            &first.idempotency_key,
            &digest,
            &Sha256Digest::for_bytes(b"wrong operation")
        )
        .is_err()
    );
    assert_eq!(
        crate::read_mutation_status(directory.path())?.map(|status| status.phase),
        Some(DurableMutationPhaseV1::EffectStarted)
    );
    Ok(())
}

#[test]
fn missing_cold_receipt_cannot_be_repaired_from_a_different_hot_identity() -> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let digest = "a".repeat(64);
    let first = crate::prepare_mutation(
        directory.path(),
        41,
        &agent,
        "epoch",
        SupervisordMutation::Start,
        &digest,
        1,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &first.idempotency_key)?;
    let terminal = crate::commit_mutation(directory.path(), &first.idempotency_key, 1, 1, &digest)?;
    crate::prepare_mutation(
        directory.path(),
        42,
        &agent,
        "epoch",
        SupervisordMutation::Stop,
        &digest,
        2,
    )?;
    let (_, _, receipt) = paths(directory.path(), 41);
    std::fs::remove_file(receipt.join(crate::MUTATION_JOURNAL_FILE))?;
    assert!(lookup(directory.path(), 41).is_err());
    assert!(preserve(directory.path(), &terminal).is_err());
    Ok(())
}

#[test]
fn history_pressure_rejects_admission_without_replacing_the_hot_terminal_receipt()
-> anyhow::Result<()> {
    let directory = tempfile::tempdir()?;
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001")?;
    let digest = "a".repeat(64);
    let first = crate::prepare_mutation(
        directory.path(),
        41,
        &agent,
        "epoch",
        SupervisordMutation::Start,
        &digest,
        1,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &first.idempotency_key)?;
    crate::commit_mutation(directory.path(), &first.idempotency_key, 1, 1, &digest)?;
    let second = crate::prepare_mutation(
        directory.path(),
        42,
        &agent,
        "epoch",
        SupervisordMutation::Stop,
        &digest,
        2,
    )?;
    crate::mark_mutation_effect_started(directory.path(), &second.idempotency_key)?;
    let terminal =
        crate::commit_mutation(directory.path(), &second.idempotency_key, 2, 2, &digest)?;
    let (_, shard, _) = paths(directory.path(), 42);
    let mut builder = std::fs::DirBuilder::new();
    #[cfg(unix)]
    {
        use std::os::unix::fs::DirBuilderExt;
        builder.mode(0o700);
    }
    match builder.create(&shard) {
        Ok(()) => {}
        Err(error) if error.kind() == ErrorKind::AlreadyExists => {}
        Err(error) => return Err(error.into()),
    }
    for index in 0..MAX_SHARD_ENTRIES {
        builder.create(shard.join(format!("pressure-{index}")))?;
    }
    assert!(
        crate::prepare_mutation(
            directory.path(),
            43,
            &agent,
            "epoch",
            SupervisordMutation::Start,
            &digest,
            3
        )
        .is_err()
    );
    assert_eq!(
        crate::read_mutation_status(directory.path())?,
        Some(terminal)
    );
    assert!(lookup(directory.path(), 41)?.is_some());
    Ok(())
}
