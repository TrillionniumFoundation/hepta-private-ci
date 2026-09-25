//! Exact authenticated publication lookup, distinct from fresh-source admission.
//!
//! The caller verifies the complete signed request against current AuthBus trust
//! before lookup. A durable publication is not recompiled using a later clock.
//! This lookup grants no effect authority: current trust and runtime final-use
//! checks still run before the recovered record can enter a coordinator.

use codex_hepta_learning_ledger::RunStartAppendReceipt;
use codex_hepta_learning_ledger::RunStartIndexKindV1;

use super::*;

pub(super) enum ObjectiveReplayPublication {
    Run {
        publication: RunStartAppendReceipt,
        record: Box<RunStartRecordV1>,
    },
    Conflict {
        conflict_digest: Digest32,
    },
}

pub(super) fn resolve_authenticated_replay(
    state: &ObjectiveHostState,
    authentication: &RunStartAuthenticationV1,
    run_id: &StableId,
    now_ms: u64,
    current_generation: u64,
    current_fence: Digest32,
) -> Result<Option<ObjectiveReplayPublication>, AgentdError> {
    // The destination owner checks its monotonic checkpoint, including the
    // poisoned/indeterminate state, before exposing a historical identity.
    let Some(entry) = state.journal.index_entry(run_id).map_err(store_error)? else {
        return Ok(None);
    };
    if &entry.authentication != authentication || authentication.expires_at_ms <= now_ms {
        return Err(invalid(
            "objective replay does not match its live signed publication",
        ));
    }
    let deadline = match entry.kind {
        RunStartIndexKindV1::Run {
            deadline_unix_micros,
            generation,
            fence_digest,
            ..
        } => {
            if generation != current_generation || fence_digest != current_fence {
                return Err(invalid(
                    "objective replay generation or fence is no longer current",
                ));
            }
            deadline_unix_micros
        }
        RunStartIndexKindV1::Conflict {
            deadline_unix_micros,
        } => deadline_unix_micros,
    };
    if deadline_is_expired(deadline, now_ms) {
        return Err(invalid("objective replay deadline expired"));
    }
    match entry.kind {
        RunStartIndexKindV1::Run { .. } => {
            let record = state
                .journal
                .get(run_id)
                .map_err(store_error)?
                .cloned()
                .ok_or_else(|| invalid("live objective replay payload is unavailable"))?;
            Ok(Some(ObjectiveReplayPublication::Run {
                publication: RunStartAppendReceipt {
                    disposition: RunStartAppendDisposition::IdempotentReplay,
                    sequence: entry.sequence,
                    record_digest: entry.record_digest,
                    chain_digest: entry.chain_digest,
                },
                record: Box::new(record),
            }))
        }
        RunStartIndexKindV1::Conflict { .. } => {
            let record = state
                .journal
                .get_conflict(run_id)
                .map_err(store_error)?
                .ok_or_else(|| invalid("live objective conflict replay payload is unavailable"))?;
            Ok(Some(ObjectiveReplayPublication::Conflict {
                conflict_digest: record.conflict_digest,
            }))
        }
    }
}
