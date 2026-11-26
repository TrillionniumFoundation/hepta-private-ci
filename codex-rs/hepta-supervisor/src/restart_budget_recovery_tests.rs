use std::time::Duration;

use pretty_assertions::assert_eq;

use super::RestartBudgetError;
use super::claim_restart;
use super::complete_restart;
use super::recover_restart_budget;
use crate::restart_journal::RESTART_JOURNAL_FILE;

#[test]
fn absent_restart_budget_does_not_create_a_recovery_claim() -> Result<(), RestartBudgetError> {
    let dir = tempfile::tempdir()?;
    assert!(recover_restart_budget(dir.path(), /*maximum_attempts*/ 3)?.is_none());
    assert!(!dir.path().join(RESTART_JOURNAL_FILE).exists());
    Ok(())
}

#[test]
fn completed_restart_recovery_keeps_consumed_attempts_without_queuing()
-> Result<(), RestartBudgetError> {
    let dir = tempfile::tempdir()?;
    for attempt in 1..=3 {
        let claim = claim_restart(
            dir.path(),
            /*maximum_attempts*/ 3,
            Duration::from_secs(/*secs*/ 60),
            Duration::from_millis(/*millis*/ 10),
        )?;
        assert_eq!(claim.attempt, attempt);
        complete_restart(dir.path())?;
        let path = dir.path().join(RESTART_JOURNAL_FILE);
        let before = std::fs::read(&path)?;
        let recovered = recover_restart_budget(dir.path(), /*maximum_attempts*/ 3)?
            .ok_or_else(|| RestartBudgetError::Invalid("missing completed budget".to_owned()))?;
        assert_eq!(
            (
                recovered.attempts,
                recovered.pending.map(|pending| pending.attempt)
            ),
            (attempt, None)
        );
        assert_eq!(std::fs::read(path)?, before);
    }
    Ok(())
}

#[test]
fn pending_restart_recovery_keeps_the_existing_claim_without_writing()
-> Result<(), RestartBudgetError> {
    let dir = tempfile::tempdir()?;
    let claim = claim_restart(
        dir.path(),
        /*maximum_attempts*/ 3,
        Duration::from_secs(/*secs*/ 60),
        Duration::from_millis(/*millis*/ 10),
    )?;
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let before = std::fs::read(&path)?;
    let recovered = recover_restart_budget(dir.path(), /*maximum_attempts*/ 3)?
        .ok_or_else(|| RestartBudgetError::Invalid("missing pending budget".to_owned()))?;
    assert_eq!(
        (
            recovered.attempts,
            recovered.pending.map(|pending| pending.attempt)
        ),
        (claim.attempt, Some(claim.attempt))
    );
    assert_eq!(std::fs::read(path)?, before);
    Ok(())
}

#[test]
fn recovery_rejects_consumed_attempts_above_the_configured_maximum()
-> Result<(), RestartBudgetError> {
    let dir = tempfile::tempdir()?;
    claim_restart(
        dir.path(),
        /*maximum_attempts*/ 3,
        Duration::from_secs(/*secs*/ 60),
        Duration::from_millis(/*millis*/ 10),
    )?;
    complete_restart(dir.path())?;
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let before = std::fs::read(&path)?;
    assert!(matches!(
        recover_restart_budget(dir.path(), /*maximum_attempts*/ 0),
        Err(RestartBudgetError::Invalid(_))
    ));
    assert_eq!(std::fs::read(path)?, before);
    Ok(())
}

#[test]
fn recovery_rejects_a_corrupt_restart_record_without_rewriting_it() -> Result<(), RestartBudgetError>
{
    let dir = tempfile::tempdir()?;
    let path = dir.path().join(RESTART_JOURNAL_FILE);
    let before = br#"{"schema_version":2}"#;
    std::fs::write(&path, before)?;
    assert!(matches!(
        recover_restart_budget(dir.path(), /*maximum_attempts*/ 3),
        Err(RestartBudgetError::Canonical(_))
    ));
    assert_eq!(std::fs::read(path)?, before);
    Ok(())
}
