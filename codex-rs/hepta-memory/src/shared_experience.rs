//! Purpose-specific native owner access for shared experience.
//!
//! Recall grants never authorize Replay. Each admitted use pins one actual
//! Memory revision and the consumer workspace. This is an in-process owner API;
//! it does not enroll a remote peer, copy context, or authorize a model update.

use codex_hepta_cognitive_types::hnmf::ContractDigestV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceInfluenceStatusV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperiencePublicationV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceRevocationReceiptV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceSourceKindV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceUseClassV2;
use codex_hepta_cognitive_types::shared_experience::SharedExperienceUseReceiptV2;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use sha2::Digest;
use sha2::Sha256;
use sqlx::Row;

use crate::CognitiveAccess;
use crate::CognitiveStore;
use crate::CognitiveStoreError;
use crate::FederationConsumerAccess;
use crate::MemoryLifecycleState;
use crate::MemoryRevisionRecord;
use crate::MemoryVerification;
use crate::StableMemoryId;
use crate::cognitive_store::unavailable;
use crate::framing::frame_part;

const MAX_POLICY_IDENTITIES: i64 = 4096;
const MAX_POLICY_REVISIONS: i64 = 1024;
const MAX_LIFETIME_SECONDS: i64 = 31 * 24 * 60 * 60;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum SharedExperiencePurposeV1 {
    Recall,
    Replay {
        parameter_scope: String,
        artifact_consumer: AgentId,
    },
}

impl SharedExperiencePurposeV1 {
    fn parts(&self) -> Result<(&str, &str, &str), CognitiveStoreError> {
        match self {
            Self::Recall => Ok(("recall", "", "")),
            Self::Replay {
                parameter_scope,
                artifact_consumer,
            } if !parameter_scope.trim().is_empty()
                && parameter_scope.len() <= 128
                && !parameter_scope.as_bytes().contains(&0) =>
            {
                Ok(("replay", parameter_scope, artifact_consumer.as_str()))
            }
            _ => Err(CognitiveStoreError::Invalid(
                "invalid shared parameter scope".into(),
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedExperienceGrantV1 {
    pub memory_id: StableMemoryId,
    pub memory_revision: u64,
    pub consumer: FederationConsumerAccess,
    pub purpose: SharedExperiencePurposeV1,
    pub expires_at_unix_seconds: i64,
}

/// Owner-produced current use. Call revalidate_shared_experience immediately
/// before attachment/training/artifact use; a cloned receipt is not a live grant.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedExperienceUseV1 {
    policy_id: Sha256Digest,
    policy_revision: u64,
    owner_id: AgentId,
    consumer: FederationConsumerAccess,
    purpose: SharedExperiencePurposeV1,
    expires_at_unix_seconds: i64,
    memory: MemoryRevisionRecord,
}

impl SharedExperienceUseV1 {
    pub fn memory(&self) -> &MemoryRevisionRecord {
        &self.memory
    }
    pub fn policy_id(&self) -> &Sha256Digest {
        &self.policy_id
    }
    pub fn policy_revision(&self) -> u64 {
        self.policy_revision
    }
    pub fn purpose(&self) -> &SharedExperiencePurposeV1 {
        &self.purpose
    }
    pub fn owner_id(&self) -> &AgentId {
        &self.owner_id
    }
    pub fn consumer(&self) -> &FederationConsumerAccess {
        &self.consumer
    }
    pub fn expires_at_unix_seconds(&self) -> i64 {
        self.expires_at_unix_seconds
    }

    /// Bind learning support to this exact source revision, not just equal text.
    /// Consumer/purpose authorization is checked separately at every use boundary.
    pub fn source_support_digest(&self) -> Sha256Digest {
        let mut hash = Sha256::new();
        for part in [
            b"hepta.shared-experience.source-support.v1".as_slice(),
            self.owner_id.as_str().as_bytes(),
            self.memory.id.memory_id.as_str().as_bytes(),
            &self.memory.id.revision.to_be_bytes(),
            self.memory.content_sha256.as_str().as_bytes(),
        ] {
            frame_part(&mut hash, part);
        }
        Sha256Digest::from_sha256_output(hash.finalize())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SharedExperiencePublicationBindingV2 {
    pub publication: SharedExperiencePublicationV2,
    pub publication_sha256: ContractDigestV1,
    pub policy_id: Sha256Digest,
    pub policy_revision: u64,
    pub source_support_sha256: Sha256Digest,
}

impl SharedExperiencePublicationBindingV2 {
    pub fn validate_against(
        &self,
        source: &SharedExperienceUseV1,
    ) -> Result<(), CognitiveStoreError> {
        self.publication
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let digest = canonical_contract_digest_v1(&self.publication)
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        if digest != self.publication_sha256.digest()
            || self.policy_id != source.policy_id
            || self.policy_revision != source.policy_revision
            || self.source_support_sha256 != source.source_support_digest()
        {
            return Err(CognitiveStoreError::Conflict(
                "shared V2 publication binding drift".into(),
            ));
        }
        validate_publication_against_source(source, &self.publication)
    }
}

fn contract_id(value: impl Into<String>, field: &str) -> Result<ContractIdV1, CognitiveStoreError> {
    ContractIdV1::new(value)
        .map_err(|_| CognitiveStoreError::Invalid(format!("invalid shared V2 {field}")))
}

fn digest_parts(domain: &[u8], parts: &[&[u8]]) -> Sha256Digest {
    let mut hash = Sha256::new();
    frame_part(&mut hash, domain);
    for part in parts {
        frame_part(&mut hash, part);
    }
    Sha256Digest::from_sha256_output(hash.finalize())
}

fn source_scope_digest(source: &SharedExperienceUseV1) -> Sha256Digest {
    let scope = source.memory.scope.projection_key();
    digest_parts(
        b"hepta.shared-experience.source-scope.v2",
        &[source.owner_id.as_str().as_bytes(), scope.as_bytes()],
    )
}

fn destination_scope_id(
    consumer: &FederationConsumerAccess,
) -> Result<ContractIdV1, CognitiveStoreError> {
    contract_id(
        format!("workspace:{}", consumer.workspace_sha256().as_str()),
        "destination scope",
    )
}

fn parameter_scope_digest(parameter_scope: &str) -> Sha256Digest {
    digest_parts(
        b"hepta.shared-experience.parameter-scope.v2",
        &[parameter_scope.as_bytes()],
    )
}

fn publication_grants_match_source(
    source: &SharedExperienceUseV1,
    publication: &SharedExperiencePublicationV2,
) -> Result<(), CognitiveStoreError> {
    if publication.destination_scope_ids
        != std::collections::BTreeSet::from([destination_scope_id(&source.consumer)?])
    {
        return Err(CognitiveStoreError::AccessDenied(
            "shared V2 destination scope mismatch".into(),
        ));
    }
    match &source.purpose {
        SharedExperiencePurposeV1::Recall => {
            let exact = publication.use_grants.iter().all(|grant| {
                matches!(
                    &grant.use_class,
                    SharedExperienceUseClassV2::RawEvidenceRead {
                        consumer_id,
                        consumer_workspace_sha256,
                    } if consumer_id.as_str() == source.consumer.agent_id().as_str()
                        && consumer_workspace_sha256.to_string()
                            == source.consumer.workspace_sha256().as_str()
                )
            });
            let widened = publication.use_grants.iter().any(|grant| {
                matches!(
                    grant.use_class,
                    SharedExperienceUseClassV2::PurposeBoundTraining { .. }
                        | SharedExperienceUseClassV2::DerivedArtifactUse { .. }
                )
            });
            if !exact || widened {
                return Err(CognitiveStoreError::AccessDenied(
                    "Recall publication cannot imply training or artifact use".into(),
                ));
            }
        }
        SharedExperiencePurposeV1::Replay {
            parameter_scope,
            artifact_consumer,
        } => {
            let parameter_digest = parameter_scope_digest(parameter_scope);
            let training = publication.use_grants.iter().any(|grant| {
                matches!(
                    &grant.use_class,
                    SharedExperienceUseClassV2::PurposeBoundTraining {
                        trainer_id,
                        purpose_id,
                        parameter_scope_sha256,
                        ..
                    } if purpose_id.as_str() == "purpose:replay"
                        && trainer_id.as_str() == source.consumer.agent_id().as_str()
                        && parameter_scope_sha256.to_string() == parameter_digest.as_str()
                )
            });
            let artifact = publication.use_grants.iter().any(|grant| {
                matches!(
                    &grant.use_class,
                    SharedExperienceUseClassV2::DerivedArtifactUse {
                        artifact_consumer_id,
                        ..
                    } if artifact_consumer_id.as_str() == artifact_consumer.as_str()
                )
            });
            let all_authorized =
                publication
                    .use_grants
                    .iter()
                    .all(|grant| match &grant.use_class {
                        SharedExperienceUseClassV2::PurposeBoundTraining {
                            trainer_id,
                            purpose_id,
                            parameter_scope_sha256,
                            ..
                        } => {
                            purpose_id.as_str() == "purpose:replay"
                                && trainer_id.as_str() == source.consumer.agent_id().as_str()
                                && parameter_scope_sha256.to_string() == parameter_digest.as_str()
                        }
                        SharedExperienceUseClassV2::DerivedArtifactUse {
                            artifact_consumer_id,
                            ..
                        } => artifact_consumer_id.as_str() == artifact_consumer.as_str(),
                        SharedExperienceUseClassV2::RawEvidenceRead { .. } => false,
                    });
            if !training || !artifact || !all_authorized {
                return Err(CognitiveStoreError::AccessDenied(
                    "Replay requires separate training and artifact grants".into(),
                ));
            }
        }
    }
    Ok(())
}

fn validate_publication_against_source(
    source: &SharedExperienceUseV1,
    publication: &SharedExperiencePublicationV2,
) -> Result<(), CognitiveStoreError> {
    let observed_at_unix_ms = u64::try_from(source.memory.valid_from_unix_seconds)
        .ok()
        .and_then(|seconds| seconds.checked_mul(1_000))
        .ok_or_else(|| CognitiveStoreError::Invalid("invalid source observation time".into()))?;
    let source_expiry_unix_ms = u64::try_from(source.expires_at_unix_seconds)
        .ok()
        .and_then(|seconds| seconds.checked_mul(1_000))
        .ok_or_else(|| CognitiveStoreError::Invalid("invalid shared expiry".into()))?;
    if publication.source_kind != SharedExperienceSourceKindV2::OwnerMemoryRevision
        || publication.source_owner_id.as_str() != source.owner_id.as_str()
        || publication.source_record_id.as_str() != source.memory.id.memory_id.as_str()
        || publication.source_revision != source.memory.id.revision
        || publication.source_record_sha256.to_string() != source.source_support_digest().as_str()
        || publication.semantic_content_sha256.to_string() != source.memory.content_sha256.as_str()
        || publication.source_scope_sha256.to_string() != source_scope_digest(source).as_str()
        || publication.publication_policy_sha256.to_string() != source.policy_id.as_str()
        || publication.policy_generation.get() != source.policy_revision
        || publication.observed_at_unix_ms != observed_at_unix_ms
        || publication
            .expires_at_unix_ms
            .is_none_or(|expiry| expiry > source_expiry_unix_ms)
    {
        return Err(CognitiveStoreError::Conflict(
            "shared V2 publication/source mismatch".into(),
        ));
    }
    publication_grants_match_source(source, publication)
}

fn now() -> Result<i64, CognitiveStoreError> {
    let value = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(unavailable)?
        .as_secs();
    i64::try_from(value).map_err(unavailable)
}

fn valid_memory(memory: &MemoryRevisionRecord, now: i64) -> bool {
    memory.lifecycle == MemoryLifecycleState::Active
        && memory.verification == MemoryVerification::Verified
        && memory.valid_from_unix_seconds <= now
        && memory
            .valid_to_unix_seconds
            .is_none_or(|expiry| expiry > now)
}

fn policy_id(
    owner: &AgentId,
    request: &SharedExperienceGrantV1,
) -> Result<Sha256Digest, CognitiveStoreError> {
    let (purpose, scope, recipient) = request.purpose.parts()?;
    let mut hash = Sha256::new();
    for part in [
        b"hepta.shared-experience.use.v1".as_slice(),
        owner.as_str().as_bytes(),
        request.memory_id.as_str().as_bytes(),
        &request.memory_revision.to_be_bytes(),
        request.consumer.agent_id().as_str().as_bytes(),
        request.consumer.workspace_sha256().as_str().as_bytes(),
        purpose.as_bytes(),
        scope.as_bytes(),
        recipient.as_bytes(),
    ] {
        frame_part(&mut hash, part);
    }
    Ok(Sha256Digest::from_sha256_output(hash.finalize()))
}

impl CognitiveStore {
    /// Append an owner-authorized exact-revision purpose grant. Expected revision
    /// is zero for first admission; updates compare against the durable head.
    /// Product callers must enter through the existing owner authorization path.
    pub async fn grant_shared_experience(
        &self,
        owner: &CognitiveAccess,
        request: &SharedExperienceGrantV1,
        expected_revision: u64,
    ) -> Result<SharedExperienceUseV1, CognitiveStoreError> {
        let time = now()?;
        if request.expires_at_unix_seconds <= time
            || request.expires_at_unix_seconds.saturating_sub(time) > MAX_LIFETIME_SECONDS
        {
            return Err(CognitiveStoreError::Invalid(
                "shared use expiry outside bounded lifetime".into(),
            ));
        }
        let key = policy_id(self.owner_agent_id(), request)?;
        let (purpose, scope, recipient) = request.purpose.parts()?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let memory = self
            .latest_memory_tx(&mut tx, owner, &request.memory_id)
            .await?;
        if memory.id.revision != request.memory_revision || !valid_memory(&memory, time) {
            return Err(CognitiveStoreError::Conflict(
                "shared source is not current verified evidence".into(),
            ));
        }
        let previous: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(revision) FROM shared_experience_use_events WHERE policy_id = ?",
        )
        .bind(key.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        let previous = previous.unwrap_or(0);
        if expected_revision.checked_add(1) == u64::try_from(previous).ok() {
            let same: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM shared_experience_use_events WHERE policy_id=? AND revision=? AND revoked=0 AND expires_at=? AND content_sha256=?")
                .bind(key.as_str()).bind(previous).bind(request.expires_at_unix_seconds).bind(memory.content_sha256.as_str())
                .fetch_one(&mut *tx).await.map_err(unavailable)?;
            if same == 1 {
                tx.commit().await.map_err(unavailable)?;
                return Ok(SharedExperienceUseV1 {
                    policy_id: key,
                    policy_revision: previous as u64,
                    owner_id: self.owner_agent_id().clone(),
                    consumer: request.consumer.clone(),
                    purpose: request.purpose.clone(),
                    expires_at_unix_seconds: request.expires_at_unix_seconds,
                    memory,
                });
            }
        }
        if u64::try_from(previous).map_err(unavailable)? != expected_revision
            || previous >= MAX_POLICY_REVISIONS
        {
            return Err(CognitiveStoreError::Conflict(
                "shared use policy predecessor".into(),
            ));
        }
        if previous == 0 {
            let count: i64 = sqlx::query_scalar(
                "SELECT COUNT(DISTINCT policy_id) FROM shared_experience_use_events",
            )
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
            if count >= MAX_POLICY_IDENTITIES {
                return Err(CognitiveStoreError::Invalid("shared use capacity".into()));
            }
        }
        let revision = previous + 1;
        sqlx::query("INSERT INTO shared_experience_use_events (policy_id,revision,revoked,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at) VALUES (?,?,0,?,?,?,?,?,?,?,?,?)")
            .bind(key.as_str()).bind(revision).bind(request.memory_id.as_str()).bind(i64::try_from(request.memory_revision).map_err(unavailable)?)
            .bind(memory.content_sha256.as_str()).bind(request.consumer.agent_id().as_str()).bind(request.consumer.workspace_sha256().as_str())
            .bind(purpose).bind(scope).bind(recipient).bind(request.expires_at_unix_seconds)
            .execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(SharedExperienceUseV1 {
            policy_id: key,
            policy_revision: revision as u64,
            owner_id: self.owner_agent_id().clone(),
            consumer: request.consumer.clone(),
            purpose: request.purpose.clone(),
            expires_at_unix_seconds: request.expires_at_unix_seconds,
            memory,
        })
    }

    /// Bind a V2 publication to an already owner-admitted V1 exact-revision grant.
    /// This does not reclassify the source Memory or create another writer.
    pub fn bind_shared_experience_publication_v2(
        &self,
        source: &SharedExperienceUseV1,
        publication: SharedExperiencePublicationV2,
    ) -> Result<SharedExperiencePublicationBindingV2, CognitiveStoreError> {
        if source.owner_id != *self.owner_agent_id() {
            return Err(CognitiveStoreError::AccessDenied(
                "wrong shared source owner".into(),
            ));
        }
        publication
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        validate_publication_against_source(source, &publication)?;
        let publication_sha256 = ContractDigestV1::from_digest(
            canonical_contract_digest_v1(&publication)
                .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?,
        )
        .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let binding = SharedExperiencePublicationBindingV2 {
            publication,
            publication_sha256,
            policy_id: source.policy_id.clone(),
            policy_revision: source.policy_revision,
            source_support_sha256: source.source_support_digest(),
        };
        binding.validate_against(source)?;
        Ok(binding)
    }

    /// Revalidate the durable V1 owner policy and bind an observed V2 final-use
    /// receipt to the exact publication. The caller still owns the physical use.
    pub async fn revalidate_shared_experience_use_v2(
        &self,
        source: &SharedExperienceUseV1,
        publication: &SharedExperiencePublicationBindingV2,
        receipt: &SharedExperienceUseReceiptV2,
    ) -> Result<(), CognitiveStoreError> {
        self.revalidate_shared_experience(source).await?;
        publication.validate_against(source)?;
        receipt
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let now_ms = u64::try_from(
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_err(unavailable)?
                .as_millis(),
        )
        .map_err(|_| CognitiveStoreError::Invalid("invalid shared use clock".into()))?;
        if now_ms < receipt.grant.valid_from_unix_ms
            || now_ms >= receipt.grant.expires_at_unix_ms
            || receipt.used_at_unix_ms > now_ms
            || publication
                .publication
                .expires_at_unix_ms
                .is_some_and(|expiry| now_ms >= expiry)
        {
            return Err(CognitiveStoreError::AccessDenied(
                "shared V2 use expired or future-dated".into(),
            ));
        }
        // The source owner observes source reads only. Training materialization and
        // artifact adoption require receipts from those actual physical-use owners.
        if !matches!(
            receipt.grant.use_class,
            SharedExperienceUseClassV2::RawEvidenceRead { .. }
        ) {
            return Err(CognitiveStoreError::AccessDenied(
                "training/artifact terminal observation belongs to its consumer owner".into(),
            ));
        }
        let expected_consumer = match &receipt.grant.use_class {
            SharedExperienceUseClassV2::RawEvidenceRead { consumer_id, .. } => consumer_id,
            SharedExperienceUseClassV2::PurposeBoundTraining { trainer_id, .. } => trainer_id,
            SharedExperienceUseClassV2::DerivedArtifactUse {
                artifact_consumer_id,
                ..
            } => artifact_consumer_id,
        };
        if receipt.publication_sha256 != publication.publication_sha256
            || receipt.source_owner_id.as_str() != source.owner_id.as_str()
            || receipt.source_revision != source.memory.id.revision
            || &receipt.consumer_id != expected_consumer
            || receipt.observed_policy_generation.get() != source.policy_revision
            || receipt.observed_revocation_frontier != source.policy_revision
            || receipt.payload_sha256.to_string() != source.memory.content_sha256.as_str()
            || !publication
                .publication
                .use_grants
                .iter()
                .any(|grant| grant == &receipt.grant)
        {
            return Err(CognitiveStoreError::Conflict(
                "shared V2 use receipt mismatch".into(),
            ));
        }
        publication_grants_match_source(source, &publication.publication)
    }

    /// Verify that the durable owner appended the terminal revocation successor
    /// before accepting a V2 revocation receipt. This never claims unlearning.
    pub async fn verify_shared_experience_revocation_v2(
        &self,
        source: &SharedExperienceUseV1,
        publication: &SharedExperiencePublicationBindingV2,
        receipt: &SharedExperienceRevocationReceiptV2,
    ) -> Result<(), CognitiveStoreError> {
        publication.validate_against(source)?;
        receipt
            .validate()
            .map_err(|error| CognitiveStoreError::Invalid(error.to_string()))?;
        let row = sqlx::query(
            "SELECT revision,revoked FROM shared_experience_use_events WHERE policy_id=? ORDER BY revision DESC LIMIT 1",
        )
        .bind(source.policy_id.as_str())
        .fetch_optional(&self.pool)
        .await
        .map_err(unavailable)?
        .ok_or_else(|| CognitiveStoreError::Conflict("shared revocation missing".into()))?;
        let durable_revision = row.try_get::<i64, _>("revision").map_err(unavailable)?;
        let durable_revoked = row.try_get::<i64, _>("revoked").map_err(unavailable)?;
        let expected_next = source
            .policy_revision
            .checked_add(1)
            .ok_or_else(|| CognitiveStoreError::Invalid("shared revision overflow".into()))?;
        if source.owner_id != *self.owner_agent_id()
            || receipt.revocation_frontier != expected_next
            || durable_revoked != 1
            || u64::try_from(durable_revision).ok() != Some(expected_next)
            || receipt.contribution_id != publication.publication.contribution_id
            || receipt.publication_sha256 != publication.publication_sha256
            || receipt.source_owner_id.as_str() != source.owner_id.as_str()
            || receipt.source_revision != source.memory.id.revision
            || receipt.predecessor_policy_generation.get() != source.policy_revision
            || receipt.next_policy_generation.get() != expected_next
        {
            return Err(CognitiveStoreError::Conflict(
                "shared V2 revocation receipt mismatch".into(),
            ));
        }
        if receipt.completeness == codex_hepta_cognitive_types::shared_experience::SharedExperienceRevocationCompletenessV2::Complete
            && (!receipt.affected_projection_sha256s.is_empty()
                || !receipt.affected_training_dataset_sha256s.is_empty()
                || !receipt.affected_artifact_sha256s.is_empty())
        {
            return Err(CognitiveStoreError::AccessDenied(
                "complete downstream propagation needs independent owner acknowledgements".into(),
            ));
        }
        // This owner can attest a policy revocation, not authenticate an unlearning proof.
        if receipt.influence_status == SharedExperienceInfluenceStatusV2::ProvedRemoved {
            return Err(CognitiveStoreError::Invalid(
                "shared influence removal requires an independent proof verifier".into(),
            ));
        }
        Ok(())
    }

    /// Owner-backed read checks policy and Memory head in one coherent transaction.
    /// The caller supplies its authenticated local consumer context, not authority
    /// inferred from a string found inside the shared Memory payload.
    pub async fn read_shared_experience(
        &self,
        consumer: &FederationConsumerAccess,
        key: &Sha256Digest,
        purpose: &SharedExperiencePurposeV1,
    ) -> Result<SharedExperienceUseV1, CognitiveStoreError> {
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        let row = sqlx::query("SELECT * FROM shared_experience_use_events WHERE policy_id = ? ORDER BY revision DESC LIMIT 1")
            .bind(key.as_str()).fetch_optional(&mut *tx).await.map_err(unavailable)?
            .ok_or_else(|| CognitiveStoreError::AccessDenied("shared use unavailable".into()))?;
        let (kind, target, recipient) = purpose.parts()?;
        let denied = row.try_get::<i64, _>("revoked").map_err(unavailable)? != 0
            || row
                .try_get::<String, _>("consumer_agent_id")
                .map_err(unavailable)?
                != consumer.agent_id().as_str()
            || row
                .try_get::<String, _>("consumer_workspace_sha256")
                .map_err(unavailable)?
                != consumer.workspace_sha256().as_str()
            || row.try_get::<String, _>("purpose").map_err(unavailable)? != kind
            || row
                .try_get::<String, _>("parameter_scope")
                .map_err(unavailable)?
                != target
            || row
                .try_get::<String, _>("artifact_consumer_id")
                .map_err(unavailable)?
                != recipient
            || row.try_get::<i64, _>("expires_at").map_err(unavailable)? <= now()?;
        if denied {
            return Err(CognitiveStoreError::AccessDenied(
                "shared use unavailable".into(),
            ));
        }
        let memory_id =
            StableMemoryId::parse(row.try_get::<String, _>("memory_id").map_err(unavailable)?)
                .map_err(CognitiveStoreError::Corrupt)?;
        let scope_row = sqlx::query("SELECT scope_kind,workspace_sha256 FROM memory_revisions WHERE memory_id = ? AND revision = ?")
            .bind(memory_id.as_str()).bind(row.try_get::<i64,_>("memory_revision").map_err(unavailable)?)
            .fetch_one(&mut *tx).await.map_err(unavailable)?;
        let scope = crate::cognitive_store::decode_scope(&scope_row)?;
        let owner = match scope {
            crate::CognitiveScope::AgentPrivate => {
                CognitiveAccess::agent_private(self.owner_agent_id().clone())
            }
            crate::CognitiveScope::WorkspacePrivate { workspace_sha256 } => {
                CognitiveAccess::workspace_private(self.owner_agent_id().clone(), workspace_sha256)
            }
        };
        let memory = self.latest_memory_tx(&mut tx, &owner, &memory_id).await?;
        if !valid_memory(&memory, now()?)
            || i64::try_from(memory.id.revision).map_err(unavailable)?
                != row
                    .try_get::<i64, _>("memory_revision")
                    .map_err(unavailable)?
            || memory.content_sha256.as_str()
                != row
                    .try_get::<String, _>("content_sha256")
                    .map_err(unavailable)?
        {
            return Err(CognitiveStoreError::Conflict(
                "shared source changed or withdrawn".into(),
            ));
        }
        let result = SharedExperienceUseV1 {
            policy_id: key.clone(),
            policy_revision: row.try_get::<i64, _>("revision").map_err(unavailable)? as u64,
            owner_id: self.owner_agent_id().clone(),
            consumer: consumer.clone(),
            purpose: purpose.clone(),
            expires_at_unix_seconds: row.try_get::<i64, _>("expires_at").map_err(unavailable)?,
            memory,
        };
        tx.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub async fn revalidate_shared_experience(
        &self,
        receipt: &SharedExperienceUseV1,
    ) -> Result<(), CognitiveStoreError> {
        if receipt.owner_id != *self.owner_agent_id() {
            return Err(CognitiveStoreError::AccessDenied(
                "wrong shared source owner".into(),
            ));
        }
        let current = self
            .read_shared_experience(&receipt.consumer, &receipt.policy_id, &receipt.purpose)
            .await?;
        if current != *receipt {
            return Err(CognitiveStoreError::Conflict(
                "shared use binding changed".into(),
            ));
        }
        Ok(())
    }

    /// Revocation appends a successor and does not claim parameter unlearning.
    /// The last ordinary revision can always enter its reserved terminal slot.
    /// Grant capacity is never a reason to reject withdrawal of an active grant.
    pub async fn revoke_shared_experience(
        &self,
        owner: &CognitiveAccess,
        receipt: &SharedExperienceUseV1,
    ) -> Result<(), CognitiveStoreError> {
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        self.latest_memory_tx(&mut tx, owner, &receipt.memory.id.memory_id)
            .await?;
        if receipt.owner_id != *self.owner_agent_id()
            || receipt.policy_revision > MAX_POLICY_REVISIONS as u64
        {
            return Err(CognitiveStoreError::Conflict(
                "invalid shared policy owner/revision".into(),
            ));
        }
        let head: Option<i64> = sqlx::query_scalar(
            "SELECT MAX(revision) FROM shared_experience_use_events WHERE policy_id=?",
        )
        .bind(receipt.policy_id.as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(unavailable)?;
        if head == Some(receipt.policy_revision as i64 + 1) {
            let revoked: i64 = sqlx::query_scalar(
                "SELECT revoked FROM shared_experience_use_events WHERE policy_id=? AND revision=?",
            )
            .bind(receipt.policy_id.as_str())
            .bind(head)
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
            if revoked == 1 {
                tx.commit().await.map_err(unavailable)?;
                return Ok(());
            }
        }
        if head != Some(receipt.policy_revision as i64) {
            return Err(CognitiveStoreError::Conflict(
                "shared use policy predecessor".into(),
            ));
        }
        sqlx::query("INSERT INTO shared_experience_use_events SELECT policy_id,revision+1,1,memory_id,memory_revision,content_sha256,consumer_agent_id,consumer_workspace_sha256,purpose,parameter_scope,artifact_consumer_id,expires_at FROM shared_experience_use_events WHERE policy_id=? AND revision=?")
            .bind(receipt.policy_id.as_str()).bind(receipt.policy_revision as i64).execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(unavailable)?;
        Ok(())
    }
}

#[cfg(test)]
#[path = "shared_experience_tests.rs"]
mod tests;
