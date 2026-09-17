//! Canonical production authority façade for the durable cognitive store.
//!
//! `CognitiveStore` is the SQLite storage backend and remains public for
//! compatibility with qualification/read-only callers. Product runtimes and
//! production writers must enter through this façade so there is one explicit
//! ownership boundary instead of a second in-memory authority.
//!
//! Recovery is deliberately fail-closed: writable recovery is not fabricated
//! from a suspect database. A host that owns an independently authenticated
//! exact-current-cut witness may open the existing image through the explicit
//! read-only recovery method until descriptor-backed writable recovery is
//! qualified.

use std::path::Path;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaAgentLayout;

use crate::CognitiveRecoveryAnchor;
use crate::CognitiveRecoveryError;
use crate::CognitiveRecoveryRequirement;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::ProductionAuthorityLease;
use crate::ProductionAuthorityVerifier;
use crate::ProductionDurableWriter;
use crate::ProductionWriterError;
use crate::RecoveredCognitiveReadOnly;

/// The only production-authority entry point for the Agent-local durable
/// cognitive database.
///
/// The contained backend is intentionally not exposed publicly. Read/runtime
/// composition inside this crate can consume it, while production writer
/// construction remains bound to this façade. The façade is deliberately not
/// `Clone`: opening a production writer consumes it, so one authority handle
/// cannot fan out into multiple independent writer constructions.
pub struct AuthoritativeCognitiveStore {
    backend: CognitiveStore,
}

impl AuthoritativeCognitiveStore {
    /// Open or migrate the canonical durable backend and verify its integrity.
    ///
    /// This is the product/runtime entry point. It does not silently recover a
    /// corrupt or rolled-back database; such a state remains fail-closed and
    /// requires an independently authenticated recovery witness.
    pub async fn open(layout: &HeptaAgentLayout) -> Result<Self, CognitiveStoreError> {
        let backend = CognitiveStore::open(layout).await?;
        Ok(Self { backend })
    }

    /// Wrap an already-open backend for an isolated qualification harness.
    ///
    /// This does not create production authority. Repository CALLERS policy
    /// requires zero product callers of qualification-only host seams that use
    /// this constructor. It exists so crash/restart qualification can control
    /// the exact pool lifetime without reintroducing a production bypass.
    pub fn from_qualification_backend(backend: CognitiveStore) -> Self {
        Self { backend }
    }

    /// Open the production durable writer from the canonical authority handle.
    /// Consuming `self` prevents the caller from retaining this authority handle
    /// and independently constructing another production writer from it.
    pub async fn open_production_writer<V>(
        self,
        authority: ProductionAuthorityLease,
        verifier: &V,
        lease_id: impl Into<String>,
        generation: u64,
    ) -> Result<ProductionDurableWriter, ProductionWriterError>
    where
        V: ProductionAuthorityVerifier + ?Sized,
    {
        ProductionDurableWriter::open(
            self.backend,
            authority,
            verifier,
            lease_id,
            generation,
        )
        .await
    }

    /// Capture the exact current-cut witness for independent host retention.
    pub async fn recovery_anchor(&self) -> Result<CognitiveRecoveryAnchor, CognitiveStoreError> {
        self.backend.recovery_anchor().await
    }

    /// Admit an existing cold image only as read-only recovery state.
    ///
    /// This is the canonical recovery seam while writable descriptor-backed
    /// recovery is not qualified. It never falls back to an ordinary writable
    /// open after a mismatch or indeterminate filesystem identity.
    pub async fn open_recovered_read_only(
        layout: &HeptaAgentLayout,
        requirement: CognitiveRecoveryRequirement<'_>,
    ) -> Result<RecoveredCognitiveReadOnly, CognitiveRecoveryError> {
        CognitiveStore::open_read_only_recovery(layout, requirement).await
    }

    #[must_use]
    pub fn path(&self) -> &Path {
        self.backend.path()
    }

    #[must_use]
    pub fn owner_agent_id(&self) -> &AgentId {
        self.backend.owner_agent_id()
    }

    /// Runtime composition is crate-owned so external product code cannot use
    /// this as a generic escape hatch back to the raw backend.
    pub(crate) fn into_runtime_backend(self) -> CognitiveStore {
        self.backend
    }
}

#[cfg(test)]
mod tests {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use codex_hepta_contracts::Sha256Digest;
    use tempfile::TempDir;

    use super::*;
    use crate::CognitiveAccess;
    use crate::CognitiveScope;
    use crate::ProductionAuthorityToken;
    use crate::cognitive_test_support::agent_id;
    use crate::cognitive_test_support::layout;
    use crate::cognitive_test_support::source;

    struct AllowVerifier;

    impl ProductionAuthorityVerifier for AllowVerifier {
        fn verify(
            &self,
            _authority: &ProductionAuthorityLease,
            _expected_agent: &AgentId,
        ) -> Result<(), String> {
            Ok(())
        }
    }

    fn authority(owner: AgentId) -> ProductionAuthorityLease {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_secs();
        ProductionAuthorityLease::from_verified_parts(
            owner,
            Sha256Digest::for_bytes(b"authoritative-store-test-grant"),
            7,
            3,
            now + 3_600,
            ProductionAuthorityToken::from_verified_bytes(
                b"authoritative-store-test-token".to_vec(),
            )
            .expect("token"),
        )
        .expect("authority")
    }

    #[tokio::test]
    async fn authoritative_open_reopens_real_sqlite_state() {
        let temp = TempDir::new().expect("tempdir");
        let owner = agent_id(241);
        let layout = layout(&temp, &owner);
        let access = CognitiveAccess::agent_private(owner.clone());

        let first = AuthoritativeCognitiveStore::open(&layout)
            .await
            .expect("authoritative store");
        let citation = first
            .backend
            .append_source(
                &access,
                &source(
                    CognitiveScope::AgentPrivate,
                    "authoritative-reopen",
                    "durable cognitive authority",
                ),
            )
            .await
            .expect("append source");
        let before = first.recovery_anchor().await.expect("anchor before reopen");
        let path = first.path().to_path_buf();
        drop(first);

        let reopened = AuthoritativeCognitiveStore::open(&layout)
            .await
            .expect("reopen authoritative store");
        assert_eq!(reopened.path(), path.as_path());
        assert_eq!(reopened.owner_agent_id(), &owner);
        let after = reopened.recovery_anchor().await.expect("anchor after reopen");
        assert_eq!(after, before);

        // The durable row must still participate in the current-cut witness;
        // keep the typed citation alive so an optimizer/test refactor cannot
        // accidentally turn this into an empty-database reopen test.
        assert_eq!(citation.revision, 1);
    }

    #[tokio::test]
    async fn authoritative_writer_fails_closed_on_second_live_owner() {
        let temp = TempDir::new().expect("tempdir");
        let owner = agent_id(242);
        let layout = layout(&temp, &owner);
        let authority = authority(owner);

        let first = AuthoritativeCognitiveStore::open(&layout)
            .await
            .expect("first authoritative store")
            .open_production_writer(
                authority.clone(),
                &AllowVerifier,
                "production:cognitive-authority:test",
                1,
            )
            .await
            .expect("first production writer");

        let second = AuthoritativeCognitiveStore::open(&layout)
            .await
            .expect("second authoritative store")
            .open_production_writer(
                authority,
                &AllowVerifier,
                "production:cognitive-authority:test",
                1,
            )
            .await
            .expect_err("a second live production writer must be fenced");

        assert!(matches!(second, ProductionWriterError::WriterBusy));
        drop(first);
    }
}
