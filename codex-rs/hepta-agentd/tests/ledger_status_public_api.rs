#![cfg(target_os = "linux")]

use codex_hepta_agentd::OriginalCellQ24TaskLedgerStatusV1;
use codex_hepta_learning_ledger::LedgerEvent;
use codex_hepta_learning_ledger::LedgerRecord;
use codex_hepta_learning_ledger::Revocation;
use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn into_records(status: OriginalCellQ24TaskLedgerStatusV1) -> (LedgerRecord, Option<LedgerRecord>) {
    match status {
        OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome { decision } => (decision, None),
        OriginalCellQ24TaskLedgerStatusV1::Complete { decision, outcome } => {
            (decision, Some(outcome))
        }
    }
}

#[test]
fn public_v1_ledger_variants_construct_and_match_owned_records() -> anyhow::Result<()> {
    let first = LedgerRecord {
        sequence: LogicalSequence::new(1)?,
        predecessor_chain_digest: Digest32::ZERO,
        event_digest: Digest32::of_bytes(b"first event"),
        chain_digest: Digest32::of_bytes(b"first head"),
        event: LedgerEvent::Revocation(Revocation {
            record_id: StableId::new("record.one")?,
            target_record_id: StableId::new("record.zero")?,
            authority_id: StableId::new("authority.one")?,
            reason_digest: Digest32::of_bytes(b"reason"),
        }),
    };
    let second = LedgerRecord {
        sequence: first.sequence.next()?,
        predecessor_chain_digest: first.chain_digest,
        ..first.clone()
    };
    let awaiting = OriginalCellQ24TaskLedgerStatusV1::AwaitingOutcome {
        decision: first.clone(),
    };
    assert_eq!(into_records(awaiting), (first.clone(), None));
    let complete = OriginalCellQ24TaskLedgerStatusV1::Complete {
        decision: first.clone(),
        outcome: second.clone(),
    };
    assert_eq!(into_records(complete), (first, Some(second)));
    Ok(())
}
