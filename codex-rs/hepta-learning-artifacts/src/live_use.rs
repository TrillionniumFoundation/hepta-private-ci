//! Withdrawal- and authority-bound final-use views for cached artifact consumers.
//!
//! A registry view alone proves only the authenticated artifact history backing a
//! signed CURRENT head. This module additionally binds the current withdrawal
//! frontier, authority epoch, head generation, expiry, and verification time.
//! Long-lived consumers must obtain a fresh [`CurrentArtifactUseViewV1`] before
//! every use. Any withdrawal-frontier advance closes the cached session and
//! requires explicit reload through the normal admission/selection path.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::DatasetWithdrawalRegistry;
use crate::LoadedPinnedCandidate;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RegistryHeadRequirementV1;
use crate::RevalidatingCandidate;
use crate::SignedCurrentArtifactHeadV1;
use crate::VerifiedCurrentRegistryViewV1;
use crate::validate_registry_head_witness;

/// Exact final-use authority context issued from an already authenticated
/// CURRENT registry view.
///
/// External callers cannot fabricate the embedded registry view. Binding the
/// signed head again here is safe because the witness digest inside that opaque
/// view was created only after signature verification by the artifact owner.
#[derive(Debug)]
pub struct CurrentArtifactUseViewV1 {
    current: VerifiedCurrentRegistryViewV1,
    withdrawal_scope_digest: Digest32,
    withdrawal_head_digest: Digest32,
    withdrawal_epoch: u64,
    current_head_epoch: u64,
    current_head_generation: Generation,
    current_head_digest: Digest32,
    authority_expires_at: u64,
    verified_at: u64,
}

impl CurrentArtifactUseViewV1 {
    /// Bind a verified registry view to the exact signed CURRENT witness and an
    /// independently authenticated withdrawal frontier.
    pub fn bind(
        current: VerifiedCurrentRegistryViewV1,
        signed_head: &SignedCurrentArtifactHeadV1,
        requirement: &RegistryHeadRequirementV1,
        withdrawal_registry: &DatasetWithdrawalRegistry,
        verified_at: u64,
    ) -> Result<Self, CurrentArtifactUseErrorV1> {
        if requirement.now != verified_at
            || verified_at < signed_head.witness.issued_at
            || verified_at > signed_head.witness.expires_at
            || current.receipt().binding != signed_head.binding
            || current.receipt().head_digest != signed_head.witness.head_digest
        {
            return Err(CurrentArtifactUseErrorV1::CurrentHeadMismatch);
        }
        let witness = validate_registry_head_witness(&signed_head.witness, requirement)
            .map_err(|_| CurrentArtifactUseErrorV1::CurrentHeadMismatch)?;
        if witness.witness_digest != current.witness_digest() {
            return Err(CurrentArtifactUseErrorV1::CurrentHeadMismatch);
        }
        let withdrawal_scope_digest = withdrawal_registry
            .scope_digest()
            .ok_or(CurrentArtifactUseErrorV1::WithdrawalScopeMismatch)?;
        if withdrawal_scope_digest != signed_head.withdrawal_scope_digest {
            return Err(CurrentArtifactUseErrorV1::WithdrawalScopeMismatch);
        }
        let withdrawal_epoch = u64::try_from(withdrawal_registry.snapshot().records().len())
            .map_err(|_| CurrentArtifactUseErrorV1::Capacity)?;
        Ok(Self {
            current,
            withdrawal_scope_digest,
            withdrawal_head_digest: withdrawal_registry.head_digest(),
            withdrawal_epoch,
            current_head_epoch: signed_head.witness.authority_epoch,
            current_head_generation: signed_head.witness.generation,
            current_head_digest: signed_head.witness.head_digest,
            authority_expires_at: signed_head.witness.expires_at,
            verified_at,
        })
    }

    #[must_use]
    pub const fn withdrawal_scope_digest(&self) -> Digest32 {
        self.withdrawal_scope_digest
    }

    #[must_use]
    pub const fn withdrawal_head_digest(&self) -> Digest32 {
        self.withdrawal_head_digest
    }

    #[must_use]
    pub const fn withdrawal_epoch(&self) -> u64 {
        self.withdrawal_epoch
    }

    #[must_use]
    pub const fn current_head_epoch(&self) -> u64 {
        self.current_head_epoch
    }

    #[must_use]
    pub const fn current_head_generation(&self) -> Generation {
        self.current_head_generation
    }

    #[must_use]
    pub const fn current_head_digest(&self) -> Digest32 {
        self.current_head_digest
    }

    #[must_use]
    pub const fn authority_expires_at(&self) -> u64 {
        self.authority_expires_at
    }

    #[must_use]
    pub const fn verified_at(&self) -> u64 {
        self.verified_at
    }

    fn into_registry_view(self) -> VerifiedCurrentRegistryViewV1 {
        self.current
    }
}

/// Long-lived cached candidate that fails closed on every withdrawal-frontier
/// change, authority expiry, time regression, registry rollback, or head fork.
///
/// This type supplies no selection or release authority. A withdrawal advance
/// may be unrelated to the cached candidate; the conservative response is still
/// explicit reload so the complete V3 admission can be recomputed.
#[derive(Debug)]
pub struct WithdrawalAwareCandidateSessionV1 {
    candidate: RevalidatingCandidate,
    withdrawal_scope_digest: Digest32,
    withdrawal_head_digest: Digest32,
    withdrawal_epoch: u64,
    current_head_epoch: u64,
    current_head_generation: Generation,
    current_head_digest: Digest32,
    authority_expires_at: u64,
    last_revalidation_at: u64,
    unavailable: bool,
}

impl WithdrawalAwareCandidateSessionV1 {
    pub fn new(
        candidate: LoadedPinnedCandidate,
        initial: CurrentArtifactUseViewV1,
    ) -> Result<Self, CurrentArtifactUseErrorV1> {
        let mut guarded = RevalidatingCandidate::new(candidate);
        let withdrawal_scope_digest = initial.withdrawal_scope_digest;
        let withdrawal_head_digest = initial.withdrawal_head_digest;
        let withdrawal_epoch = initial.withdrawal_epoch;
        let current_head_epoch = initial.current_head_epoch;
        let current_head_generation = initial.current_head_generation;
        let current_head_digest = initial.current_head_digest;
        let authority_expires_at = initial.authority_expires_at;
        let last_revalidation_at = initial.verified_at;
        if last_revalidation_at > authority_expires_at {
            return Err(CurrentArtifactUseErrorV1::AuthorityExpired);
        }
        guarded
            .with_current(initial.into_registry_view(), |_| ())
            .map_err(CurrentArtifactUseErrorV1::Candidate)?;
        Ok(Self {
            candidate: guarded,
            withdrawal_scope_digest,
            withdrawal_head_digest,
            withdrawal_epoch,
            current_head_epoch,
            current_head_generation,
            current_head_digest,
            authority_expires_at,
            last_revalidation_at,
            unavailable: false,
        })
    }

    #[must_use]
    pub const fn spec(&self) -> &PinnedCandidateSpec {
        self.candidate.spec()
    }

    #[must_use]
    pub const fn withdrawal_head_digest(&self) -> Digest32 {
        self.withdrawal_head_digest
    }

    #[must_use]
    pub const fn last_revalidation_at(&self) -> u64 {
        self.last_revalidation_at
    }

    #[must_use]
    pub const fn authority_expires_at(&self) -> u64 {
        self.authority_expires_at
    }

    #[must_use]
    pub const fn is_unavailable(&self) -> bool {
        self.unavailable
    }

    pub fn with_current<T>(
        &mut self,
        current: CurrentArtifactUseViewV1,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, CurrentArtifactUseErrorV1> {
        if self.unavailable {
            return Err(CurrentArtifactUseErrorV1::Unavailable);
        }
        // Stay closed on validation errors and panics. Only a completed use
        // reopens the session for another independently verified view.
        self.unavailable = true;
        if current.verified_at < self.last_revalidation_at {
            return Err(CurrentArtifactUseErrorV1::TimeRegression);
        }
        if current.verified_at > current.authority_expires_at {
            return Err(CurrentArtifactUseErrorV1::AuthorityExpired);
        }
        if current.withdrawal_scope_digest != self.withdrawal_scope_digest {
            return Err(CurrentArtifactUseErrorV1::WithdrawalScopeMismatch);
        }
        if current.withdrawal_head_digest != self.withdrawal_head_digest
            || current.withdrawal_epoch != self.withdrawal_epoch
        {
            return Err(CurrentArtifactUseErrorV1::WithdrawalFrontierChanged);
        }
        if current.current_head_generation < self.current_head_generation
            || current.current_head_epoch < self.current_head_epoch
            || (current.current_head_generation == self.current_head_generation
                && current.current_head_digest != self.current_head_digest)
        {
            return Err(CurrentArtifactUseErrorV1::CurrentHeadRollbackOrFork);
        }
        let verified_at = current.verified_at;
        let authority_expires_at = current.authority_expires_at;
        let current_head_epoch = current.current_head_epoch;
        let current_head_generation = current.current_head_generation;
        let current_head_digest = current.current_head_digest;
        let result = self
            .candidate
            .with_current(current.into_registry_view(), consume)
            .map_err(CurrentArtifactUseErrorV1::Candidate)?;
        self.current_head_epoch = current_head_epoch;
        self.current_head_generation = current_head_generation;
        self.current_head_digest = current_head_digest;
        self.authority_expires_at = authority_expires_at;
        self.last_revalidation_at = verified_at;
        self.unavailable = false;
        Ok(result)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CurrentArtifactUseErrorV1 {
    CurrentHeadMismatch,
    WithdrawalScopeMismatch,
    WithdrawalFrontierChanged,
    CurrentHeadRollbackOrFork,
    AuthorityExpired,
    TimeRegression,
    Capacity,
    Unavailable,
    Candidate(PinnedCandidateLoadError),
}

impl fmt::Display for CurrentArtifactUseErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CurrentArtifactUseErrorV1 {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Candidate(error) => Some(error),
            Self::CurrentHeadMismatch
            | Self::WithdrawalScopeMismatch
            | Self::WithdrawalFrontierChanged
            | Self::CurrentHeadRollbackOrFork
            | Self::AuthorityExpired
            | Self::TimeRegression
            | Self::Capacity
            | Self::Unavailable => None,
        }
    }
}
