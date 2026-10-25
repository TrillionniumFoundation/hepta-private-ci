//! Owner-aware serving checks both registry eligibility and source withdrawals.
//! The owner must install the authenticated withdrawal feed and serialize reads
//! at its effect boundary. This wrapper grants no selector or dispatch authority.

use super::*;
use crate::ArtifactAdmissionError;
use crate::DatasetWithdrawalRegistrySnapshotV1;
use crate::LearningArtifactManifestV2;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceError;
use crate::admit_manifest_at_withdrawal_head_v3;
use std::convert::Infallible;

/// Exact full manifest and current host owner used for a load or rollback.
/// The manifest is checked against every field of the selected compact record.
pub struct OwnerCandidateContextV5<'a> {
    pub owner: &'a LearningArtifactOwnerService,
    pub manifest: &'a LearningArtifactManifestV2,
    pub now: u64,
}

pub struct OwnerTypedSelectedCandidateV5<T> {
    selected: TypedSelectedCandidateV5<T>,
    manifest: LearningArtifactManifestV2,
    withdrawals: DatasetWithdrawalRegistrySnapshotV1,
}

impl<T> OwnerTypedSelectedCandidateV5<T> {
    pub fn load<E>(
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        context: OwnerCandidateContextV5<'_>,
        compatibility: Digest32,
        decode: impl FnOnce(&[u8], &ArtifactManifest) -> Result<T, E>,
    ) -> Result<Self, OwnerTypedCandidateErrorV5<E>> {
        let current = context
            .owner
            .current_registry_view(context.now)
            .map_err(OwnerTypedCandidateErrorV5::Owner)?;
        let compact = context
            .owner
            .registry()
            .manifest(selection.artifact_id())
            .ok_or(OwnerTypedCandidateErrorV5::ManifestBinding)?;
        check_manifest(&context, compact)?;
        let selected = TypedSelectedCandidateV5::load(
            snapshot,
            payload,
            selection,
            current,
            compatibility,
            decode,
        )
        .map_err(OwnerTypedCandidateErrorV5::Typed)?;
        Ok(Self {
            selected,
            manifest: context.manifest.clone(),
            withdrawals: context.owner.withdrawal_registry().snapshot(),
        })
    }

    #[must_use]
    pub fn spec(&self) -> &PinnedCandidateSpec {
        self.selected.spec()
    }

    /// Read only after fresh CURRENT and full-manifest provenance validation.
    /// Any failure closes this reader until an explicit eligible predecessor
    /// reload. A newer withdrawal frontier remains remembered even on failure.
    pub fn with_owner<R>(
        &mut self,
        owner: &LearningArtifactOwnerService,
        now: u64,
        consume: impl FnOnce(&T) -> R,
    ) -> Result<R, OwnerTypedCandidateErrorV5<Infallible>> {
        let current = owner.current_registry_view(now).map_err(|error| {
            self.selected.unavailable = true;
            OwnerTypedCandidateErrorV5::Owner(error)
        })?;
        if let Err(error) = self.observe(owner, &current) {
            self.selected.unavailable = true;
            return Err(error);
        }
        if self.selected.unavailable {
            return Err(OwnerTypedCandidateErrorV5::Typed(
                TypedCandidateErrorV5::Current(PinnedCandidateLoadError::Unavailable),
            ));
        }
        let context = OwnerCandidateContextV5 {
            owner,
            manifest: &self.manifest,
            now,
        };
        if let Err(error) = check_manifest(&context, &self.spec().manifest) {
            self.selected.unavailable = true;
            return Err(error);
        }
        self.selected
            .with_current(current, consume)
            .map_err(|error| {
                OwnerTypedCandidateErrorV5::Typed(TypedCandidateErrorV5::Current(error))
            })
    }

    /// Restore only the selected artifact's eligible immutable predecessor.
    /// Source withdrawals and registry history must both extend every previously
    /// observed view, including views that made the old cache unusable.
    pub fn rollback_to_predecessor<E>(
        &mut self,
        snapshot: File,
        payload: File,
        selection: VerifiedArtifactSelectionV1,
        context: OwnerCandidateContextV5<'_>,
        decode: impl FnOnce(&[u8], &ArtifactManifest) -> Result<T, E>,
    ) -> Result<(), OwnerTypedCandidateErrorV5<E>> {
        let current = context
            .owner
            .current_registry_view(context.now)
            .map_err(OwnerTypedCandidateErrorV5::Owner)?;
        self.observe(context.owner, &current)?;
        if self.spec().manifest.predecessor_id.as_ref() != Some(selection.artifact_id())
            || self.manifest.rollback_predecessor.as_ref() != Some(selection.artifact_id())
        {
            return Err(OwnerTypedCandidateErrorV5::Typed(
                TypedCandidateErrorV5::RollbackTarget,
            ));
        }
        let replacement = Self::load(
            snapshot,
            payload,
            selection,
            context,
            self.selected.compatibility,
            decode,
        )?;
        if replacement.spec().manifest.objective_digest != self.spec().manifest.objective_digest {
            return Err(OwnerTypedCandidateErrorV5::ManifestBinding);
        }
        *self = replacement;
        Ok(())
    }

    fn observe<E>(
        &mut self,
        owner: &LearningArtifactOwnerService,
        current: &VerifiedCurrentRegistryViewV1,
    ) -> Result<(), OwnerTypedCandidateErrorV5<E>> {
        let registry_result = self.selected.observe_frontier(current);
        let next = owner.withdrawal_registry().snapshot();
        let withdrawal_matches = next.scope_digest() == self.withdrawals.scope_digest()
            && next.records().len() >= self.withdrawals.records().len()
            && next.records().get(..self.withdrawals.records().len())
                == Some(self.withdrawals.records());
        // Preserve each independently valid observation even if the other
        // frontier fails; a mixed stale/current view must not erase knowledge.
        if withdrawal_matches {
            self.withdrawals = next;
        }
        registry_result.map_err(|error| {
            OwnerTypedCandidateErrorV5::Typed(TypedCandidateErrorV5::Current(error))
        })?;
        if !withdrawal_matches {
            return Err(OwnerTypedCandidateErrorV5::WithdrawalFrontier);
        }
        Ok(())
    }
}

fn check_manifest<E>(
    context: &OwnerCandidateContextV5<'_>,
    compact: &ArtifactManifest,
) -> Result<(), OwnerTypedCandidateErrorV5<E>> {
    let admission = admit_manifest_at_withdrawal_head_v3(
        context.owner.withdrawal_registry(),
        context.owner.withdrawal_registry().head_digest(),
        context.manifest.clone(),
        context.now,
    )
    .map_err(OwnerTypedCandidateErrorV5::Admission)?;
    let full = &admission.validated_manifest.manifest;
    let expected = ArtifactManifest {
        artifact_id: full.artifact_id.clone(),
        kind: full.kind,
        generation: full.generation,
        predecessor_id: if full.predecessor_ids.len() == 1 {
            full.predecessor_ids.first().cloned()
        } else {
            None
        },
        content_digest: full.bytes_digest,
        objective_digest: full.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: full.producer_id.clone(),
        compatibility_digest: full.compatibility_digest,
        encoded_size_bytes: full.encoded_size_bytes,
    };
    if &expected != compact {
        return Err(OwnerTypedCandidateErrorV5::ManifestBinding);
    }
    Ok(())
}

#[derive(Debug)]
pub enum OwnerTypedCandidateErrorV5<E> {
    Owner(LearningArtifactOwnerServiceError),
    Typed(TypedCandidateErrorV5<E>),
    Admission(ArtifactAdmissionError),
    ManifestBinding,
    WithdrawalFrontier,
}

impl<E: std::fmt::Debug> std::fmt::Display for OwnerTypedCandidateErrorV5<E> {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl<E: std::error::Error + 'static> std::error::Error for OwnerTypedCandidateErrorV5<E> {}
