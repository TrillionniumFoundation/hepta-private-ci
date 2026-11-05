//! Shared PQ trust composition for ordinary external-effect owners.
//! External key custody and rollback-independent service deployment still need
//! separate qualification; local configuration never bootstraps their state.

use std::collections::BTreeSet;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::FinalUseAuthenticationProfile;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocationFeedVerifier;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::PqAuthorityTrustKey;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::VerifiedUseToken;
use codex_hepta_contracts::authority_trust_unix::UnixPqAuthorityClock;
use codex_hepta_contracts::authority_trust_unix::UnixPqFinalUseFrontier;
use codex_hepta_contracts::authority_trust_unix::UnixPqTrustEndpointConfig;
use codex_hepta_contracts::pq_auth::PqNativeVerifier;
use serde::Deserialize;
use sha2::Digest;
use sha2::Sha256;

const MAX_FEED_BYTES: u64 = 4 * 1024 * 1024;

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct PqFinalUseConfig {
    pub(crate) signer_id: String,
    pub(crate) issuer_keys: Vec<PqAuthorityTrustKey>,
    pub(crate) head: FinalUseRevocations,
    pub(crate) revocation_distributor_id: String,
    pub(crate) revocation_keys: Vec<PqAuthorityTrustKey>,
    pub(crate) signed_revocations_file: PathBuf,
    pub(crate) external_clock: UnixPqTrustEndpointConfig,
    pub(crate) external_frontier: UnixPqTrustEndpointConfig,
}

impl PqFinalUseConfig {
    pub(crate) fn open(
        self,
        owner: &Path,
        additional_roles: &[&PqAuthorityTrustKey],
    ) -> anyhow::Result<(FinalUseAuthority, PqFinalUseGate)> {
        self.validate_roles_and_paths(owner, additional_roles)?;
        let clock = Arc::new(UnixPqAuthorityClock::new(self.external_clock)?);
        let frontier = Arc::new(UnixPqFinalUseFrontier::new(self.external_frontier)?);
        let feed = FinalUseRevocationFeedVerifier::new_pq_with_keys(
            self.revocation_distributor_id,
            self.revocation_keys,
        )?;
        clock.now_unix_ms()?;
        frontier.load(&self.signer_id)?;
        let authority_epoch = self.head.authority_epoch;
        let authority = FinalUseAuthority::open_pq_state_dir_with_issuer_keys(
            owner,
            self.signer_id,
            self.issuer_keys,
            self.head,
            clock.clone(),
            frontier,
        )?;
        Ok((
            authority,
            PqFinalUseGate {
                clock,
                feed,
                authority_epoch,
            },
        ))
    }

    fn validate_roles_and_paths(
        &self,
        owner: &Path,
        additional_roles: &[&PqAuthorityTrustKey],
    ) -> anyhow::Result<()> {
        anyhow::ensure!(
            (1..=8).contains(&self.issuer_keys.len())
                && (1..=8).contains(&self.revocation_keys.len()),
            "PQ effect requires one to eight keys per authority ring"
        );
        let mut keys = BTreeSet::new();
        for (spki, pin) in self
            .issuer_keys
            .iter()
            .chain(&self.revocation_keys)
            .chain(additional_roles.iter().copied())
            .map(|key| (key.public_key_spki.as_slice(), key.public_key_id))
            .chain([
                (
                    self.external_clock.public_key_spki.as_slice(),
                    self.external_clock.public_key_id,
                ),
                (
                    self.external_frontier.public_key_spki.as_slice(),
                    self.external_frontier.public_key_id,
                ),
            ])
        {
            let key = PqNativeVerifier::from_pinned_spki(spki, pin)?;
            anyhow::ensure!(
                keys.insert(*key.public_spki()),
                "PQ effect authority roles must have distinct public keys"
            );
        }
        let parent = owner
            .parent()
            .ok_or_else(|| anyhow::anyhow!("authority parent missing"))?
            .canonicalize()?;
        let name = owner
            .file_name()
            .ok_or_else(|| anyhow::anyhow!("authority name missing"))?;
        anyhow::ensure!(
            owner.is_absolute() && parent.join(name).as_os_str() == owner.as_os_str(),
            "PQ effect authority directory contains an alias"
        );
        match std::fs::symlink_metadata(owner) {
            Ok(metadata) => anyhow::ensure!(
                metadata.is_dir() && owner.canonicalize()?.as_os_str() == owner.as_os_str(),
                "PQ effect authority directory contains an alias"
            ),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let clock = &self.external_clock.socket_path;
        let frontier = &self.external_frontier.socket_path;
        for path in [clock, frontier] {
            anyhow::ensure!(
                path.is_absolute()
                    && path.canonicalize()?.as_os_str() == path.as_os_str()
                    && !path.starts_with(owner),
                "PQ effect requires canonical external trust services"
            );
        }
        anyhow::ensure!(
            clock != frontier,
            "PQ effect clock and frontier must be distinct services"
        );
        anyhow::ensure!(
            self.signed_revocations_file.is_absolute(),
            "PQ signed revocation file must be absolute"
        );
        Ok(())
    }
}

pub(crate) struct PqFinalUseGate {
    clock: Arc<dyn AuthorityClock>,
    feed: FinalUseRevocationFeedVerifier,
    authority_epoch: u64,
}

impl PqFinalUseGate {
    pub(crate) fn authenticate(
        &self,
        authority: &FinalUseAuthority,
        path: &Path,
        grant: &SignedFinalUseGrant,
    ) -> anyhow::Result<PqDispatchLease> {
        let bytes = crate::protected_file::read(path, MAX_FEED_BYTES)?;
        let signed: SignedFinalUseRevocationUpdate = serde_json::from_slice(&bytes)?;
        let now = self.clock.now_unix_ms()?;
        let receipt = self
            .feed
            .apply_or_confirm_current(authority, &signed, now)?;
        anyhow::ensure!(
            grant.grant.schema_version == 2
                && grant.grant.authority_epoch == receipt.authority_epoch()
                && receipt.authority_epoch() == self.authority_epoch
                && grant.grant.expires_at_unix_ms <= receipt.valid_until_unix_ms(),
            "PQ effect grant, authority and authenticated feed disagree"
        );
        Ok(PqDispatchLease {
            authority: authority.clone(),
            clock: Arc::clone(&self.clock),
            head: signed.update.head,
            valid_until_unix_ms: grant.grant.expires_at_unix_ms,
        })
    }
}

/// Only an authenticated feed can create this exact-head lease.
#[derive(Clone)]
pub(crate) struct PqDispatchLease {
    authority: FinalUseAuthority,
    clock: Arc<dyn AuthorityClock>,
    head: FinalUseRevocations,
    valid_until_unix_ms: u64,
}

impl PqDispatchLease {
    /// For the async active-effect fence, which does not retain the owner mutex.
    pub(crate) fn check(&self) -> Result<(), FinalUseError> {
        if self.authority.authentication_profile() != FinalUseAuthenticationProfile::MlDsa65V2
            || self.authority.revocation_head()? != self.head
        {
            return Err(FinalUseError::StaleRevocationHead);
        }
        check_clock(&self.clock, self.valid_until_unix_ms)
    }

    /// Bind the authenticated head to a real, single-use claim. The subsequent
    /// dispatch_final_use checks current == claimed under its owner mutex;
    /// LockedDispatchLease must only be checked inside that token's callback.
    pub(crate) fn check_claim(
        self,
        token: &VerifiedUseToken,
    ) -> Result<LockedDispatchLease, FinalUseError> {
        let mut canonical = b"hepta.kernel.authority.revocation-head.v1\0".to_vec();
        canonical.extend(serde_json::to_vec(&self.head).map_err(|_| FinalUseError::InvalidTrust)?);
        let digest: [u8; 32] = Sha256::digest(&canonical).into();
        if self.authority.authentication_profile() != FinalUseAuthenticationProfile::MlDsa65V2
            || token.claimed_revocation_head_sha256() != digest
        {
            return Err(FinalUseError::StaleRevocationHead);
        }
        Ok(LockedDispatchLease {
            clock: self.clock,
            valid_until_unix_ms: self.valid_until_unix_ms,
        })
    }
}

pub(crate) struct LockedDispatchLease {
    clock: Arc<dyn AuthorityClock>,
    valid_until_unix_ms: u64,
}

impl LockedDispatchLease {
    /// The owner mutex is already held here. Never re-enter it to read a head.
    pub(crate) fn check(&self) -> Result<(), FinalUseError> {
        check_clock(&self.clock, self.valid_until_unix_ms)
    }
}

fn check_clock(
    clock: &Arc<dyn AuthorityClock>,
    valid_until_unix_ms: u64,
) -> Result<(), FinalUseError> {
    let now = clock
        .now_unix_ms()
        .map_err(|_| FinalUseError::Unavailable)?;
    if now >= valid_until_unix_ms {
        return Err(FinalUseError::Expired);
    }
    Ok(())
}
