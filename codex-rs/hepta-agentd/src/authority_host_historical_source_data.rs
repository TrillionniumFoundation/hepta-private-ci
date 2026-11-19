//! Internal once-only optional captures. Both independent refusal arms contain
//! the full original Root action; no partial data observation grants Dataset use.

use super::*;

pub(crate) struct OriginalSourceDataCaptureV1 {
    pub(crate) cell: Option<cell::RegisteredOriginalCellCaptureV1>,
    pub(crate) ledger: Option<ledger::RegisteredOriginalLedgerCaptureV1>,
}

impl OriginalSourceDataCaptureV1 {
    pub(super) fn with_original_capture<T>(
        original: Self,
        action: impl FnOnce(
            Option<&mut cell::PendingOriginalCellCaptureV1<'_>>,
            Option<&mut ledger::PendingOriginalLedgerCaptureV1<'_>>,
        ) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        if original.ledger.is_some() && original.cell.is_none() {
            return Err(io::Error::other(
                "original Ledger capture requires actual Cell custody",
            ));
        }
        cell::RegisteredOriginalCellCaptureV1::with_original_cell_capture(original.cell, |cell| {
            ledger::RegisteredOriginalLedgerCaptureV1::with_original_ledger_capture(
                original.ledger,
                |ledger| action(cell, ledger),
            )
        })
    }
}
