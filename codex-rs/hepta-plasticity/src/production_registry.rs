//! Production-only durable registry gate with mandatory external anchor state.
//!
//! A bootstrap open is allowed only for a physically empty file. Every reopen
//! after the host has acknowledged at least one append requires the exact
//! externally retained anchor and delegates to `open_anchored`. This makes the
//! anti-rollback host responsibility executable instead of advisory.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io;

use codex_hepta_types::Digest32;

use crate::{
    DurableProposalAppendReceiptV1, DurableProposalRegistry, DurableProposalRegistryError,
    DurableRegistryAnchorV1, ParameterProposalV2,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionAnchorStateV1 {
    /// Valid only for a newly enrolled, physically empty registry file.
    BootstrapEmpty,
    /// Exact last host-acknowledged frame retained outside this file's rollback domain.
    Acknowledged(DurableRegistryAnchorV1),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProductionProposalRegistryError {
    BootstrapRequiresEmptyFile,
    MissingAnchorAfterAppend,
    Io(io::ErrorKind),
    Durable(DurableProposalRegistryError),
}

impl fmt::Display for ProductionProposalRegistryError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductionProposalRegistryError {}
impl From<io::Error> for ProductionProposalRegistryError {
    fn from(value: io::Error) -> Self {
        Self::Io(value.kind())
    }
}
impl From<DurableProposalRegistryError> for ProductionProposalRegistryError {
    fn from(value: DurableProposalRegistryError) -> Self {
        Self::Durable(value)
    }
}

/// A production durable registry that can only be opened from an explicit host
/// anchor posture. The wrapper grants no acceptance, selection, activation,
/// promotion, or release authority.
pub struct ProductionProposalRegistry {
    inner: DurableProposalRegistry,
}

impl ProductionProposalRegistry {
    pub fn open(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        anchor_state: ProductionAnchorStateV1,
    ) -> Result<Self, ProductionProposalRegistryError> {
        let inner = match anchor_state {
            ProductionAnchorStateV1::BootstrapEmpty => {
                if file.metadata()?.len() != 0 {
                    return Err(ProductionProposalRegistryError::BootstrapRequiresEmptyFile);
                }
                DurableProposalRegistry::open(
                    file,
                    registry_scope_digest,
                    writer_fence,
                    maximum_records,
                )?
            }
            ProductionAnchorStateV1::Acknowledged(anchor) => DurableProposalRegistry::open_anchored(
                file,
                registry_scope_digest,
                writer_fence,
                maximum_records,
                anchor,
            )?,
        };
        Ok(Self { inner })
    }

    pub fn append_v2(
        &mut self,
        expected_predecessor_frame_digest: Digest32,
        proposal: ParameterProposalV2,
    ) -> Result<DurableProposalAppendReceiptV1, ProductionProposalRegistryError> {
        self.inner
            .append_v2(expected_predecessor_frame_digest, proposal)
            .map_err(Into::into)
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, ProductionProposalRegistryError> {
        self.inner.current_anchor().map_err(Into::into)
    }

    pub fn acknowledged_anchor_after_append(
        &self,
    ) -> Result<DurableRegistryAnchorV1, ProductionProposalRegistryError> {
        self.current_anchor()?
            .ok_or(ProductionProposalRegistryError::MissingAnchorAfterAppend)
    }
}
