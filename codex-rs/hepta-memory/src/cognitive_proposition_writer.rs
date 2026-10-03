//! Additive assertion input through the existing source/Memory/KG transaction.
//! Historical KG relations, including arbitrary similarly named predicates,
//! remain opaque: only this new extractor-contract identity is interpreted.

use super::*;
use crate::KgRelationFactDraft;
use sqlx::Sqlite;
use sqlx::Transaction;

impl CognitiveStore {
    /// Append explicit affirmative and negative propositions with cited source
    /// lineage. `affirmed.entities` declares the common endpoints. No polarity
    /// is inferred from source text, legacy relation labels or content hashes.
    /// The existing owner's access and write authorization still apply.
    pub async fn remember_with_assertions(
        &self,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        affirmed: &KgFactSetDraft,
        denied: &[KgRelationFactDraft],
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let receipt = self
            .remember_with_assertions_tx(&mut transaction, access, source, draft, affirmed, denied)
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    pub(crate) async fn remember_with_assertions_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        source: &SourceDraft,
        draft: &MemoryDraft,
        affirmed: &KgFactSetDraft,
        denied: &[KgRelationFactDraft],
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        let facts = assertion_facts(affirmed, denied)?;
        validate_source_binding(source, &draft.revision.scope, &draft.revision.content)?;
        if draft.revision.lifecycle != MemoryLifecycleState::Active {
            return Err(CognitiveStoreError::Invalid(
                "remember requires an active revision".to_string(),
            ));
        }
        validate_fact_eligibility(&draft.revision, &facts)?;
        let citation = self.append_source_tx(transaction, access, source).await?;
        let mut bound = draft.clone();
        bind_exact_citation(&mut bound.revision, &citation)?;
        let memory = self
            .create_memory_revision_tx(transaction, access, &bound)
            .await?;
        let canonical =
            self.canonicalize_fact_set(&memory, &citation, &facts, ASSERTION_CONTRACT)?;
        self.insert_revision_facts_tx(transaction, &memory, &citation, &canonical)
            .await?;
        let projection = self
            .refresh_scope_projection_tx(transaction, &memory.scope, &memory, &citation, &canonical)
            .await?;
        Ok(CognitiveWriteReceipt {
            memory,
            source: citation,
            projection,
        })
    }

    /// Correct the complete assertion set under the same compare-and-swap
    /// revision fence as the existing KG writer. An old proposition cannot
    /// survive by being left in a second index or side store.
    #[allow(clippy::too_many_arguments)]
    pub async fn correct_with_assertions(
        &self,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        affirmed: &KgFactSetDraft,
        denied: &[KgRelationFactDraft],
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        let mut transaction = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let receipt = self
            .correct_with_assertions_tx(
                &mut transaction,
                access,
                memory_id,
                expected_revision,
                source,
                draft,
                affirmed,
                denied,
            )
            .await?;
        transaction.commit().await.map_err(unavailable)?;
        Ok(receipt)
    }

    #[allow(clippy::too_many_arguments)]
    pub(crate) async fn correct_with_assertions_tx(
        &self,
        transaction: &mut Transaction<'_, Sqlite>,
        access: &CognitiveAccess,
        memory_id: &StableMemoryId,
        expected_revision: u64,
        source: &SourceDraft,
        draft: &MemoryRevisionDraft,
        affirmed: &KgFactSetDraft,
        denied: &[KgRelationFactDraft],
    ) -> Result<CognitiveWriteReceipt, CognitiveStoreError> {
        let facts = assertion_facts(affirmed, denied)?;
        validate_source_binding(source, &draft.scope, &draft.content)?;
        if draft.verification != MemoryVerification::Verified
            || draft.lifecycle != MemoryLifecycleState::Active
        {
            return Err(CognitiveStoreError::Invalid(
                "correction requires a verified active revision".to_string(),
            ));
        }
        validate_fact_eligibility(draft, &facts)?;
        let citation = self.append_source_tx(transaction, access, source).await?;
        let mut bound = draft.clone();
        bind_exact_citation(&mut bound, &citation)?;
        let memory = self
            .revise_memory_revision_tx(transaction, access, memory_id, expected_revision, &bound)
            .await?;
        let canonical =
            self.canonicalize_fact_set(&memory, &citation, &facts, ASSERTION_CONTRACT)?;
        self.insert_revision_facts_tx(transaction, &memory, &citation, &canonical)
            .await?;
        let projection = self
            .refresh_scope_projection_tx(transaction, &memory.scope, &memory, &citation, &canonical)
            .await?;
        Ok(CognitiveWriteReceipt {
            memory,
            source: citation,
            projection,
        })
    }
}

fn assertion_facts(
    affirmed: &KgFactSetDraft,
    denied: &[KgRelationFactDraft],
) -> Result<KgFactSetDraft, CognitiveStoreError> {
    let count = affirmed
        .relations
        .len()
        .checked_add(denied.len())
        .ok_or_else(|| CognitiveStoreError::Invalid("assertion count overflow".to_string()))?;
    if affirmed.entities.len() > MAX_ENTITIES || count > MAX_RELATIONS {
        return Err(CognitiveStoreError::Invalid(
            "assertions exceed existing KG capacity".to_string(),
        ));
    }
    let mut facts = KgFactSetDraft {
        entities: affirmed.entities.clone(),
        relations: Vec::with_capacity(count),
    };
    for (prefix, relations) in [
        (ASSERTED_PREDICATE_PREFIX, affirmed.relations.as_slice()),
        (DENIED_PREDICATE_PREFIX, denied),
    ] {
        for relation in relations {
            let predicate = canonical_token(
                &relation.relation,
                MAX_RELATION_BYTES,
                "assertion predicate",
            )?;
            let digest = Sha256Digest::for_bytes(predicate.as_bytes());
            let mut relation = relation.clone();
            // The revision fact-set contract, not this string alone, enables
            // the new interpretation. Preserve canonical endpoint ownership.
            relation.relation = format!("{prefix}{}", digest.as_str());
            facts.relations.push(relation);
        }
    }
    Ok(facts)
}
