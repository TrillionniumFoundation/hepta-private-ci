//! Executable V2 protocol specification. Nothing here grants time authority.
//!
//! Inputs, including monotonic samples and policy, are unverified. The future
//! owner acceptance path must verify signatures, live issuer/epoch, one-use
//! challenges, clock qualification, durable floors, and checkpoint publication.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum TimeSpecError {
    InvalidPolicy,
    InvalidSource,
    Arithmetic,
    ClockEpochMismatch,
    ClockRollback,
    RoundtripExceeded,
    AnchorStale,
    RequestMismatch,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct Rate {
    ticks: u64,
    milliseconds: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct UnverifiedTimePolicy {
    minimum_rate: Rate,
    maximum_rate: Rate,
    measurement_error_ticks: u64,
    issuer_uncertainty_ms: u64,
    maximum_roundtrip_ms: u64,
    maximum_anchor_age_ms: u64,
}

impl UnverifiedTimePolicy {
    fn validate(self) -> Result<(), TimeSpecError> {
        let minimum = self.minimum_rate;
        let maximum = self.maximum_rate;
        if minimum.ticks == 0
            || minimum.milliseconds == 0
            || maximum.ticks == 0
            || maximum.milliseconds == 0
            || u128::from(minimum.ticks) * u128::from(maximum.milliseconds)
                > u128::from(maximum.ticks) * u128::from(minimum.milliseconds)
            || self.maximum_roundtrip_ms == 0
            || self.maximum_anchor_age_ms == 0
        {
            return Err(TimeSpecError::InvalidPolicy);
        }
        Ok(())
    }

    fn elapsed(self, start: u64, end: u64) -> Result<(u64, u64), TimeSpecError> {
        self.validate()?;
        let delta = u128::from(end.checked_sub(start).ok_or(TimeSpecError::ClockRollback)?);
        let error = 2 * u128::from(self.measurement_error_ticks);
        // Elapsed time has a physical zero lower bound. Upper bounds never saturate.
        let lower_ticks = delta.saturating_sub(error);
        let lower = lower_ticks
            .checked_mul(u128::from(self.maximum_rate.milliseconds))
            .ok_or(TimeSpecError::Arithmetic)?
            / u128::from(self.maximum_rate.ticks);
        let upper_numerator = (delta + error)
            .checked_mul(u128::from(self.minimum_rate.milliseconds))
            .ok_or(TimeSpecError::Arithmetic)?;
        let divisor = u128::from(self.minimum_rate.ticks);
        let upper = upper_numerator / divisor + u128::from(upper_numerator % divisor != 0);
        Ok((
            u64::try_from(lower).map_err(|_| TimeSpecError::Arithmetic)?,
            u64::try_from(upper).map_err(|_| TimeSpecError::Arithmetic)?,
        ))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct UnverifiedMonotonicSample {
    epoch: Digest32,
    ticks: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
struct UnverifiedProjectedBounds {
    earliest_ms: u64,
    latest_ms: u64,
}

impl UnverifiedProjectedBounds {
    fn project(
        policy: UnverifiedTimePolicy,
        sampled_wall_ms: u64,
        sent: UnverifiedMonotonicSample,
        received: UnverifiedMonotonicSample,
        current: UnverifiedMonotonicSample,
        committed_expiry_floor_ms: u64,
    ) -> Result<Self, TimeSpecError> {
        if sent.epoch != received.epoch || sent.epoch != current.epoch {
            return Err(TimeSpecError::ClockEpochMismatch);
        }
        let (_, roundtrip_upper) = policy.elapsed(sent.ticks, received.ticks)?;
        let (_, age_upper) = policy.elapsed(sent.ticks, current.ticks)?;
        let (since_receipt_lower, _) = policy.elapsed(received.ticks, current.ticks)?;
        if roundtrip_upper > policy.maximum_roundtrip_ms {
            return Err(TimeSpecError::RoundtripExceeded);
        }
        if age_upper > policy.maximum_anchor_age_ms {
            return Err(TimeSpecError::AnchorStale);
        }
        let earliest_ms = sampled_wall_ms
            .checked_sub(policy.issuer_uncertainty_ms)
            .and_then(|value| value.checked_add(since_receipt_lower))
            .ok_or(TimeSpecError::Arithmetic)?;
        let latest_ms = sampled_wall_ms
            .checked_add(policy.issuer_uncertainty_ms)
            .and_then(|value| value.checked_add(age_upper))
            .ok_or(TimeSpecError::Arithmetic)?
            .max(committed_expiry_floor_ms);
        Ok(Self {
            earliest_ms,
            latest_ms,
        })
    }

    fn fits_window(self, not_before_ms: u64, expires_at_ms: u64) -> bool {
        self.earliest_ms >= not_before_ms && self.latest_ms < expires_at_ms
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct UnverifiedTimeChallengeV2 {
    nonce: [u8; 32],
    requester: StableId,
    owner_incarnation: Digest32,
    clock_domain: StableId,
    policy_digest: Digest32,
    issuer: StableId,
    key_epoch: Generation,
}

impl UnverifiedTimeChallengeV2 {
    fn canonical_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.authbus.current-time.challenge.v2\0".to_vec();
        bytes.extend_from_slice(&self.nonce);
        crate::push_id(&mut bytes, &self.requester);
        bytes.extend_from_slice(self.owner_incarnation.as_array());
        crate::push_id(&mut bytes, &self.clock_domain);
        bytes.extend_from_slice(self.policy_digest.as_array());
        crate::push_id(&mut bytes, &self.issuer);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        bytes
    }

    fn digest(&self) -> Digest32 {
        Digest32::of_bytes(&self.canonical_bytes())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct UnverifiedTimeResponseV2 {
    request_digest: Digest32,
    issuer: StableId,
    key_epoch: Generation,
    sampled_wall_ms: u64,
    source_revision: u64,
    source_digest: Digest32,
}

impl UnverifiedTimeResponseV2 {
    // Retains V1's nonzero source-field invariants. This is not live verification.
    fn validate_source(&self) -> Result<(), TimeSpecError> {
        if self.sampled_wall_ms == 0 || self.source_revision == 0 || self.source_digest.is_zero() {
            return Err(TimeSpecError::InvalidSource);
        }
        Ok(())
    }

    fn signing_bytes(&self) -> Vec<u8> {
        let mut bytes = b"hepta.authbus.current-time.response.v2\0".to_vec();
        bytes.extend_from_slice(self.request_digest.as_array());
        crate::push_id(&mut bytes, &self.issuer);
        bytes.extend_from_slice(&self.key_epoch.get().to_be_bytes());
        bytes.extend_from_slice(&self.sampled_wall_ms.to_be_bytes());
        bytes.extend_from_slice(&self.source_revision.to_be_bytes());
        bytes.extend_from_slice(self.source_digest.as_array());
        bytes
    }

    // Structural binding only. Success does not verify a signature or live state.
    fn matches_request(&self, request: &UnverifiedTimeChallengeV2) -> Result<(), TimeSpecError> {
        self.validate_source()?;
        if self.request_digest != request.digest()
            || self.issuer != request.issuer
            || self.key_epoch != request.key_epoch
        {
            return Err(TimeSpecError::RequestMismatch);
        }
        Ok(())
    }
}

#[path = "trusted_time_v2_tests.rs"]
mod tests;
