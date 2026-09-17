//! Production writer wrapper that makes an external anti-rollback anchor mandatory.
//!
//! `DurableProposalRegistry::open` remains useful for qualification/bootstrap, but
//! production composition must not trust a file that can be replaced by an older
//! valid prefix. This wrapper refuses non-empty unanchored history and advances a
//! host-owned anchor with compare-and-store after every durable append.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;

use crate::DurableProposalAppendReceiptV1;
use crate::DurableProposalRegistry;
use crate::DurableProposalRegistryError;
use crate::DurableRegistryAnchorV1;
use crate::ParameterProposalV2;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionAnchorStoreErrorV1 {
    Unavailable,
    Conflict,
    Corrupt,
}

impl fmt::Display for ProductionAnchorStoreErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductionAnchorStoreErrorV1 {}

/// Host-owned storage outside the proposal file's rollback domain.
///
/// The implementation MUST survive replacement/restore of the proposal file and
/// MUST provide atomic compare-and-store semantics for one `(scope, fence)` key.
pub trait DurableProposalAnchorStoreV1 {
    fn load_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
    ) -> Result<Option<DurableRegistryAnchorV1>, ProductionAnchorStoreErrorV1>;

    fn compare_and_store_anchor(
        &mut self,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        expected: Option<DurableRegistryAnchorV1>,
        next: DurableRegistryAnchorV1,
    ) -> Result<(), ProductionAnchorStoreErrorV1>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionProposalAppendReceiptV1 {
    pub durable: DurableProposalAppendReceiptV1,
    pub acknowledged_anchor: DurableRegistryAnchorV1,
}

#[derive(Debug)]
pub enum ProductionProposalRegistryErrorV1 {
    Durable(DurableProposalRegistryError),
    Anchor(ProductionAnchorStoreErrorV1),
    AnchorRequiredForExistingHistory,
    AnchorCommitIndeterminate,
    Poisoned,
}

impl fmt::Display for ProductionProposalRegistryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl StdError for ProductionProposalRegistryErrorV1 {}
impl From<DurableProposalRegistryError> for ProductionProposalRegistryErrorV1 {
    fn from(value: DurableProposalRegistryError) -> Self {
        Self::Durable(value)
    }
}
impl From<ProductionAnchorStoreErrorV1> for ProductionProposalRegistryErrorV1 {
    fn from(value: ProductionAnchorStoreErrorV1) -> Self {
        Self::Anchor(value)
    }
}

/// Externally anchored production proposal writer.
///
/// If the proposal append reaches stable storage but the external anchor cannot
/// be advanced, the handle becomes poisoned. Reopen only after an operator or
/// host reconciles the durable file against the authoritative anchor store.
pub struct ProductionProposalRegistryV1<S: DurableProposalAnchorStoreV1> {
    inner: DurableProposalRegistry,
    anchor_store: S,
    registry_scope_digest: Digest32,
    writer_fence: u64,
    acknowledged_anchor: Option<DurableRegistryAnchorV1>,
    poisoned: bool,
}

impl<S: DurableProposalAnchorStoreV1> ProductionProposalRegistryV1<S> {
    pub fn open(
        file: File,
        registry_scope_digest: Digest32,
        writer_fence: u64,
        maximum_records: usize,
        mut anchor_store: S,
    ) -> Result<Self, ProductionProposalRegistryErrorV1> {
        let physical_len = file.metadata().map_err(DurableProposalRegistryError::from)?.len();
        let acknowledged_anchor = anchor_store.load_anchor(registry_scope_digest, writer_fence)?;
        let inner = match acknowledged_anchor {
            Some(anchor) => DurableProposalRegistry::open_anchored(
                file,
                registry_scope_digest,
                writer_fence,
                maximum_records,
                anchor,
            )?,
            None => {
                if physical_len != 0 {
                    return Err(
                        ProductionProposalRegistryErrorV1::AnchorRequiredForExistingHistory,
                    );
                }
                DurableProposalRegistry::open(
                    file,
                    registry_scope_digest,
                    writer_fence,
                    maximum_records,
                )?
            }
        };
        Ok(Self {
            inner,
            anchor_store,
            registry_scope_digest,
            writer_fence,
            acknowledged_anchor,
            poisoned: false,
        })
    }

    /// Append after the exact internally observed predecessor, then synchronously
    /// acknowledge the new anchor in an independent rollback domain.
    pub fn append_v2(
        &mut self,
        proposal: ParameterProposalV2,
    ) -> Result<ProductionProposalAppendReceiptV1, ProductionProposalRegistryErrorV1> {
        if self.poisoned {
            return Err(ProductionProposalRegistryErrorV1::Poisoned);
        }
        let predecessor = self
            .acknowledged_anchor
            .map_or(Digest32::ZERO, |anchor| anchor.frame_digest);
        let durable = self.inner.append_v2(predecessor, proposal)?;
        let next = self
            .inner
            .current_anchor()?
            .ok_or(ProductionProposalRegistryErrorV1::AnchorCommitIndeterminate)?;
        if let Err(_error) = self.anchor_store.compare_and_store_anchor(
            self.registry_scope_digest,
            self.writer_fence,
            self.acknowledged_anchor,
            next,
        ) {
            self.poisoned = true;
            return Err(ProductionProposalRegistryErrorV1::AnchorCommitIndeterminate);
        }
        self.acknowledged_anchor = Some(next);
        Ok(ProductionProposalAppendReceiptV1 {
            durable,
            acknowledged_anchor: next,
        })
    }

    pub fn current_anchor(
        &self,
    ) -> Result<Option<DurableRegistryAnchorV1>, ProductionProposalRegistryErrorV1> {
        if self.poisoned {
            return Err(ProductionProposalRegistryErrorV1::Poisoned);
        }
        Ok(self.acknowledged_anchor)
    }

    pub fn record_count(&self) -> Result<usize, ProductionProposalRegistryErrorV1> {
        if self.poisoned {
            return Err(ProductionProposalRegistryErrorV1::Poisoned);
        }
        self.inner.record_count().map_err(Into::into)
    }

    #[must_use]
    pub const fn is_poisoned(&self) -> bool {
        self.poisoned
    }
}
