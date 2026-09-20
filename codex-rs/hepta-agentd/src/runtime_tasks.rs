//! Bounded task supervision for already-admitted Agentd components.
//!
//! This is a lifecycle host, not a plugin loader or an authority issuer. The
//! composition owner supplies the future and chooses its failure domain. An
//! optional task must provide an owner-local quarantine callback; a failed
//! callback, writer error or generation fence still stops the entire host.
//! Tasks are never restarted automatically: retrying an unknown external effect
//! requires its existing durable owner and reconciliation protocol.

use std::collections::BTreeSet;
use std::collections::HashMap;
use std::collections::VecDeque;
use std::future::Future;
use std::time::Duration;

use tokio::task::Id;
use tokio::task::JoinError;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;

const MAX_TASKS: usize = 128;
const MAX_NAME_BYTES: usize = 128;
const MAX_DIAGNOSTIC_CHARS: usize = 2_048;

type Quarantine = Box<dyn FnOnce() -> Result<(), AgentdError> + Send>;

struct TaskEntry {
    name: String,
    quarantine: Option<Quarantine>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTaskFailure {
    pub name: String,
    pub diagnostic: String,
}

/// One collection supervises all host tasks, including future optional services.
///
/// Registering a future does not select a module, authenticate its executable,
/// grant effects, or perform writer handoff. Those remain composition/admission
/// responsibilities. A name is single-use within this host generation, including
/// after failure; a stopped task cannot silently resurrect through re-registration.
pub struct RuntimeTasks {
    tasks: JoinSet<Result<(), AgentdError>>,
    entries: HashMap<Id, TaskEntry>,
    admitted_names: BTreeSet<String>,
    failures: VecDeque<RuntimeTaskFailure>,
    cancellation: CancellationToken,
    shutdown_grace: Duration,
    stopped: bool,
}

impl RuntimeTasks {
    pub fn new(
        cancellation: CancellationToken,
        shutdown_grace: Duration,
    ) -> Result<Self, AgentdError> {
        if shutdown_grace.is_zero() || shutdown_grace > Duration::from_secs(30) {
            return Err(AgentdError::Invalid(
                "runtime shutdown grace must be in (0, 30s]".to_string(),
            ));
        }
        Ok(Self {
            tasks: JoinSet::new(),
            entries: HashMap::new(),
            admitted_names: BTreeSet::new(),
            failures: VecDeque::new(),
            cancellation,
            shutdown_grace,
            stopped: false,
        })
    }

    pub fn spawn_required<F>(&mut self, name: &str, future: F) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        self.spawn(name, future, None)
    }

    /// Optional means failure-isolated, not permission to ignore owner errors.
    /// The callback must quarantine the component and any owner-local dependent
    /// routes. Components with required dependents must be registered as required.
    pub fn spawn_optional<F, Q>(
        &mut self,
        name: &str,
        future: F,
        quarantine: Q,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        self.spawn(name, future, Some(Box::new(quarantine)))
    }

    fn spawn<F>(
        &mut self,
        name: &str,
        future: F,
        quarantine: Option<Quarantine>,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        if self.stopped || self.cancellation.is_cancelled() {
            return Err(AgentdError::Protocol("runtime host is stopping".to_string()));
        }
        if name.is_empty()
            || name.len() > MAX_NAME_BYTES
            || name
                .bytes()
                .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
        {
            return Err(AgentdError::Invalid("invalid runtime task name".to_string()));
        }
        if self.admitted_names.len() >= MAX_TASKS || !self.admitted_names.insert(name.to_string()) {
            return Err(AgentdError::Invalid(
                "duplicate runtime task or generation task capacity exceeded".to_string(),
            ));
        }
        let handle = self.tasks.spawn(future);
        self.entries.insert(
            handle.id(),
            TaskEntry {
                name: name.to_string(),
                quarantine,
            },
        );
        Ok(())
    }

    pub fn failures(&self) -> &VecDeque<RuntimeTaskFailure> {
        &self.failures
    }

    pub fn active_count(&self) -> usize {
        self.entries.len()
    }

    /// Wait for one task, isolate optional failures, and propagate required ones.
    /// JoinSet preserves task identity across panic and select cancellation.
    pub async fn observe_next(&mut self) -> Result<(), AgentdError> {
        let completion = self.tasks.join_next_with_id().await.ok_or_else(|| {
            AgentdError::Protocol("runtime has no remaining tasks".to_string())
        })?;
        self.observe(completion)
    }

    fn observe(
        &mut self,
        completion: Result<(Id, Result<(), AgentdError>), JoinError>,
    ) -> Result<(), AgentdError> {
        let (id, result) = match completion {
            Ok((id, result)) => (id, result),
            Err(error) => (
                error.id(),
                Err(AgentdError::Protocol(format!("runtime task failed: {error}"))),
            ),
        };
        let entry = self.entries.remove(&id).ok_or_else(|| {
            AgentdError::Protocol("runtime completion identity was not registered".to_string())
        })?;
        let error = match result {
            Ok(()) => AgentdError::Protocol(format!(
                "{} exited before agentd shutdown",
                entry.name
            )),
            Err(error) => error,
        };
        // Optional availability never suppresses a shared generation/writer fence.
        if matches!(
            error,
            AgentdError::GenerationFenced(_)
                | AgentdError::Fleet(_)
                | AgentdError::ProductionWriter(_)
        ) {
            return Err(error);
        }
        let Some(quarantine) = entry.quarantine else {
            return Err(error);
        };
        let diagnostic = error.to_string().chars().take(MAX_DIAGNOSTIC_CHARS).collect();
        if self.failures.len() == MAX_TASKS {
            self.failures.pop_front();
        }
        self.failures.push_back(RuntimeTaskFailure {
            name: entry.name.clone(),
            diagnostic,
        });
        // A panicking quarantine is a failed safety boundary, not an optional
        // task panic. Convert it to a host failure so run_until still drains.
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(quarantine)).map_err(|_| {
            AgentdError::Protocol("runtime quarantine callback panicked".to_string())
        })??;
        tracing::warn!(module = %entry.name, "optional runtime component quarantined");
        Ok(())
    }

    /// Every exit path, including shutdown-listener errors, cancels and joins.
    pub async fn run_until<S>(&mut self, shutdown: S) -> Result<(), AgentdError>
    where
        S: Future<Output = Result<(), AgentdError>>,
    {
        tokio::pin!(shutdown);
        let cancellation = self.cancellation.clone();
        let result = loop {
            tokio::select! {
                biased;
                signal = &mut shutdown => break signal,
                () = cancellation.cancelled() => break Ok(()),
                result = self.observe_next() => {
                    if let Err(error) = result {
                        break Err(error);
                    }
                }
            }
        };
        self.shutdown().await;
        result
    }

    /// Cooperative cancellation first, then abort and join all remaining tasks.
    /// Durable owners, not task completion, determine external-effect outcomes.
    pub async fn shutdown(&mut self) {
        self.stopped = true;
        self.cancellation.cancel();
        let grace = self.shutdown_grace;
        if timeout(grace, async {
            while self.tasks.join_next().await.is_some() {}
        })
        .await
        .is_err()
        {
            self.tasks.abort_all();
            while self.tasks.join_next().await.is_some() {}
        }
        self.entries.clear();
    }
}

impl Drop for RuntimeTasks {
    fn drop(&mut self) {
        // Also covers cancellation of the run_until future by an outer owner.
        self.cancellation.cancel();
        self.tasks.abort_all();
    }
}

#[cfg(test)]
#[path = "runtime_tasks_tests.rs"]
mod tests;
