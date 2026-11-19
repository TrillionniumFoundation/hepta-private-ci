use crate::wire::{self, Method, Payload, Request, Response};
use crate::{
    EndpointConfig, HealthObservation, Observation, ObserverError, RunObservation,
    CONTROL_SCHEMA_VERSION, MAX_EVENTS, MAX_FRAME_BYTES, POLL_TIMEOUT_MS,
};
use std::os::unix::fs::{FileTypeExt, MetadataExt};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::{AsyncBufReadExt, AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::net::UnixStream;
use tokio::runtime::{Builder, Handle, Runtime};
use tokio::sync::Semaphore;
use tokio::time::timeout;

/// Blocking facade. Own this on one background worker; there is no retry,
/// process launch, persistence, signing, or generic method dispatch inside it.
pub struct ObserverClient {
    config: EndpointConfig,
    runtime: Option<Runtime>,
    next_request_id: u64,
    metadata_gate: Arc<Semaphore>,
    // Ephemeral read watermark for this configured spawn; it grants no
    // authority and stores neither operations nor business history.
    generation_floor: u64,
}

impl ObserverClient {
    pub fn new(config: EndpointConfig) -> Result<Self, ObserverError> {
        require_blocking_context()?;
        let runtime = Builder::new_current_thread()
            .enable_io()
            .enable_time()
            .max_blocking_threads(1)
            .build()
            .map_err(|_| ObserverError::Unavailable)?;
        let generation_floor = config.spawn_generation;
        Ok(Self {
            config,
            runtime: Some(runtime),
            next_request_id: 1,
            metadata_gate: Arc::new(Semaphore::new(1)),
            generation_floor,
        })
    }

    /// Health → capabilities → event page → health, within one five-second
    /// deadline. Any failure discards the entire new observation. All four
    /// connections must report the configured spawn and the same kernel peer
    /// PID. Current generation may progress through the original Starting,
    /// Running and Draining phases. This is not an atomic read.
    pub fn poll(&mut self, after_cursor: u64, limit: u16) -> Result<Observation, ObserverError> {
        require_blocking_context()?;
        if !(1..=MAX_EVENTS).contains(&limit) {
            return Err(ObserverError::InvalidRequest);
        }
        let observation = self
            .runtime
            .as_ref()
            .expect("live runtime")
            .block_on(async {
                timeout(
                    Duration::from_millis(POLL_TIMEOUT_MS),
                    poll(
                        &self.config,
                        &mut self.next_request_id,
                        &self.metadata_gate,
                        self.generation_floor,
                        after_cursor,
                        limit,
                    ),
                )
                .await
                .map_err(|_| ObserverError::Timeout)?
            })?;
        self.generation_floor = observation.current_generation;
        Ok(observation)
    }

    /// Read one already-known run ID. There is no list, submit, cancel, ACK,
    /// terminal write, history retirement, or authority-renewal API here.
    pub fn run_status(&mut self, run_id: &str) -> Result<Option<RunObservation>, ObserverError> {
        require_blocking_context()?;
        if !wire::valid_identity(run_id) {
            return Err(ObserverError::InvalidRequest);
        }
        let (observation, current_generation) = self
            .runtime
            .as_ref()
            .expect("live runtime")
            .block_on(async {
                timeout(Duration::from_millis(POLL_TIMEOUT_MS), async {
                    let (_, pid, first_generation) = health(
                        &self.config,
                        &mut self.next_request_id,
                        &self.metadata_gate,
                        None,
                    )
                    .await?;
                    monotonic_generation(self.generation_floor, first_generation)?;
                    let (payload, _, run_generation) = call(
                        &self.config,
                        &mut self.next_request_id,
                        &self.metadata_gate,
                        Method::RunStatus { run_id },
                        Some(pid),
                    )
                    .await?;
                    monotonic_generation(first_generation, run_generation)?;
                    let Payload::RunStatus { run } = payload else {
                        return Err(ObserverError::ProtocolMismatch);
                    };
                    let observed = run.map(|run| run.project(run_id)).transpose()?;
                    let (_, _, final_generation) = health(
                        &self.config,
                        &mut self.next_request_id,
                        &self.metadata_gate,
                        Some(pid),
                    )
                    .await?;
                    monotonic_generation(run_generation, final_generation)?;
                    Ok((observed, final_generation))
                })
                .await
                .map_err(|_| ObserverError::Timeout)?
            })?;
        self.generation_floor = current_generation;
        Ok(observation)
    }
}

impl Drop for ObserverClient {
    fn drop(&mut self) {
        if let Some(runtime) = self.runtime.take() {
            // Do not make Session shutdown wait on a stalled filesystem worker.
            // A renderer must independently expire its last-success timestamp.
            runtime.shutdown_background();
        }
    }
}

pub(crate) fn require_blocking_context() -> Result<(), ObserverError> {
    if Handle::try_current().is_ok() {
        Err(ObserverError::InvalidExecutionContext)
    } else {
        Ok(())
    }
}

fn monotonic_generation(previous: u64, current: u64) -> Result<(), ObserverError> {
    if current < previous {
        Err(ObserverError::GenerationFenced)
    } else {
        Ok(())
    }
}

async fn poll(
    config: &EndpointConfig,
    counter: &mut u64,
    metadata_gate: &Arc<Semaphore>,
    generation_floor: u64,
    after_cursor: u64,
    limit: u16,
) -> Result<Observation, ObserverError> {
    let (_, pid, first_generation) = health(config, counter, metadata_gate, None).await?;
    monotonic_generation(generation_floor, first_generation)?;
    let (payload, _, caps_generation) = call(
        config,
        counter,
        metadata_gate,
        Method::Capabilities,
        Some(pid),
    )
    .await?;
    monotonic_generation(first_generation, caps_generation)?;
    let Payload::Capabilities(capabilities) = payload else {
        return Err(ObserverError::ProtocolMismatch);
    };
    let capabilities = capabilities.project()?;
    let (payload, _, events_generation) = call(
        config,
        counter,
        metadata_gate,
        Method::Events {
            after_cursor,
            limit,
        },
        Some(pid),
    )
    .await?;
    monotonic_generation(caps_generation, events_generation)?;
    let Payload::Events(batch) = payload else {
        return Err(ObserverError::ProtocolMismatch);
    };
    let events = batch.project(
        after_cursor,
        limit,
        config.spawn_generation,
        events_generation,
    )?;
    let (health, _, current_generation) = health(config, counter, metadata_gate, Some(pid)).await?;
    monotonic_generation(events_generation, current_generation)?;
    Ok(Observation {
        agent_id: config.expected_agent_id.clone(),
        spawn_generation: config.spawn_generation,
        current_generation,
        health,
        capabilities,
        events,
        next_cursor: batch.next_cursor,
        latest_cursor: batch.latest_cursor,
        history_gap: batch.gap,
    })
}

async fn health(
    config: &EndpointConfig,
    counter: &mut u64,
    metadata_gate: &Arc<Semaphore>,
    expected_pid: Option<u32>,
) -> Result<(HealthObservation, u32, u64), ObserverError> {
    let (payload, pid, current_generation) =
        call(config, counter, metadata_gate, Method::Health, expected_pid).await?;
    let Payload::Health(health) = payload else {
        return Err(ObserverError::ProtocolMismatch);
    };
    Ok((
        health.project(pid, config.spawn_generation, current_generation)?,
        pid,
        current_generation,
    ))
}

async fn call(
    config: &EndpointConfig,
    counter: &mut u64,
    metadata_gate: &Arc<Semaphore>,
    method: Method<'_>,
    expected_pid: Option<u32>,
) -> Result<(Payload, u32, u64), ObserverError> {
    validate_socket(config, metadata_gate).await?;
    let mut stream = UnixStream::connect(&config.socket_path)
        .await
        .map_err(|_| ObserverError::Unavailable)?;
    let credentials = stream.peer_cred().map_err(|_| ObserverError::PeerDenied)?;
    let pid = credentials
        .pid()
        .and_then(|pid| u32::try_from(pid).ok())
        .filter(|pid| *pid != 0)
        .ok_or(ObserverError::PeerDenied)?;
    if credentials.uid() != config.expected_peer_uid
        || expected_pid.is_some_and(|expected| pid != expected)
    {
        return Err(ObserverError::PeerDenied);
    }
    let request_id = *counter;
    *counter = counter
        .checked_add(1)
        .ok_or(ObserverError::RequestIdsExhausted)?;
    let mut bytes = serde_json::to_vec(&Request {
        schema_version: CONTROL_SCHEMA_VERSION,
        request_id,
        spawn_generation: config.spawn_generation,
        method,
    })
    .map_err(|_| ObserverError::InvalidRequest)?;
    bytes.push(b'\n');
    if bytes.len() as u64 > MAX_FRAME_BYTES {
        return Err(ObserverError::InvalidRequest);
    }
    stream
        .write_all(&bytes)
        .await
        .map_err(|_| ObserverError::Unavailable)?;
    let mut reader = BufReader::new(stream).take(MAX_FRAME_BYTES + 1);
    let mut frame = Vec::new();
    let count = reader
        .read_until(b'\n', &mut frame)
        .await
        .map_err(|_| ObserverError::Unavailable)?;
    if count == 0 || count as u64 > MAX_FRAME_BYTES || !frame.ends_with(b"\n") {
        return Err(ObserverError::ProtocolMismatch);
    }
    if frame == wire::OVERLOAD_FRAME {
        return Err(ObserverError::Overloaded);
    }
    let response: Response =
        serde_json::from_slice(&frame).map_err(|_| ObserverError::ProtocolMismatch)?;
    if response.schema_version != CONTROL_SCHEMA_VERSION
        || response.request_id != request_id
        || response.agent_id != config.expected_agent_id
        || response.spawn_generation != config.spawn_generation
    {
        return Err(ObserverError::ProtocolMismatch);
    }
    if !matches!(
        response
            .current_generation
            .checked_sub(config.spawn_generation),
        Some(0..=2)
    ) {
        return Err(ObserverError::GenerationFenced);
    }
    if let Payload::Error { code, message } = response.payload {
        // Owner diagnostics can contain paths or other sensitive context.
        // Parse their strict shape, then collapse them to one fixed local code.
        if !wire::valid_identity(&code) || message.len() > MAX_FRAME_BYTES as usize {
            return Err(ObserverError::ProtocolMismatch);
        }
        return Err(ObserverError::OwnerRejected);
    }
    Ok((response.payload, pid, response.current_generation))
}

pub(crate) async fn validate_socket(
    config: &EndpointConfig,
    metadata_gate: &Arc<Semaphore>,
) -> Result<(), ObserverError> {
    let socket_path = config.socket_path.clone();
    let expected_uid = config.expected_peer_uid;
    metadata_job(metadata_gate, move || {
        let parent = socket_path.parent().ok_or(ObserverError::InvalidEndpoint)?;
        let parent_meta =
            std::fs::symlink_metadata(parent).map_err(|_| ObserverError::Unavailable)?;
        let canonical_parent =
            std::fs::canonicalize(parent).map_err(|_| ObserverError::Unavailable)?;
        let socket_meta =
            std::fs::symlink_metadata(&socket_path).map_err(|_| ObserverError::Unavailable)?;
        if !parent_meta.is_dir()
            || canonical_parent != parent
            || parent_meta.uid() != expected_uid
            || parent_meta.mode() & 0o077 != 0
            || !socket_meta.file_type().is_socket()
            || socket_meta.uid() != expected_uid
            || socket_meta.mode() & 0o077 != 0
        {
            return Err(ObserverError::PeerDenied);
        }
        Ok(())
    })
    .await
}

async fn metadata_job(
    metadata_gate: &Arc<Semaphore>,
    job: impl FnOnce() -> Result<(), ObserverError> + Send + 'static,
) -> Result<(), ObserverError> {
    let permit = Arc::clone(metadata_gate)
        .try_acquire_owned()
        .map_err(|_| ObserverError::Unavailable)?;
    tokio::task::spawn_blocking(move || {
        // The worker owns this permit until the actual syscalls return. An
        // outer timeout cannot cancel a filesystem syscall, and must not free
        // admission for an unbounded queue of replacement metadata jobs.
        let _permit = permit;
        job()
    })
    .await
    .map_err(|_| ObserverError::Unavailable)?
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn timed_out_metadata_keeps_its_admission_until_actual_worker_completion() {
        let runtime = Builder::new_current_thread().enable_time().build().unwrap();
        let gate = Arc::new(Semaphore::new(1));
        let (release, wait_for_release) = std::sync::mpsc::channel();
        runtime.block_on(async {
            let first = timeout(
                Duration::from_millis(20),
                metadata_job(&gate, move || {
                    wait_for_release.recv().unwrap();
                    Ok(())
                }),
            )
            .await;
            assert!(first.is_err());
            assert_eq!(gate.available_permits(), 0);
            // This closure must never enter the blocking pool while the old
            // syscall is still outstanding, even though its waiter timed out.
            assert_eq!(
                metadata_job(&gate, || panic!("unbounded replacement job")).await,
                Err(ObserverError::Unavailable)
            );
            release.send(()).unwrap();
            timeout(Duration::from_secs(1), async {
                while gate.available_permits() == 0 {
                    tokio::time::sleep(Duration::from_millis(1)).await;
                }
            })
            .await
            .unwrap();
            metadata_job(&gate, || Ok(())).await.unwrap();
        });
    }
}
