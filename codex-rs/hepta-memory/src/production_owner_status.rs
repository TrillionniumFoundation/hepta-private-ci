//! Read-only lease metadata from an already-owned durable writer.

use super::*;

/// A point-in-time observation, never a grant or a writable-owner claim.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ProductionLeaseDisposition {
    Missing,
    Active,
    ExpiredActive,
    Released,
    RolledBack,
}

/// Token-free lease metadata. Generation is the observed durable lease
/// generation, not a checkpoint ordinal or recovery incarnation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ProductionLeaseHeadObservation {
    pub generation: Option<u64>,
    pub disposition: ProductionLeaseDisposition,
}

impl ProductionDurableWriter {
    /// Inspect only this writer's captured lease ID without opening a store or
    /// issuing authority. The existing inspector verifies the full bounded
    /// lease history, so cost grows with that history. Callers should bound
    /// in-flight reads and timeouts rather than poll without limit.
    ///
    /// Expiry uses the existing observation clock; this does not establish a
    /// protected current-time source. The result may become stale immediately.
    /// Corruption and read errors remain errors, never a healthy observation.
    pub async fn inspect_lease_head(
        &self,
    ) -> Result<ProductionLeaseHeadObservation, ProductionWriterError> {
        let inspection = self
            .store
            .inspect_local_lease_head(self.lease_id.as_ref())
            .await?;
        let disposition = match inspection.disposition {
            LocalLeaseHeadDisposition::Missing => ProductionLeaseDisposition::Missing,
            LocalLeaseHeadDisposition::Active => ProductionLeaseDisposition::Active,
            LocalLeaseHeadDisposition::ExpiredActive => ProductionLeaseDisposition::ExpiredActive,
            LocalLeaseHeadDisposition::Released => ProductionLeaseDisposition::Released,
            LocalLeaseHeadDisposition::RolledBack => ProductionLeaseDisposition::RolledBack,
        };
        Ok(ProductionLeaseHeadObservation {
            generation: inspection.head.as_ref().map(|head| head.generation),
            disposition,
        })
    }
}

#[cfg(test)]
#[path = "production_owner_status_tests.rs"]
mod tests;
