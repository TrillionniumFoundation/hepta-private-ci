//! Fresh observations from the original Fleet owner over its existing issuer.
//! Neither a local resource DTO nor the process generation creates a grant.
use std::path::Path;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_agent_components::fleet::AllocationGrant;
use codex_hepta_agent_components::fleet::FLEET_RESOURCE_OBSERVATION_OPERATION;
use codex_hepta_agent_components::fleet::FleetExecutionContextV1;
use codex_hepta_agent_components::fleet::FleetResourceObservationRequestV1;
use codex_hepta_agent_components::fleet::FleetResourceObservationResponseV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::final_use_authorizer::FinalUseAuthorizerConfig;

type Result<T> = std::result::Result<T, Box<dyn std::error::Error + Send + Sync>>;
const TIMEOUT: Duration = Duration::from_secs(2);

/// These facts describe the original process, separately from model generation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FleetWorkerProcessBindingV2 {
    pub worker_generation: Generation,
    pub context: FleetExecutionContextV1,
    pub process_id: u32,
    pub process_start_ticks: u64,
    pub boot_digest: Digest32,
}

/// Only the authenticated original owner exchange constructs this value.
pub struct CurrentFleetWorkerResourcesV2 {
    binding: FleetWorkerProcessBindingV2,
    allocation: AllocationGrant,
    observed_at_ms: u64,
}
impl CurrentFleetWorkerResourcesV2 {
    pub fn binding(&self) -> &FleetWorkerProcessBindingV2 {
        &self.binding
    }
    pub fn allocation(&self) -> &AllocationGrant {
        &self.allocation
    }
    pub fn observed_at_ms(&self) -> u64 {
        self.observed_at_ms
    }
}

/// The initial observation freezes only process identity. Every later dispatch
/// reads the actual current allocation, expiry and revocation from the same owner.
pub struct FleetWorkerResourcePortV2 {
    config: FinalUseAuthorizerConfig,
    request: FleetResourceObservationRequestV1,
    binding: FleetWorkerProcessBindingV2,
    cursor: Mutex<(u64, u64, u64)>,
}
impl std::fmt::Debug for FleetWorkerResourcePortV2 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter
            .debug_struct("FleetWorkerResourcePortV2")
            .field("binding", &self.binding)
            .finish_non_exhaustive()
    }
}
impl FleetWorkerResourcePortV2 {
    pub fn open(
        authority_config: &Path,
        identity: &codex_hepta_agentd::AgentdIdentity,
        execution_id: String,
        fleet_manifest_digest: Digest32,
    ) -> Result<Self> {
        use std::os::unix::fs::MetadataExt;
        let meta = std::fs::symlink_metadata(authority_config)?;
        if authority_config.canonicalize()? != authority_config
            || meta.uid() != 0
            || meta.mode() & 0o222 != 0
            || meta.nlink() != 1
            || !meta.is_file()
        {
            return Err("resource port requires immutable Root authority configuration".into());
        }
        for parent in authority_config.ancestors().skip(1) {
            let meta = std::fs::symlink_metadata(parent)?;
            if parent.canonicalize()? != parent
                || meta.uid() != 0
                || meta.mode() & 0o022 != 0
                || !meta.is_dir()
            {
                return Err("mutable Root resource configuration ancestor".into());
            }
        }
        let config: FinalUseAuthorizerConfig = serde_json::from_slice(
            &crate::final_use_authorizer::read_private_config(authority_config)?,
        )?;
        if config.issuer_uid != 0
            || config.issuer_process_attestation.is_none()
            || execution_id.is_empty()
            || execution_id.len() > 128
            || fleet_manifest_digest.is_zero()
        {
            return Err("original resource issuer or execution identity missing".into());
        }
        let worker_generation = Generation::new(identity.spawn_generation)?;
        let request = FleetResourceObservationRequestV1 {
            schema_version: 1,
            operation: FLEET_RESOURCE_OBSERVATION_OPERATION.into(),
            subject_id: identity.agent_id.to_string(),
            execution_id,
            manifest_digest: fleet_manifest_digest.to_string(),
        };
        let started = Instant::now();
        let response = exchange(&config, &request)?;
        let allocation = validate_response(&request, &response, started.elapsed())?;
        if response.observation.process_id != std::process::id()
            || response.observation.process_start_ticks == 0
        {
            return Err("resource response differs from actual kernel peer".into());
        }
        let binding = FleetWorkerProcessBindingV2 {
            worker_generation,
            context: response.observation.context.clone(),
            process_id: response.observation.process_id,
            process_start_ticks: response.observation.process_start_ticks,
            boot_digest: boot_digest()?,
        };
        let cursor = Mutex::new((
            response.observed_at_ms,
            allocation.authority_epoch,
            allocation.lease_generation,
        ));
        Ok(Self {
            config,
            request,
            binding,
            cursor,
        })
    }

    pub fn binding(&self) -> &FleetWorkerProcessBindingV2 {
        &self.binding
    }

    pub fn observe_current(&self) -> Result<CurrentFleetWorkerResourcesV2> {
        let mut cursor = self
            .cursor
            .try_lock()
            .map_err(|_| "resource observation busy")?;
        if boot_digest()? != self.binding.boot_digest
            || std::process::id() != self.binding.process_id
        {
            return Err("original worker process changed".into());
        }
        let started = Instant::now();
        let response = exchange(&self.config, &self.request)?;
        let allocation = validate_response(&self.request, &response, started.elapsed())?;
        if response.observation.context != self.binding.context
            || response.observation.process_id != self.binding.process_id
            || response.observation.process_start_ticks != self.binding.process_start_ticks
            || response.observed_at_ms < cursor.0
            || allocation.authority_epoch < cursor.1
            || allocation.authority_epoch == cursor.1 && allocation.lease_generation < cursor.2
            || boot_digest()? != self.binding.boot_digest
        {
            return Err(
                "original worker or current resource frontier changed or rolled back".into(),
            );
        }
        *cursor = (
            response.observed_at_ms,
            allocation.authority_epoch,
            allocation.lease_generation,
        );
        Ok(CurrentFleetWorkerResourcesV2 {
            binding: self.binding.clone(),
            allocation: allocation.clone(),
            observed_at_ms: response.observed_at_ms,
        })
    }
}

fn boot_digest() -> Result<Digest32> {
    let bytes = std::fs::read("/proc/sys/kernel/random/boot_id")?;
    if !(1..=128).contains(&bytes.len()) {
        return Err("native boot identity bounds".into());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_response<'a>(
    request: &FleetResourceObservationRequestV1,
    response: &'a FleetResourceObservationResponseV1,
    elapsed: Duration,
) -> Result<&'a AllocationGrant> {
    let context = &response.observation.context;
    let allocation = response
        .observation
        .allocation
        .as_ref()
        .ok_or("current resource allocation absent")?;
    let conservative_now = response
        .observed_at_ms
        .checked_add(u64::try_from(elapsed.as_millis())?)
        .ok_or("resource clock overflow")?;
    if response.schema_version != 1
        || response.operation != FLEET_RESOURCE_OBSERVATION_OPERATION
        || response.observed_at_ms == 0
        || elapsed >= TIMEOUT
        || context.execution_id != request.execution_id
        || context.principal_id != request.subject_id
        || context.manifest_digest != request.manifest_digest
        || allocation.allocation_id != context.allocation_id
        || allocation.principal_id != context.principal_id
        || allocation.host_id != context.host_id
        || allocation.host_generation != context.host_generation
        || allocation.semantic_digest != context.manifest_digest
        || allocation.resources != context.resources
        || allocation.authority_epoch == 0
        || allocation.lease_generation < context.lease_generation
        || allocation.revoked
        || allocation.expires_at_ms <= conservative_now
        || allocation.resources.memory_bytes == 0
        || allocation.resources.concurrent_turns == 0
    {
        return Err("original current resource response is stale, revoked or substituted".into());
    }
    Ok(allocation)
}

fn exchange(
    config: &FinalUseAuthorizerConfig,
    request: &FleetResourceObservationRequestV1,
) -> Result<FleetResourceObservationResponseV1> {
    use crate::final_use_authorizer::validate_connected_issuer_with_attestation;
    use crate::final_use_authorizer::validate_issuer_socket;
    use codex_hepta_contracts::MODEL_ISSUER_MAX_REQUEST_BYTES;
    use codex_hepta_contracts::MODEL_ISSUER_MAX_RESPONSE_BYTES;
    use std::io::Write;
    use std::os::unix::net::UnixStream;
    let deadline = Instant::now()
        .checked_add(TIMEOUT)
        .ok_or("resource deadline overflow")?;
    validate_issuer_socket(&config.issuer_socket, config.issuer_uid)?;
    let bytes = serde_json::to_vec(request)?;
    if bytes.is_empty() || bytes.len() > MODEL_ISSUER_MAX_REQUEST_BYTES {
        return Err("resource request bounds".into());
    }
    let socket = rustix::net::socket_with(
        rustix::net::AddressFamily::UNIX,
        rustix::net::SocketType::STREAM,
        rustix::net::SocketFlags::NONBLOCK | rustix::net::SocketFlags::CLOEXEC,
        /*protocol*/ None,
    )?;
    rustix::net::connect(
        &socket,
        &rustix::net::SocketAddrUnix::new(&config.issuer_socket)?,
    )?;
    let peer = rustix::net::sockopt::socket_peercred(&socket)?;
    if peer.uid.as_raw() != config.issuer_uid {
        return Err("resource issuer peer UID differs".into());
    }
    let guard = validate_connected_issuer_with_attestation(
        Some(u32::try_from(peer.pid.as_raw_pid())?),
        config.issuer_process_identity.as_ref(),
        config.issuer_process_attestation.as_deref(),
    )?
    .ok_or("resource issuer identity missing")?;
    let mut stream = UnixStream::from(socket);
    stream.set_nonblocking(false)?;
    let mut frame = u32::try_from(bytes.len())?.to_be_bytes().to_vec();
    frame.extend_from_slice(&bytes);
    while !frame.is_empty() {
        stream.set_write_timeout(Some(remaining(deadline)?))?;
        match stream.write(&frame) {
            Ok(0) => return Err("resource issuer closed request".into()),
            Ok(count) => {
                frame.drain(..count);
            }
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
    let mut header = [0; 4];
    read_before(&mut stream, &mut header, deadline)?;
    let length = usize::try_from(u32::from_be_bytes(header))?;
    if !(1..=MODEL_ISSUER_MAX_RESPONSE_BYTES).contains(&length) {
        return Err("resource response bounds".into());
    }
    let mut response = vec![0; length];
    read_before(&mut stream, &mut response, deadline)?;
    guard.revalidate()?;
    remaining(deadline)?;
    Ok(serde_json::from_slice(&response)?)
}
fn remaining(deadline: Instant) -> Result<Duration> {
    deadline
        .checked_duration_since(Instant::now())
        .filter(|remaining| !remaining.is_zero())
        .ok_or_else(|| "original resource observation timed out".into())
}
fn read_before(
    stream: &mut std::os::unix::net::UnixStream,
    mut output: &mut [u8],
    deadline: Instant,
) -> Result<()> {
    use std::io::Read;
    while !output.is_empty() {
        stream.set_read_timeout(Some(remaining(deadline)?))?;
        match stream.read(output) {
            Ok(0) => return Err("resource issuer closed response".into()),
            Ok(count) => output = &mut output[count..],
            Err(error) if error.kind() == std::io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(error.into()),
        }
    }
    Ok(())
}

#[cfg(test)]
#[path = "fleet_worker_resource_port_v2_tests.rs"]
mod tests;
