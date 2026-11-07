use super::Endpoint;
use super::PqTrustOperationV2;
use super::PqTrustOutcomeV2;
use super::UnixPqTrustEndpointConfig;
use super::identifier;
use crate::AuthorityFrontierStore;
use crate::AuthorityTrustError;
use crate::ReleaseFrontierV1;

/// Actual external release-journal adapter with a distinct operation namespace.
///
/// A missing external value permits only an explicit initialization to generation
/// one; the owner must never treat it as permission to bootstrap an existing
/// journal again. Failed CAS responses do not prove that no external write took
/// place. The owner must retain the proposal and fence uncertain updates.
pub struct UnixPqReleaseFrontier {
    endpoint: Endpoint,
}

impl UnixPqReleaseFrontier {
    pub fn new(config: UnixPqTrustEndpointConfig) -> Result<Self, AuthorityTrustError> {
        Ok(Self {
            endpoint: Endpoint::new(config)?,
        })
    }
}

impl AuthorityFrontierStore<Option<ReleaseFrontierV1>> for UnixPqReleaseFrontier {
    fn load(&self, owner_id: &str) -> Result<Option<ReleaseFrontierV1>, AuthorityTrustError> {
        match self
            .endpoint
            .exchange(PqTrustOperationV2::ReleaseFrontierLoad {
                owner_id: owner_id.to_string(),
            })? {
            PqTrustOutcomeV2::ReleaseFrontier { value } => {
                if let Some(frontier) = &value {
                    frontier.validate()?;
                }
                Ok(value)
            }
            _ => Err(AuthorityTrustError::Invalid),
        }
    }

    fn compare_and_set(
        &self,
        owner_id: &str,
        expected: &Option<ReleaseFrontierV1>,
        next: &Option<ReleaseFrontierV1>,
    ) -> Result<(), AuthorityTrustError> {
        let next = next.ok_or(AuthorityTrustError::Invalid)?;
        match self
            .endpoint
            .exchange(PqTrustOperationV2::ReleaseFrontierCompareAndSet {
                owner_id: owner_id.to_string(),
                expected: *expected,
                next,
            })? {
            PqTrustOutcomeV2::ReleaseCompareAndSetApplied { value } if value == next => Ok(()),
            _ => Err(AuthorityTrustError::Invalid),
        }
    }
}

pub(super) fn valid_owner(owner_id: &str) -> bool {
    identifier(owner_id)
        && owner_id
            .strip_prefix("hepta.fleet.release.")
            .is_some_and(|suffix| !suffix.is_empty())
}

pub(super) fn valid_transition(
    expected: Option<&ReleaseFrontierV1>,
    next: &ReleaseFrontierV1,
) -> bool {
    if next.validate().is_err() {
        return false;
    }
    match expected {
        None => next.generation == 1,
        Some(previous) => {
            previous.validate().is_ok()
                && previous.initial_root_sha256 == next.initial_root_sha256
                && previous.generation.checked_add(1) == Some(next.generation)
        }
    }
}
