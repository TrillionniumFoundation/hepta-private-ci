//! Volatile mirrors of actual original issue results, never an authority log.
use super::*;
use std::collections::VecDeque;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

const MAX_ENTRIES: usize = 16;
const MAX_BYTES: usize = 64 * 1024;
const MAX_ENTRY_BYTES: usize = 8 * 1024;

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum RootIssuedNotesGrantSelection {
    Latest {},
    Exact { grant_id: String },
}

/// An original signed artifact, not proof of delivery, effect or fresh use.
#[derive(Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum RootIssuedNotesGrantObservation {
    Captured {
        selection_scope: &'static str,
        signed_grant_json: String,
        signed_grant_sha256: Sha256Digest,
        observation_attempt: u64,
        delivery_observed: bool,
        effect_observed: bool,
    },
    Unknown {
        reason: &'static str,
    },
}

struct Entry {
    attempt: u64,
    grant_id: Box<str>,
    raw: Box<str>,
}

struct State {
    entries: VecDeque<Entry>,
    bytes: usize,
}

pub(super) struct OriginalNotesGrantObservations {
    attempts: AtomicU64,
    overflowed: AtomicBool,
    state: Mutex<State>,
}

impl OriginalNotesGrantObservations {
    fn new() -> Self {
        Self {
            attempts: AtomicU64::new(0),
            overflowed: AtomicBool::new(false),
            state: Mutex::new(State {
                entries: VecDeque::with_capacity(MAX_ENTRIES),
                bytes: 0,
            }),
        }
    }

    /// Only called with the SAME actual returned SignedGrant. The original
    /// issue result is never blocked, changed, retried or replaced on failure.
    pub(super) fn record(&self, signed: &SignedFinalUseGrant) {
        let previous = self.attempts.fetch_add(1, Ordering::AcqRel);
        if previous == u64::MAX {
            self.overflowed.store(true, Ordering::Release);
            return;
        }
        let Ok(mut state) = self.state.try_lock() else {
            return;
        };
        let Ok(raw) = serde_json::to_string(signed) else {
            return;
        };
        let cost = raw.len().saturating_add(signed.grant.grant_id.len());
        let fixed =
            std::mem::size_of::<Self>() + state.entries.capacity() * std::mem::size_of::<Entry>();
        if raw.len() > MAX_ENTRY_BYTES || fixed.saturating_add(cost) > MAX_BYTES {
            return;
        }
        while state.entries.len() >= MAX_ENTRIES || fixed + state.bytes + cost > MAX_BYTES {
            let Some(old) = state.entries.pop_front() else {
                return;
            };
            state.bytes -= old.raw.len() + old.grant_id.len();
        }
        state.bytes += cost;
        state.entries.push_back(Entry {
            attempt: previous + 1,
            grant_id: signed.grant.grant_id.clone().into_boxed_str(),
            raw: raw.into_boxed_str(),
        });
    }

    fn observe(
        &self,
        selection: &RootIssuedNotesGrantSelection,
    ) -> RootIssuedNotesGrantObservation {
        let unknown = |reason| RootIssuedNotesGrantObservation::Unknown { reason };
        if self.overflowed.load(Ordering::Acquire) {
            return unknown("observation_counter_exhausted");
        }
        let Ok(state) = self.state.try_lock() else {
            return unknown("observation_busy");
        };
        let selected = match selection {
            RootIssuedNotesGrantSelection::Latest {} => state.entries.back(),
            RootIssuedNotesGrantSelection::Exact { grant_id } => state
                .entries
                .iter()
                .find(|entry| entry.grant_id.as_ref() == grant_id.as_str()),
        };
        let Some(entry) = selected else {
            return unknown("not_observed_or_not_retained");
        };
        let attempts = self.attempts.load(Ordering::Acquire);
        if matches!(selection, RootIssuedNotesGrantSelection::Latest {})
            && entry.attempt != attempts
        {
            return unknown("latest_original_issue_observation_was_lost");
        }
        RootIssuedNotesGrantObservation::Captured {
            selection_scope: "volatile_original_notes_issue_artifact",
            signed_grant_json: entry.raw.to_string(),
            signed_grant_sha256: Sha256Digest::for_bytes(entry.raw.as_bytes()),
            observation_attempt: entry.attempt,
            delivery_observed: false,
            effect_observed: false,
        }
    }
}

impl RootNotesGrantAdmission {
    pub(crate) fn enable_original_issued_observations(
        &mut self,
        issuer: &DeploymentFinalUseIssuer,
    ) -> io::Result<()> {
        // SAFETY: these scalar observations do not borrow process memory.
        if unsafe { libc::getuid() } != 0
            || unsafe { libc::geteuid() } != 0
            || self.observations.is_some()
        {
            return Err(denied(
                "one original Root notes observation episode required",
            ));
        }
        self.writer.with_live(&self.registry.verifier(), |_| {
            if issuer.retained_writer_authorization(&self.writer)? != self.proof {
                return Err(denied("original notes observation issuer/writer changed"));
            }
            Ok(())
        })?;
        self.observations = Some(OriginalNotesGrantObservations::new());
        Ok(())
    }

    pub(crate) fn observe_original_issued_grant(
        &self,
        selection: &RootIssuedNotesGrantSelection,
    ) -> RootIssuedNotesGrantObservation {
        match &self.observations {
            Some(observed) => observed.observe(selection),
            None => RootIssuedNotesGrantObservation::Unknown {
                reason: "original_observation_not_enabled",
            },
        }
    }
}

#[cfg(test)]
#[path = "deployment_notes_observation_tests.rs"]
mod tests;
