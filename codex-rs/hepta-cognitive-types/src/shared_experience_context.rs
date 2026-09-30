//! Cross-object final-use validation for Shared Experience V2.
//!
//! Raw wire DTOs, type-local `Validated<T>` values, and this contextual proof
//! are deliberately separate stages. Constructing this proof does not
//! authenticate an owner or grant authority: the caller must supply the exact
//! owner-authenticated cut and trusted timestamp observed at the physical use
//! boundary. The immutable borrows prevent safe mutation while the proof is in
//! use, and revalidation rejects owner-cut drift.

use codex_hepta_types::Digest32;

use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::Validated;
use crate::hnmf::ContractIdV1;
use crate::shared_experience::SharedExperienceOwnerCutV2;
use crate::shared_experience::SharedExperiencePublicationV2;
use crate::shared_experience::SharedExperienceSourceKindV2;
use crate::shared_experience::SharedExperienceUseClassV2;
use crate::shared_experience::SharedExperienceUseDispositionV2;
use crate::shared_experience::SharedExperienceUseGrantV2;
use crate::shared_experience::SharedExperienceUseReceiptV2;
use crate::wire::canonical_contract_digest_v1;

const FINAL_USE_CONTEXT_DOMAIN_V2: &[u8] = b"hepta.shared-experience.final-use-context.v2\0";

impl SharedExperienceUseClassV2 {
    /// Stable protocol token. Never derive digest input from `Debug` output.
    #[must_use]
    pub const fn wire_token(&self) -> &'static str {
        match self {
            Self::RawEvidenceRead { .. } => "raw_evidence_read",
            Self::PurposeBoundTraining { .. } => "purpose_bound_training",
            Self::DerivedArtifactUse { .. } => "derived_artifact_use",
        }
    }
}

impl SharedExperienceSourceKindV2 {
    /// Stable protocol token. Never derive digest input from `Debug` output.
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::CanonicalMemoryEvent => "canonical_memory_event",
            Self::OwnerMemoryRevision => "owner_memory_revision",
        }
    }
}

impl SharedExperienceUseDispositionV2 {
    /// Stable protocol token. Never derive digest input from `Debug` output.
    #[must_use]
    pub const fn wire_token(self) -> &'static str {
        match self {
            Self::Delivered => "delivered",
            Self::TrainingBatchMaterialized => "training_batch_materialized",
            Self::ArtifactAdopted => "artifact_adopted",
            Self::Rejected => "rejected",
            Self::Indeterminate => "indeterminate",
        }
    }

    #[must_use]
    pub const fn is_successful_final_use(self) -> bool {
        matches!(
            self,
            Self::Delivered | Self::TrainingBatchMaterialized | Self::ArtifactAdopted
        )
    }
}

/// A completed Shared Experience V2 use whose publication, exact grant,
/// consumer, destination, source owner, policy, revocation frontier and trusted
/// use time have been checked together.
///
/// This value is not an authorization capability. It proves only that the
/// caller-supplied, owner-authenticated observations are mutually consistent.
/// The product owner must still authenticate those observations and persist the
/// receipt according to its own durability contract.
#[derive(Debug)]
pub struct FinalSharedExperienceUseV2<'a> {
    publication: &'a Validated<SharedExperiencePublicationV2>,
    receipt: &'a Validated<SharedExperienceUseReceiptV2>,
    owner_cut: &'a SharedExperienceOwnerCutV2,
    grant: &'a SharedExperienceUseGrantV2,
    destination_scope_id: &'a ContractIdV1,
    checked_at_unix_ms: u64,
    publication_digest: Digest32,
    receipt_digest: Digest32,
    context_digest: Digest32,
}

impl<'a> FinalSharedExperienceUseV2<'a> {
    pub fn new(
        publication: &'a Validated<SharedExperiencePublicationV2>,
        receipt: &'a Validated<SharedExperienceUseReceiptV2>,
        owner_cut: &'a SharedExperienceOwnerCutV2,
        destination_scope_id: &'a ContractIdV1,
        checked_at_unix_ms: u64,
    ) -> Result<Self, ContractViolationV1> {
        owner_cut.validate().map_err(|_| {
            violation(
                ContractErrorCodeV1::InvalidValue,
                "ownerCut",
                "current owner cut is structurally invalid",
            )
        })?;
        if checked_at_unix_ms == 0 {
            return Err(violation(
                ContractErrorCodeV1::ZeroValue,
                "checkedAtUnixMs",
                "trusted final-use time must be non-zero",
            ));
        }

        let publication_value = publication.as_inner();
        let receipt_value = receipt.as_inner();
        if !receipt_value.disposition.is_successful_final_use() || !receipt_value.final_use_observed
        {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.disposition",
                "only an observed successful physical use can create a final-use proof",
            ));
        }
        if receipt_value.used_at_unix_ms != checked_at_unix_ms {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.usedAtUnixMs",
                "receipt time must equal the trusted time used for the final boundary check",
            ));
        }
        if checked_at_unix_ms < publication_value.observed_at_unix_ms
            || publication_value
                .expires_at_unix_ms
                .is_some_and(|expiry| checked_at_unix_ms >= expiry)
        {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "publication.validity",
                "publication is not current at the final-use time",
            ));
        }

        let grant = publication_value
            .use_grants
            .iter()
            .find(|candidate| candidate.grant_id == receipt_value.grant.grant_id)
            .ok_or_else(|| {
                violation(
                    ContractErrorCodeV1::MissingValue,
                    "receipt.grant.grantId",
                    "receipt grant is absent from the publication",
                )
            })?;
        if grant != &receipt_value.grant {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.grant",
                "receipt grant differs from the exact published grant",
            ));
        }
        if !(grant.valid_from_unix_ms..grant.expires_at_unix_ms).contains(&checked_at_unix_ms) {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.grant.validity",
                "published grant is not current at the final-use time",
            ));
        }
        if !publication_value
            .destination_scope_ids
            .contains(destination_scope_id)
        {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "destinationScopeId",
                "destination is not admitted by the publication",
            ));
        }
        if &receipt_value.consumer_id != grant.use_class.consumer_id() {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.consumerId",
                "receipt consumer differs from the exact published grant",
            ));
        }
        if receipt_value.source_owner_id != publication_value.source_owner_id
            || receipt_value.source_revision != publication_value.source_revision
        {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.source",
                "receipt does not bind the publication source owner and revision",
            ));
        }
        if owner_cut.owner_id != publication_value.source_owner_id
            || owner_cut.owner_epoch != publication_value.source_owner_epoch
        {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "ownerCut.owner",
                "current owner identity or epoch differs from the publication",
            ));
        }
        if owner_cut.source_frontier < publication_value.source_revision {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "ownerCut.sourceFrontier",
                "current owner cut does not cover the published source revision",
            ));
        }
        if receipt_value.observed_policy_generation != publication_value.policy_generation {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.observedPolicyGeneration",
                "receipt policy generation differs from the publication",
            ));
        }
        if owner_cut.policy_sha256 != publication_value.publication_policy_sha256 {
            return Err(violation(
                ContractErrorCodeV1::DigestMismatch,
                "ownerCut.policySha256",
                "current owner policy differs from the publication policy",
            ));
        }
        if owner_cut.revocation_frontier != receipt_value.observed_revocation_frontier {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "receipt.observedRevocationFrontier",
                "receipt was not checked against the exact current revocation frontier",
            ));
        }

        let publication_digest = canonical_contract_digest_v1(publication_value).map_err(|_| {
            violation(
                ContractErrorCodeV1::InvalidValue,
                "publication",
                "publication cannot be canonically digested",
            )
        })?;
        if receipt_value.publication_sha256.digest() != publication_digest {
            return Err(violation(
                ContractErrorCodeV1::DigestMismatch,
                "receipt.publicationSha256",
                "receipt does not bind the exact canonical publication",
            ));
        }
        let receipt_digest = canonical_contract_digest_v1(receipt_value).map_err(|_| {
            violation(
                ContractErrorCodeV1::InvalidValue,
                "receipt",
                "receipt cannot be canonically digested",
            )
        })?;
        let context_digest = compute_context_digest(
            publication_value,
            receipt_value,
            owner_cut,
            destination_scope_id,
            checked_at_unix_ms,
            publication_digest,
            receipt_digest,
        );

        Ok(Self {
            publication,
            receipt,
            owner_cut,
            grant,
            destination_scope_id,
            checked_at_unix_ms,
            publication_digest,
            receipt_digest,
            context_digest,
        })
    }

    /// Recheck the owner observation immediately before consuming this proof.
    /// Any owner, epoch, policy, schema or frontier drift invalidates it.
    pub fn require_unchanged_owner_cut(
        &self,
        current_owner_cut: &SharedExperienceOwnerCutV2,
    ) -> Result<&Validated<SharedExperienceUseReceiptV2>, ContractViolationV1> {
        current_owner_cut.validate().map_err(|_| {
            violation(
                ContractErrorCodeV1::InvalidValue,
                "currentOwnerCut",
                "current owner cut is structurally invalid",
            )
        })?;
        if current_owner_cut != self.owner_cut {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "currentOwnerCut",
                "owner cut changed after contextual validation",
            ));
        }
        Ok(self.receipt)
    }

    #[must_use]
    pub const fn publication(&self) -> &Validated<SharedExperiencePublicationV2> {
        self.publication
    }

    #[must_use]
    pub const fn receipt(&self) -> &Validated<SharedExperienceUseReceiptV2> {
        self.receipt
    }

    #[must_use]
    pub const fn owner_cut(&self) -> &SharedExperienceOwnerCutV2 {
        self.owner_cut
    }

    #[must_use]
    pub const fn grant(&self) -> &SharedExperienceUseGrantV2 {
        self.grant
    }

    #[must_use]
    pub const fn destination_scope_id(&self) -> &ContractIdV1 {
        self.destination_scope_id
    }

    #[must_use]
    pub const fn checked_at_unix_ms(&self) -> u64 {
        self.checked_at_unix_ms
    }

    #[must_use]
    pub const fn publication_digest(&self) -> Digest32 {
        self.publication_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn context_digest(&self) -> Digest32 {
        self.context_digest
    }
}

#[allow(clippy::too_many_arguments)]
fn compute_context_digest(
    publication: &SharedExperiencePublicationV2,
    receipt: &SharedExperienceUseReceiptV2,
    owner_cut: &SharedExperienceOwnerCutV2,
    destination_scope_id: &ContractIdV1,
    checked_at_unix_ms: u64,
    publication_digest: Digest32,
    receipt_digest: Digest32,
) -> Digest32 {
    let mut bytes = FINAL_USE_CONTEXT_DOMAIN_V2.to_vec();
    push_digest(&mut bytes, publication_digest);
    push_digest(&mut bytes, receipt_digest);
    push_text(&mut bytes, publication.source_kind.wire_token());
    push_text(&mut bytes, owner_cut.owner_id.as_str());
    push_u64(&mut bytes, owner_cut.owner_epoch);
    push_u64(&mut bytes, owner_cut.source_frontier);
    push_u64(&mut bytes, owner_cut.revocation_frontier);
    push_digest(&mut bytes, owner_cut.schema_sha256.digest());
    push_digest(&mut bytes, owner_cut.policy_sha256.digest());
    push_text(&mut bytes, destination_scope_id.as_str());
    push_text(&mut bytes, receipt.grant.grant_id.as_str());
    push_text(&mut bytes, receipt.grant.use_class.wire_token());
    push_text(&mut bytes, receipt.disposition.wire_token());
    push_u64(&mut bytes, checked_at_unix_ms);
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u64::try_from(value.len()).unwrap_or(u64::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn violation(
    code: ContractErrorCodeV1,
    field_path: &'static str,
    message: &'static str,
) -> ContractViolationV1 {
    ContractViolationV1::new(code, field_path, message)
}
