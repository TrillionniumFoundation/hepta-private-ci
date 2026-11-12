//! Concurrent original metadata reads without concurrent dispatch entry.
//! Every existing entry keeps its original serial mutex. Only this opaque
//! observation guard bypasses that serial while holding the same live state
//! against mutation. It is not a verified-use token or a dispatch witness.

use super::*;
use std::ops::Deref;
use std::ops::DerefMut;
use std::sync::MutexGuard;
use std::sync::RwLockReadGuard;
use std::sync::RwLockWriteGuard;

/// Non-authorizing metadata from one actual live owner. The caller must finish
/// its bounded local read and check the returned result before publishing it.
/// This guard cannot enter an effect, sign, replace or revoke an authority.
/// Do not reenter this registry while holding it.
#[must_use = "finish the original observation before returning its metadata"]
pub struct AuthorityLeaseObservationV1<'a> {
    // Field order is deliberate: panic poisons the observation mutex before
    // releasing the state read fence. A read-only RwLock guard does not poison.
    _serial: MutexGuard<'a, ()>,
    state: RwLockReadGuard<'a, State>,
    owner: &'a Inner,
}

impl AuthorityLeaseObservationV1<'_> {
    pub fn original_store_revision(&self) -> u64 {
        self.state.store_revision
    }

    /// Final poison/failure check, without resampling or renewing a clock.
    /// The original consumer must validate its own final trusted time after
    /// all of its blocking owner reads, as it does for the dispatch path.
    pub fn finish_original_observation(self) -> Result<(), AuthorityLeaseError> {
        self.owner.require_available(&self.state)
    }
}

pub(super) struct DispatchStateGuard<'a> {
    // Preserve original entry panic poisoning before releasing shared state.
    _serial: MutexGuard<'a, ()>,
    state: RwLockReadGuard<'a, State>,
}

impl Deref for DispatchStateGuard<'_> {
    type Target = State;

    fn deref(&self) -> &Self::Target {
        &self.state
    }
}

pub(super) struct MutationStateGuard<'a> {
    // Preserve original entry panic poisoning before releasing mutable state.
    _serial: MutexGuard<'a, ()>,
    state: RwLockWriteGuard<'a, State>,
}

impl Deref for MutationStateGuard<'_> {
    type Target = State;

    fn deref(&self) -> &Self::Target {
        &self.state
    }
}

impl DerefMut for MutationStateGuard<'_> {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.state
    }
}

impl Inner {
    fn require_available(&self, state: &State) -> Result<(), AuthorityLeaseError> {
        if self.serial.is_poisoned() || self.observations.is_poisoned() || state.failed {
            return Err(AuthorityLeaseError::Unavailable);
        }
        Ok(())
    }

    pub(super) fn lock_dispatch_state(
        &self,
    ) -> Result<DispatchStateGuard<'_>, AuthorityLeaseError> {
        let serial = self
            .serial
            .lock()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        let state = self
            .state
            .read()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        self.require_available(&state)?;
        Ok(DispatchStateGuard {
            _serial: serial,
            state,
        })
    }

    pub(super) fn lock_mutation_state(
        &self,
    ) -> Result<MutationStateGuard<'_>, AuthorityLeaseError> {
        let serial = self
            .serial
            .lock()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        let state = self
            .state
            .write()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        self.require_available(&state)?;
        Ok(MutationStateGuard {
            _serial: serial,
            state,
        })
    }

    pub(super) fn try_lock_mutation_state(
        &self,
    ) -> Result<MutationStateGuard<'_>, AuthorityLeaseError> {
        let serial = self
            .serial
            .try_lock()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        let state = self
            .state
            .try_write()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        self.require_available(&state)?;
        Ok(MutationStateGuard {
            _serial: serial,
            state,
        })
    }
}

impl AuthorityLeaseVerifier {
    /// Pin the complete exact original lease for a bounded metadata read.
    /// This constructs no dispatch token, witness, replacement lease or
    /// signature. The live clock is owned by this verifier, never supplied
    /// as an untrusted timestamp. All state mutations retain the write fence.
    pub fn observe_original_lease(
        &self,
        original: &AuthorityLease,
    ) -> Result<AuthorityLeaseObservationV1<'_>, AuthorityLeaseError> {
        original.validate()?;
        let serial = self
            .0
            .observations
            .lock()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        let state = self
            .0
            .state
            .read()
            .map_err(|_| AuthorityLeaseError::Unavailable)?;
        // Construct before any fallible clock callback so panic poisoning is
        // visible before this original state fence can be released.
        let observation = AuthorityLeaseObservationV1 {
            _serial: serial,
            state,
            owner: &self.0,
        };
        observation.owner.require_available(&observation.state)?;
        let now_unix_ms = self.0.clock.now_unix_ms().map_err(map_trust_error)?;
        validate_live(
            original,
            &observation.state,
            original.revision,
            &original.binding,
            now_unix_ms,
        )?;
        Ok(observation)
    }
}

#[cfg(all(test, unix))]
#[path = "authority_lease_observation_tests.rs"]
mod tests;
