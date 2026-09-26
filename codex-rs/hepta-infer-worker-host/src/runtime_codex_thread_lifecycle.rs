//! Process-local lifecycle accounting for App Server threads prepared by the
//! runtime.codex native caller.
//!
//! Metrics are observability only. They do not prove provider terminality,
//! authorize replay, release durable capacity or replace owner reconciliation.

use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::OnceLock;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ThreadLifecyclePhase {
    Prepared,
    EffectEntered,
    Started,
    TerminalObserved,
    Closed,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ThreadCleanupDisposition {
    Unsubscribed,
    ConnectionClosed,
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct ThreadLifecycleSnapshot {
    pub prepared: u64,
    pub effect_entered: u64,
    pub started: u64,
    pub terminal_observed: u64,
    pub cleanup_attempted: u64,
    pub unsubscribe_succeeded: u64,
    pub connection_close_succeeded: u64,
    pub cleanup_failed: u64,
    pub orphaned_pre_effect: u64,
    pub orphaned_post_effect: u64,
    pub orphaned_after_terminal: u64,
}

#[derive(Debug, Default)]
pub struct ThreadLifecycleMetrics {
    prepared: AtomicU64,
    effect_entered: AtomicU64,
    started: AtomicU64,
    terminal_observed: AtomicU64,
    cleanup_attempted: AtomicU64,
    unsubscribe_succeeded: AtomicU64,
    connection_close_succeeded: AtomicU64,
    cleanup_failed: AtomicU64,
    orphaned_pre_effect: AtomicU64,
    orphaned_post_effect: AtomicU64,
    orphaned_after_terminal: AtomicU64,
}

impl ThreadLifecycleMetrics {
    #[must_use]
    pub fn snapshot(&self) -> ThreadLifecycleSnapshot {
        ThreadLifecycleSnapshot {
            prepared: self.prepared.load(Ordering::Relaxed),
            effect_entered: self.effect_entered.load(Ordering::Relaxed),
            started: self.started.load(Ordering::Relaxed),
            terminal_observed: self.terminal_observed.load(Ordering::Relaxed),
            cleanup_attempted: self.cleanup_attempted.load(Ordering::Relaxed),
            unsubscribe_succeeded: self.unsubscribe_succeeded.load(Ordering::Relaxed),
            connection_close_succeeded: self
                .connection_close_succeeded
                .load(Ordering::Relaxed),
            cleanup_failed: self.cleanup_failed.load(Ordering::Relaxed),
            orphaned_pre_effect: self.orphaned_pre_effect.load(Ordering::Relaxed),
            orphaned_post_effect: self.orphaned_post_effect.load(Ordering::Relaxed),
            orphaned_after_terminal: self.orphaned_after_terminal.load(Ordering::Relaxed),
        }
    }
}

static GLOBAL_METRICS: OnceLock<Arc<ThreadLifecycleMetrics>> = OnceLock::new();

#[must_use]
pub fn runtime_codex_thread_lifecycle_metrics() -> Arc<ThreadLifecycleMetrics> {
    Arc::clone(GLOBAL_METRICS.get_or_init(|| Arc::new(ThreadLifecycleMetrics::default())))
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ThreadLifecycleError {
    InvalidIdentity(&'static str),
    InvalidConnection,
    InvalidTransition {
        from: ThreadLifecyclePhase,
        operation: &'static str,
    },
    TurnMismatch,
    CleanupAlreadyAttempted,
}

impl fmt::Display for ThreadLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ThreadLifecycleError {}

pub struct PreparedThreadGuard {
    thread_id: String,
    session_id: String,
    connection_id: u64,
    turn_id: Option<String>,
    phase: ThreadLifecyclePhase,
    cleanup_attempted: bool,
    cleanup_failure_recorded: bool,
    metrics: Arc<ThreadLifecycleMetrics>,
}

impl fmt::Debug for PreparedThreadGuard {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedThreadGuard")
            .field("thread_id", &self.thread_id)
            .field("session_id", &self.session_id)
            .field("connection_id", &self.connection_id)
            .field("turn_id", &self.turn_id)
            .field("phase", &self.phase)
            .field("cleanup_attempted", &self.cleanup_attempted)
            .finish_non_exhaustive()
    }
}

impl PreparedThreadGuard {
    pub fn new(
        thread_id: String,
        session_id: String,
        connection_id: u64,
        metrics: Arc<ThreadLifecycleMetrics>,
    ) -> Result<Self, ThreadLifecycleError> {
        validate_identity(&thread_id, "thread")?;
        validate_identity(&session_id, "session")?;
        if connection_id == 0 {
            return Err(ThreadLifecycleError::InvalidConnection);
        }
        metrics.prepared.fetch_add(1, Ordering::Relaxed);
        Ok(Self {
            thread_id,
            session_id,
            connection_id,
            turn_id: None,
            phase: ThreadLifecyclePhase::Prepared,
            cleanup_attempted: false,
            cleanup_failure_recorded: false,
            metrics,
        })
    }

    #[must_use]
    pub fn thread_id(&self) -> &str {
        &self.thread_id
    }

    #[must_use]
    pub fn session_id(&self) -> &str {
        &self.session_id
    }

    #[must_use]
    pub fn connection_id(&self) -> u64 {
        self.connection_id
    }

    #[must_use]
    pub fn phase(&self) -> ThreadLifecyclePhase {
        self.phase
    }

    pub fn mark_effect_entered(&mut self) -> Result<(), ThreadLifecycleError> {
        self.require_phase(ThreadLifecyclePhase::Prepared, "enter_effect")?;
        self.phase = ThreadLifecyclePhase::EffectEntered;
        self.metrics.effect_entered.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    pub fn mark_started(&mut self, turn_id: &str) -> Result<(), ThreadLifecycleError> {
        self.require_phase(ThreadLifecyclePhase::EffectEntered, "mark_started")?;
        validate_identity(turn_id, "turn")?;
        self.turn_id = Some(turn_id.to_string());
        self.phase = ThreadLifecyclePhase::Started;
        self.metrics.started.fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    pub fn mark_terminal_observed(&mut self, turn_id: &str) -> Result<(), ThreadLifecycleError> {
        if !matches!(
            self.phase,
            ThreadLifecyclePhase::EffectEntered | ThreadLifecyclePhase::Started
        ) {
            return Err(ThreadLifecycleError::InvalidTransition {
                from: self.phase,
                operation: "mark_terminal_observed",
            });
        }
        validate_identity(turn_id, "turn")?;
        if let Some(expected) = self.turn_id.as_deref()
            && expected != turn_id
        {
            return Err(ThreadLifecycleError::TurnMismatch);
        }
        self.turn_id = Some(turn_id.to_string());
        self.phase = ThreadLifecyclePhase::TerminalObserved;
        self.metrics
            .terminal_observed
            .fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    pub fn begin_cleanup(&mut self) -> Result<(), ThreadLifecycleError> {
        if self.cleanup_attempted {
            return Err(ThreadLifecycleError::CleanupAlreadyAttempted);
        }
        if self.phase == ThreadLifecyclePhase::Closed {
            return Err(ThreadLifecycleError::InvalidTransition {
                from: self.phase,
                operation: "begin_cleanup",
            });
        }
        self.cleanup_attempted = true;
        self.metrics
            .cleanup_attempted
            .fetch_add(1, Ordering::Relaxed);
        Ok(())
    }

    pub fn complete_cleanup(
        &mut self,
        disposition: ThreadCleanupDisposition,
    ) -> Result<(), ThreadLifecycleError> {
        if !self.cleanup_attempted || self.phase == ThreadLifecyclePhase::Closed {
            return Err(ThreadLifecycleError::InvalidTransition {
                from: self.phase,
                operation: "complete_cleanup",
            });
        }
        match disposition {
            ThreadCleanupDisposition::Unsubscribed => {
                self.metrics
                    .unsubscribe_succeeded
                    .fetch_add(1, Ordering::Relaxed);
            }
            ThreadCleanupDisposition::ConnectionClosed => {
                self.metrics
                    .connection_close_succeeded
                    .fetch_add(1, Ordering::Relaxed);
            }
        }
        self.phase = ThreadLifecyclePhase::Closed;
        Ok(())
    }

    pub fn record_cleanup_failure(&mut self) -> Result<(), ThreadLifecycleError> {
        if !self.cleanup_attempted || self.phase == ThreadLifecyclePhase::Closed {
            return Err(ThreadLifecycleError::InvalidTransition {
                from: self.phase,
                operation: "record_cleanup_failure",
            });
        }
        if !self.cleanup_failure_recorded {
            self.metrics.cleanup_failed.fetch_add(1, Ordering::Relaxed);
            self.cleanup_failure_recorded = true;
        }
        Ok(())
    }

    fn require_phase(
        &self,
        expected: ThreadLifecyclePhase,
        operation: &'static str,
    ) -> Result<(), ThreadLifecycleError> {
        if self.phase == expected {
            Ok(())
        } else {
            Err(ThreadLifecycleError::InvalidTransition {
                from: self.phase,
                operation,
            })
        }
    }
}

impl Drop for PreparedThreadGuard {
    fn drop(&mut self) {
        if self.phase == ThreadLifecyclePhase::Closed {
            return;
        }
        if !self.cleanup_failure_recorded {
            self.metrics.cleanup_failed.fetch_add(1, Ordering::Relaxed);
        }
        match self.phase {
            ThreadLifecyclePhase::Prepared => {
                self.metrics
                    .orphaned_pre_effect
                    .fetch_add(1, Ordering::Relaxed);
            }
            ThreadLifecyclePhase::EffectEntered | ThreadLifecyclePhase::Started => {
                self.metrics
                    .orphaned_post_effect
                    .fetch_add(1, Ordering::Relaxed);
            }
            ThreadLifecyclePhase::TerminalObserved => {
                self.metrics
                    .orphaned_after_terminal
                    .fetch_add(1, Ordering::Relaxed);
            }
            ThreadLifecyclePhase::Closed => {}
        }
    }
}

fn validate_identity(value: &str, field: &'static str) -> Result<(), ThreadLifecycleError> {
    if value.is_empty()
        || value.len() > 128
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        Err(ThreadLifecycleError::InvalidIdentity(field))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn metrics() -> Arc<ThreadLifecycleMetrics> {
        Arc::new(ThreadLifecycleMetrics::default())
    }

    fn guard(metrics: Arc<ThreadLifecycleMetrics>) -> PreparedThreadGuard {
        PreparedThreadGuard::new(
            "thread:one".to_string(),
            "session:one".to_string(),
            7,
            metrics,
        )
        .unwrap()
    }

    #[test]
    fn explicit_unsubscribe_closes_without_orphan() {
        let metrics = metrics();
        {
            let mut guard = guard(Arc::clone(&metrics));
            guard.mark_effect_entered().unwrap();
            guard.mark_started("turn:one").unwrap();
            guard.mark_terminal_observed("turn:one").unwrap();
            guard.begin_cleanup().unwrap();
            guard
                .complete_cleanup(ThreadCleanupDisposition::Unsubscribed)
                .unwrap();
        }
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.prepared, 1);
        assert_eq!(snapshot.effect_entered, 1);
        assert_eq!(snapshot.started, 1);
        assert_eq!(snapshot.terminal_observed, 1);
        assert_eq!(snapshot.unsubscribe_succeeded, 1);
        assert_eq!(snapshot.cleanup_failed, 0);
        assert_eq!(snapshot.orphaned_pre_effect, 0);
        assert_eq!(snapshot.orphaned_post_effect, 0);
        assert_eq!(snapshot.orphaned_after_terminal, 0);
    }

    #[test]
    fn connection_shutdown_is_a_bounded_cleanup_fallback() {
        let metrics = metrics();
        {
            let mut guard = guard(Arc::clone(&metrics));
            guard.begin_cleanup().unwrap();
            guard.record_cleanup_failure().unwrap();
            guard
                .complete_cleanup(ThreadCleanupDisposition::ConnectionClosed)
                .unwrap();
        }
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.cleanup_attempted, 1);
        assert_eq!(snapshot.cleanup_failed, 1);
        assert_eq!(snapshot.connection_close_succeeded, 1);
        assert_eq!(snapshot.orphaned_pre_effect, 0);
    }

    #[test]
    fn drop_classifies_unclosed_threads_by_effect_phase() {
        let metrics = metrics();
        drop(guard(Arc::clone(&metrics)));
        {
            let mut value = guard(Arc::clone(&metrics));
            value.mark_effect_entered().unwrap();
        }
        {
            let mut value = guard(Arc::clone(&metrics));
            value.mark_effect_entered().unwrap();
            value.mark_started("turn:one").unwrap();
            value.mark_terminal_observed("turn:one").unwrap();
        }
        let snapshot = metrics.snapshot();
        assert_eq!(snapshot.cleanup_failed, 3);
        assert_eq!(snapshot.orphaned_pre_effect, 1);
        assert_eq!(snapshot.orphaned_post_effect, 1);
        assert_eq!(snapshot.orphaned_after_terminal, 1);
    }

    #[test]
    fn terminal_and_cleanup_transitions_are_exact() {
        let metrics = metrics();
        let mut value = guard(metrics);
        assert!(matches!(
            value.mark_started("turn:one"),
            Err(ThreadLifecycleError::InvalidTransition { .. })
        ));
        value.mark_effect_entered().unwrap();
        value.mark_started("turn:one").unwrap();
        assert_eq!(
            value.mark_terminal_observed("turn:other"),
            Err(ThreadLifecycleError::TurnMismatch)
        );
        value.mark_terminal_observed("turn:one").unwrap();
        value.begin_cleanup().unwrap();
        assert_eq!(
            value.begin_cleanup(),
            Err(ThreadLifecycleError::CleanupAlreadyAttempted)
        );
        value
            .complete_cleanup(ThreadCleanupDisposition::Unsubscribed)
            .unwrap();
    }
}
