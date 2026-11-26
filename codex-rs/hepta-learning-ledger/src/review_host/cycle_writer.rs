//! Reuse the existing sole durable writer and independent acknowledged witness.
//! Their native recover operations acquire exclusive file ownership; no duplicate
//! locking owner, history reset or alternative admission path is introduced.
use super::files::ReviewResult;
use super::files::mutable_file;
use super::independent_trust::IndependentTrust;
use crate::DurableLedger;
use crate::LedgerRecovery;
use crate::LedgerWitnessStore;
use crate::LedgerWriter;
use codex_hepta_types::Digest32;
use std::fs::File;
use std::path::Path;
pub(super) struct ExistingHistory<'a> {
    pub trust: &'a IndependentTrust,
    pub binding: Digest32,
    pub ledger_path: &'a Path,
    pub witness_path: &'a Path,
    pub ledger_directory: &'a File,
    pub witness_directory: &'a File,
}
pub(super) fn open_existing(input: ExistingHistory<'_>) -> ReviewResult<LedgerWriter> {
    let witness = LedgerWitnessStore::recover(mutable_file(input.witness_path)?, input.binding)?;
    let anchor = witness.frontier()?.anchor;
    let recovery = if anchor.sequence == 0 && anchor.chain_digest.is_zero() {
        LedgerRecovery::Unacknowledged
    } else {
        LedgerRecovery::Acknowledged(anchor)
    };
    let ledger = DurableLedger::recover(
        mutable_file(input.ledger_path)?,
        input.binding,
        4096,
        recovery,
    )?;
    let writer = LedgerWriter::from_durable(
        ledger,
        witness,
        input.trust.activated.clone(),
        input.ledger_directory,
        input.witness_directory,
    )?;
    let snapshot = writer.snapshot()?;
    if input.trust.cycle.as_ref().is_some_and(|a| {
        a.previous_sequence != anchor.sequence || a.previous_head != snapshot.head_digest
    }) {
        return Err(
            "new program approval does not bind actual previous ledger/witness frontier".into(),
        );
    }
    Ok(writer)
}
