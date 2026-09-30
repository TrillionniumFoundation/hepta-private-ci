//! Bounded, non-waiting FIFO admission with terminal and shutdown reserves.
//!
//! The gate serializes admission with shutdown, not journal execution. A full
//! mailbox rejects a command before the owner sees it. Shutdown seals all
//! clones and places its barrier after every accepted command, including when
//! every data slot is occupied. Terminal transitions have their own bounded
//! admission quota, but never overtake earlier commands. No producer task waits
//! in an unbounded queue. Queue/apply timings are observations, not durability proofs.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Serialize;
use tokio::sync::mpsc;

use crate::actor_latency::LatencyWindow;
pub use crate::actor_latency::NativeLatencySummary;

pub const DEFAULT_QUEUE_CAPACITY: usize = 256;
const MAX_QUEUE_CAPACITY: usize = 65_536;
pub const DEFAULT_TERMINAL_CAPACITY: usize = 64;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum AdmissionClass {
    Ordinary,
    Terminal,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SendError {
    Full,
    Closed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeWriterQueueMetrics {
    pub capacity: usize,
    pub depth: usize,
    pub ordinary_capacity: usize,
    pub ordinary_depth: usize,
    pub terminal_capacity: usize,
    pub terminal_depth: usize,
    pub rejected_terminal_full: u64,
    pub ordinary_queue_wait: NativeLatencySummary,
    pub terminal_queue_wait: NativeLatencySummary,
    pub ordinary_apply: NativeLatencySummary,
    pub terminal_apply: NativeLatencySummary,
    pub active_millis: u64,
    pub successful_replies_lost: u64,
    pub high_water: usize,
    pub rejected_full: u64,
    pub accepting: bool,
    pub oldest_queued_millis: u64,
    pub last_enqueue_unix_ms: Option<u64>,
}

struct State {
    capacity: usize,
    terminal_capacity: usize,
    ordinary_depth: usize,
    terminal_depth: usize,
    rejected_terminal_full: u64,
    enqueued: VecDeque<(Instant, AdmissionClass)>,
    queue_wait: [LatencyWindow; 2],
    apply: [LatencyWindow; 2],
    active: Option<(Instant, AdmissionClass)>,
    successful_replies_lost: u64,
    high_water: usize,
    rejected_full: u64,
    accepting: bool,
    last_enqueue_unix_ms: Option<u64>,
}

struct Envelope<T> {
    command: T,
    class: Option<AdmissionClass>,
}

pub(crate) struct Sender<T> {
    inner: mpsc::Sender<Envelope<T>>,
    state: Arc<Mutex<State>>,
}

impl<T> Clone for Sender<T> {
    fn clone(&self) -> Self {
        Self {
            inner: self.inner.clone(),
            state: Arc::clone(&self.state),
        }
    }
}

pub(crate) struct Receiver<T> {
    inner: mpsc::Receiver<Envelope<T>>,
    state: Arc<Mutex<State>>,
}

#[cfg(test)]
pub(crate) fn channel<T>(capacity: usize) -> Option<(Sender<T>, Receiver<T>)> {
    channel_with_terminal_capacity(capacity, DEFAULT_TERMINAL_CAPACITY.min(capacity))
}

pub(crate) fn channel_with_terminal_capacity<T>(
    capacity: usize,
    terminal_capacity: usize,
) -> Option<(Sender<T>, Receiver<T>)> {
    let total = capacity.checked_add(terminal_capacity)?;
    if capacity == 0 || terminal_capacity == 0 || total > MAX_QUEUE_CAPACITY {
        return None;
    }
    // One additional slot belongs exclusively to the shutdown barrier.
    let (sender, receiver) = mpsc::channel(total + 1);
    let state = Arc::new(Mutex::new(State {
        capacity,
        terminal_capacity,
        ordinary_depth: 0,
        terminal_depth: 0,
        rejected_terminal_full: 0,
        enqueued: VecDeque::new(),
        queue_wait: Default::default(),
        apply: Default::default(),
        active: None,
        successful_replies_lost: 0,
        high_water: 0,
        rejected_full: 0,
        accepting: true,
        last_enqueue_unix_ms: None,
    }));
    Some((
        Sender {
            inner: sender,
            state: Arc::clone(&state),
        },
        Receiver {
            inner: receiver,
            state,
        },
    ))
}

impl<T> Sender<T> {
    pub(crate) fn send(&self, command: T) -> Result<(), SendError> {
        self.send_class(command, AdmissionClass::Ordinary)
    }

    pub(crate) fn send_terminal(&self, command: T) -> Result<(), SendError> {
        self.send_class(command, AdmissionClass::Terminal)
    }

    fn send_class(&self, command: T, class: AdmissionClass) -> Result<(), SendError> {
        let mut state = self.state.lock().map_err(|_| SendError::Closed)?;
        if !state.accepting || self.inner.is_closed() {
            return Err(SendError::Closed);
        }
        let full = match class {
            AdmissionClass::Ordinary => state.ordinary_depth >= state.capacity,
            AdmissionClass::Terminal => state.terminal_depth >= state.terminal_capacity,
        };
        if full {
            state.rejected_full = state.rejected_full.saturating_add(1);
            if class == AdmissionClass::Terminal {
                state.rejected_terminal_full = state.rejected_terminal_full.saturating_add(1);
            }
            return Err(SendError::Full);
        }
        let enqueued = Instant::now();
        self.inner
            .try_send(Envelope {
                command,
                class: Some(class),
            })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => SendError::Full,
                mpsc::error::TrySendError::Closed(_) => SendError::Closed,
            })?;
        state.enqueued.push_back((enqueued, class));
        match class {
            AdmissionClass::Ordinary => state.ordinary_depth += 1,
            AdmissionClass::Terminal => state.terminal_depth += 1,
        }
        state.high_water = state.high_water.max(state.enqueued.len());
        state.last_enqueue_unix_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .ok()
            .and_then(|value| u64::try_from(value.as_millis()).ok());
        Ok(())
    }

    pub(crate) fn seal_and_send(&self, command: T) -> Result<(), SendError> {
        let mut state = self.state.lock().map_err(|_| SendError::Closed)?;
        if !state.accepting {
            return Err(SendError::Closed);
        }
        state.accepting = false;
        self.inner
            .try_send(Envelope {
                command,
                class: None,
            })
            .map_err(|_| SendError::Closed)
    }

    pub(crate) fn metrics(&self) -> Result<NativeWriterQueueMetrics, SendError> {
        let state = self.state.lock().map_err(|_| SendError::Closed)?;
        let queue_wait = state.queue_wait.clone();
        let apply = state.apply.clone();
        let mut metrics = NativeWriterQueueMetrics {
            capacity: state.capacity + state.terminal_capacity,
            ordinary_capacity: state.capacity,
            ordinary_depth: state.ordinary_depth,
            terminal_capacity: state.terminal_capacity,
            terminal_depth: state.terminal_depth,
            rejected_terminal_full: state.rejected_terminal_full,
            ordinary_queue_wait: Default::default(),
            terminal_queue_wait: Default::default(),
            ordinary_apply: Default::default(),
            terminal_apply: Default::default(),
            active_millis: state
                .active
                .map(|(instant, _)| {
                    u64::try_from(instant.elapsed().as_millis()).unwrap_or(u64::MAX)
                })
                .unwrap_or(0),
            successful_replies_lost: state.successful_replies_lost,
            depth: state.enqueued.len(),
            high_water: state.high_water,
            rejected_full: state.rejected_full,
            accepting: state.accepting && !self.inner.is_closed(),
            oldest_queued_millis: state
                .enqueued
                .front()
                .map(|(instant, _)| {
                    u64::try_from(instant.elapsed().as_millis()).unwrap_or(u64::MAX)
                })
                .unwrap_or(0),
            last_enqueue_unix_ms: state.last_enqueue_unix_ms,
        };
        // Sort bounded timing windows outside the admission gate.
        drop(state);
        metrics.ordinary_queue_wait = queue_wait[0].summary();
        metrics.terminal_queue_wait = queue_wait[1].summary();
        metrics.ordinary_apply = apply[0].summary();
        metrics.terminal_apply = apply[1].summary();
        Ok(metrics)
    }
}

impl<T> Receiver<T> {
    pub(crate) fn blocking_recv(&mut self) -> Option<T> {
        let envelope = self.inner.blocking_recv()?;
        if let Some(class) = envelope.class {
            let mut state = self.state.lock().ok()?;
            let (enqueued, queued_class) = state.enqueued.pop_front()?;
            if queued_class != class {
                state.accepting = false;
                return None;
            }
            let index = match class {
                AdmissionClass::Ordinary => {
                    state.ordinary_depth -= 1;
                    0
                }
                AdmissionClass::Terminal => {
                    state.terminal_depth -= 1;
                    1
                }
            };
            state.queue_wait[index].observe(enqueued.elapsed());
            state.active = Some((Instant::now(), class));
        }
        Some(envelope.command)
    }

    pub(crate) fn finish_command(&self, successful_reply_lost: bool) {
        if let Ok(mut state) = self.state.lock() {
            if let Some((started, class)) = state.active.take() {
                let index = match class {
                    AdmissionClass::Ordinary => 0,
                    AdmissionClass::Terminal => 1,
                };
                state.apply[index].observe(started.elapsed());
            }
            if successful_reply_lost {
                state.successful_replies_lost = state.successful_replies_lost.saturating_add(1);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn saturation_rejects_before_delivery_and_recovers_capacity() {
        let (sender, mut receiver) = channel(2).unwrap();
        sender.send(1).unwrap();
        sender.send(2).unwrap();
        assert_eq!(sender.send(3), Err(SendError::Full));
        let metrics = sender.metrics().unwrap();
        assert_eq!(metrics.depth, 2);
        assert_eq!(metrics.high_water, 2);
        assert_eq!(metrics.rejected_full, 1);
        assert!(metrics.last_enqueue_unix_ms.is_some());
        assert_eq!(receiver.blocking_recv(), Some(1));
        sender.send(4).unwrap();
        assert_eq!(receiver.blocking_recv(), Some(2));
        assert_eq!(receiver.blocking_recv(), Some(4));
        assert_eq!(sender.metrics().unwrap().depth, 0);
    }

    #[test]
    fn shutdown_is_admitted_when_full_and_fences_every_clone() {
        let (sender, mut receiver) = channel(1).unwrap();
        let clone = sender.clone();
        sender.send(1).unwrap();
        sender.seal_and_send(9).unwrap();
        assert_eq!(clone.send(2), Err(SendError::Closed));
        assert_eq!(clone.seal_and_send(10), Err(SendError::Closed));
        assert_eq!(receiver.blocking_recv(), Some(1));
        assert_eq!(receiver.blocking_recv(), Some(9));
        assert!(!sender.metrics().unwrap().accepting);
        assert_eq!(sender.metrics().unwrap().depth, 0);
    }

    #[test]
    fn disconnected_receiver_never_looks_like_overload() {
        let (sender, receiver) = channel(1).unwrap();
        drop(receiver);
        assert_eq!(sender.send(1), Err(SendError::Closed));
        assert!(!sender.metrics().unwrap().accepting);
        assert_eq!(sender.metrics().unwrap().rejected_full, 0);
        assert!(channel::<u8>(0).is_none());
        assert!(channel::<u8>(MAX_QUEUE_CAPACITY + 1).is_none());
    }

    #[test]
    fn more_than_one_hundred_thousand_mailbox_lifecycles_remain_bounded() {
        let (sender, mut receiver) = channel(4).unwrap();
        for sequence in 0..100_001 {
            sender.send(sequence).unwrap();
            assert_eq!(receiver.blocking_recv(), Some(sequence));
        }
        let metrics = sender.metrics().unwrap();
        assert_eq!(metrics.depth, 0);
        assert_eq!(metrics.high_water, 1);
        assert_eq!(metrics.rejected_full, 0);
    }
}

#[cfg(test)]
#[path = "actor_mailbox_boundary_tests.rs"]
mod boundary_tests;
