//! Bounded, non-waiting admission with a reserved shutdown barrier.
//!
//! The gate serializes admission with shutdown, not journal execution. A full
//! mailbox rejects a command before the owner sees it. Shutdown seals all
//! clones and places its barrier after every accepted command, including when
//! every data slot is occupied. No producer task waits in an unbounded queue.

use std::collections::VecDeque;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use serde::Serialize;
use tokio::sync::mpsc;

pub const DEFAULT_QUEUE_CAPACITY: usize = 256;
const MAX_QUEUE_CAPACITY: usize = 65_536;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum SendError {
    Full,
    Closed,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct NativeWriterQueueMetrics {
    pub capacity: usize,
    pub depth: usize,
    pub high_water: usize,
    pub rejected_full: u64,
    pub accepting: bool,
    pub oldest_queued_millis: u64,
    pub last_enqueue_unix_ms: Option<u64>,
}

struct State {
    capacity: usize,
    enqueued: VecDeque<Instant>,
    high_water: usize,
    rejected_full: u64,
    accepting: bool,
    last_enqueue_unix_ms: Option<u64>,
}

struct Envelope<T> {
    command: T,
    data: bool,
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

pub(crate) fn channel<T>(capacity: usize) -> Option<(Sender<T>, Receiver<T>)> {
    if !(1..=MAX_QUEUE_CAPACITY).contains(&capacity) {
        return None;
    }
    // One additional slot belongs exclusively to the shutdown barrier.
    let (sender, receiver) = mpsc::channel(capacity + 1);
    let state = Arc::new(Mutex::new(State {
        capacity,
        enqueued: VecDeque::new(),
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
        let mut state = self.state.lock().map_err(|_| SendError::Closed)?;
        if !state.accepting || self.inner.is_closed() {
            return Err(SendError::Closed);
        }
        if state.enqueued.len() >= state.capacity {
            state.rejected_full = state.rejected_full.saturating_add(1);
            return Err(SendError::Full);
        }
        self.inner
            .try_send(Envelope { command, data: true })
            .map_err(|error| match error {
                mpsc::error::TrySendError::Full(_) => SendError::Full,
                mpsc::error::TrySendError::Closed(_) => SendError::Closed,
            })?;
        state.enqueued.push_back(Instant::now());
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
                data: false,
            })
            .map_err(|_| SendError::Closed)
    }

    pub(crate) fn metrics(&self) -> Result<NativeWriterQueueMetrics, SendError> {
        let state = self.state.lock().map_err(|_| SendError::Closed)?;
        Ok(NativeWriterQueueMetrics {
            capacity: state.capacity,
            depth: state.enqueued.len(),
            high_water: state.high_water,
            rejected_full: state.rejected_full,
            accepting: state.accepting && !self.inner.is_closed(),
            oldest_queued_millis: state
                .enqueued
                .front()
                .map(|instant| u64::try_from(instant.elapsed().as_millis()).unwrap_or(u64::MAX))
                .unwrap_or(0),
            last_enqueue_unix_ms: state.last_enqueue_unix_ms,
        })
    }
}

impl<T> Receiver<T> {
    pub(crate) fn blocking_recv(&mut self) -> Option<T> {
        let envelope = self.inner.blocking_recv()?;
        if envelope.data {
            let _ = self.state.lock().ok()?.enqueued.pop_front();
        }
        Some(envelope.command)
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
