//! A first, actually verified publication fact. It is committed only by the
//! original publication refusal arm, together with its Ready transition.
//! This historical DATA never grants a new selection, dispatch or signature.

use std::time::Instant;

use codex_hepta_contracts::FinalUseRevocations;

use super::*;

const ACCEPTANCE_PURPOSE: &str = "runtime.learning.original-publication-accepted.v1";

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct PublicationAcceptance {
    schema: u8,
    purpose: String,
    original_profile: String,
    current: CurrentHead,
    verified_at_unix_ms: u64,
    original_work_expiry_seconds: u64,
    previous_observation: String,
    target_observation: String,
    accepted_revocations: FinalUseRevocations,
}

impl PublicationAcceptance {
    pub(super) fn verified_at_unix_ms(&self) -> u64 {
        self.verified_at_unix_ms
    }

    pub(super) fn original_current(&self) -> &CurrentHead {
        &self.current
    }

    pub(super) fn original_work_expiry_seconds(&self) -> u64 {
        self.original_work_expiry_seconds
    }

    /// The only producer is the successful fresh Publish command, after its
    /// entire original Root context returned. The surrounding durable arm is
    /// still Armed; a failed final check cannot publish this fact as Ready.
    pub(super) fn observe_original_publish(
        service: &HostAuthorityService,
        slot: &RegisteredGenerationPublication,
        expected: &CurrentHead,
        end: Instant,
    ) -> io::Result<Self> {
        original_root()?;
        refusal::require_end(end)?;
        let original = slot
            .reserved
            .original_for_version(PublicationVersion::DurableV2)?;
        slot.require_profile()?;
        let published = expected
            .published
            .as_ref()
            .filter(|published| published.intent == original.intent)
            .ok_or_else(|| io::Error::other("original accepted publication missing"))?;
        if expected.current != original.intent.target
            || expected.prepared.is_some()
            || expected.initial.is_some()
            || slot
                .current
                .original_broker_head()
                .map_err(io::Error::other)?
                != *expected
        {
            return Err(io::Error::other("original accepted CURRENT differs"));
        }
        let previous = slot.previous.observe().map_err(io::Error::other)?;
        let target = slot.target.observe().map_err(io::Error::other)?;
        if !previous.is_drained()
            || previous.owner_binding() != &original.intent.previous
            || previous.observation().digest().map_err(io::Error::other)?
                != original.intent.previous_observation
            || !target.is_genesis()
            || target.owner_binding() != &original.intent.target
        {
            return Err(io::Error::other(
                "original publication Generation cut differs",
            ));
        }
        let accepted_revocations = slot.verify_retained(&published.signed, &published.witness)?;
        if service.issuer.revocations()? != accepted_revocations
            || slot.previous.observe().map_err(io::Error::other)? != previous
            || slot.target.observe().map_err(io::Error::other)? != target
            || slot
                .current
                .original_broker_head()
                .map_err(io::Error::other)?
                != *expected
        {
            return Err(io::Error::other("publication changed during acceptance"));
        }
        let verified_at_unix_ms = service
            .clock
            .refresh_projection()
            .map_err(io::Error::other)?
            .observed_unix_ms;
        slot.require_selection(verified_at_unix_ms)?;
        transport::require_fresh_window(
            verified_at_unix_ms,
            slot.decision.request.envelope.expiry_unix_seconds,
            &published.signed,
            &published.witness,
        )?;
        if slot.verify_retained(&published.signed, &published.witness)? != accepted_revocations
            || service.issuer.revocations()? != accepted_revocations
        {
            return Err(io::Error::other(
                "publication consumer changed at acceptance",
            ));
        }
        slot.require_profile()?;
        refusal::require_end(end)?;
        let accepted = Self {
            schema: 1,
            purpose: ACCEPTANCE_PURPOSE.into(),
            original_profile: original.binding.clone(),
            current: expected.clone(),
            verified_at_unix_ms,
            original_work_expiry_seconds: slot.decision.request.envelope.expiry_unix_seconds,
            previous_observation: Digest32::from_array(
                previous.observation().digest().map_err(io::Error::other)?,
            )
            .to_string(),
            target_observation: Digest32::from_array(
                target.observation().digest().map_err(io::Error::other)?,
            )
            .to_string(),
            accepted_revocations,
        };
        accepted.require_original(&slot.reserved)?;
        Ok(accepted)
    }

    pub(super) fn require_original(&self, reserved: &ReservedPublicationProfile) -> io::Result<()> {
        let original = reserved.original_for_version(PublicationVersion::DurableV2)?;
        let published = self
            .current
            .published
            .as_ref()
            .ok_or_else(|| io::Error::other("accepted publication absent"))?;
        if self.schema != 1
            || self.purpose != ACCEPTANCE_PURPOSE
            || self.original_profile != original.binding
            || self.current.current != original.intent.target
            || self.current.prepared.is_some()
            || self.current.initial.is_some()
            || published.intent != original.intent
            || self.verified_at_unix_ms == 0
            || self.previous_observation
                != Digest32::from_array(original.intent.previous_observation).to_string()
            || self
                .target_observation
                .parse::<Digest32>()
                .map_err(io::Error::other)?
                .is_zero()
            || crate::neuron_generation_current::signed_grant_digest(&published.signed)
                .map_err(io::Error::other)?
                .into_array()
                != published.signed_grant_digest
            || self.accepted_revocations.authority_epoch != published.signed.grant.authority_epoch
            || self
                .accepted_revocations
                .revoked_grant_ids
                .contains(&published.signed.grant.grant_id)
        {
            return Err(io::Error::other("original publication acceptance differs"));
        }
        transport::require_fresh_window(
            self.verified_at_unix_ms,
            self.original_work_expiry_seconds,
            &published.signed,
            &published.witness,
        )
    }
}
