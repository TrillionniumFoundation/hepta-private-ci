//! Read-only validation of every canonical slot in a retained source receipt.
use std::collections::BTreeMap;

use serde_json::json;
use sqlx::Sqlite;
use sqlx::Transaction;

use super::ProductionCognitiveMutationCapability;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::EpisodicImportReceipt;
use crate::EpisodicMemoryBinding;
use crate::MemoryLifecycleState;
use crate::ProductionCognitiveMutationError;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;
use crate::episodic_source::invalid;
use crate::episodic_source::snapshot::MAX_BINDINGS;
use crate::episodic_source::snapshot::digest;

impl ProductionCognitiveMutationCapability {
    /// Recheck a retained episodic mapping through its original writer without
    /// importing a snapshot, creating an event, or changing the canonical cut.
    /// Every slot is checked, including retired slots and dependencies absent
    /// from a particular retrieval result. Callers must supply the complete
    /// receipt retained from an acknowledged import through the original owner.
    /// This native-correspondence check does not authenticate an arbitrary
    /// caller-supplied receipt or establish that its binding roster is complete.
    /// It does not authenticate the external source or grant final-use authority.
    pub async fn revalidate_episodic_receipt(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        receipt: &EpisodicImportReceipt,
    ) -> Result<(), ProductionCognitiveMutationError> {
        let store = self.writer.store();
        store.authorize(access, scope)?;
        self.writer.verify_current_authority().await?;
        let mut transaction = store
            .observation_pool()
            .begin()
            .await
            .map_err(unavailable)?;
        self.revalidate_episodic_bindings_tx(&mut transaction, access, scope, receipt)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        self.writer.verify_current_authority().await?;
        Ok(())
    }

    pub(super) async fn revalidate_episodic_bindings_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
        receipt: &EpisodicImportReceipt,
    ) -> Result<BTreeMap<(String, String), EpisodicMemoryBinding>, ProductionCognitiveMutationError>
    {
        let store = self.writer.store();
        let scope_binding = digest(&json!([store.owner_agent_id(), scope, receipt.namespace]))?;
        if receipt.schema_version != 1
            || receipt.owner_agent_id != store.owner_agent_id().as_str()
            || receipt.scope_binding != scope_binding
            || receipt.bindings.len() > MAX_BINDINGS
        {
            return Err(invalid("episodic receipt identity or bound changed"));
        }
        let mut bindings = BTreeMap::new();
        for binding in &receipt.bindings {
            let id = StableMemoryId::parse(&binding.memory_id).map_err(invalid)?;
            let current = store.latest_memory_tx(transaction, access, &id).await?;
            let source_head: Option<(i64, String)> = sqlx::query_as(
                "SELECT source_revision, content_sha256 FROM source_ledger
                 WHERE source_id = ? ORDER BY source_revision DESC LIMIT 1",
            )
            .bind(&binding.canonical_source_id)
            .fetch_optional(&mut **transaction)
            .await
            .map_err(unavailable)?;
            if source_head
                != Some((
                    i64::try_from(binding.canonical_source_revision)
                        .map_err(|error| invalid(error.to_string()))?,
                    binding.source_content_sha256.clone(),
                ))
                || current.citations.len() != 1
                || current.citations[0].source_id.as_str() != binding.canonical_source_id
                || current.citations[0].revision != binding.canonical_source_revision
                || current.id.revision != binding.memory_revision
                || (current.lifecycle == MemoryLifecycleState::Active) != binding.active
                || current.scope != *scope
                || bindings
                    .insert(
                        (binding.source_id.clone(), binding.key.clone()),
                        binding.clone(),
                    )
                    .is_some()
            {
                return Err(invalid(
                    "canonical episodic head changed outside the bridge",
                ));
            }
        }
        Ok(bindings)
    }
}
