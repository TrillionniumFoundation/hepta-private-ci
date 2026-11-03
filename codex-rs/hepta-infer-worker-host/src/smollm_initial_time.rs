//! Authentication time retained from the original configured FinalUse owner.
//! PQ reads never substitute process wall time when that protected clock fails.

use super::initial_now_seconds;
use crate::final_use_authorizer::UnixFinalUseAuthorizer;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::LearningAuthenticationProfile;
use std::sync::Arc;

#[derive(Clone)]
pub(super) enum InitialAuthorityTime {
    ClassicalV1,
    MlDsa65V2(Arc<dyn AuthorityClock>),
}

impl InitialAuthorityTime {
    pub(super) fn from_authorizer(
        authorizer: &UnixFinalUseAuthorizer,
        selected: LearningAuthenticationProfile,
    ) -> Result<Self, String> {
        super::validate_final_use_profile(authorizer, selected)?;
        match selected {
            LearningAuthenticationProfile::ClassicalV1 => Ok(Self::ClassicalV1),
            LearningAuthenticationProfile::MlDsa65V2 => authorizer
                .protected_clock()
                .map(Self::MlDsa65V2)
                .ok_or_else(|| {
                    "PQ initial material requires its protected authority clock".to_owned()
                }),
        }
    }

    pub(super) fn now_seconds(&self) -> Result<u64, String> {
        self.now_seconds_with_legacy(&mut initial_now_seconds)
    }

    pub(super) fn now_seconds_with_legacy(
        &self,
        legacy_clock: &mut impl FnMut() -> Result<u64, String>,
    ) -> Result<u64, String> {
        match self {
            Self::ClassicalV1 => legacy_clock(),
            Self::MlDsa65V2(clock) => clock
                .now_unix_ms()
                .map(|milliseconds| milliseconds / 1_000)
                .map_err(|error| error.to_string()),
        }
    }

    pub(super) fn protected_clock(&self) -> Option<Arc<dyn AuthorityClock>> {
        match self {
            Self::ClassicalV1 => None,
            Self::MlDsa65V2(clock) => Some(Arc::clone(clock)),
        }
    }
}

#[cfg(all(test, target_os = "linux"))]
#[path = "smollm_initial_time_tests.rs"]
mod tests;
