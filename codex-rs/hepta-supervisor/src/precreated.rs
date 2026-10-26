//! Consume already created children through the original Supervisor's real
//! Starting/SpawnSpec path. This driver never forks, execs, grants a kernel
//! role, writes Registry state or invents a generation. Native callers must
//! select these children from their verified kernel bootstrap before binding.

use super::*;
use crate::AgentCommand;
use codex_hepta_contracts::HostAuthorityPeerChannel;
use codex_hepta_contracts::HostAuthorityPeerPolicy;
use codex_hepta_contracts::HostIssuerPeer;
use codex_hepta_contracts::HostIssuerTransportError;
use sha2::Digest;
use sha2::Sha256;
use std::collections::VecDeque;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::ffi::OsStrExt;
use std::os::unix::net::UnixStream;

const PREFIX: &[u8] = b"HEPTA_PRECREATED_SPAWN_V1\n";
const FRAME_BOUND: usize = 65_536;
const HANDOFF_TIMEOUT: Duration = Duration::from_millis(200);

/// One actual child selected by the original parent, pinned before connection
/// acceptance. The same verified executable keeps running after handoff.
pub struct PrecreatedChild {
    parent_pid: u32,
    identity: ProcessIdentity,
    command: AgentCommand,
    channel: HostAuthorityPeerChannel,
    startup_descriptor: Option<OwnedFd>,
    pin: PinnedChild,
}

impl PrecreatedChild {
    /// The caller must retain its original Child/pidfd before accepting the
    /// stream. A numeric PID discovered from an arbitrary request is not a
    /// substitute. The existing protected channel verifies both inputs.
    pub fn from_stream(
        stream: UnixStream,
        owner_pidfd: OwnedFd,
        peer: HostIssuerPeer,
        command: AgentCommand,
    ) -> Result<Self, ProcessDriverError> {
        let command = AgentCommand::new(command.program, command.args)
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        let parent_pid = std::process::id();
        let mut stat = String::new();
        std::fs::File::open(format!("/proc/{}/stat", peer.pid))?
            .take(4097)
            .read_to_string(&mut stat)?;
        let fields: Vec<_> = stat
            .rsplit_once(") ")
            .ok_or_else(|| ProcessDriverError::new("precreated child stat is invalid"))?
            .1
            .split_whitespace()
            .collect();
        if stat.len() > 4096
            || fields.get(1).and_then(|field| field.parse::<u32>().ok()) != Some(parent_pid)
        {
            return Err(ProcessDriverError::new(
                "precreated process is not our actual child",
            ));
        }
        let start = fields
            .get(19)
            .and_then(|field| field.parse::<u64>().ok())
            .ok_or_else(|| ProcessDriverError::new("precreated child start identity is absent"))?;
        verify_command(peer.pid, &command)?;
        let channel = HostAuthorityPeerChannel::from_stream(
            stream,
            HostAuthorityPeerPolicy {
                peer,
                timeout: HANDOFF_TIMEOUT,
                lifetime: Duration::from_secs(300),
                request_bound: FRAME_BOUND,
                response_bound: 32,
            },
            owner_pidfd.try_clone()?,
        )
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        let identity = ProcessIdentity::new(
            u64::from(peer.pid),
            format!("precreated-pid-{}-start-{start}", peer.pid),
        )
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        Ok(Self {
            parent_pid,
            identity,
            command,
            channel,
            startup_descriptor: None,
            pin: PinnedChild {
                fd: owner_pidfd,
                pid: peer.pid,
                exit: None,
            },
        })
    }

    /// Retain one already-created startup capability for this exact child. It
    /// is transferred only after the child's exact original SpawnSpec ACK, and
    /// is consumed even if delivery is uncertain. The original recipient must
    /// still validate its purpose/provenance; this driver creates no authority.
    /// This lets a native Root pass its real late-handoff pair after the kernel
    /// has already created the child, without changing kernel role grants.
    pub fn with_startup_descriptor(
        mut self,
        descriptor: OwnedFd,
    ) -> Result<Self, ProcessDriverError> {
        if self.startup_descriptor.is_some() {
            return Err(ProcessDriverError::new(
                "this original child already holds a startup descriptor",
            ));
        }
        self.startup_descriptor = Some(descriptor);
        Ok(self)
    }
}

/// Finite original-parent driver for one initial child and at most one
/// independently precreated replacement. Every attempted handoff consumes its
/// child once, including uncertain replies. No numeric-PID adoption exists.
pub struct PrecreatedProcessDriver {
    agent_id: AgentId,
    pending: VecDeque<PrecreatedChild>,
}

impl PrecreatedProcessDriver {
    pub fn new(
        agent_id: AgentId,
        children: Vec<PrecreatedChild>,
    ) -> Result<Self, ProcessDriverError> {
        if !(1..=2).contains(&children.len())
            || children
                .iter()
                .any(|child| child.parent_pid != std::process::id())
            || (children.len() == 2 && children[0].pin.pid == children[1].pin.pid)
        {
            return Err(ProcessDriverError::new(
                "distinct original-parent children are required",
            ));
        }
        Ok(Self {
            agent_id,
            pending: children.into(),
        })
    }
}

impl ProcessDriver for PrecreatedProcessDriver {
    type Process = UnixManagedProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let child = self
            .pending
            .front()
            .ok_or_else(|| ProcessDriverError::new("no unused precreated child"))?;
        if spec.agent_id != self.agent_id
            || spec.generation == 0
            || spec.command != child.command
            || child.parent_pid != std::process::id()
        {
            return Err(ProcessDriverError::new(
                "SpawnSpec differs from the selected original child",
            ));
        }
        let mut bytes = PREFIX.to_vec();
        bytes.extend(serde_json::to_vec(spec)?);
        if bytes.len() > FRAME_BOUND {
            return Err(ProcessDriverError::new(
                "precreated SpawnSpec exceeds the original channel bound",
            ));
        }
        // Removal precedes the first possible delivery. An ambiguous handoff
        // must never retarget the same role with a new Registry generation.
        let PrecreatedChild {
            identity,
            command,
            mut channel,
            startup_descriptor,
            pin,
            ..
        } = self.pending.pop_front().unwrap();
        let outcome = (|| {
            verify_command(pin.pid, &command)?;
            let reply = channel
                .request(&bytes)
                .map_err(|error| ProcessDriverError::new(error.to_string()))?;
            if reply != Sha256::digest(&bytes).as_slice() {
                return Err(ProcessDriverError::new(
                    "precreated child did not acknowledge the exact SpawnSpec",
                ));
            }
            if let Some(descriptor) = startup_descriptor {
                channel
                    .send_one_descriptor(descriptor)
                    .map_err(|error| ProcessDriverError::new(error.to_string()))?;
            }
            let agent_control = AgentHealthProbeIdentity::from_spawn(spec, pin.pid);
            let health_probe =
                HealthProbe::spawn(HealthProbeIdentity::Agentd(agent_control.clone()))?;
            Ok((agent_control, health_probe))
        })();
        let (agent_control, health_probe) = match outcome {
            Ok(value) => value,
            Err(error) => {
                let _ = pin.signal(libc::SIGKILL);
                return Err(error);
            }
        };
        let (_sender, logs) = std::sync::mpsc::sync_channel(1);
        Ok(SpawnedProcess {
            identity,
            process: UnixManagedProcess {
                handle: UnixProcessHandle::Precreated(pin),
                logs,
                health_probe,
                agent_control: Some(agent_control),
                drain_requested: false,
                next_drain_request_id: 1,
            },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        // A persisted lease is not a new held child or a native image grant.
        Ok(Adoption::Rejected)
    }
}

/// Receive the original parent's exact SpawnSpec in the current final image.
/// The caller pins its actual parent before connecting and supplies that peer
/// identity, independently of any incoming bytes. Returning a spec creates no
/// writer, authority lease, current cut, kernel slot or healthy Agentd status.
pub fn receive_precreated_spawn(
    stream: UnixStream,
    parent_pidfd: OwnedFd,
    parent: HostIssuerPeer,
    command: &AgentCommand,
) -> Result<SpawnSpec, ProcessDriverError> {
    receive_spawn_channel(stream, parent_pidfd, parent, command).map(|(spec, _channel)| spec)
}

/// Receive the same original SpawnSpec and its one terminal startup capability.
/// The inherited Root handoff validator must still verify the returned socket,
/// Root creator, seals and retained lifetime before accepting any authority.
/// A missing/extra/late FD cannot fall back to the descriptor-free protocol.
pub fn receive_precreated_spawn_with_descriptor(
    stream: UnixStream,
    parent_pidfd: OwnedFd,
    parent: HostIssuerPeer,
    command: &AgentCommand,
) -> Result<(SpawnSpec, OwnedFd), ProcessDriverError> {
    let (spec, channel) = receive_spawn_channel(stream, parent_pidfd, parent, command)?;
    let descriptor = channel
        .receive_one_descriptor()
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
    Ok((spec, descriptor))
}

fn receive_spawn_channel(
    stream: UnixStream,
    parent_pidfd: OwnedFd,
    parent: HostIssuerPeer,
    command: &AgentCommand,
) -> Result<(SpawnSpec, HostAuthorityPeerChannel), ProcessDriverError> {
    // SAFETY: getppid has no pointer arguments and reads the actual parent.
    if unsafe { libc::getppid() } != parent.pid as i32 {
        return Err(ProcessDriverError::new(
            "precreated handoff peer is not the actual parent",
        ));
    }
    verify_command(std::process::id(), command)?;
    let mut channel = HostAuthorityPeerChannel::from_stream(
        stream,
        HostAuthorityPeerPolicy {
            peer: parent,
            timeout: HANDOFF_TIMEOUT,
            lifetime: Duration::from_secs(300),
            request_bound: FRAME_BOUND,
            response_bound: 32,
        },
        parent_pidfd,
    )
    .map_err(|error| ProcessDriverError::new(error.to_string()))?;
    let mut received = None;
    let delivered = channel
        .exchange(|bytes| {
            let json = bytes
                .strip_prefix(PREFIX)
                .ok_or(HostIssuerTransportError::InvalidRequest)?;
            let spec: SpawnSpec = serde_json::from_slice(json)
                .map_err(|_| HostIssuerTransportError::InvalidRequest)?;
            if spec.generation == 0 || &spec.command != command {
                return Err(HostIssuerTransportError::InvalidRequest);
            }
            received = Some(spec);
            Ok(Sha256::digest(bytes).to_vec())
        })
        .map_err(|error| ProcessDriverError::new(error.to_string()))?;
    if !delivered {
        return Err(ProcessDriverError::new(
            "original parent closed before SpawnSpec handoff",
        ));
    }
    received
        .map(|spec| (spec, channel))
        .ok_or_else(|| ProcessDriverError::new("no complete original SpawnSpec received"))
}

fn verify_command(pid: u32, command: &AgentCommand) -> Result<(), ProcessDriverError> {
    let argument_bytes = command.args.iter().try_fold(0_usize, |bytes, argument| {
        bytes.checked_add(argument.as_bytes().len())
    });
    if command.program.as_os_str().as_bytes().len() > 4096
        || command.args.len() > 128
        || argument_bytes.is_none_or(|bytes| bytes > 65_536)
    {
        return Err(ProcessDriverError::new(
            "precreated command exceeds the original argument bound",
        ));
    }
    if std::fs::read_link(format!("/proc/{pid}/exe"))? != command.program {
        return Err(ProcessDriverError::new(
            "precreated child is not the selected executable",
        ));
    }
    let mut actual = Vec::new();
    std::fs::File::open(format!("/proc/{pid}/cmdline"))?
        .take(69_762)
        .read_to_end(&mut actual)?;
    let mut expected = Vec::new();
    for argument in std::iter::once(command.program.as_os_str())
        .chain(command.args.iter().map(std::ffi::OsString::as_os_str))
    {
        expected.extend_from_slice(argument.as_bytes());
        expected.push(0);
    }
    if actual.len() > 69_761 || actual != expected {
        return Err(ProcessDriverError::new(
            "precreated child arguments differ from the selected command",
        ));
    }
    Ok(())
}

pub(super) struct PinnedChild {
    fd: OwnedFd,
    pub(super) pid: u32,
    exit: Option<ProcessExit>,
}

impl PinnedChild {
    pub(super) fn signal(&self, signal: i32) -> Result<(), ProcessDriverError> {
        // SAFETY: the retained descriptor was verified as this original child's
        // pidfd; the fixed signal has no accompanying siginfo. No PID fallback.
        let result = unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                self.fd.as_raw_fd(),
                signal,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        };
        if result != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        Ok(())
    }

    pub(super) fn poll(&mut self) -> Result<Option<ProcessExit>, ProcessDriverError> {
        if self.exit.is_some() {
            return Ok(self.exit);
        }
        // SAFETY: siginfo_t is an initialized C output record, and waitid uses
        // the retained exact pidfd with WNOHANG. This driver is the sole reaper.
        let mut info: libc::siginfo_t = unsafe { std::mem::zeroed() };
        let result = unsafe {
            libc::waitid(
                libc::P_PIDFD,
                self.fd.as_raw_fd() as libc::id_t,
                &mut info,
                libc::WEXITED | libc::WNOHANG,
            )
        };
        if result != 0 {
            return Err(std::io::Error::last_os_error().into());
        }
        // SAFETY: a successful waitid initialized this standard SIGCHLD record.
        let pid = unsafe { info.si_pid() };
        if pid == 0 {
            return Ok(None);
        }
        if pid != self.pid as i32 {
            return Err(ProcessDriverError::new(
                "pidfd wait returned a foreign process",
            ));
        }
        let code = match info.si_code {
            // SAFETY: CLD_EXITED selects the standard child status member.
            libc::CLD_EXITED => Some(unsafe { info.si_status() }),
            libc::CLD_KILLED | libc::CLD_DUMPED => None,
            _ => return Err(ProcessDriverError::new("pidfd wait did not observe exit")),
        };
        self.exit = Some(ProcessExit {
            success: code == Some(0),
            code,
        });
        Ok(self.exit)
    }
}

#[cfg(test)]
#[path = "precreated_tests.rs"]
mod tests;
