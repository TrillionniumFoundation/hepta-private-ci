//! Concurrent final-use revalidation for immutable loaded candidates.
//!
//! Registry frontier mutation is serialized briefly, but immutable candidate
//! bytes are consumed after the frontier lock is released. Valid concurrent
//! reads therefore do not take exclusive ownership of the candidate. Any bad
//! frontier, revocation, panic, or explicit host close permanently fails closed
//! until a newly admitted candidate is loaded.

use std::fmt;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;

use crate::LoadedPinnedCandidate;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::RegistrySnapshotReceipt;
use crate::VerifiedCurrentRegistryViewV1;

pub struct ConcurrentRevalidatingCandidate {
    candidate: LoadedPinnedCandidate,
    frontier: Mutex<RegistrySnapshotReceipt>,
    unavailable: AtomicBool,
}

impl ConcurrentRevalidatingCandidate {
    #[must_use]
    pub fn new(candidate: LoadedPinnedCandidate) -> Self {
        let frontier = candidate.spec().registry_receipt;
        Self {
            candidate,
            frontier: Mutex::new(frontier),
            unavailable: AtomicBool::new(false),
        }
    }

    #[must_use]
    pub fn spec(&self) -> &PinnedCandidateSpec {
        self.candidate.spec()
    }

    #[must_use]
    pub fn is_available(&self) -> bool {
        !self.unavailable.load(Ordering::Acquire)
    }

    pub fn current_receipt(&self) -> Result<RegistrySnapshotReceipt, PinnedCandidateLoadError> {
        self.frontier
            .lock()
            .map(|frontier| *frontier)
            .map_err(|_| {
                self.close();
                PinnedCandidateLoadError::Unavailable
            })
    }

    pub fn close(&self) {
        self.unavailable.store(true, Ordering::Release);
    }

    pub fn with_current<T>(
        &self,
        current: VerifiedCurrentRegistryViewV1,
        consume: impl FnOnce(&[u8]) -> T,
    ) -> Result<T, PinnedCandidateLoadError> {
        if self.unavailable.load(Ordering::Acquire) {
            return Err(PinnedCandidateLoadError::Unavailable);
        }
        let current_receipt = current.receipt();
        {
            let mut previous = self.frontier.lock().map_err(|_| {
                self.close();
                PinnedCandidateLoadError::Unavailable
            })?;
            if self.unavailable.load(Ordering::Acquire) {
                return Err(PinnedCandidateLoadError::Unavailable);
            }
            if current_receipt.binding != previous.binding
                || current_receipt.records < previous.records
                || previous.records == 0
                || current
                    .registry()
                    .records()
                    .get(previous.records - 1)
                    .map(|record| record.chain_digest)
                    != Some(previous.head_digest)
            {
                self.close();
                return Err(PinnedCandidateLoadError::FrontierMismatch);
            }
            let selected = &self.candidate.spec().manifest;
            if current.registry().manifest(&selected.artifact_id) != Some(selected) {
                self.close();
                return Err(PinnedCandidateLoadError::PinMismatch);
            }
            if !current.registry().is_eligible(&selected.artifact_id) {
                self.close();
                return Err(PinnedCandidateLoadError::Ineligible);
            }
            *previous = current_receipt;
        }

        struct PanicClose<'a> {
            candidate: &'a ConcurrentRevalidatingCandidate,
            armed: bool,
        }
        impl Drop for PanicClose<'_> {
            fn drop(&mut self) {
                if self.armed {
                    self.candidate.close();
                }
            }
        }
        let mut guard = PanicClose {
            candidate: self,
            armed: true,
        };
        let result = consume(self.candidate.bytes());
        guard.armed = false;
        Ok(result)
    }
}

impl fmt::Debug for ConcurrentRevalidatingCandidate {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ConcurrentRevalidatingCandidate")
            .field("candidate", &self.candidate)
            .field("frontier", &self.current_receipt().ok())
            .field("available", &self.is_available())
            .finish()
    }
}
