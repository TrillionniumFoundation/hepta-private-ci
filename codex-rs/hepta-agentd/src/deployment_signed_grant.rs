//! Validate an existing signed artifact against this SAME actual issuer.
//! This check issues no grant and is not an administrative permission token.
use super::*;

impl DeploymentFinalUseIssuer {
    pub(crate) fn verify_original_signed_grant(
        &self,
        signed: &SignedFinalUseGrant,
        before: Instant,
    ) -> io::Result<FinalUseRevocations> {
        require_before(before)?;
        let _guard = self
            .request_lock
            .try_lock()
            .map_err(|_| io::Error::other("issuer fenced"))?;
        let state = self.store.load(STATE_OWNER).map_err(io::Error::other)?;
        let bytes = signed.grant.signing_bytes().map_err(io::Error::other)?;
        let signature =
            ed25519_dalek::Signature::from_slice(&signed.signature).map_err(io::Error::other)?;
        self.key
            .verifying_key()
            .verify_strict(&bytes, &signature)
            .map_err(io::Error::other)?;
        let grant = &signed.grant;
        let prefix = format!("{}:{}:", state.signer_id, state.head.authority_epoch);
        let sequence = grant
            .grant_id
            .strip_prefix(&prefix)
            .and_then(|value| value.parse::<u64>().ok())
            .filter(|value| *value > 0)
            .ok_or_else(|| io::Error::other("original signed grant id mismatch"))?;
        let now = self.clock.now_unix_ms().map_err(io::Error::other)?;
        if grant.signer_id != state.signer_id
            || grant.authority_epoch != state.head.authority_epoch
            || grant.grant_id != format!("{prefix}{sequence}")
            || sequence > state.sequence
            || now < grant.not_before_unix_ms
            || now >= grant.expires_at_unix_ms
        {
            return Err(io::Error::other(
                "original signed grant issuer/epoch/sequence/time mismatch",
            ));
        }
        require_before(before)?;
        Ok(state.head)
    }
}

pub(super) fn require_before(before: Instant) -> io::Result<()> {
    if Instant::now() >= before {
        return Err(io::Error::other(
            "original issuer cumulative deadline elapsed",
        ));
    }
    Ok(())
}

#[cfg(test)]
#[path = "deployment_signed_grant_tests.rs"]
mod tests;
