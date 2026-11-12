//! The complete original task cut beneath independent persistent refusals.
//! A caller must authenticate the new recipient inside the borrowed action.
//! All five data kinds are mandatory; no partial cut grants historical access.

use std::path::PathBuf;
use std::time::Instant;

use super::cell::RootHistoricalCellInputsV1;
use super::cell::RootRetainedCellDataV1;
use super::ledger::PendingOriginalLedgerHistoryV1;
use super::ledger::RootOriginalHistoricalLedgerObservationV1;
use super::task_data::OriginalHistoricalSourceCellReadV1;
use super::*;
use crate::authority_host_runtime::RootInitialRunStartFilesV1;
use crate::authority_host_service::generation_initial::historical_source_handoff::RootHistoricalSourceHandoffV1;
use crate::authority_host_service::generation_initial::run_start_retention::RootOriginalRunStartReadV1;
use crate::authority_host_service::generation_initial::run_start_retention::RootRetainedRunStartDataV1;

pub(crate) struct RootRetainedHistoricalCompleteTaskV1 {
    root: Arc<RootAuthorityDirectory>,
    target: CellGenerationOwnerBindingV1,
    source: RootHistoricalSourcePinV1,
    cell: RootRetainedCellDataV1,
    handoff: RootHistoricalSourceHandoffV1,
    run_start: RootRetainedRunStartDataV1,
    ledger_deployment: PathBuf,
}

enum ReadState {
    AwaitingTarget,
    Bound,
    Verifying,
    Complete,
}

pub(crate) struct RootOriginalHistoricalTaskReadV1<'a, 'source, 'run_start, 'ledger> {
    original: &'a RootRetainedHistoricalCompleteTaskV1,
    source: &'a mut OriginalHistoricalSourceCellReadV1<'source>,
    run_start: &'a RootOriginalRunStartReadV1<'run_start>,
    ledger: &'a mut PendingOriginalLedgerHistoryV1<'ledger>,
    handoff_digest: Digest32,
    end: Instant,
    state: ReadState,
}

/// Data returned only after actual Source, Cell, RunStart and signed terminal
/// Ledger observations agree. No constructor accepts a peer-authored digest.
pub(crate) struct RootOriginalHistoricalCompleteTaskObservationV1 {
    cut: Digest32,
    ledger: RootOriginalHistoricalLedgerObservationV1,
}

impl RootRetainedHistoricalCompleteTaskV1 {
    /// All locators come from the Root provider's protected deployment. Each
    /// cold open requires an existing finalized record and independent marker;
    /// no constructor initializes, repairs or promotes missing original data.
    pub(crate) fn open_existing(
        root: Arc<RootAuthorityDirectory>,
        target: CellGenerationOwnerBindingV1,
        ledger_deployment: PathBuf,
        open_original_cell: impl FnOnce() -> io::Result<RootHistoricalCellInputsV1>,
    ) -> io::Result<Self> {
        original_root()?;
        let handoff = RootHistoricalSourceHandoffV1::open_finalized(Arc::clone(&root), &target)?;
        let source = RootHistoricalSourcePinV1::open_existing(Arc::clone(&root), &target)?;
        let cell =
            RootRetainedCellDataV1::open_captured(Arc::clone(&root), &target, open_original_cell)?;
        let run_start = RootRetainedRunStartDataV1::open_finalized(Arc::clone(&root), &target)?;
        Ok(Self {
            root,
            target,
            source,
            cell,
            handoff,
            run_start,
            ledger_deployment,
        })
    }

    pub(crate) fn with_original_historical_task<T>(
        &self,
        service: &HostAuthorityService,
        end: Instant,
        action: impl FnOnce(&mut RootOriginalHistoricalTaskReadV1<'_, '_, '_, '_>) -> io::Result<T>,
    ) -> io::Result<T> {
        original_root()?;
        self.handoff
            .with_finalized_source_data(&self.source, |handoff_digest| {
                self.source
                    .with_original_source_cell_data(&self.cell, |source| {
                        self.run_start
                            .with_original_run_start_data(end, |run_start| {
                                service.with_retained_original_ledger(
                                    Arc::clone(&self.root),
                                    &self.target,
                                    &self.ledger_deployment,
                                    end,
                                    |ledger| {
                                        if Instant::now() >= end {
                                            return Err(io::Error::other(
                                                "historical task session expired",
                                            ));
                                        }
                                        let mut read = RootOriginalHistoricalTaskReadV1 {
                                            original: self,
                                            source,
                                            run_start,
                                            ledger,
                                            handoff_digest,
                                            end,
                                            state: ReadState::AwaitingTarget,
                                        };
                                        // The actual recipient writer, pidfd, AuthBus,
                                        // lease and revocation postchecks must return here.
                                        let value = action(&mut read)?;
                                        if !matches!(read.state, ReadState::Complete)
                                            || Instant::now() >= end
                                        {
                                            return Err(io::Error::other(
                                                "complete historical task observation required",
                                            ));
                                        }
                                        Ok(value)
                                    },
                                )
                            })
                    })
            })
    }
}

impl RootOriginalHistoricalTaskReadV1<'_, '_, '_, '_> {
    /// Bind the actual Root recipient profile's configured original target,
    /// inside its authenticated context. A caught mismatch cannot be retried.
    pub(crate) fn require_original_target(
        &mut self,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<()> {
        if !matches!(
            std::mem::replace(&mut self.state, ReadState::Verifying),
            ReadState::AwaitingTarget
        ) || target != &self.original.target
            || Instant::now() >= self.end
        {
            return Err(io::Error::other("original historical task target differs"));
        }
        self.state = ReadState::Bound;
        Ok(())
    }

    /// The provider opens Source and RunStart descriptors inside this same
    /// action from fixed Root metadata. The outer readers retain their real
    /// files and locks through the recipient's final checks and physical reread.
    pub(crate) fn observe_original_task(
        &mut self,
        load_original_source: impl FnOnce(
            &crate::AgentdIdentity,
        ) -> io::Result<RootHistoricalSourceInputsV1>,
        load_original_run_start: impl FnOnce() -> io::Result<Arc<RootInitialRunStartFilesV1>>,
    ) -> io::Result<RootOriginalHistoricalCompleteTaskObservationV1> {
        original_root()?;
        if !matches!(
            std::mem::replace(&mut self.state, ReadState::Verifying),
            ReadState::Bound
        ) || Instant::now() >= self.end
        {
            return Err(io::Error::other(
                "historical task read already attempted or expired",
            ));
        }
        let source = self
            .source
            .read_original_retired_source_cell(load_original_source)?;
        let pin = &self.original.source.expected.pin;
        RootOriginalRunStartReadV1::require_original_publisher(
            self.run_start,
            source.source.original_identity(),
            &self.original.target,
            &pin.publisher,
            pin.publisher_epoch,
            &pin.initial_profile,
            &pin.writer,
            &pin.target_files,
        )?;
        let run_start = RootOriginalRunStartReadV1::read_original_publication(
            self.run_start,
            load_original_run_start()?,
            source.source.original_identity(),
        )?;
        if &run_start.observed.record != source.source.publication().original_record() {
            return Err(io::Error::other(
                "Source request is not the original Root-retained RunStart",
            ));
        }
        let ledger = PendingOriginalLedgerHistoryV1::observe_original_terminal(
            self.ledger,
            &self.original.source,
            &source.source,
            &source.definition,
            &source.cell,
        )?;
        let run_start_digest = RootOriginalRunStartReadV1::retained_digest(self.run_start)?;
        let ledger_digest = RootOriginalHistoricalLedgerObservationV1::data_cut_digest(&ledger)?;
        let cut = Digest32::of_parts(&[
            b"hepta.root.original-historical-complete-task-cut.v1\0",
            &self.original.target.digest().map_err(io::Error::other)?,
            self.handoff_digest.as_array(),
            source.source_pin_digest.as_array(),
            source.cell_cut_digest.as_array(),
            run_start_digest.as_array(),
            ledger_digest.as_array(),
            source.source.publication().publication_digest().as_array(),
        ]);
        if Instant::now() >= self.end {
            return Err(io::Error::other(
                "historical task expired during physical observation",
            ));
        }
        self.state = ReadState::Complete;
        Ok(RootOriginalHistoricalCompleteTaskObservationV1 { cut, ledger })
    }
}

impl RootOriginalHistoricalCompleteTaskObservationV1 {
    pub(crate) fn data_cut_digest(&self) -> Digest32 {
        self.cut
    }

    /// The transport may project only the exact Ledger data observed in the
    /// complete task. This object itself grants no Dataset or current access.
    pub(crate) fn ledger_read_data(
        &self,
    ) -> io::Result<crate::root_historical_ledger_data::RootHistoricalLedgerReadDataV1> {
        RootOriginalHistoricalLedgerObservationV1::ledger_read_data(&self.ledger)
    }
}
