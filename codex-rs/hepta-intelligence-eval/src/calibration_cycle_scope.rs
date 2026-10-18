//! Current cycle membership is exact, signed and contiguous, never a success subset.
use crate::CalibrationPreflightError;
use codex_hepta_learning_ledger::CalibrationCutBindingV1;
use codex_hepta_learning_ledger::CalibrationCycleScopeV2;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::LedgerSnapshot;
use codex_hepta_types::Digest32;
pub(crate) fn current_records<'a>(
    snapshot: &'a LedgerSnapshot,
    cut: &CalibrationCutBindingV1,
    cycle: Option<&CalibrationCycleScopeV2>,
) -> Result<&'a [LedgerRecord], CalibrationPreflightError> {
    let Some(cycle) = cycle else {
        return Ok(snapshot.records());
    };
    if cycle.first_sequence == 0
        || cycle.run_snapshot_digests.is_empty()
        || cycle.run_snapshot_digests.len() > 2048
        || cycle.original_task_sources_digest.is_zero()
        || cycle.current_program_approval_digest.is_zero()
        || cycle
            .run_snapshot_digests
            .iter()
            .flatten()
            .any(|v| v.is_zero())
    {
        return Err(CalibrationPreflightError::Binding(
            "complete bounded signed cycle scope",
        ));
    }
    let offset = usize::try_from(cycle.first_sequence - 1)
        .map_err(|_| CalibrationPreflightError::Arithmetic)?;
    let records = snapshot
        .records()
        .get(offset..)
        .ok_or(CalibrationPreflightError::Binding(
            "cycle start not in original history",
        ))?;
    let previous = if offset == 0 {
        Digest32::ZERO
    } else {
        snapshot.records()[offset - 1].chain_digest
    };
    if previous != cycle.previous_acknowledged_head
        || records.len() != cycle.run_snapshot_digests.len() * 4
        || cut.acknowledged_sequence != (offset + records.len()) as u64
    {
        return Err(CalibrationPreflightError::Binding(
            "original acknowledged prefix and whole current cycle",
        ));
    }
    for (index, group) in records.chunks_exact(4).enumerate() {
        for (policy, offset) in [("candidate", 0usize), ("baseline", 2usize)] {
            let expected = format!("calibration.episode.{}.{policy}.{index}", cut.audit_digest);
            match (&group[offset].event, &group[offset + 1].event) {
                (
                    LedgerEvent::AuthenticatedDecisionV2(decision),
                    LedgerEvent::AuthenticatedOutcomeV2(outcome),
                ) if decision.episode_id.as_str() == expected
                    && outcome.episode_id == decision.episode_id
                    && decision.run_snapshot_digest
                        == cycle.run_snapshot_digests[index][offset / 2]
                    && group[offset].sequence.get()
                        == cycle.first_sequence + (index * 4 + offset) as u64
                    && group[offset + 1].sequence.get() == group[offset].sequence.get() + 1 => {}
                _ => {
                    return Err(CalibrationPreflightError::Binding(
                        "original ordered complete task pair/current snapshots",
                    ));
                }
            }
        }
    }
    Ok(records)
}
