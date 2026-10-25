use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocationReceipt;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_types::Digest32;

use super::NduAuthenticatedOwnerV1;
use super::NduOwnerError;
use super::owner_scope_digest;
use crate::NduProjectionKindV1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduProjectionReadRequestV1 {
    pub request_id: Digest32,
    pub objective_digest: Digest32,
    pub subject_digest: Digest32,
}

pub(super) struct CurrentReadTrust {
    verifier: FinalUseRevocationFeedVerifier,
    clock: Arc<dyn AuthorityClock>,
    instance: Arc<()>,
    feed: Option<(FinalUseRevocationReceipt, u64)>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct ProjectionSnapshot {
    projection: Digest32,
    scope: Digest32,
    digest: Digest32,
    selection_sequence: u64,
    journal_sequence: u64,
}

/// An authenticated observation, not authority for another read or model call.
/// Revalidation is local to this configured owner incarnation and requires its
/// current authenticated feed. It does not certify another owner's atomicity,
/// physical clock continuity, or rollback resistance of the projection volume.
#[derive(Debug)]
pub struct NduCurrentProjectionV1 {
    instance: Arc<()>,
    request: NduProjectionReadRequestV1,
    snapshot: ProjectionSnapshot,
    grant_id: String,
    authority_epoch: u64,
    not_before_unix_ms: u64,
    expires_at_unix_ms: u64,
    observed_unix_ms: u64,
}

impl NduCurrentProjectionV1 {
    pub const fn request(&self) -> &NduProjectionReadRequestV1 {
        &self.request
    }
    pub const fn projection_digest(&self) -> Digest32 {
        self.snapshot.projection
    }
    /// Stable state identity: excludes observation time and grant expiry.
    pub const fn digest(&self) -> Digest32 {
        self.snapshot.digest
    }
    pub const fn selection_sequence(&self) -> u64 {
        self.snapshot.selection_sequence
    }
    pub const fn journal_sequence(&self) -> u64 {
        self.snapshot.journal_sequence
    }
}

impl NduAuthenticatedOwnerV1 {
    /// Trusted host installation. Reinstallation invalidates existing proofs;
    /// no current read is available until a signed feed has been applied here.
    pub fn with_current_reads(
        mut self,
        verifier: FinalUseRevocationFeedVerifier,
        clock: Arc<dyn AuthorityClock>,
    ) -> Self {
        self.current_reads = Some(CurrentReadTrust {
            verifier,
            clock,
            instance: Arc::new(()),
            feed: None,
        });
        self
    }

    pub fn apply_read_revocation_update(
        &mut self,
        signed: &SignedFinalUseRevocationUpdate,
    ) -> Result<(), NduOwnerError> {
        let trust = self
            .current_reads
            .as_mut()
            .ok_or(NduOwnerError::InvalidContext(
                "current read trust unavailable",
            ))?;
        let now = trust
            .clock
            .now_unix_ms()
            .map_err(|_| FinalUseError::Unavailable)?;
        let receipt = trust
            .verifier
            .apply(&self.authority, signed, now)
            .map_err(NduOwnerError::ReadTrust)?;
        trust.feed = Some((receipt, signed.update.issued_at_unix_ms));
        Ok(())
    }

    /// Prepare the exact binding for the external issuer. This grants no read.
    pub fn current_projection_binding(
        &self,
        request: &NduProjectionReadRequestV1,
    ) -> Result<FinalUseBinding, NduOwnerError> {
        let (snapshot, _, _) = self.current_projection_snapshot(request)?;
        Ok(FinalUseBinding {
            subject_id: self.context.principal_id.to_string(),
            destination_id: self.context.owner_id.to_string(),
            request_sha256: *request.request_id.as_array(),
            scope_sha256: *snapshot.scope.as_array(),
            payload_sha256: *snapshot.digest.as_array(),
        })
    }

    /// Consume one issuer grant for this exact current observation. The proof
    /// may be revalidated repeatedly; revalidation never claims another nonce.
    pub fn read_current_projection(
        &self,
        request: &NduProjectionReadRequestV1,
        signed: &SignedFinalUseGrant,
    ) -> Result<NduCurrentProjectionV1, NduOwnerError> {
        let (snapshot, _, observed_unix_ms) = self.current_projection_snapshot(request)?;
        let binding = self.current_projection_binding(request)?;
        let token = self.authority.claim(signed, &binding)?;
        self.authority.with_verified_use(token, &binding, || ())?;
        let trust = self
            .current_reads
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "current read trust unavailable",
            ))?;
        let proof = NduCurrentProjectionV1 {
            instance: Arc::clone(&trust.instance),
            request: *request,
            snapshot,
            grant_id: signed.grant.grant_id.clone(),
            authority_epoch: signed.grant.authority_epoch,
            not_before_unix_ms: signed.grant.not_before_unix_ms,
            expires_at_unix_ms: signed.grant.expires_at_unix_ms,
            observed_unix_ms,
        };
        self.revalidate_current_projection(&proof)?;
        Ok(proof)
    }

    pub fn revalidate_current_projection(
        &self,
        proof: &NduCurrentProjectionV1,
    ) -> Result<(), NduOwnerError> {
        let trust = self
            .current_reads
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "current read trust unavailable",
            ))?;
        if !Arc::ptr_eq(&trust.instance, &proof.instance) {
            return Err(NduOwnerError::InvalidContext("current projection owner"));
        }
        let (snapshot, head, now) = self.current_projection_snapshot(&proof.request)?;
        if now < proof.observed_unix_ms || now < proof.not_before_unix_ms {
            return Err(FinalUseError::NotYetValid.into());
        }
        if now >= proof.expires_at_unix_ms {
            return Err(FinalUseError::Expired.into());
        }
        if head.authority_epoch != proof.authority_epoch {
            return Err(FinalUseError::EpochMismatch.into());
        }
        if head.revoked_grant_ids.contains(&proof.grant_id) {
            return Err(FinalUseError::Revoked.into());
        }
        if snapshot != proof.snapshot {
            return Err(NduOwnerError::InvalidContext("current projection version"));
        }
        Ok(())
    }

    fn current_projection_snapshot(
        &self,
        request: &NduProjectionReadRequestV1,
    ) -> Result<(ProjectionSnapshot, FinalUseRevocations, u64), NduOwnerError> {
        if request.request_id.is_zero()
            || request.objective_digest.is_zero()
            || request.subject_digest.is_zero()
        {
            return Err(NduOwnerError::InvalidContext("current projection request"));
        }
        let trust = self
            .current_reads
            .as_ref()
            .ok_or(NduOwnerError::InvalidContext(
                "current read trust unavailable",
            ))?;
        let (feed, issued_at) = trust.feed.as_ref().ok_or(NduOwnerError::InvalidContext(
            "authenticated revocation feed unavailable",
        ))?;
        let now = trust
            .clock
            .now_unix_ms()
            .map_err(|_| FinalUseError::Unavailable)?;
        if now < *issued_at || now >= feed.valid_until_unix_ms() {
            return Err(NduOwnerError::InvalidContext(
                "authenticated revocation feed stale",
            ));
        }
        let head = self.authority.revocation_head()?;
        if head.authority_epoch != feed.authority_epoch() || head.revision != feed.revision() {
            return Err(FinalUseError::StaleRevocationHead.into());
        }
        let projection = self
            .store
            .selected_projection_digest(request.objective_digest, request.subject_digest)?
            .ok_or(NduOwnerError::InvalidContext(
                "selected projection unavailable",
            ))?;
        let entries = self.store.entries()?;
        let last = entries
            .last()
            .ok_or(NduOwnerError::InvalidContext("projection journal empty"))?;
        let selection = entries
            .iter()
            .rev()
            .find(|entry| {
                entry.kind == NduProjectionKindV1::SelectedProjection
                    && entry.objective_digest == request.objective_digest
                    && entry.subject_digest == request.subject_digest
            })
            .ok_or(NduOwnerError::InvalidContext(
                "projection selection unavailable",
            ))?;
        let scope = owner_scope_digest(
            &self.context,
            self.production_policy_digest,
            request.objective_digest,
            request.subject_digest,
            /*mutation_tag*/ 3,
        );
        let mut bytes = b"hepta.ndu.current-projection.v1\0".to_vec();
        bytes.extend_from_slice(scope.as_array());
        bytes.extend_from_slice(projection.as_array());
        bytes.extend_from_slice(&selection.sequence.to_be_bytes());
        bytes.extend_from_slice(selection.entry_digest.as_array());
        bytes.extend_from_slice(&last.sequence.to_be_bytes());
        bytes.extend_from_slice(last.entry_digest.as_array());
        bytes.extend_from_slice(&head.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(&head.revision.to_be_bytes());
        bytes.extend_from_slice(&feed.update_sha256());
        if self.authority.revocation_head()? != head {
            return Err(FinalUseError::StaleRevocationHead.into());
        }
        let finished = trust
            .clock
            .now_unix_ms()
            .map_err(|_| FinalUseError::Unavailable)?;
        if finished < now || finished >= feed.valid_until_unix_ms() {
            return Err(NduOwnerError::InvalidContext(
                "authenticated revocation feed stale",
            ));
        }
        Ok((
            ProjectionSnapshot {
                projection,
                scope,
                digest: Digest32::of_bytes(&bytes),
                selection_sequence: selection.sequence,
                journal_sequence: last.sequence,
            },
            head,
            finished,
        ))
    }
}
