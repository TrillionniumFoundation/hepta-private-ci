//! Private source transaction custody. Only the original occupied readonly
//! lane supplies its permit; a failed actual read permanently fences the owner.

use tokio::sync::OwnedSemaphorePermit;

use super::*;
use crate::cell_q24_training_source::readonly::OriginalSourceReadTailV1;
use crate::cell_q24_training_source::readonly::OriginalSourceReadV1;

impl<W: AnchorWitnessStore> CellQ24TrainingOwnerV1<W> {
    pub(crate) fn begin_original_source_read<'lane>(
        &mut self,
        lane: &'lane OwnedSemaphorePermit,
    ) -> Result<Option<OriginalSourceReadV1<'lane>>, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = self
            .source
            .as_ref()
            .map(|source| OriginalCellQ24TrainingSourceV1::begin_readonly_in_lane(source, lane))
            .transpose()
            .map_err(Error::from);
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    pub(crate) fn finish_original_source_read<'lane>(
        &mut self,
        before: Option<OriginalSourceReadV1<'lane>>,
    ) -> Result<Option<OriginalSourceReadTailV1<'lane>>, Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = match (self.source.as_ref(), before) {
            (Some(source), Some(before)) => {
                OriginalCellQ24TrainingSourceV1::finish_readonly_in_lane(source, before)
                    .map(Some)
                    .map_err(Error::from)
            }
            (None, None) => Ok(None),
            _ => Err(Error::Binding("same original readonly source custody")),
        };
        if result.is_err() {
            self.fenced = true;
        }
        result
    }

    pub(crate) fn authenticate_original_source_read(
        &mut self,
        after: Option<OriginalSourceReadTailV1<'_>>,
    ) -> Result<(), Error> {
        if self.fenced {
            return Err(Error::CommitUncertain);
        }
        let result = match (self.source.as_ref(), after) {
            (Some(source), Some(after)) => {
                OriginalCellQ24TrainingSourceV1::authenticate_readonly_tail(source, after)
                    .map_err(Error::from)
            }
            (None, None) => Ok(()),
            _ => Err(Error::Binding("same original readonly source custody")),
        };
        if result.is_err() {
            self.fenced = true;
        }
        result
    }
}
