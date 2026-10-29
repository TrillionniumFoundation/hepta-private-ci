//! One immutable authority clock for both CURRENT and material validity.
use super::CurrentCognitiveRegistry;
use super::current_unix_micros;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::LearningAuthenticationProfile;
use std::sync::Arc;

pub(super) struct RankerAuthorityTime {
    profile: LearningAuthenticationProfile,
    clock: Option<Arc<dyn AuthorityClock>>,
}

#[cfg(test)]
#[path = "cognitive_ranker_time_tests.rs"]
mod tests;

impl RankerAuthorityTime {
    pub(super) fn new(
        profile: LearningAuthenticationProfile,
        current: &dyn CurrentCognitiveRegistry,
    ) -> Result<Self, String> {
        let clock = match profile {
            LearningAuthenticationProfile::ClassicalV1 => None,
            LearningAuthenticationProfile::MlDsa65V2 => Some(
                current
                    .authority_clock()
                    .ok_or("PQ ranker requires the CURRENT owner's protected clock")?,
            ),
        };
        Ok(Self { profile, clock })
    }

    pub(super) const fn profile(&self) -> LearningAuthenticationProfile {
        self.profile
    }

    pub(super) fn now_unix_micros(&self) -> Result<u64, String> {
        match &self.clock {
            Some(clock) => clock
                .now_unix_ms()
                .map_err(|error| error.to_string())?
                .checked_mul(1_000)
                .ok_or_else(|| "ranker authority time overflow".to_owned()),
            None => current_unix_micros(),
        }
    }

    pub(super) fn validate_source_window(
        &self,
        window: Option<(u64, u64)>,
        now: u64,
    ) -> Result<(), String> {
        if window.is_some_and(|(created_at, expires_at)| {
            now < created_at || self.profile.expired_at(now, expires_at)
        }) {
            return Err("published ranker source validity ended".to_owned());
        }
        Ok(())
    }
}
