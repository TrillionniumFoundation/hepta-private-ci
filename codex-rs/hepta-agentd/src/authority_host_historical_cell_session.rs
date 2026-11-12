//! Cell file custody is fixed in the same original Source runtime before A.
//! The real Root enrollment records its baseline before acknowledging the
//! Initial offer; only the post-drain worker consumes the resulting capability.

use super::*;
use crate::authority_host_service::generation_initial::cell_retention::OriginalCellFiles;
use crate::authority_host_service::generation_initial::cell_retention::RegisteredOriginalCellCaptureV1;
use crate::authority_host_service::generation_initial::cell_retention::RootHistoricalCellInputsV1;

pub(super) enum OriginalCellCustody {
    Absent,
    Held(OriginalCellFiles),
    Registered(RegisteredOriginalCellCaptureV1),
}

impl PreparedHostAuthoritySession {
    pub(super) fn install_initial_source_cell(
        &mut self,
        inputs: RootHistoricalCellInputsV1,
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
        {
            return Err(io::Error::other("original Cell inputs must precede A"));
        }
        let mut retained = None;
        self.service.with_initial_publication_context(
            &self.config,
            &self.registration,
            &self.owner_pidfd,
            |_| {
                retained = Some(OriginalCellFiles::retain_original_cell(
                    inputs,
                    self.config.peer_uid,
                    self.config.peer_gid,
                )?);
                Ok(())
            },
        )?;
        let mut held = source
            .cell
            .try_lock()
            .map_err(|_| io::Error::other("original Cell custody busy"))?;
        if !matches!(&*held, OriginalCellCustody::Absent)
            || initial.phase.load(Ordering::Acquire) != PREPARED
            || source.phase.load(Ordering::Acquire) != PREPARED
        {
            source.close();
            return Err(io::Error::other(
                "original Cell custody already selected or released",
            ));
        }
        *held = OriginalCellCustody::Held(
            retained.ok_or_else(|| io::Error::other("original Cell input custody missing"))?,
        );
        Ok(())
    }
}

impl HistoricalSourceRuntime {
    pub(crate) fn register_original_source_cell(
        &self,
        context: SourceCaptureContext<'_>,
    ) -> io::Result<()> {
        self.root.require_current()?;
        let mut held = self
            .cell
            .try_lock()
            .map_err(|_| io::Error::other("original Cell custody busy"))?;
        let files = match std::mem::replace(&mut *held, OriginalCellCustody::Absent) {
            OriginalCellCustody::Absent => return Ok(()),
            OriginalCellCustody::Held(files) => files,
            OriginalCellCustody::Registered(_) => {
                self.close();
                return Err(io::Error::other(
                    "original Cell baseline was already registered",
                ));
            }
        };
        let registered = context.service.register_original_initial_cell(
            context.slot,
            context.config,
            context.registration,
            context.owner,
            files,
            context.end,
        );
        match registered {
            Ok(registered) => {
                *held = OriginalCellCustody::Registered(registered);
                Ok(())
            }
            Err(error) => {
                self.close();
                Err(error)
            }
        }
    }

    pub(super) fn take_original_source_cell(
        &self,
    ) -> io::Result<Option<RegisteredOriginalCellCaptureV1>> {
        let mut held = self
            .cell
            .try_lock()
            .map_err(|_| io::Error::other("original Cell custody busy"))?;
        match std::mem::replace(&mut *held, OriginalCellCustody::Absent) {
            OriginalCellCustody::Absent => Ok(None),
            OriginalCellCustody::Registered(original) => Ok(Some(original)),
            OriginalCellCustody::Held(_) => {
                self.close();
                Err(io::Error::other(
                    "original Cell baseline was never registered",
                ))
            }
        }
    }
}
