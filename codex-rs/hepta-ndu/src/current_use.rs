use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::{AuthorityPosture, Digest32};

use crate::{
    NduProjectionArtifactKindV2, NduProjectionCatalogEntryV2,
    NduProjectionCatalogV2, NduVerifiedProjectionArtifactV3,
};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduCurrentUseErrorV2 {
    EmptyDigest(&'static str),
    InvalidTimeWindow,
    ProjectionNotSelected,
    ProjectionMismatch,
    ArtifactBindingMismatch,
    AuthenticatedArtifactExpired,
    InvalidHistoricalReplay,
    ReceiptDigestMismatch,
}

impl fmt::Display for NduCurrentUseErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduCurrentUseErrorV2 {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduHistoricalReplayReceiptV2 {
    identity_digest: Digest32,
    semantic_digest: Digest32,
    entry_digest: Digest32,
    sequence: u64,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduHistoricalReplayReceiptV2 {
    pub fn from_entry(
        entry: &NduProjectionCatalogEntryV2,
    ) -> Result<Self, NduCurrentUseErrorV2> {
        require_digest(entry.identity_digest(), "operation identity")?;
        require_digest(entry.semantic_digest(), "semantic")?;
        require_digest(entry.entry_digest(), "entry")?;
        if entry.sequence() == 0 {
            return Err(NduCurrentUseErrorV2::InvalidHistoricalReplay);
        }
        let receipt_digest = digest_historical_replay(
            entry.identity_digest(),
            entry.semantic_digest(),
            entry.entry_digest(),
            entry.sequence(),
        );
        Ok(Self {
            identity_digest: entry.identity_digest(),
            semantic_digest: entry.semantic_digest(),
            entry_digest: entry.entry_digest(),
            sequence: entry.sequence(),
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    #[must_use]
    pub const fn identity_digest(&self) -> Digest32 {
        self.identity_digest
    }

    #[must_use]
    pub const fn semantic_digest(&self) -> Digest32 {
        self.semantic_digest
    }

    #[must_use]
    pub const fn entry_digest(&self) -> Digest32 {
        self.entry_digest
    }

    #[must_use]
    pub const fn sequence(&self) -> u64 {
        self.sequence
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduCurrentUseErrorV2> {
        require_digest(self.identity_digest, "operation identity")?;
        require_digest(self.semantic_digest, "semantic")?;
        require_digest(self.entry_digest, "entry")?;
        if self.sequence == 0 || self.authority != AuthorityPosture::DENY_ALL {
            return Err(NduCurrentUseErrorV2::InvalidHistoricalReplay);
        }
        if digest_historical_replay(
            self.identity_digest,
            self.semantic_digest,
            self.entry_digest,
            self.sequence,
        ) != self.receipt_digest
        {
            return Err(NduCurrentUseErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCurrentUseRequestV2 {
    pub objective_digest: Digest32,
    pub subject_digest: Digest32,
    pub projection_kind: NduProjectionArtifactKindV2,
    pub projection_digest: Digest32,
    pub checked_at_ms: u64,
    pub grant_expires_at_ms: u64,
    pub trusted_time_receipt_digest: Digest32,
    pub current_revocation_frontier_digest: Digest32,
    pub artifact_availability_receipt_digest: Digest32,
    pub final_use_grant_binding_digest: Digest32,
    pub production_policy_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCurrentUseReceiptV2 {
    objective_digest: Digest32,
    subject_digest: Digest32,
    projection_kind: NduProjectionArtifactKindV2,
    projection_digest: Digest32,
    artifact_binding_digest: Digest32,
    catalog_head_digest: Digest32,
    authenticated_artifact_receipt_digest: Digest32,
    trust_binding_digest: Digest32,
    checked_at_ms: u64,
    valid_until_ms: u64,
    trusted_time_receipt_digest: Digest32,
    current_revocation_frontier_digest: Digest32,
    artifact_availability_receipt_digest: Digest32,
    final_use_grant_binding_digest: Digest32,
    production_policy_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduCurrentUseReceiptV2 {
    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub const fn artifact_binding_digest(&self) -> Digest32 {
        self.artifact_binding_digest
    }

    #[must_use]
    pub const fn catalog_head_digest(&self) -> Digest32 {
        self.catalog_head_digest
    }

    #[must_use]
    pub const fn valid_until_ms(&self) -> u64 {
        self.valid_until_ms
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }

    pub fn validate(&self) -> Result<(), NduCurrentUseErrorV2> {
        validate_request_fields(
            self.objective_digest,
            self.subject_digest,
            self.projection_digest,
            self.checked_at_ms,
            self.valid_until_ms,
            self.trusted_time_receipt_digest,
            self.current_revocation_frontier_digest,
            self.artifact_availability_receipt_digest,
            self.final_use_grant_binding_digest,
            self.production_policy_digest,
        )?;
        require_digest(self.artifact_binding_digest, "artifact binding")?;
        require_digest(self.catalog_head_digest, "catalog head")?;
        require_digest(
            self.authenticated_artifact_receipt_digest,
            "authenticated artifact receipt",
        )?;
        require_digest(self.trust_binding_digest, "trust binding")?;
        if self.authority != AuthorityPosture::DENY_ALL
            || digest_current_use(self) != self.receipt_digest
        {
            return Err(NduCurrentUseErrorV2::ReceiptDigestMismatch);
        }
        Ok(())
    }
}

pub fn validate_current_use_v2(
    catalog: &NduProjectionCatalogV2,
    authenticated_artifact: &NduVerifiedProjectionArtifactV3,
    request: &NduCurrentUseRequestV2,
) -> Result<NduCurrentUseReceiptV2, NduCurrentUseErrorV2> {
    validate_request_fields(
        request.objective_digest,
        request.subject_digest,
        request.projection_digest,
        request.checked_at_ms,
        request.grant_expires_at_ms,
        request.trusted_time_receipt_digest,
        request.current_revocation_frontier_digest,
        request.artifact_availability_receipt_digest,
        request.final_use_grant_binding_digest,
        request.production_policy_digest,
    )?;
    if request.checked_at_ms > authenticated_artifact.valid_until_ms() {
        return Err(NduCurrentUseErrorV2::AuthenticatedArtifactExpired);
    }
    let selected = catalog
        .selected_artifact(
            request.objective_digest,
            request.subject_digest,
            request.projection_kind,
        )
        .ok_or(NduCurrentUseErrorV2::ProjectionNotSelected)?;
    if selected.projection_digest() != request.projection_digest
        || authenticated_artifact.projection_digest() != request.projection_digest
    {
        return Err(NduCurrentUseErrorV2::ProjectionMismatch);
    }
    if selected.binding_digest() != authenticated_artifact.artifact_binding_digest() {
        return Err(NduCurrentUseErrorV2::ArtifactBindingMismatch);
    }
    let catalog_head_digest = catalog
        .entries()
        .last()
        .map(NduProjectionCatalogEntryV2::entry_digest)
        .ok_or(NduCurrentUseErrorV2::ProjectionNotSelected)?;
    let valid_until_ms = request
        .grant_expires_at_ms
        .min(authenticated_artifact.valid_until_ms());
    let mut receipt = NduCurrentUseReceiptV2 {
        objective_digest: request.objective_digest,
        subject_digest: request.subject_digest,
        projection_kind: request.projection_kind,
        projection_digest: request.projection_digest,
        artifact_binding_digest: selected.binding_digest(),
        catalog_head_digest,
        authenticated_artifact_receipt_digest: authenticated_artifact
            .signed_receipt_digest(),
        trust_binding_digest: authenticated_artifact.trust_binding_digest(),
        checked_at_ms: request.checked_at_ms,
        valid_until_ms,
        trusted_time_receipt_digest: request.trusted_time_receipt_digest,
        current_revocation_frontier_digest: request.current_revocation_frontier_digest,
        artifact_availability_receipt_digest: request
            .artifact_availability_receipt_digest,
        final_use_grant_binding_digest: request.final_use_grant_binding_digest,
        production_policy_digest: request.production_policy_digest,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_current_use(&receipt);
    receipt.validate()?;
    Ok(receipt)
}

#[allow(clippy::too_many_arguments)]
fn validate_request_fields(
    objective_digest: Digest32,
    subject_digest: Digest32,
    projection_digest: Digest32,
    checked_at_ms: u64,
    valid_until_ms: u64,
    trusted_time_receipt_digest: Digest32,
    current_revocation_frontier_digest: Digest32,
    artifact_availability_receipt_digest: Digest32,
    final_use_grant_binding_digest: Digest32,
    production_policy_digest: Digest32,
) -> Result<(), NduCurrentUseErrorV2> {
    require_digest(objective_digest, "objective")?;
    require_digest(subject_digest, "subject")?;
    require_digest(projection_digest, "projection")?;
    require_digest(trusted_time_receipt_digest, "trusted time receipt")?;
    require_digest(
        current_revocation_frontier_digest,
        "revocation frontier",
    )?;
    require_digest(
        artifact_availability_receipt_digest,
        "artifact availability receipt",
    )?;
    require_digest(final_use_grant_binding_digest, "final-use grant binding")?;
    require_digest(production_policy_digest, "production policy")?;
    if checked_at_ms == 0 || valid_until_ms < checked_at_ms {
        return Err(NduCurrentUseErrorV2::InvalidTimeWindow);
    }
    Ok(())
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduCurrentUseErrorV2> {
    if digest.is_zero() {
        Err(NduCurrentUseErrorV2::EmptyDigest(field))
    } else {
        Ok(())
    }
}

fn digest_historical_replay(
    identity_digest: Digest32,
    semantic_digest: Digest32,
    entry_digest: Digest32,
    sequence: u64,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.historical-replay-receipt.v2\0",
        identity_digest.as_array(),
        semantic_digest.as_array(),
        entry_digest.as_array(),
        &sequence.to_be_bytes(),
        &[0],
    ])
}

fn digest_current_use(receipt: &NduCurrentUseReceiptV2) -> Digest32 {
    let kind = match receipt.projection_kind {
        NduProjectionArtifactKindV2::Preference => 0,
        NduProjectionArtifactKindV2::Utility => 1,
        NduProjectionArtifactKindV2::Coefficient => 2,
    };
    Digest32::of_parts(&[
        b"hepta.ndu.current-use-receipt.v2\0",
        receipt.objective_digest.as_array(),
        receipt.subject_digest.as_array(),
        &[kind],
        receipt.projection_digest.as_array(),
        receipt.artifact_binding_digest.as_array(),
        receipt.catalog_head_digest.as_array(),
        receipt.authenticated_artifact_receipt_digest.as_array(),
        receipt.trust_binding_digest.as_array(),
        &receipt.checked_at_ms.to_be_bytes(),
        &receipt.valid_until_ms.to_be_bytes(),
        receipt.trusted_time_receipt_digest.as_array(),
        receipt.current_revocation_frontier_digest.as_array(),
        receipt.artifact_availability_receipt_digest.as_array(),
        receipt.final_use_grant_binding_digest.as_array(),
        receipt.production_policy_digest.as_array(),
        &[0],
    ])
}

#[cfg(test)]
mod tests {
    use crate::NduDurableProjectionArtifactV2;

    use super::*;

    fn digest(value: &str) -> Digest32 {
        Digest32::of_bytes(value.as_bytes())
    }

    #[test]
    fn historical_replay_does_not_grant_current_use_after_revocation() {
        let objective = digest("objective");
        let subject = digest("subject");
        let projection = digest("projection");
        let artifact = NduDurableProjectionArtifactV2::new(
            NduProjectionArtifactKindV2::Preference,
            projection,
            "artifact://sha256/legacy".to_string(),
            1,
            1,
            digest("policy"),
            digest("provenance"),
            1,
        )
        .expect("artifact");
        let mut catalog = NduProjectionCatalogV2::new();
        catalog
            .publish(digest("publish"), objective, subject, artifact)
            .expect("publish");
        let selected = catalog
            .select(
                digest("select"),
                objective,
                subject,
                NduProjectionArtifactKindV2::Preference,
                projection,
            )
            .expect("select");
        let replay = NduHistoricalReplayReceiptV2::from_entry(&selected)
            .expect("historical replay");
        replay.validate().expect("valid replay");
        catalog
            .revoke(
                digest("revoke"),
                objective,
                subject,
                NduProjectionArtifactKindV2::Preference,
                projection,
            )
            .expect("revoke");
        assert!(catalog
            .selected_artifact(
                objective,
                subject,
                NduProjectionArtifactKindV2::Preference,
            )
            .is_none());
        assert_eq!(replay.authority(), AuthorityPosture::DENY_ALL);
    }
}
