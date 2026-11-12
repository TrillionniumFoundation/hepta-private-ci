//! Independent Root-owned refusal history for one initial-data scope slot.
//! Arm before opening or observing primary data; interrupted verification stays
//! ineligible after restart. This does not protect rollback of the whole Root
//! directory and never turns retained data into a learning authorization.

use std::io;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityFrontierStore;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::HostAuthorityFrontierStore;
use codex_hepta_contracts::RootAuthorityDirectory;
use codex_hepta_neuron::CellGenerationOwnerBindingV1;
use serde::Deserialize;
use serde::Serialize;

use super::original_root;

const PURPOSE: &str = "runtime.initial-data-refusal.v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
pub(super) enum RootDataKind {
    SourcePin,
    SourceHandoff,
    CellSnapshot,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum Phase {
    Ready,
    Armed,
    Refused,
}

#[derive(Clone, Debug, Eq, PartialEq, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RefusalRecord {
    schema: u8,
    purpose: String,
    kind: RootDataKind,
    target: CellGenerationOwnerBindingV1,
    attempt: u64,
    phase: Phase,
}

/// Private to the original Root stores. No peer chooses a key, binding, phase,
/// or attempt. The primary store's entire physical operation and its required
/// final postchecks must be inside the action; no same-kind action is nested.
pub(super) struct RootDataRefusalV1 {
    store: HostAuthorityFrontierStore<RefusalRecord>,
    owner: String,
    binding: RefusalRecord,
    gate: Mutex<()>,
    poisoned: AtomicBool,
}

impl RootDataRefusalV1 {
    /// Fresh registration arms durably before any primary IO. Existing-marker
    /// conflicts are distinct from primary initialization errors in the action.
    /// In particular, an old primary with no marker cannot be retrofitted.
    pub(super) fn create_fresh<T>(
        root: Arc<RootAuthorityDirectory>,
        kind: RootDataKind,
        target: &CellGenerationOwnerBindingV1,
        initialize: impl FnOnce() -> io::Result<T>,
    ) -> io::Result<(Self, T)> {
        original_root()?;
        let (owner, binding) = binding(kind, target)?;
        let mut armed = binding.clone();
        armed.attempt = 1;
        armed.phase = Phase::Armed;
        let store = HostAuthorityFrontierStore::initialize(root, owner.clone(), armed.clone())
            .map_err(|error| match error {
                AuthorityTrustError::Conflict => {
                    io::Error::new(io::ErrorKind::AlreadyExists, error)
                }
                error => io::Error::other(error),
            })?;
        let retained = Self {
            store,
            owner,
            binding,
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        };
        let value = retained.complete_armed(&armed, initialize)?;
        Ok((retained, value))
    }

    /// Open only the independent existing marker. Never initialize or finish
    /// an Armed attempt during recovery, even if primary bytes now look valid.
    pub(super) fn open_existing(
        root: Arc<RootAuthorityDirectory>,
        kind: RootDataKind,
        target: &CellGenerationOwnerBindingV1,
    ) -> io::Result<Self> {
        original_root()?;
        let (owner, binding) = binding(kind, target)?;
        let store =
            HostAuthorityFrontierStore::open(root, owner.clone()).map_err(io::Error::other)?;
        let retained = Self {
            store,
            owner,
            binding,
            gate: Mutex::new(()),
            poisoned: AtomicBool::new(false),
        };
        if retained.load_matching()?.phase != Phase::Ready {
            return Err(io::Error::other(
                "original data verification is unfinished or refused",
            ));
        }
        Ok(retained)
    }

    pub(super) fn inspect<T>(&self, action: impl FnOnce() -> io::Result<T>) -> io::Result<T> {
        original_root()?;
        let _gate = self
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original data inspection is busy"))?;
        if self.poisoned.load(Ordering::Acquire) {
            return Err(io::Error::other("original data refusal handle is poisoned"));
        }
        let before = self.load_matching()?;
        if before.phase != Phase::Ready {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original data verification is unfinished or refused",
            ));
        }
        let Some(attempt) = before.attempt.checked_add(1) else {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(
                "original data inspection sequence exhausted",
            ));
        };
        let mut armed = before.clone();
        armed.attempt = attempt;
        armed.phase = Phase::Armed;
        // This backend holds the original per-owner flock for its exact CAS.
        // The durable Armed state, not the local mutex, spans the action.
        if let Err(error) = self.store.compare_and_set(&self.owner, &before, &armed) {
            self.poisoned.store(true, Ordering::Release);
            return Err(io::Error::other(error));
        }
        self.complete_armed(&armed, action)
    }

    fn complete_armed<T>(
        &self,
        armed: &RefusalRecord,
        action: impl FnOnce() -> io::Result<T>,
    ) -> io::Result<T> {
        let result = action().and_then(|value| {
            if self.poisoned.load(Ordering::Acquire) {
                return Err(io::Error::other("original data poisoned before completion"));
            }
            let mut ready = armed.clone();
            ready.phase = Phase::Ready;
            // Compare the complete attempt: a stale handle cannot clear a
            // different arm or a concurrent refusal. Never retry this CAS.
            self.store
                .compare_and_set(&self.owner, armed, &ready)
                .map_err(io::Error::other)?;
            if self.poisoned.load(Ordering::Acquire) {
                return Err(io::Error::other("original data changed during completion"));
            }
            Ok(value)
        });
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        // An error, unwind or process exit leaves Armed; no failure handler
        // needs to decode or write the primary to preserve that refusal.
        result
    }

    /// Persist refusal independently before attempting a legacy primary fence.
    /// Failure is reported honestly if the refusal storage itself is unusable.
    pub(super) fn refuse(&self) -> io::Result<()> {
        original_root()?;
        let _gate = self
            .gate
            .try_lock()
            .map_err(|_| io::Error::other("original data refusal is busy"))?;
        self.poisoned.store(true, Ordering::Release);
        let observed = self.load_matching()?;
        if observed.phase == Phase::Refused {
            return Ok(());
        }
        let mut refused = observed.clone();
        refused.phase = Phase::Refused;
        if let Err(error) = self.store.compare_and_set(&self.owner, &observed, &refused) {
            if matches!(self.load_matching(), Ok(record) if record.phase == Phase::Refused) {
                return Ok(());
            }
            return Err(io::Error::other(error));
        }
        if self.store.load(&self.owner).map_err(io::Error::other)? != refused {
            return Err(io::Error::other(
                "original data refusal acknowledgement differs",
            ));
        }
        Ok(())
    }

    fn load_matching(&self) -> io::Result<RefusalRecord> {
        let result = (|| {
            let observed = self.store.load(&self.owner).map_err(io::Error::other)?;
            let mut same_binding = observed.clone();
            same_binding.phase = self.binding.phase;
            same_binding.attempt = self.binding.attempt;
            if observed.attempt == 0 || same_binding != self.binding {
                return Err(io::Error::other(
                    "original data refusal registration differs",
                ));
            }
            Ok(observed)
        })();
        if result.is_err() {
            self.poisoned.store(true, Ordering::Release);
        }
        result
    }
}

fn binding(
    kind: RootDataKind,
    target: &CellGenerationOwnerBindingV1,
) -> io::Result<(String, RefusalRecord)> {
    target.digest().map_err(io::Error::other)?;
    let scope = crate::neuron_generation_current::types::scope_digest(target.scope())
        .map_err(io::Error::other)?;
    let name = match kind {
        RootDataKind::SourcePin => "source-pin",
        RootDataKind::SourceHandoff => "source-handoff",
        RootDataKind::CellSnapshot => "cell-snapshot",
    };
    // Match the primary slot's scope namespace. The complete target remains
    // inside the record, so a different target cannot create another gate.
    let owner = format!("initial-data-refusal/{name}/{scope}");
    Ok((
        owner,
        RefusalRecord {
            schema: 1,
            purpose: PURPOSE.into(),
            kind,
            target: target.clone(),
            attempt: 0,
            phase: Phase::Ready,
        },
    ))
}

#[cfg(test)]
#[path = "authority_host_data_refusal_tests.rs"]
mod tests;
