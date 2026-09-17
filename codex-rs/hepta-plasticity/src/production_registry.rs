//! Production-safe durable registry wrapper.
//!
//! Product composition must not reopen acknowledged history without an external
//! anti-rollback anchor. The raw `DurableProposalRegistry::open` API remains for
//! compatibility/tests, while this wrapper exposes only fresh initialization or
//! anchored reconciliation.

use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurableProposalAppendReceiptV1;
use crate::DurableProposalRegistry;
use crate::DurableProposalRegistryError;
use crate::DurableRegistryAnchorV1;
use crate::ParameterProposalV2;

pub struct ProductionProposalRegistry {
    inner: DurableProposalRegistry,
}

impl ProductionProposalRegistry {
    /// Initialize a host-enrolled file that is provably empty at this handle.
    /// Hosts MUST ensure the path is new and cannot alias acknowledged history.
    pub fn initialize_new(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
    ) -> Result<Self, DurableProposalRegistryError> {
        if file.metadata()?.len() != 0 {
            return Err(DurableProposalRegistryError::AcknowledgedHistoryMissing);
        }
        DurableProposalRegistry::open(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
        )
        .map(|inner| Self { inner })
    }

    /// Reopen acknowledged history only after matching a separately retained
    /// external anchor. A stale valid prefix therefore fails closed.
    pub fn open_anchored(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor: DurableRegistryAnchorV1,
    ) -> Result<Self, DurableProposalRegistryError> {
        DurableProposalRegistry::open_anchored(
            file,
            registry_scope_digest,
            writer_fence,
            maximum_records,
            anchor,
        )
        .map(|inner| Self { inner })
    }

    pub fn append_v2(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<DurableProposalAppendReceiptV1, DurableProposalRegistryError> {
        self.inner
            .append_v2(expected_predecessor_frame_digest, proposal)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, DurableProposalRegistryError> {
        self.inner.current_anchor()
    }

    pub fn get_v2_by_proposal_id(
        &self,
        proposal_id: &StableId,
    ) -> Result<Option<&ParameterProposalV2>, DurableProposalRegistryError> {
        self.inner.get_v2_by_proposal_id(proposal_id)
    }

    pub fn record_count(&self) -> Result<usize, DurableProposalRegistryError> {
        self.inner.record_count()
    }
}
