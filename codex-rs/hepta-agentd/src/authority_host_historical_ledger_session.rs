//! Actual original Root Source runtime custody for the four Ledger files.
//! The peer cannot select or replace this optional pre-A attachment.

use super::*;
use crate::authority_host_runtime::RootHistoricalLedgerDeploymentV1;
use crate::authority_host_service::generation_initial::historical_source_pin::ledger::OriginalLedgerFiles;
use crate::authority_host_service::generation_initial::historical_source_pin::ledger::RegisteredOriginalLedgerCaptureV1;

pub(super) enum OriginalLedgerCustody {
    Absent,
    Held(OriginalLedgerFiles),
    Registered(RegisteredOriginalLedgerCaptureV1),
}

impl PreparedHostAuthoritySession {
    pub(super) fn install_initial_source_ledger(
        &mut self,
        inputs: RootHistoricalLedgerDeploymentV1,
    ) -> io::Result<()> {
        crate::authority_host_service::generation_initial::original_root()?;
        let initial = self
            .initial_publication
            .as_mut()
            .ok_or_else(|| io::Error::other("original Initial runtime missing"))?;
        let source = initial
            .source_capture
            .as_ref()
            .ok_or_else(|| io::Error::other("original Source runtime missing"))?;
        if initial.phase.load(Ordering::Acquire) != PREPARED
            || source.phase.load(Ordering::Acquire) != PREPARED
            || inputs.initial != initial.deployment
            || !matches!(
                &*source
                    .cell
                    .try_lock()
                    .map_err(|_| io::Error::other("original Cell custody busy"))?,
                cell_retention::OriginalCellCustody::Held(_)
            )
        {
            return Err(io::Error::other(
                "original Ledger and Cell custody must precede A",
            ));
        }
        let mut retained = None;
        self.service.with_initial_publication_context(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            |_| {
                retained = Some(OriginalLedgerFiles::retain_original_ledger(
                    inputs,
                    self.config.peer_uid,
                    self.config.peer_gid,
                )?);
                Ok(())
            },
        )?;
        let mut held = source
            .ledger
            .try_lock()
            .map_err(|_| io::Error::other("original Ledger custody busy"))?;
        if !matches!(&*held, OriginalLedgerCustody::Absent)
            || initial.phase.load(Ordering::Acquire) != PREPARED
            || source.phase.load(Ordering::Acquire) != PREPARED
        {
            source.close();
            return Err(io::Error::other(
                "original Ledger custody already selected or released",
            ));
        }
        *held = OriginalLedgerCustody::Held(
            retained.ok_or_else(|| io::Error::other("original Ledger input custody missing"))?,
        );
        Ok(())
    }
}

impl HistoricalSourceRuntime {
    pub(crate) fn register_original_source_ledger(
        &self,
        context: SourceCaptureContext<'_>,
    ) -> io::Result<()> {
        self.root.require_current()?;
        let mut held = self
            .ledger
            .try_lock()
            .map_err(|_| io::Error::other("original Ledger custody busy"))?;
        let files = match std::mem::replace(&mut *held, OriginalLedgerCustody::Absent) {
            OriginalLedgerCustody::Absent => return Ok(()),
            OriginalLedgerCustody::Held(files) => files,
            OriginalLedgerCustody::Registered(_) => {
                self.close();
                return Err(io::Error::other(
                    "original Ledger baseline was already registered",
                ));
            }
        };
        let registered = context.service.register_original_initial_ledger(
            context.slot,
            context.config,
            context.registration,
            context.owner,
            files,
            context.end,
        );
        match registered {
            Ok(registered) => {
                *held = OriginalLedgerCustody::Registered(registered);
                Ok(())
            }
            Err(error) => {
                self.close();
                Err(error)
            }
        }
    }

    pub(super) fn take_original_source_ledger(
        &self,
    ) -> io::Result<Option<RegisteredOriginalLedgerCaptureV1>> {
        let mut held = self
            .ledger
            .try_lock()
            .map_err(|_| io::Error::other("original Ledger custody busy"))?;
        match std::mem::replace(&mut *held, OriginalLedgerCustody::Absent) {
            OriginalLedgerCustody::Absent => Ok(None),
            OriginalLedgerCustody::Registered(original) => Ok(Some(original)),
            OriginalLedgerCustody::Held(_) => {
                self.close();
                Err(io::Error::other(
                    "original Ledger baseline was never registered",
                ))
            }
        }
    }
}
