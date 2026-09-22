//! Canonical production façade for authoritative cognitive persistence.
//!
//! `hepta-memory` remains the physical SQLite durability engine, but product
//! callers should open and acquire the production writer through this module.
//! Keeping the semantic owner here prevents a second public "cognitive store"
//! role from becoming the product composition boundary.

use std::error::Error as StdError;
use std::fmt;
use std::path::Path;

use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::CognitiveRecoveryError;
use codex_hepta_memory::CognitiveRecoveryRequirement;
use codex_hepta_memory::CognitiveStore as DurableCognitiveBackend;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_memory::ProductionAuthorityLease;
use codex_hepta_memory::ProductionAuthorityVerifier;
use codex_hepta_memory::ProductionDurableWriter;
use codex_hepta_memory::ProductionWriterError;
use codex_hepta_paths::HeptaAgentLayout;

/// Product-facing authoritative cognitive store.
///
/// The contained backend is intentionally private. Product code obtains a
/// fenced durable writer through [`Self::open_writer`] instead of receiving a
/// raw `hepta-memory::CognitiveStore` handle that could bypass the owner seam.
#[derive(Clone)]
pub struct ProductionCognitiveStore {
    backend: DurableCognitiveBackend,
}

impl fmt::Debug for ProductionCognitiveStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProductionCognitiveStore")
            .field("path", &self.backend.path())
            .finish_non_exhaustive()
    }
}

#[derive(Debug)]
pub enum ProductionCognitiveStoreError {
    Durable(CognitiveStoreError),
    Recovery(CognitiveRecoveryError),
    Writer(ProductionWriterError),
}

impl fmt::Display for ProductionCognitiveStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Durable(error) => write!(formatter, "durable cognitive store: {error}"),
            Self::Recovery(error) => write!(formatter, "cognitive recovery: {error}"),
            Self::Writer(error) => write!(formatter, "production cognitive writer: {error}"),
        }
    }
}

impl StdError for ProductionCognitiveStoreError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Durable(error) => Some(error),
            Self::Recovery(error) => Some(error),
            Self::Writer(error) => Some(error),
        }
    }
}

impl From<CognitiveStoreError> for ProductionCognitiveStoreError {
    fn from(error: CognitiveStoreError) -> Self {
        Self::Durable(error)
    }
}

impl From<CognitiveRecoveryError> for ProductionCognitiveStoreError {
    fn from(error: CognitiveRecoveryError) -> Self {
        Self::Recovery(error)
    }
}

impl From<ProductionWriterError> for ProductionCognitiveStoreError {
    fn from(error: ProductionWriterError) -> Self {
        Self::Writer(error)
    }
}

impl ProductionCognitiveStore {
    /// Canonical bootstrap/reopen path for the durable cognitive database.
    ///
    /// This delegates physical durability and schema verification to
    /// `hepta-memory`, while preserving `hepta-cognitive-store` as the product
    /// ownership boundary. Rollback-sensitive hosts should prefer
    /// [`Self::open_with_recovery`] when they possess an independently retained
    /// exact-current-cut witness.
    pub async fn open(layout: &HeptaAgentLayout) -> Result<Self, ProductionCognitiveStoreError> {
        let backend = DurableCognitiveBackend::open(layout).await?;
        Ok(Self { backend })
    }

    /// Recovery-gated open for hosts that retain an authenticated current-cut
    /// witness outside the cognitive database.
    ///
    /// The underlying backend currently fails closed when the platform cannot
    /// provide its descriptor-bound recovery VFS. Surfacing that result here is
    /// deliberate: product code must not silently fall back to an unanchored
    /// writer after requesting recovery semantics.
    pub async fn open_with_recovery(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<Self, ProductionCognitiveStoreError> {
        let backend = DurableCognitiveBackend::open_with_recovery(layout, requirement).await?;
        Ok(Self { backend })
    }

    /// Capture the exact logical cut that a trusted host can persist outside
    /// the database and later feed to [`Self::open_with_recovery`].
    pub async fn recovery_anchor(
        &self,
    ) -> Result<CognitiveRecoveryAnchor, ProductionCognitiveStoreError> {
        Ok(self.backend.recovery_anchor().await?)
    }

    /// Acquire the single externally-authorized production writer against this
    /// store. The raw backend never leaves the authority façade.
    pub async fn open_writer<V>(
        &self,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        lease_generation: u64,
    ) -> Result<ProductionDurableWriter, ProductionCognitiveStoreError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        Ok(ProductionDurableWriter::open(
            self.backend.clone(),
            authority,
            verifier,
            lease_id,
            lease_generation,
        )
        .await?)
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        self.backend.path()
    }

    /// Crate-only escape hatch for owner tests. Product crates cannot obtain a
    /// raw durability handle through this API.
    #[cfg(test)]
    pub(crate) fn backend_for_test(&self) -> &DurableCognitiveBackend {
        &self.backend
    }
}

#[cfg(test)]
#[path = "production_tests.rs"]
mod tests;
