//! Typed mutation under both the existing live lease and one-shot final use.

use std::sync::Arc;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_types::Digest32;
use serde::Serialize;

use super::PreparedProductionCognitiveMutation;
use super::ProductionCognitiveMutationCapability;
use super::ProductionCognitiveMutationError;
use super::ProductionCognitiveMutationReceiptV1;
use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::CognitiveAccess;
use crate::CognitiveScope;
use crate::CognitiveStoreError;
use crate::DurableCognitiveSnapshot;
use crate::cognitive_store::unavailable;
use crate::typed_memory_admission::TYPED_MEMORY_ADMISSION_PURPOSE_V1;
use crate::typed_memory_admission::TypedMemoryChangeV1;
use crate::typed_memory_admission::TypedMemoryEvidenceVerifierV1;
use crate::typed_memory_admission::TypedMemoryKindV1;
use crate::typed_memory_admission::TypedMemoryProposalV1;
use crate::typed_memory_storage::RevisionAdmissionV1;
use crate::typed_memory_storage::StoredTypedAdmissionV1;
use crate::typed_memory_storage::digest_bytes;

/// Only the writer can mint this capability. Host trust is explicitly
/// installed; a request cannot supply its own verifier or final-use authority.
#[derive(Clone)]
pub struct ProductionTypedMemoryCapabilityV1 {
    mutation: ProductionCognitiveMutationCapability,
    final_use: FinalUseAuthority,
    evidence: Arc<dyn TypedMemoryEvidenceVerifierV1>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct TypedMemoryAdmissionReceiptV1 {
    pub kind: TypedMemoryKindV1,
    pub admission_sha256: Sha256Digest,
    pub mutation: ProductionCognitiveMutationReceiptV1,
}

impl ProductionDurableWriter {
    /// Host composition installs existing trust; this method creates no issuer
    /// key, verifier, grant, or fallback authority.
    pub fn typed_memory_capability(
        self: &Arc<Self>,
        final_use: FinalUseAuthority,
        evidence: Arc<dyn TypedMemoryEvidenceVerifierV1>,
    ) -> Result<ProductionTypedMemoryCapabilityV1, ProductionWriterError> {
        Ok(ProductionTypedMemoryCapabilityV1 {
            mutation: self.cognitive_mutation_capability()?,
            final_use,
            evidence,
        })
    }
}

impl ProductionTypedMemoryCapabilityV1 {
    /// Read the actual owner cut used to prepare a later signed proposal.
    /// This is a historical observation, not authority for a future write.
    pub async fn observe_cut(
        &self,
        access: &CognitiveAccess,
        scope: &CognitiveScope,
    ) -> Result<DurableCognitiveSnapshot, ProductionCognitiveMutationError> {
        self.mutation.writer.verify_current_authority().await?;
        Ok(self
            .mutation
            .writer
            .store()
            .lane_c_snapshot(
                access,
                scope,
                i64::try_from(super::now_unix_seconds()?)
                    .map_err(|_| CognitiveStoreError::Invalid("owner clock overflow".into()))?,
            )
            .await?)
    }

    /// Exact request for an independent signer. Constructing it consumes no
    /// nonce and admits nothing; commit reacquires the cut and verifies trust.
    pub fn proposal_binding(
        &self,
        proposal: &TypedMemoryProposalV1,
    ) -> Result<FinalUseBinding, ProductionCognitiveMutationError> {
        let prepared = self.prepare(proposal)?;
        self.binding(proposal, &prepared)
    }

    fn prepare(
        &self,
        proposal: &TypedMemoryProposalV1,
    ) -> Result<PreparedProductionCognitiveMutation, ProductionCognitiveMutationError> {
        proposal.validate()?;
        let (operation, predecessor) = match &proposal.change {
            TypedMemoryChangeV1::Create { .. } => ("typed_remember_v1", None),
            TypedMemoryChangeV1::Correct {
                expected_revision, ..
            } => ("typed_correct_v1", Some(*expected_revision)),
        };
        self.mutation
            .prepare_semantic_mutation(operation, &proposal.source, predecessor, proposal)
    }

    fn binding(
        &self,
        proposal: &TypedMemoryProposalV1,
        prepared: &PreparedProductionCognitiveMutation,
    ) -> Result<FinalUseBinding, ProductionCognitiveMutationError> {
        let owner = self.mutation.writer.owner_agent_id();
        let scope_bytes =
            serde_json::to_vec(&(TYPED_MEMORY_ADMISSION_PURPOSE_V1, owner, proposal.scope()))
                .map_err(unavailable)?;
        Ok(FinalUseBinding {
            subject_id: owner.as_str().to_string(),
            destination_id: format!("memory-typed:v1:{}", owner.as_str()),
            request_sha256: digest_bytes(&prepared.operation_digest)?,
            scope_sha256: *Digest32::of_bytes(&scope_bytes).as_array(),
            payload_sha256: digest_bytes(&prepared.input_payload_sha256)?,
        })
    }

    fn verify_host(&self, proposal: &TypedMemoryProposalV1) -> Result<(), ProductionWriterError> {
        let writer = &self.mutation.writer;
        writer
            .authority
            .validate_for_agent(writer.owner_agent_id())?;
        writer
            .live_verifier
            .as_ref()
            .ok_or(ProductionWriterError::LiveVerifierRequired)?
            .verify(&writer.authority, writer.owner_agent_id())
            .map_err(ProductionWriterError::AuthorityRejected)?;
        self.evidence
            .verify(writer.owner_agent_id(), proposal)
            .map_err(ProductionWriterError::AuthorityRejected)
    }

    /// Persist type, immutable admission, source, revision, facts and lease
    /// provenance atomically. A consumed nonce is never refunded on failure.
    pub async fn admit(
        &self,
        access: &CognitiveAccess,
        proposal: &TypedMemoryProposalV1,
        signed: &SignedFinalUseGrant,
    ) -> Result<TypedMemoryAdmissionReceiptV1, ProductionCognitiveMutationError> {
        let prepared = self.prepare(proposal)?;
        let binding = self.binding(proposal, &prepared)?;
        let writer = &self.mutation.writer;
        writer.verify_current_authority().await?;
        self.verify_host(proposal)?;
        let mut transaction = writer
            .store()
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        writer
            .lease
            .verify_current_in_transaction(&mut transaction)
            .await
            .map_err(ProductionWriterError::from)?;
        let now = i64::try_from(super::now_unix_seconds()?)
            .map_err(|_| CognitiveStoreError::Invalid("owner clock overflow".into()))?;
        let cut = writer
            .store()
            .lane_c_snapshot_tx(&mut transaction, access, proposal.scope(), now)
            .await?;
        if cut.cut_digest().to_string() != proposal.expected_owner_cut_sha256.as_str()
            || cut.frontiers().source != proposal.expected_source_frontier
            || cut.frontiers().tombstone != proposal.expected_tombstone_frontier
        {
            return Err(CognitiveStoreError::Conflict(
                "typed owner source/forget cut changed".into(),
            )
            .into());
        }
        let token = self
            .final_use
            .claim(signed, &binding)
            .map_err(ProductionWriterError::from)?;
        let (memory_id, admitted_revision) = proposal.change.target(writer.owner_agent_id());
        let admission = RevisionAdmissionV1::signed(&StoredTypedAdmissionV1 {
            purpose: TYPED_MEMORY_ADMISSION_PURPOSE_V1.to_string(),
            kind: proposal.kind,
            memory_id: memory_id.as_str().to_string(),
            admitted_revision,
            owner_agent_id: writer.owner_agent_id().as_str().to_string(),
            input_payload_sha256: prepared.input_payload_sha256.clone(),
            owner_cut_sha256: proposal.expected_owner_cut_sha256.clone(),
            source_frontier: cut.frontiers().source,
            tombstone_frontier: cut.frontiers().tombstone,
            host_evidence_sha256: proposal.host_evidence_sha256.clone(),
            binding: binding.clone(),
            signed_grant: signed.clone(),
            claim_witness_sha256: Sha256Digest::parse(
                Digest32::from_array(token.witness_sha256()).to_string(),
            )
            .map_err(CognitiveStoreError::Corrupt)?,
        })?;
        self.final_use
            .with_verified_use_async(token, &binding, || async move {
                let queued = self
                    .mutation
                    .admit_prepared_mutation(&mut transaction, &prepared)
                    .await?;
                let write = match &proposal.change {
                    TypedMemoryChangeV1::Create { draft } => {
                        writer
                            .store()
                            .remember_admitted_with_kg_tx(
                                &mut transaction,
                                access,
                                &proposal.source,
                                draft,
                                &proposal.facts,
                                &admission,
                            )
                            .await?
                    }
                    TypedMemoryChangeV1::Correct {
                        memory_id,
                        expected_revision,
                        draft,
                    } => {
                        writer
                            .store()
                            .correct_admitted_with_kg_tx(
                                &mut transaction,
                                access,
                                memory_id,
                                *expected_revision,
                                &proposal.source,
                                draft,
                                &proposal.facts,
                                Some(&admission),
                            )
                            .await?
                    }
                };
                let receipt = self
                    .mutation
                    .finish_prepared_mutation(&mut transaction, prepared, queued, write)
                    .await?;
                self.verify_host(proposal)?;
                writer
                    .lease
                    .verify_current_in_transaction(&mut transaction)
                    .await
                    .map_err(ProductionWriterError::from)?;
                transaction.commit().await.map_err(unavailable)?;
                receipt.validate()?;
                Ok::<_, ProductionCognitiveMutationError>(TypedMemoryAdmissionReceiptV1 {
                    kind: proposal.kind,
                    admission_sha256: admission.sha256.ok_or_else(|| {
                        CognitiveStoreError::Corrupt("missing typed admission digest".into())
                    })?,
                    mutation: receipt,
                })
            })
            .await
            .map_err(ProductionWriterError::from)?
    }
}

#[cfg(test)]
#[path = "production_typed_memory_tests.rs"]
mod tests;
