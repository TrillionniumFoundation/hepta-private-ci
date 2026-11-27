//! Strict DATA mirror of the first Root-verified fresh publication. The cold
//! parent may observe this fact, but cannot manufacture or renew one.

use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::post_a_retained::RetainedOrdinaryQ24Fixture;
use crate::authority_host_service::generation_publication::PublicationProfile;
use crate::neuron_generation_current::types::CurrentHead;

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalAcceptedPublicationData {
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

impl OriginalAcceptedPublicationData {
    pub(super) fn require_original(
        &self,
        original: &RetainedOrdinaryQ24Fixture,
        profile: &PublicationProfile,
    ) -> anyhow::Result<()> {
        let initial = original.plan.profile.original_initial_data()?;
        let published = self
            .current
            .published
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("first accepted publication is absent"))?;
        let actual_target =
            Digest32::from_array(original.completed.generation.observation().digest()?);
        anyhow::ensure!(
            self.schema == 1
                && self.purpose == "runtime.learning.original-publication-accepted.v1"
                && self.original_profile == profile.binding
                && self.current == original.completed.current
                && self.current.current == profile.intent.target
                && self.current.prepared.is_none()
                && self.current.initial.is_none()
                && published.intent == profile.intent
                && self.verified_at_unix_ms > 0
                && self.original_work_expiry_seconds
                    == initial.request.envelope.expiry_unix_seconds
                && self.previous_observation
                    == Digest32::from_array(profile.intent.previous_observation).to_string()
                && self.target_observation == actual_target.to_string()
                && original.completed.generation.is_genesis()
                && crate::neuron_generation_current::signed_grant_digest(&published.signed)?
                    .into_array()
                    == published.signed_grant_digest
                && self.accepted_revocations.authority_epoch
                    == published.signed.grant.authority_epoch
                && !self
                    .accepted_revocations
                    .revoked_grant_ids
                    .contains(&published.signed.grant.grant_id),
            "actual first publication verification fact differs"
        );
        // Check the original fresh-time relationship. This does not validate
        // an expired grant at today's clock or authorize any cold operation.
        anyhow::ensure!(
            self.verified_at_unix_ms >= published.signed.grant.not_before_unix_ms
                && self.verified_at_unix_ms < published.signed.grant.expires_at_unix_ms
                && self.verified_at_unix_ms / 1000 < self.original_work_expiry_seconds
                && published.witness.verified_at_unix_ms <= self.verified_at_unix_ms,
            "first publication fact was not verified in its original work window"
        );
        Ok(())
    }
}
