//! Independently retained original Ledger custody. This module supplies data
//! capture only; historical Dataset admission requires a new Root recipient.

use super::*;

#[path = "authority_host_historical_ledger_files.rs"]
mod files;
pub(crate) use files::OriginalLedgerFiles;
use files::OriginalLedgerObservation;
use files::OriginalLedgerReadGuard;
