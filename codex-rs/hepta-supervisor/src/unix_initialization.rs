//! Complete post-acquisition setup without ever turning an owned child into an
//! error-only return. Initialization failure is immutable and non-serving; the
//! existing lifecycle owner publishes the lease, fences, signals and observes.

use std::process::Child;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use super::AgentHealthProbeIdentity;
use super::HealthProbe;
use super::ProcessRef;
use super::UnixManagedProcess;
use super::UnixProcessHandle;
use super::spawn_log_reader;
use crate::ProcessDriverError;
use crate::ProcessIdentity;
use crate::ProcessStream;
use crate::SpawnedProcess;
use crate::runtime::bounded_message;

fn retain_probe(probe: Result<HealthProbe, ProcessDriverError>) -> (HealthProbe, Option<String>) {
    match probe {
        Ok(probe) => (probe, None),
        Err(error) => (
            HealthProbe {
                ready: Arc::new(AtomicBool::new(false)),
                shutdown: Arc::new(AtomicBool::new(true)),
            },
            Some(bounded_message(error.to_string())),
        ),
    }
}

fn remember_fault(failure: &mut Option<String>, result: Result<(), ProcessDriverError>) {
    if let Err(error) = result {
        failure.get_or_insert_with(|| bounded_message(error.to_string()));
    }
}

pub(super) fn finish_child(
    mut child: Child,
    generation: u64,
    companion: bool,
    probe: Result<HealthProbe, ProcessDriverError>,
    agent_control: Option<AgentHealthProbeIdentity>,
    capacity: usize,
) -> SpawnedProcess<UnixManagedProcess> {
    // Child::id is an OS-assigned positive PID. Both generated ASCII strings
    // have at most 79 bytes even at the u32/u64 maxima. No request text enters
    // this constructor, so ProcessIdentity's fallible validation cannot fail.
    let incarnation = if companion {
        format!(
            "unix-matrix-pid-{}-agent-generation-{generation}",
            child.id()
        )
    } else {
        format!("unix-pid-{}-generation-{generation}", child.id())
    };
    let identity = ProcessIdentity::new(u64::from(child.id()), incarnation)
        .expect("OS child PID and bounded generated incarnation satisfy ProcessIdentity");
    let (health_probe, mut failure) = retain_probe(probe);
    let (sender, logs) = std::sync::mpsc::sync_channel(capacity);
    let stdout = match child.stdout.take() {
        Some(stdout) => spawn_log_reader(stdout, ProcessStream::Stdout, sender.clone()),
        None => Err(ProcessDriverError::new(
            "acquired child stdout pipe is missing",
        )),
    };
    remember_fault(&mut failure, stdout);
    let stderr = match child.stderr.take() {
        Some(stderr) => spawn_log_reader(stderr, ProcessStream::Stderr, sender),
        None => Err(ProcessDriverError::new(
            "acquired child stderr pipe is missing",
        )),
    };
    remember_fault(&mut failure, stderr);
    if failure.is_some() {
        health_probe.shutdown();
    }
    SpawnedProcess {
        identity,
        process: UnixManagedProcess {
            handle: UnixProcessHandle::Child(child),
            logs,
            health_probe,
            agent_control,
            drain_requested: false,
            next_drain_request_id: 1,
            initialization_failure: failure,
            #[cfg(all(target_os = "linux", feature = "local-host"))]
            resource_execution: None,
        },
    }
}

pub(super) fn finish_adoption(
    reference: ProcessRef,
    probe: Result<HealthProbe, ProcessDriverError>,
    agent_control: Option<AgentHealthProbeIdentity>,
) -> UnixManagedProcess {
    let (health_probe, failure) = retain_probe(probe);
    let (_sender, logs) = std::sync::mpsc::sync_channel(1);
    UnixManagedProcess {
        handle: UnixProcessHandle::Adopted(reference),
        logs,
        health_probe,
        agent_control,
        drain_requested: false,
        next_drain_request_id: 1,
        initialization_failure: failure,
        #[cfg(all(target_os = "linux", feature = "local-host"))]
        resource_execution: None,
    }
}

#[cfg(test)]
#[path = "unix_initialization_tests.rs"]
mod tests;
