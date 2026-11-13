//! Admission only: one original Initial frame waits and executes under its
//! original absolute deadline. The existing data mutex retains poison/consume
//! semantics; the unit token never represents Root authority.

use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Instant;

use crossbeam_channel::Receiver;
use crossbeam_channel::Sender;

use super::Lane;
use super::RootGenerationInitialClient;
use super::initial_error_class;
use super::initial_failure;
use super::uncertain;
use crate::AgentdError;

struct AdmissionDomain {
    waiting: &'static str,
    locking: &'static str,
    deadline: &'static str,
    returning: &'static str,
}

const WIRE: AdmissionDomain = AdmissionDomain {
    waiting: "lane_admission",
    locking: "lane_try_lock",
    deadline: "lane_deadline",
    returning: "lane_return",
};
const ARTIFACT: AdmissionDomain = AdmissionDomain {
    waiting: "artifact_admission",
    locking: "artifact_try_lock",
    deadline: "artifact_deadline",
    returning: "artifact_return",
};

pub(super) struct InitialLaneAdmission {
    available: Receiver<()>,
    returned: Sender<()>,
    domain: AdmissionDomain,
}

struct Permit<'a> {
    admission: &'a InitialLaneAdmission,
    fenced: &'a AtomicBool,
    returned: bool,
}

pub(super) struct Held<'a, T> {
    // Fields drop in declaration order, including during unwinding: release
    // the original data mutex before making the admission token available.
    pub(super) data: MutexGuard<'a, T>,
    permit: Permit<'a>,
    pub(super) end: Instant,
}

impl InitialLaneAdmission {
    pub(super) fn new() -> Result<Self, AgentdError> {
        Self::with_domain(WIRE)
    }

    pub(super) fn for_artifact() -> Result<Self, AgentdError> {
        Self::with_domain(ARTIFACT)
    }

    fn with_domain(domain: AdmissionDomain) -> Result<Self, AgentdError> {
        let (returned, available) = crossbeam_channel::bounded(/*cap*/ 1);
        returned.try_send(()).map_err(|_| uncertain())?;
        Ok(Self {
            available,
            returned,
            domain,
        })
    }

    pub(super) fn acquire<'a, T>(
        &'a self,
        data: &'a Mutex<T>,
        fenced: &'a AtomicBool,
        end: Instant,
    ) -> Result<Held<'a, T>, AgentdError> {
        require_admission_open(fenced, end, self.domain.deadline)?;
        self.available.recv_deadline(end).map_err(|error| {
            refuse(
                fenced,
                self.domain.waiting,
                match error {
                    crossbeam_channel::RecvTimeoutError::Timeout => "Deadline",
                    crossbeam_channel::RecvTimeoutError::Disconnected => "Disconnected",
                },
            )
        })?;
        let permit = Permit {
            admission: self,
            fenced,
            returned: false,
        };
        // recv_deadline may take an immediately available token even after
        // its deadline; neither that fast path nor a queued wakeup may send.
        require_admission_open(fenced, end, self.domain.deadline)?;
        let held = data.try_lock().map_err(|error| {
            refuse(
                fenced,
                self.domain.locking,
                match error {
                    std::sync::TryLockError::WouldBlock => "WouldBlock",
                    std::sync::TryLockError::Poisoned(_) => "Poisoned",
                },
            )
        })?;
        require_admission_open(fenced, end, self.domain.deadline)?;
        Ok(Held {
            data: held,
            permit,
            end,
        })
    }
}

impl InitialLaneAdmission {
    /// Keep the entire Artifact observation serialized. This bounds admission
    /// and successful return; synchronous I/O retains its own original bounds.
    pub(super) fn with_original_action<T, R>(
        &self,
        data: &Mutex<T>,
        fenced: &AtomicBool,
        end: Instant,
        mut require_current: impl FnMut(&T) -> Result<(), AgentdError>,
        action: impl FnOnce(&T) -> Result<R, AgentdError>,
    ) -> Result<R, AgentdError> {
        let held = self.acquire(data, fenced, end)?;
        if let Err(error) = require_current(&held.data) {
            fenced.store(true, Ordering::Release);
            return Err(error);
        }
        held.require_open()?;
        let result = action(&held.data);
        // Failed work still receives the original postcheck and token return.
        let post = require_current(&held.data);
        if post.is_err() {
            fenced.store(true, Ordering::Release);
        }
        let open = held.require_open();
        let released = held.release();
        post?;
        open?;
        released?;
        result
    }
}

impl<T> Held<'_, T> {
    pub(super) fn require_open(&self) -> Result<(), AgentdError> {
        require_admission_open(
            self.permit.fenced,
            self.end,
            self.permit.admission.domain.deadline,
        )
    }

    pub(super) fn require_deadline(&self) -> Result<(), AgentdError> {
        if Instant::now() >= self.end {
            return Err(refuse(
                self.permit.fenced,
                self.permit.admission.domain.deadline,
                "Deadline",
            ));
        }
        Ok(())
    }

    pub(super) fn release(self) -> Result<(), AgentdError> {
        let Self {
            data, mut permit, ..
        } = self;
        drop(data);
        permit.return_token()
    }
}

impl Permit<'_> {
    fn return_token(&mut self) -> Result<(), AgentdError> {
        self.returned = true;
        self.admission
            .returned
            .try_send(())
            .map_err(|_| refuse(self.fenced, self.admission.domain.returning, "TokenState"))
    }
}

impl Drop for Permit<'_> {
    fn drop(&mut self) {
        if !self.returned {
            let _ = self.return_token();
        }
    }
}

fn require_admission_open(
    fenced: &AtomicBool,
    end: Instant,
    deadline_phase: &'static str,
) -> Result<(), AgentdError> {
    if fenced.load(Ordering::Acquire) {
        return Err(uncertain());
    }
    if Instant::now() >= end {
        return Err(refuse(fenced, deadline_phase, "Deadline"));
    }
    Ok(())
}

fn refuse(fenced: &AtomicBool, phase: &'static str, class: &'static str) -> AgentdError {
    fenced.store(true, Ordering::Release);
    initial_failure(phase, None, format_args!("class={class}"));
    uncertain()
}

impl RootGenerationInitialClient {
    pub(super) fn original_frame_end(&self) -> Result<Instant, AgentdError> {
        let end = Instant::now()
            .checked_add(self.frame_timeout)
            .ok_or_else(|| refuse(&self.fenced, "lane_deadline", "Overflow"))?
            .min(self.session_end);
        Ok(end)
    }

    pub(super) fn acquire_original_lane(
        &self,
        end: Instant,
    ) -> Result<Held<'_, Option<Lane>>, AgentdError> {
        let held = self.admission.acquire(&self.lane, &self.fenced, end)?;
        // Admission may have waited: revalidate the original live session
        // before taking the lane or advancing its request sequence.
        if let Err(error) = self.connection.require_original_publication_session() {
            self.fence();
            initial_failure(
                "session_after_wait",
                None,
                format_args!("class={}", initial_error_class(&error)),
            );
            return Err(uncertain());
        }
        held.require_open()?;
        Ok(held)
    }
}

#[cfg(test)]
#[path = "root_generation_initial_lane_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "root_generation_initial_artifact_admission_tests.rs"]
mod artifact_tests;
