//! Original completed Task data through one actual authenticated Root receipt.
//! The Source/Cell writers may have exited. Each read still invokes Root's
//! mandatory five-kind physical join and its independent persistent refusals.

use super::*;
use crate::AgentdRootAuthoritySession;
use crate::root_historical_task_read_client::OriginalHistoricalTaskReadReceiptV1;
use crate::root_historical_task_read_client::RootHistoricalTaskReadClientV1;

struct HistoricalTaskSource {
    receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
}

impl OriginalTask for HistoricalTaskSource {
    fn read(&self) -> Result<CircuitTaskSourcePublicationV1, Error> {
        self.receipt
            .read_original_publication()
            .map(|(publication, _)| publication)
            .map_err(|_| Error::Binding("original historical Task no longer available"))
    }

    fn read_for_historical_receipt(
        &self,
        receipt: &Arc<OriginalHistoricalTaskReadReceiptV1>,
    ) -> Result<CircuitTaskSourcePublicationV1, Error> {
        if !Arc::ptr_eq(&self.receipt, receipt) {
            return Err(Error::Binding(
                "Task and Dataset use different actual Root receipts",
            ));
        }
        self.read()
    }
}

impl CellQ24DatasetTaskV1 {
    /// This constructor accepts the opaque original-client receipt, never a
    /// decoded publication, raw Cell decision, digest or caller-authored cut.
    pub(crate) fn capture_historical(
        receipt: Arc<OriginalHistoricalTaskReadReceiptV1>,
        client: &Arc<RootHistoricalTaskReadClientV1>,
        session: &AgentdRootAuthoritySession,
    ) -> Result<Self, Error> {
        receipt
            .require_original_client(client, session)
            .map_err(|_| Error::Binding("original historical Root session differs"))?;
        let (publication, decision) = receipt
            .read_original_publication()
            .map_err(|_| Error::Binding("complete original historical Task required"))?;
        let source = Arc::new(HistoricalTaskSource { receipt });
        if source.read()? != publication {
            return Err(Error::Binding("historical Task changed during capture"));
        }
        source
            .receipt
            .require_original_client(client, session)
            .map_err(|_| Error::Binding("original historical Root session changed"))?;
        Ok(Self {
            source,
            publication,
            decision,
        })
    }

    /// The Dataset and every Task retain this exact opaque receipt. A second
    /// raw DTO or another client cannot substitute even identical bytes.
    pub(crate) fn require_historical_receipt(
        &self,
        receipt: &Arc<OriginalHistoricalTaskReadReceiptV1>,
    ) -> Result<(), Error> {
        if self.source.read_for_historical_receipt(receipt)? != self.publication {
            return Err(Error::Binding("original historical Dataset Task changed"));
        }
        Ok(())
    }
}
