//! Registry-owned context admission authority for the canonical compiler path.
//!
//! This module deliberately does not expose constructors for verified context
//! snapshots or admissions.  The only producer is `DurablePromptRegistry`,
//! which re-opens the exact current registry view and dereferences every
//! selected realization before issuing a deny-all, digest-bound snapshot.  A
//! caller therefore cannot promote an arbitrary record into trusted context by
//! constructing a similarly shaped Rust value.

use std::collections::BTreeSet;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::DurablePromptRegistry;
use crate::PromptModelTupleV2;
use crate::PromptRegistrySnapshotV2;
use crate::PromptRoleV2;
use crate::RealizationDeliveryV2;

const AUTHORITY_VERIFIER_DOMAIN: &[u8] = b"hepta.prompt-context-authority.verifier.v3";
const ADMISSION_DOMAIN: &[u8] = b"hepta.prompt-context-authority.admission.v3";
const SNAPSHOT_DOMAIN: &[u8] = b"hepta.prompt-context-authority.snapshot.v3";
const SUCCESSOR_DOMAIN: &[u8] = b"hepta.prompt-context-authority.successor.v3";
const MAX_CONTEXT_AUTHORITY_ADMISSIONS: usize = 128;

/// Stable identity of the registry-owned context authority adapter.
///
/// The identity is intentionally stable across snapshots.  Snapshot-specific
/// state is bound separately, allowing the context compiler to prove monotonic
/// successor lineage without confusing each current cut with a new verifier.
#[must_use]
pub fn prompt_context_authority_verifier_digest_v3() -> Digest32 {
    Digest32::of_bytes(AUTHORITY_VERIFIER_DOMAIN)
}

#[derive(Clone, Eq, PartialEq)]
pub struct PromptContextAuthorityAdmissionV3 {
    admission_id: StableId,
    realization_id: StableId,
    role: PromptRoleV2,
    content_digest: Digest32,
    source_digest: Digest32,
    generation_vector_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
    issued_unix_ms: u64,
    expires_unix_ms: u64,
    registry_binding_digest: Digest32,
    admission_digest: Digest32,
}

impl PromptContextAuthorityAdmissionV3 {
    #[must_use]
    pub fn admission_id(&self) -> &StableId {
        &self.admission_id
    }

    #[must_use]
    pub fn realization_id(&self) -> &StableId {
        &self.realization_id
    }

    #[must_use]
    pub const fn role(&self) -> PromptRoleV2 {
        self.role
    }

    #[must_use]
    pub const fn content_digest(&self) -> Digest32 {
        self.content_digest
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn authority_domain_digest(&self) -> Digest32 {
        self.authority_domain_digest
    }

    #[must_use]
    pub const fn issued_unix_ms(&self) -> u64 {
        self.issued_unix_ms
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.expires_unix_ms
    }

    #[must_use]
    pub const fn registry_binding_digest(&self) -> Digest32 {
        self.registry_binding_digest
    }

    #[must_use]
    pub const fn admission_digest(&self) -> Digest32 {
        self.admission_digest
    }

    fn validate(&self) -> Result<(), PromptContextAuthorityErrorV3> {
        for digest in [
            self.content_digest,
            self.source_digest,
            self.generation_vector_digest,
            self.scope_digest,
            self.authority_domain_digest,
            self.registry_binding_digest,
            self.admission_digest,
        ] {
            if digest.is_zero() {
                return Err(PromptContextAuthorityErrorV3::EmptyDigest);
            }
        }
        if self.issued_unix_ms == 0 || self.expires_unix_ms <= self.issued_unix_ms {
            return Err(PromptContextAuthorityErrorV3::InvalidTime);
        }
        if self.admission_digest != self.compute_digest() {
            return Err(PromptContextAuthorityErrorV3::Integrity);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = ADMISSION_DOMAIN.to_vec();
        push_id(&mut bytes, &self.admission_id);
        push_id(&mut bytes, &self.realization_id);
        bytes.push(role_code(self.role));
        for digest in [
            self.content_digest,
            self.source_digest,
            self.generation_vector_digest,
            self.scope_digest,
            self.authority_domain_digest,
            self.registry_binding_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.extend_from_slice(&self.issued_unix_ms.to_be_bytes());
        bytes.extend_from_slice(&self.expires_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for PromptContextAuthorityAdmissionV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptContextAuthorityAdmissionV3")
            .field("admission_id", &self.admission_id)
            .field("realization_id", &self.realization_id)
            .field("role", &self.role)
            .field("content_digest", &self.content_digest)
            .field("source_digest", &self.source_digest)
            .field("expires_unix_ms", &self.expires_unix_ms)
            .field("admission_digest", &self.admission_digest)
            .finish()
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct PromptContextAuthoritySnapshotV3 {
    registry_snapshot: PromptRegistrySnapshotV2,
    model_tuple: PromptModelTupleV2,
    generation_vector_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
    observed_unix_ms: u64,
    admissions: Vec<PromptContextAuthorityAdmissionV3>,
    snapshot_digest: Digest32,
    authority: AuthorityPosture,
}

impl PromptContextAuthoritySnapshotV3 {
    #[must_use]
    pub fn registry_snapshot(&self) -> &PromptRegistrySnapshotV2 {
        &self.registry_snapshot
    }

    #[must_use]
    pub fn model_tuple(&self) -> &PromptModelTupleV2 {
        &self.model_tuple
    }

    #[must_use]
    pub const fn generation_vector_digest(&self) -> Digest32 {
        self.generation_vector_digest
    }

    #[must_use]
    pub const fn scope_digest(&self) -> Digest32 {
        self.scope_digest
    }

    #[must_use]
    pub const fn authority_domain_digest(&self) -> Digest32 {
        self.authority_domain_digest
    }

    #[must_use]
    pub const fn observed_unix_ms(&self) -> u64 {
        self.observed_unix_ms
    }

    #[must_use]
    pub fn admissions(&self) -> &[PromptContextAuthorityAdmissionV3] {
        &self.admissions
    }

    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot_digest
    }

    #[must_use]
    pub const fn revocation_frontier(&self) -> u64 {
        self.registry_snapshot.revocation_frontier
    }

    #[must_use]
    pub const fn lifecycle_frontier(&self) -> u64 {
        self.registry_snapshot.lifecycle_frontier
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), PromptContextAuthorityErrorV3> {
        self.registry_snapshot
            .validate()
            .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;
        self.model_tuple
            .validate()
            .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;
        for digest in [
            self.generation_vector_digest,
            self.scope_digest,
            self.authority_domain_digest,
            self.snapshot_digest,
        ] {
            if digest.is_zero() {
                return Err(PromptContextAuthorityErrorV3::EmptyDigest);
            }
        }
        if self.observed_unix_ms == 0
            || self.admissions.is_empty()
            || self.admissions.len() > MAX_CONTEXT_AUTHORITY_ADMISSIONS
            || self.authority.grants_any()
            || self.registry_snapshot.generation_vector_digest != self.generation_vector_digest
            || self.registry_snapshot.model_tuple_digest != self.model_tuple.digest()
        {
            return Err(PromptContextAuthorityErrorV3::Integrity);
        }
        let mut seen = BTreeSet::new();
        for admission in &self.admissions {
            admission.validate()?;
            if !seen.insert(admission.realization_id.clone())
                || admission.generation_vector_digest != self.generation_vector_digest
                || admission.scope_digest != self.scope_digest
                || admission.authority_domain_digest != self.authority_domain_digest
            {
                return Err(PromptContextAuthorityErrorV3::Integrity);
            }
        }
        if self.snapshot_digest != self.compute_digest() {
            return Err(PromptContextAuthorityErrorV3::Integrity);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = SNAPSHOT_DOMAIN.to_vec();
        bytes.extend_from_slice(self.registry_snapshot.snapshot_digest.as_array());
        bytes.extend_from_slice(self.model_tuple.digest().as_array());
        bytes.extend_from_slice(self.generation_vector_digest.as_array());
        bytes.extend_from_slice(self.scope_digest.as_array());
        bytes.extend_from_slice(self.authority_domain_digest.as_array());
        bytes.extend_from_slice(&self.observed_unix_ms.to_be_bytes());
        push_len(&mut bytes, self.admissions.len());
        for admission in &self.admissions {
            bytes.extend_from_slice(admission.admission_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for PromptContextAuthoritySnapshotV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptContextAuthoritySnapshotV3")
            .field(
                "registry_snapshot_digest",
                &self.registry_snapshot.snapshot_digest,
            )
            .field("model_tuple_digest", &self.model_tuple.digest())
            .field("generation_vector_digest", &self.generation_vector_digest)
            .field("scope_digest", &self.scope_digest)
            .field("authority_domain_digest", &self.authority_domain_digest)
            .field("observed_unix_ms", &self.observed_unix_ms)
            .field("admission_count", &self.admissions.len())
            .field("snapshot_digest", &self.snapshot_digest)
            .finish()
    }
}

/// Typed proof that `current` was obtained from the same durable owner after
/// `predecessor`.  The fields are private so callers cannot manufacture a
/// monotonic-looking fork and bypass the owner check.
#[derive(Clone, Eq, PartialEq)]
pub struct PromptContextAuthoritySuccessorV3 {
    predecessor_snapshot_digest: Digest32,
    current: PromptContextAuthoritySnapshotV3,
    lineage_digest: Digest32,
}

impl PromptContextAuthoritySuccessorV3 {
    #[must_use]
    pub const fn predecessor_snapshot_digest(&self) -> Digest32 {
        self.predecessor_snapshot_digest
    }

    #[must_use]
    pub fn current(&self) -> &PromptContextAuthoritySnapshotV3 {
        &self.current
    }

    #[must_use]
    pub const fn lineage_digest(&self) -> Digest32 {
        self.lineage_digest
    }

    pub fn validate(
        &self,
        predecessor: &PromptContextAuthoritySnapshotV3,
    ) -> Result<(), PromptContextAuthorityErrorV3> {
        predecessor.validate()?;
        self.current.validate()?;
        if self.predecessor_snapshot_digest != predecessor.snapshot_digest
            || self.current.scope_digest != predecessor.scope_digest
            || self.current.authority_domain_digest != predecessor.authority_domain_digest
            || self.current.generation_vector_digest != predecessor.generation_vector_digest
            || self.current.model_tuple != predecessor.model_tuple
            || self.current.observed_unix_ms < predecessor.observed_unix_ms
            || self.current.registry_snapshot.revision < predecessor.registry_snapshot.revision
            || self.current.registry_snapshot.lifecycle_frontier
                < predecessor.registry_snapshot.lifecycle_frontier
            || self.current.registry_snapshot.revocation_frontier
                < predecessor.registry_snapshot.revocation_frontier
            || self
                .current
                .admissions
                .iter()
                .map(PromptContextAuthorityAdmissionV3::realization_id)
                .ne(predecessor
                    .admissions
                    .iter()
                    .map(PromptContextAuthorityAdmissionV3::realization_id))
            || self.lineage_digest != self.compute_digest()
        {
            return Err(PromptContextAuthorityErrorV3::Lineage);
        }
        Ok(())
    }

    fn compute_digest(&self) -> Digest32 {
        let mut bytes = SUCCESSOR_DOMAIN.to_vec();
        bytes.extend_from_slice(self.predecessor_snapshot_digest.as_array());
        bytes.extend_from_slice(self.current.snapshot_digest.as_array());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for PromptContextAuthoritySuccessorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PromptContextAuthoritySuccessorV3")
            .field(
                "predecessor_snapshot_digest",
                &self.predecessor_snapshot_digest,
            )
            .field("current_snapshot_digest", &self.current.snapshot_digest)
            .field("lineage_digest", &self.lineage_digest)
            .finish()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptContextAuthorityErrorV3 {
    InvalidTime,
    EmptySelection,
    AdmissionLimitExceeded,
    DuplicateRealization(String),
    EmptyDigest,
    Registry(String),
    SelectionDrift(String),
    Integrity,
    Lineage,
}

impl PromptContextAuthorityErrorV3 {
    #[must_use]
    pub const fn code(&self) -> &'static str {
        match self {
            Self::InvalidTime => "context_authority_invalid_time",
            Self::EmptySelection => "context_authority_empty_selection",
            Self::AdmissionLimitExceeded => "context_authority_admission_limit",
            Self::DuplicateRealization(_) => "context_authority_duplicate_realization",
            Self::EmptyDigest => "context_authority_empty_digest",
            Self::Registry(_) => "context_authority_registry",
            Self::SelectionDrift(_) => "context_authority_selection_drift",
            Self::Integrity => "context_authority_integrity",
            Self::Lineage => "context_authority_lineage",
        }
    }
}

impl fmt::Display for PromptContextAuthorityErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{}", self.code())
    }
}

impl std::error::Error for PromptContextAuthorityErrorV3 {}

impl DurablePromptRegistry {
    /// Re-open the current durable registry cut and issue a context-only,
    /// deny-all authority snapshot for the exact selected realizations.
    #[allow(clippy::too_many_arguments)]
    pub fn context_authority_snapshot_v3(
        &self,
        generation_vector_digest: Digest32,
        model_tuple: &PromptModelTupleV2,
        scope_digest: Digest32,
        authority_domain_digest: Digest32,
        observed_unix_ms: u64,
        realization_ids: &[StableId],
    ) -> Result<PromptContextAuthoritySnapshotV3, PromptContextAuthorityErrorV3> {
        if observed_unix_ms == 0 {
            return Err(PromptContextAuthorityErrorV3::InvalidTime);
        }
        if realization_ids.is_empty() {
            return Err(PromptContextAuthorityErrorV3::EmptySelection);
        }
        if realization_ids.len() > MAX_CONTEXT_AUTHORITY_ADMISSIONS {
            return Err(PromptContextAuthorityErrorV3::AdmissionLimitExceeded);
        }
        if generation_vector_digest.is_zero()
            || scope_digest.is_zero()
            || authority_domain_digest.is_zero()
        {
            return Err(PromptContextAuthorityErrorV3::EmptyDigest);
        }
        model_tuple
            .validate()
            .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;

        let mut seen = BTreeSet::new();
        for realization_id in realization_ids {
            if !seen.insert(realization_id.clone()) {
                return Err(PromptContextAuthorityErrorV3::DuplicateRealization(
                    realization_id.to_string(),
                ));
            }
        }

        let registry_snapshot = self
            .snapshot_v2(generation_vector_digest, model_tuple)
            .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;
        let mut admissions = Vec::with_capacity(realization_ids.len());
        for realization_id in realization_ids {
            let delivery = self
                .dereference_realization_v2(
                    realization_id,
                    &registry_snapshot,
                    generation_vector_digest,
                    model_tuple,
                    observed_unix_ms,
                )
                .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;
            admissions.push(authority_admission(
                &delivery,
                generation_vector_digest,
                scope_digest,
                authority_domain_digest,
                observed_unix_ms,
            )?);
        }

        let mut snapshot = PromptContextAuthoritySnapshotV3 {
            registry_snapshot,
            model_tuple: model_tuple.clone(),
            generation_vector_digest,
            scope_digest,
            authority_domain_digest,
            observed_unix_ms,
            admissions,
            snapshot_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        snapshot.snapshot_digest = snapshot.compute_digest();
        snapshot.validate()?;
        Ok(snapshot)
    }

    /// Obtain a typed current successor from the same durable registry owner.
    /// Revoked, retired, expired, superseded or byte-drifted realizations fail
    /// while dereferencing and therefore cannot produce a successor proof.
    pub fn context_authority_successor_v3(
        &self,
        predecessor: &PromptContextAuthoritySnapshotV3,
        observed_unix_ms: u64,
    ) -> Result<PromptContextAuthoritySuccessorV3, PromptContextAuthorityErrorV3> {
        predecessor.validate()?;
        let realization_ids = predecessor
            .admissions
            .iter()
            .map(|admission| admission.realization_id.clone())
            .collect::<Vec<_>>();
        let current = self.context_authority_snapshot_v3(
            predecessor.generation_vector_digest,
            &predecessor.model_tuple,
            predecessor.scope_digest,
            predecessor.authority_domain_digest,
            observed_unix_ms,
            &realization_ids,
        )?;
        let mut successor = PromptContextAuthoritySuccessorV3 {
            predecessor_snapshot_digest: predecessor.snapshot_digest,
            current,
            lineage_digest: Digest32::ZERO,
        };
        successor.lineage_digest = successor.compute_digest();
        successor.validate(predecessor)?;
        Ok(successor)
    }
}

fn authority_admission(
    delivery: &RealizationDeliveryV2,
    generation_vector_digest: Digest32,
    scope_digest: Digest32,
    authority_domain_digest: Digest32,
    observed_unix_ms: u64,
) -> Result<PromptContextAuthorityAdmissionV3, PromptContextAuthorityErrorV3> {
    delivery
        .validate()
        .map_err(|error| PromptContextAuthorityErrorV3::Registry(error.to_string()))?;
    let issued_unix_ms = observed_unix_ms;
    let expires_unix_ms = delivery.binding.expires_unix_ms.unwrap_or(u64::MAX);
    if expires_unix_ms <= issued_unix_ms {
        return Err(PromptContextAuthorityErrorV3::InvalidTime);
    }
    let admission_id = StableId::new(format!(
        "context-admission:v3:{}",
        delivery.binding.realization_id
    ))
    .map_err(|_| PromptContextAuthorityErrorV3::Integrity)?;
    let mut admission = PromptContextAuthorityAdmissionV3 {
        admission_id,
        realization_id: delivery.binding.realization_id.clone(),
        role: delivery.binding.role,
        content_digest: delivery.binding.payload_digest,
        source_digest: delivery.binding.digest(),
        generation_vector_digest,
        scope_digest,
        authority_domain_digest,
        issued_unix_ms,
        expires_unix_ms,
        registry_binding_digest: delivery.delivery_digest,
        admission_digest: Digest32::ZERO,
    };
    admission.admission_digest = admission.compute_digest();
    admission.validate()?;
    Ok(admission)
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

const fn role_code(role: PromptRoleV2) -> u8 {
    match role {
        PromptRoleV2::SystemInstruction => 0,
        PromptRoleV2::DeveloperInstruction => 1,
        PromptRoleV2::UserTemplate => 2,
        PromptRoleV2::ToolSchemaFragment => 3,
    }
}
