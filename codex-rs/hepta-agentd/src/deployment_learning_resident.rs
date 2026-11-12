//! Verify a new, exact resident intent at the original issuer's local fence.
//! This child never issues a grant, installs a lease, signs, or adopts a model.

use std::sync::MutexGuard;

use super::*;
use crate::authority_host_service::resident::ROOT_RESIDENT_LEARNING_EXECUTE_V3;
use crate::authority_host_service::resident::ROOT_RESIDENT_LEARNING_READBACK_V3;

/// The guard is private to the bounded synchronous Root store boundary.
/// It is never returned in a public bootstrap or held across async/remote work.
pub(crate) struct OriginalResidentGrantFenceV3<'a> {
    issuer: &'a DeploymentFinalUseIssuer,
    _guard: MutexGuard<'a, ()>,
    head: FinalUseRevocations,
    signed: &'a SignedFinalUseGrant,
    before: Instant,
}

impl DeploymentFinalUseIssuer {
    pub(crate) fn hold_original_resident_intent_v3<'a>(
        &'a self,
        signed: &'a SignedFinalUseGrant,
        expected: &FinalUseBinding,
        before: Instant,
    ) -> io::Result<OriginalResidentGrantFenceV3<'a>> {
        original_grant::require_before(before)?;
        if !matches!(expected.destination_id.as_str(),
            ROOT_RESIDENT_LEARNING_EXECUTE_V3 | ROOT_RESIDENT_LEARNING_READBACK_V3)
            || signed.grant.binding != *expected
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied, "resident intent exact purpose differs",
            ));
        }
        // Lock order matches issuance: original Registry -> issuer -> Root CAS.
        // try_lock never waits for a caller holding a contrary outer lock.
        let guard = self.request_lock.try_lock()
            .map_err(|_| io::Error::other("original resident issuer busy or fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let bytes = signed.grant.signing_bytes().map_err(io::Error::other)?;
        let signature = ed25519_dalek::Signature::from_slice(&signed.signature)
            .map_err(io::Error::other)?;
        self.key.verifying_key().verify_strict(&bytes, &signature).map_err(io::Error::other)?;
        let grant = &signed.grant;
        let prefix = format!("{}:{}:", state.signer_id, state.head.authority_epoch);
        let sequence = grant.grant_id.strip_prefix(&prefix)
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .ok_or_else(|| io::Error::other("resident original grant sequence differs"))?;
        if grant.signer_id != state.signer_id
            || grant.authority_epoch != state.head.authority_epoch
            || grant.grant_id != format!("{prefix}{sequence}")
            || sequence > state.sequence
            || state.head.revoked_grant_ids.contains(&grant.grant_id)
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied, "resident original grant is not current",
            ));
        }
        let fence = OriginalResidentGrantFenceV3 {
            issuer: self, _guard: guard, head: state.head, signed, before,
        };
        fence.require_current()?;
        Ok(fence)
    }
}

impl OriginalResidentGrantFenceV3<'_> {
    pub(crate) fn require_current(&self) -> io::Result<u64> {
        original_grant::require_before(self.before)?;
        let current = self.issuer.store.load(STATE_OWNER).map_err(io::Error::other)?;
        if current.head != self.head
            || current.head.revoked_grant_ids.contains(&self.signed.grant.grant_id)
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied, "resident issuer CURRENT changed",
            ));
        }
        let now = self.issuer.clock.now_unix_ms().map_err(io::Error::other)?;
        if now < self.signed.grant.not_before_unix_ms
            || now >= self.signed.grant.expires_at_unix_ms
        {
            return Err(io::Error::new(
                io::ErrorKind::PermissionDenied, "resident original intent window elapsed",
            ));
        }
        original_grant::require_before(self.before)?;
        Ok(now)
    }
}
