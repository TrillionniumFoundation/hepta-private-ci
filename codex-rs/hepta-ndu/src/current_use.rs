use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::NduProjectionEntryV1;
use crate::NduProjectionJournalV1;
use crate::NduProjectionKindV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NduCurrentUseErrorV2 {
    EmptyDigest(&'static str),
    HistoricalOperationNotFound,
    ProjectionNotCurrent,
    SelectionEntryNotFound,
    ReceiptDigest,
}

impl fmt::Display for NduCurrentUseErrorV2 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduCurrentUseErrorV2 {}

/// Historical terminal evidence for one operation identity. This type is
/// deliberately not accepted by final-use APIs and carries no claim that the
/// projection remains selected or unrevoked.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduHistoricalProjectionReplayV1 {
    entry: NduProjectionEntryV1,
    observed_journal_head_digest: Digest32,
}

impl NduHistoricalProjectionReplayV1 {
    #[must_use]
    pub const fn entry(&self) -> &NduProjectionEntryV1 {
        &self.entry
    }

    #[must_use]
    pub const fn observed_journal_head_digest(&self) -> Digest32 {
        self.observed_journal_head_digest
    }
}

/// A current selected view. It is still not a final-use authorization: the
/// artifact, grant, revocation frontier, trusted time and owner fence are bound
/// only by `validate_ndu_current_use_v2`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCurrentProjectionSelectionV2 {
    objective_digest: Digest32,
    subject_digest: Digest32,
    projection_digest: Digest32,
    selection_entry_digest: Digest32,
    journal_head_digest: Digest32,
}

impl NduCurrentProjectionSelectionV2 {
    #[must_use]
    pub const fn objective_digest(&self) -> Digest32 {
        self.objective_digest
    }

    #[must_use]
    pub const fn subject_digest(&self) -> Digest32 {
        self.subject_digest
    }

    #[must_use]
    pub const fn projection_digest(&self) -> Digest32 {
        self.projection_digest
    }

    #[must_use]
    pub const fn selection_entry_digest(&self) -> Digest32 {
        self.selection_entry_digest
    }

    #[must_use]
    pub const fn journal_head_digest(&self) -> Digest32 {
        self.journal_head_digest
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCurrentUseContextV2 {
    pub objective_digest: Digest32,
    pub subject_digest: Digest32,
    pub projection_digest: Digest32,
    pub artifact_binding_digest: Digest32,
    pub final_use_grant_digest: Digest32,
    pub revocation_frontier_digest: Digest32,
    pub trusted_time_receipt_digest: Digest32,
    pub owner_fence_digest: Digest32,
    pub production_policy_digest: Digest32,
    pub adapter_manifest_digest: Digest32,
    pub validated_at_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCurrentUseReceiptV2 {
    current_selection: NduCurrentProjectionSelectionV2,
    artifact_binding_digest: Digest32,
    final_use_grant_digest: Digest32,
    revocation_frontier_digest: Digest32,
    trusted_time_receipt_digest: Digest32,
    owner_fence_digest: Digest32,
    production_policy_digest: Digest32,
    adapter_manifest_digest: Digest32,
    validated_at_ms: u64,
    receipt_digest: Digest32,
}

impl NduCurrentUseReceiptV2 {
    #[must_use]
    pub const fn current_selection(&self) -> &NduCurrentProjectionSelectionV2 {
        &self.current_selection
    }

    #[must_use]
    pub const fn artifact_binding_digest(&self) -> Digest32 {
        self.artifact_binding_digest
    }

    #[must_use]
    pub const fn final_use_grant_digest(&self) -> Digest32 {
        self.final_use_grant_digest
    }

    #[must_use]
    pub const fn revocation_frontier_digest(&self) -> Digest32 {
        self.revocation_frontier_digest
    }

    #[must_use]
    pub const fn trusted_time_receipt_digest(&self) -> Digest32 {
        self.trusted_time_receipt_digest
    }

    #[must_use]
    pub const fn owner_fence_digest(&self) -> Digest32 {
        self.owner_fence_digest
    }

    #[must_use]
    pub const fn production_policy_digest(&self) -> Digest32 {
        self.production_policy_digest
    }

    #[must_use]
    pub const fn adapter_manifest_digest(&self) -> Digest32 {
        self.adapter_manifest_digest
    }

    #[must_use]
    pub const fn validated_at_ms(&self) -> u64 {
        self.validated_at_ms
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    pub fn validate(&self) -> Result<(), NduCurrentUseErrorV2> {
        let expected = digest_current_use(
            &self.current_selection,
            self.artifact_binding_digest,
            self.final_use_grant_digest,
            self.revocation_frontier_digest,
            self.trusted_time_receipt_digest,
            self.owner_fence_digest,
            self.production_policy_digest,
            self.adapter_manifest_digest,
            self.validated_at_ms,
        );
        if expected != self.receipt_digest {
            return Err(NduCurrentUseErrorV2::ReceiptDigest);
        }
        Ok(())
    }
}

pub trait NduProjectionJournalViewExt {
    fn historical_replay_v1(
        &self,
        operation_identity_digest: Digest32,
    ) -> Result<NduHistoricalProjectionReplayV1, NduCurrentUseErrorV2>;

    fn current_selection_v2(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<NduCurrentProjectionSelectionV2, NduCurrentUseErrorV2>;
}

impl NduProjectionJournalViewExt for NduProjectionJournalV1 {
    fn historical_replay_v1(
        &self,
        operation_identity_digest: Digest32,
    ) -> Result<NduHistoricalProjectionReplayV1, NduCurrentUseErrorV2> {
        require_digest(operation_identity_digest, "operation identity")?;
        let entry = self
            .entries()
            .iter()
            .find(|entry| entry.identity_digest == operation_identity_digest)
            .cloned()
            .ok_or(NduCurrentUseErrorV2::HistoricalOperationNotFound)?;
        Ok(NduHistoricalProjectionReplayV1 {
            entry,
            observed_journal_head_digest: journal_head(self),
        })
    }

    fn current_selection_v2(
        &self,
        objective_digest: Digest32,
        subject_digest: Digest32,
    ) -> Result<NduCurrentProjectionSelectionV2, NduCurrentUseErrorV2> {
        require_digest(objective_digest, "objective")?;
        require_digest(subject_digest, "subject")?;
        let projection_digest = self
            .selected_projection_digest(objective_digest, subject_digest)
            .ok_or(NduCurrentUseErrorV2::ProjectionNotCurrent)?;
        let selection = self
            .entries()
            .iter()
            .rev()
            .find(|entry| {
                entry.kind == NduProjectionKindV1::SelectedProjection
                    && entry.objective_digest == objective_digest
                    && entry.subject_digest == subject_digest
                    && entry.payload_digest == projection_digest
            })
            .ok_or(NduCurrentUseErrorV2::SelectionEntryNotFound)?;
        Ok(NduCurrentProjectionSelectionV2 {
            objective_digest,
            subject_digest,
            projection_digest,
            selection_entry_digest: selection.entry_digest,
            journal_head_digest: journal_head(self),
        })
    }
}

pub fn validate_ndu_current_use_v2(
    journal: &NduProjectionJournalV1,
    context: NduCurrentUseContextV2,
) -> Result<NduCurrentUseReceiptV2, NduCurrentUseErrorV2> {
    for (field, digest) in [
        ("objective", context.objective_digest),
        ("subject", context.subject_digest),
        ("projection", context.projection_digest),
        ("artifact binding", context.artifact_binding_digest),
        ("final-use grant", context.final_use_grant_digest),
        ("revocation frontier", context.revocation_frontier_digest),
        ("trusted time", context.trusted_time_receipt_digest),
        ("owner fence", context.owner_fence_digest),
        ("production policy", context.production_policy_digest),
        ("adapter manifest", context.adapter_manifest_digest),
    ] {
        require_digest(digest, field)?;
    }
    let current_selection =
        journal.current_selection_v2(context.objective_digest, context.subject_digest)?;
    if current_selection.projection_digest != context.projection_digest {
        return Err(NduCurrentUseErrorV2::ProjectionNotCurrent);
    }
    let receipt_digest = digest_current_use(
        &current_selection,
        context.artifact_binding_digest,
        context.final_use_grant_digest,
        context.revocation_frontier_digest,
        context.trusted_time_receipt_digest,
        context.owner_fence_digest,
        context.production_policy_digest,
        context.adapter_manifest_digest,
        context.validated_at_ms,
    );
    let receipt = NduCurrentUseReceiptV2 {
        current_selection,
        artifact_binding_digest: context.artifact_binding_digest,
        final_use_grant_digest: context.final_use_grant_digest,
        revocation_frontier_digest: context.revocation_frontier_digest,
        trusted_time_receipt_digest: context.trusted_time_receipt_digest,
        owner_fence_digest: context.owner_fence_digest,
        production_policy_digest: context.production_policy_digest,
        adapter_manifest_digest: context.adapter_manifest_digest,
        validated_at_ms: context.validated_at_ms,
        receipt_digest,
    };
    receipt.validate()?;
    Ok(receipt)
}

fn journal_head(journal: &NduProjectionJournalV1) -> Digest32 {
    journal
        .entries()
        .last()
        .map_or(Digest32::ZERO, |entry| entry.entry_digest)
}

#[allow(clippy::too_many_arguments)]
fn digest_current_use(
    selection: &NduCurrentProjectionSelectionV2,
    artifact_binding_digest: Digest32,
    final_use_grant_digest: Digest32,
    revocation_frontier_digest: Digest32,
    trusted_time_receipt_digest: Digest32,
    owner_fence_digest: Digest32,
    production_policy_digest: Digest32,
    adapter_manifest_digest: Digest32,
    validated_at_ms: u64,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.current-use-receipt.v2\0",
        selection.objective_digest.as_array(),
        selection.subject_digest.as_array(),
        selection.projection_digest.as_array(),
        selection.selection_entry_digest.as_array(),
        selection.journal_head_digest.as_array(),
        artifact_binding_digest.as_array(),
        final_use_grant_digest.as_array(),
        revocation_frontier_digest.as_array(),
        trusted_time_receipt_digest.as_array(),
        owner_fence_digest.as_array(),
        production_policy_digest.as_array(),
        adapter_manifest_digest.as_array(),
        &validated_at_ms.to_be_bytes(),
    ])
}

fn require_digest(
    value: Digest32,
    field: &'static str,
) -> Result<(), NduCurrentUseErrorV2> {
    if value.is_zero() {
        return Err(NduCurrentUseErrorV2::EmptyDigest(field));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    #![allow(clippy::expect_used)]
    use super::*;

    fn digest(value: &[u8]) -> Digest32 {
        Digest32::of_bytes(value)
    }

    #[test]
    fn historical_replay_does_not_become_current_use() {
        let objective = digest(b"objective");
        let subject = digest(b"subject");
        let projection = digest(b"projection");
        let mut journal = NduProjectionJournalV1::new_ephemeral();
        journal
            .append_projection(
                NduProjectionKindV1::Utility,
                digest(b"append"),
                objective,
                subject,
                projection,
            )
            .expect("append");
        journal
            .select_projection(
                digest(b"select"),
                objective,
                subject,
                projection,
            )
            .expect("select");
        journal
            .revoke_projection(
                digest(b"revoke"),
                objective,
                subject,
                projection,
            )
            .expect("revoke");

        let replay = journal
            .historical_replay_v1(digest(b"select"))
            .expect("historical replay");
        assert_eq!(replay.entry().payload_digest, projection);
        assert_eq!(
            journal.current_selection_v2(objective, subject),
            Err(NduCurrentUseErrorV2::ProjectionNotCurrent)
        );
    }
}
