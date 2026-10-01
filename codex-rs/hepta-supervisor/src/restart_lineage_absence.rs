//! Only the original process owner's actual absence proof advances this state.
use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ExitedRestart {
    pub(crate) window_started_unix_ms: u64,
    pub(crate) attempt: u32,
    pub(crate) replacement: RestartProcessWitness,
}

pub(crate) fn process_to_reconcile(
    run_root: &Path,
    agent_id: &AgentId,
    window: u64,
    attempt: u32,
) -> Result<Option<RestartProcessWitness>, RestartLineageError> {
    let Some(lineage) = read(run_root)? else {
        return Ok(None);
    };
    if lineage.agent_id != *agent_id {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".into(),
        ));
    }
    if !lineage.same_operation(window, attempt) {
        return Ok(None);
    }
    Ok(match lineage.phase {
        RestartLineagePhase::PredecessorOwned => lineage.predecessor,
        RestartLineagePhase::ReplacementStarted | RestartLineagePhase::Completed => {
            lineage.replacement
        }
        RestartLineagePhase::ReplacementPending
        | RestartLineagePhase::ReplacementExited
        | RestartLineagePhase::Cancelled => None,
    })
}

pub(crate) fn completed_process_matches(
    run_root: &Path,
    agent_id: &AgentId,
    process: &RestartProcessWitness,
) -> Result<bool, RestartLineageError> {
    Ok(read(run_root)?.is_some_and(|lineage| {
        lineage.agent_id == *agent_id
            && lineage.phase == RestartLineagePhase::Completed
            && lineage.replacement.as_ref() == Some(process)
    }))
}

pub(crate) fn begin_absence_if_unrecorded(
    run_root: &Path,
    agent_id: &AgentId,
    window: u64,
    attempt: u32,
    predecessor: &RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    if read(run_root)?
        .is_none_or(|lineage| lineage.terminal() && !lineage.same_operation(window, attempt))
    {
        begin_absent(run_root, agent_id, window, attempt, predecessor.clone())?;
    }
    Ok(())
}

pub(crate) fn exited_restart(
    run_root: &Path,
    agent_id: &AgentId,
) -> Result<Option<ExitedRestart>, RestartLineageError> {
    let Some(lineage) = read(run_root)? else {
        return Ok(None);
    };
    if lineage.agent_id != *agent_id {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".into(),
        ));
    }
    Ok(if lineage.phase == RestartLineagePhase::ReplacementExited {
        lineage.replacement.map(|replacement| ExitedRestart {
            window_started_unix_ms: lineage.window_started_unix_ms,
            attempt: lineage.attempt,
            replacement,
        })
    } else {
        None
    })
}

pub(crate) fn mark_process_absent(
    run_root: &Path,
    agent_id: &AgentId,
    process: &RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    let Some(lineage) = read(run_root)? else {
        return Ok(());
    };
    if lineage.agent_id != *agent_id {
        return Err(RestartLineageError::Invalid(
            "restart lineage belongs to another Agent".into(),
        ));
    }
    match lineage.phase {
        RestartLineagePhase::PredecessorOwned => {
            mark_predecessor_exited(run_root, agent_id, process)
        }
        RestartLineagePhase::ReplacementStarted | RestartLineagePhase::ReplacementExited => {
            if lineage.replacement.as_ref() != Some(process) {
                return Err(RestartLineageError::Invalid(
                    "absence proof does not match the exact restart replacement".into(),
                ));
            }
            if lineage.phase == RestartLineagePhase::ReplacementExited {
                return Ok(());
            }
            write(
                run_root,
                &lineage.with_state(
                    /*predecessor_exit_observed*/ true,
                    Some(process.clone()),
                    RestartLineagePhase::ReplacementExited,
                )?,
            )
        }
        // A queued predecessor already has a durable exact exit; a completed
        // or cancelled operation does not acquire a new restart intent here.
        RestartLineagePhase::ReplacementPending
            if lineage.predecessor.as_ref() == Some(process) =>
        {
            Ok(())
        }
        RestartLineagePhase::Completed | RestartLineagePhase::Cancelled => Ok(()),
        RestartLineagePhase::ReplacementPending => Err(RestartLineageError::Invalid(
            "absence proof does not belong to the pending restart".into(),
        )),
    }
}

pub(crate) fn begin_absent(
    run_root: &Path,
    agent_id: &AgentId,
    window: u64,
    attempt: u32,
    predecessor: RestartProcessWitness,
) -> Result<(), RestartLineageError> {
    let next = DurableRestartLineage::new(agent_id.clone(), window, attempt, Some(predecessor))?
        .with_state(
            /*predecessor_exit_observed*/ true,
            /*replacement*/ None,
            RestartLineagePhase::ReplacementPending,
        )?;
    publish_begin(run_root, next)
}

#[cfg(test)]
#[path = "restart_lineage_absence_tests.rs"]
mod tests;
