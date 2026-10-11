//! Bounded task supervision for already-admitted Agentd components.
//!
//! This is a lifecycle host, not a plugin loader or an authority issuer. The
//! composition owner supplies the future and chooses its failure domain. An
//! optional task must provide an owner-local quarantine callback; a failed
//! callback, writer error or generation fence still stops the entire host.
//! Tasks are never restarted automatically: retrying an unknown external effect
//! requires its existing durable owner and reconciliation protocol.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::HashMap;
use std::collections::VecDeque;
use std::future::Future;
use std::time::Duration;

use codex_hepta_types::Generation;
use tokio::task::Id;
use tokio::task::JoinError;
use tokio::task::JoinSet;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

use crate::AgentdError;

#[path = "runtime_service_generations.rs"]
mod service_generations;

const MAX_TASKS: usize = 128;
const MAX_NAME_BYTES: usize = 128;
const MAX_DIAGNOSTIC_CHARS: usize = 2_048;

type Quarantine = Box<dyn FnOnce() -> Result<(), AgentdError> + Send>;

struct TaskEntry {
    name: String,
    quarantine: Option<Quarantine>,
    retirement: Option<(CancellationToken, Quarantine)>,
    retiring: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeTaskFailure {
    pub name: String,
    pub diagnostic: String,
}

/// One collection supervises all host tasks, including future optional services.
///
/// Registration does not select a module, authenticate its executable, grant
/// effects or perform writer handoff. Legacy names remain single-use. Versioned
/// optional services reuse one identity slot only after acknowledged retirement,
/// with a monotone generation fence that survives retirement within this host.
pub struct RuntimeTasks {
    tasks: JoinSet<Result<(), AgentdError>>,
    entries: HashMap<Id, TaskEntry>,
    admitted_names: BTreeSet<String>,
    retired_names: BTreeSet<String>,
    service_generations: BTreeMap<String, Generation>,
    failures: VecDeque<RuntimeTaskFailure>,
    cancellation: CancellationToken,
    shutdown_grace: Duration,
    stopped: bool,
    // Preserve the outcome as well as the cancellation fence. A caller may
    // observe an error while retiring a service, then delegate final cleanup to
    // run_until. That cleanup must not relabel the cancelled host as successful.
    failed: bool,
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
            retired_names: BTreeSet::new(),
            service_generations: BTreeMap::new(),
            failures: VecDeque::new(),
            cancellation,
            shutdown_grace,
            stopped: false,
            failed: false,
        })
    }

    pub fn spawn_required<F>(&mut self, name: &str, future: F) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        self.reject_versioned_name(name)?;
        self.spawn(
            name, future, /*quarantine*/ None, /*retirement*/ None,
        )
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
        self.reject_versioned_name(name)?;
        self.spawn(
            name,
            future,
            Some(Box::new(quarantine)),
            /*retirement*/ None,
        )
    }

    /// Register a cooperatively removable, already-admitted optional service.
    ///
    /// The factory runs only after admission and receives a CHILD cancellation
    /// token, so retiring this service cannot stop its siblings or the host.
    /// The service must drain its owner work before returning Ok. The retirement
    /// callback must unpublish its routes and reject unresolved effects; it is
    /// not a writer-handoff, topology-selection or external-effect receipt.
    /// Replacement remains a separately admitted generation, never a blind retry.
    pub fn spawn_optional_service<F, S, Q, R>(
        &mut self,
        name: &str,
        start: S,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
        S: FnOnce(CancellationToken) -> F + Send + 'static,
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        self.reject_versioned_name(name)?;
        self.spawn_service(name, start, quarantine, retire)
    }

    fn spawn_service<F, S, Q, R>(
        &mut self,
        name: &str,
        start: S,
        quarantine: Q,
        retire: R,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
        S: FnOnce(CancellationToken) -> F + Send + 'static,
        Q: FnOnce() -> Result<(), AgentdError> + Send + 'static,
        R: FnOnce() -> Result<(), AgentdError> + Send + 'static,
    {
        let cancellation = self.cancellation.child_token();
        let service_cancellation = cancellation.clone();
        self.spawn(
            name,
            async move { start(service_cancellation).await },
            Some(Box::new(quarantine)),
            Some((cancellation, Box::new(retire))),
        )
    }

    /// Stop a legacy optional service without cancelling its siblings.
    /// Versioned identities require retire_optional_generation instead, so an
    /// old unversioned request cannot retire the successor using the same name.
    pub async fn retire_optional(&mut self, name: &str) -> Result<(), AgentdError> {
        self.reject_versioned_name(name)?;
        self.retire_optional_inner(name).await
    }

    /// Timeout is NOT retirement success. The service remains draining and its
    /// name remains reserved until an acknowledged owner callback completes.
    async fn retire_optional_inner(&mut self, name: &str) -> Result<(), AgentdError> {
        if self.retired_names.contains(name) {
            return Ok(());
        }
        if self.stopped || self.cancellation.is_cancelled() {
            return Err(AgentdError::Protocol(
                "runtime host is stopping".to_string(),
            ));
        }
        let entry = self
            .entries
            .values_mut()
            .find(|entry| entry.name == name)
            .ok_or_else(|| AgentdError::Protocol("runtime service is not active".to_string()))?;
        let (cancellation, _) = entry.retirement.as_ref().ok_or_else(|| {
            AgentdError::Protocol("service has no optional retirement contract".to_string())
        })?;
        entry.retiring = true;
        cancellation.cancel();
        let grace = self.shutdown_grace;
        timeout(grace, async {
            while self.entries.values().any(|entry| entry.name == name) {
                // Do not lose other task completions while draining this one.
                // Shared fences and failed owner callbacks still propagate.
                self.observe_next().await?;
            }
            if self.retired_names.contains(name) {
                Ok(())
            } else {
                Err(AgentdError::Protocol(
                    "service failed or was quarantined, not retired".to_string(),
                ))
            }
        })
        .await
        .map_err(|_| {
            AgentdError::Protocol("service retirement remains unacknowledged".to_string())
        })?
    }

    fn spawn<F>(
        &mut self,
        name: &str,
        future: F,
        quarantine: Option<Quarantine>,
        retirement: Option<(CancellationToken, Quarantine)>,
    ) -> Result<(), AgentdError>
    where
        F: Future<Output = Result<(), AgentdError>> + Send + 'static,
    {
        if self.stopped || self.cancellation.is_cancelled() {
            return Err(AgentdError::Protocol(
                "runtime host is stopping".to_string(),
            ));
        }
        if name.is_empty()
            || name.len() > MAX_NAME_BYTES
            || name
                .bytes()
                .any(|byte| byte.is_ascii_control() || byte.is_ascii_whitespace())
        {
            return Err(AgentdError::Invalid(
                "invalid runtime task name".to_string(),
            ));
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
                retirement,
                retiring: false,
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
        if self.stopped {
            return Err(AgentdError::Protocol(
                "runtime host is stopping".to_string(),
            ));
        }
        let result = match self.tasks.join_next_with_id().await {
            Some(completion) => self.observe(completion),
            None => Err(AgentdError::Protocol(
                "runtime has no remaining tasks".to_string(),
            )),
        };
        if result.is_err() {
            self.failed = true;
            self.stopped = true;
            self.cancellation.cancel();
        }
        result
    }

    fn observe(
        &mut self,
        completion: Result<(Id, Result<(), AgentdError>), JoinError>,
    ) -> Result<(), AgentdError> {
        let (id, result) = match completion {
            Ok((id, result)) => (id, result),
            Err(error) => (
                error.id(),
                Err(AgentdError::Protocol(format!(
                    "runtime task failed: {error}"
                ))),
            ),
        };
        let entry = self.entries.remove(&id).ok_or_else(|| {
            AgentdError::Protocol("runtime completion identity was not registered".to_string())
        })?;
        if entry.retiring && result.is_ok() {
            let (_, retire) = entry.retirement.ok_or_else(|| {
                AgentdError::Protocol("runtime retirement contract was lost".to_string())
            })?;
            std::panic::catch_unwind(std::panic::AssertUnwindSafe(retire)).map_err(|_| {
                AgentdError::Protocol("runtime retirement callback panicked".to_string())
            })??;
            self.retired_names.insert(entry.name);
            return Ok(());
        }
        let error = match result {
            Ok(()) => {
                AgentdError::Protocol(format!("{} exited before agentd shutdown", entry.name))
            }
            Err(error) => error,
        };
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
        let diagnostic = error
            .to_string()
            .chars()
            .take(MAX_DIAGNOSTIC_CHARS)
            .collect();
        if self.failures.len() == MAX_TASKS {
            self.failures.pop_front();
        }
        self.failures.push_back(RuntimeTaskFailure {
            name: entry.name.clone(),
            diagnostic,
        });
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(quarantine)).map_err(|_| {
            AgentdError::Protocol("runtime quarantine callback panicked".to_string())
        })??;
        lifecycle_warning(&entry.name, "optional runtime component quarantined");
        Ok(())
    }

    /// Every exit path, including shutdown-listener errors, cancels and joins.
    pub async fn run_until<S>(&mut self, shutdown: S) -> Result<(), AgentdError>
    where
        S: Future<Output = Result<(), AgentdError>>,
    {
        if self.failed {
            self.shutdown().await;
            return Err(AgentdError::Protocol(
                "runtime host previously failed; cleanup cannot certify success".to_string(),
            ));
        }
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
        if result.is_err() {
            self.failed = true;
        }
        self.shutdown().await;
        if result.is_ok() && self.failed {
            return Err(AgentdError::Protocol(
                "runtime failed while draining; shutdown is not successful".to_string(),
            ));
        }
        result
    }

    /// A normal host stop is NOT module retirement. Only an explicit retirement
    /// may run its callback and publish an acknowledgement. Host-initiated aborts
    /// never acknowledge drain or external effects.
    fn observe_shutdown_completion(
        &mut self,
        completion: Result<(Id, Result<(), AgentdError>), JoinError>,
        abort_requested: bool,
    ) {
        let id = match &completion {
            Ok((id, _)) => *id,
            Err(error) => error.id(),
        };
        let Some(entry) = self.entries.get(&id) else {
            self.failed = true;
            return;
        };
        let name = entry.name.clone();
        let retiring = entry.retiring;
        let result = match completion {
            Ok((id, Ok(()))) if !retiring => {
                self.entries.remove(&id);
                Ok(())
            }
            Err(error) if abort_requested && error.is_cancelled() => {
                self.entries.remove(&id);
                if retiring {
                    // Stopping a task cannot complete an owner retirement.
                    // Keep the failure latched without calling the owner or
                    // publishing an acknowledgement for unresolved work.
                    Err(AgentdError::Protocol(
                        "service retirement aborted before owner acknowledgement".to_string(),
                    ))
                } else {
                    Ok(())
                }
            }
            completion => self.observe(completion),
        };
        if let Err(error) = result {
            self.failed = true;
            if self.failures.len() == MAX_TASKS {
                self.failures.pop_front();
            }
            lifecycle_warning(&name, "runtime owner failure retained during shutdown");
            self.failures.push_back(RuntimeTaskFailure {
                name,
                diagnostic: error
                    .to_string()
                    .chars()
                    .take(MAX_DIAGNOSTIC_CHARS)
                    .collect(),
            });
        }
    }

    /// Cooperative cancellation first, then abort and join all remaining tasks.
    /// Durable owners, not task completion, determine external-effect outcomes.
    /// Errors remain latched for run_until, including on reentry.
    pub async fn shutdown(&mut self) {
        self.stopped = true;
        self.cancellation.cancel();
        let grace = self.shutdown_grace;
        if timeout(grace, async {
            while let Some(completion) = self.tasks.join_next_with_id().await {
                self.observe_shutdown_completion(completion, /*abort_requested*/ false);
            }
        })
        .await
        .is_err()
        {
            self.tasks.abort_all();
            while let Some(completion) = self.tasks.join_next_with_id().await {
                self.observe_shutdown_completion(completion, /*abort_requested*/ true);
            }
        }
        self.entries.clear();
    }
}

fn lifecycle_warning(name: &str, message: &str) {
    use std::io::Write;
    let _ = writeln!(
        std::io::stderr().lock(),
        "hepta-agentd module={name}: {message}"
    );
}

impl Drop for RuntimeTasks {
    fn drop(&mut self) {
        self.cancellation.cancel();
        self.tasks.abort_all();
    }
}

#[cfg(test)]
#[path = "runtime_tasks_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runtime_service_retirement_tests.rs"]
mod retirement_tests;

#[cfg(test)]
#[path = "runtime_task_fence_tests.rs"]
mod failure_latch_tests;

#[cfg(test)]
#[path = "runtime_task_outcome_tests.rs"]
mod outcome_tests;
