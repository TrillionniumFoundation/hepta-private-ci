//! Process-bound HOS2 transport for explicit production host composition.
//!
//! The retained file is already tied to a real process image by the kernel.
//! Bootstrap values only select existing slots; opening a file or supplying
//! different identifiers never grants a native capability.

use std::fs::File;
use std::os::fd::AsRawFd;

use codex_hepta_memory::HOS2_CPU_PERIOD_NS;
use codex_hepta_memory::Hos2DeliveryId;
use codex_hepta_memory::Hos2DeliveryObservation;
use codex_hepta_memory::Hos2Device;
use codex_hepta_memory::Hos2InstallBudgetV1;
use codex_hepta_memory::Hos2InstallContradiction;
use codex_hepta_memory::Hos2InstallOutcome;
use codex_hepta_memory::Hos2RetirementObservation;
use codex_hepta_memory::Hos2RetirementPermit;

const HEADER_BYTES: usize = 64;
const HOS2_IOCTL: libc::c_ulong = 0xc020_4802;

/// Retains a control file for the current manager or recovery image. The
/// constructor verifies QueryAbi against the sealed bootstrap discovery page;
/// the actual kernel checks image lifetime and retained capabilities per call.
pub struct AgentdHos2Device {
    transport: Box<dyn ControlTransport>,
    boot_id: [u8; 16],
    local_space: [u8; 16],
    manager_space: [u8; 16],
    recovery_space: [u8; 16],
    observe_slot: u64,
    observe_generation: u64,
    manage_slot: u64,
    manage_generation: u64,
    manager_history: (u64, u64),
    recovery_history: (u64, u64),
    maximum_cap_ns: u64,
}

/// One correlated N0 CPU observation, not an operation outcome or a grant.
/// The observer namespace identifies this process's capability space; it is
/// not the controlled resource's stable object ID. A later write still needs
/// the original owner's immutable intent, live authority and revision CAS.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdHos2Usage {
    pub boot_id: [u8; 16],
    pub observer_space_id: [u8; 16],
    pub revision: u64,
    pub sample_boottime_ns: u64,
    pub cumulative_cpu_ns: u64,
    pub window_start_ns: u64,
    pub window_consumed_ns: u64,
    pub active_cap_ns: u64,
    pub active_period_ns: u64,
    pub event_sequence: u64,
    pub dropped_events: u64,
}

struct Response {
    status: u16,
    revision: u64,
    payload: Vec<u8>,
}

/// A single synchronous ioctl exchange. Implementations cannot queue an
/// effect, retry an ambiguous call, or retain either borrowed frame buffer.
trait ControlTransport: Send + Sync {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String>;
}

struct FileTransport {
    file: File,
}

impl ControlTransport for FileTransport {
    fn exchange(&self, input: &[u8], output: &mut [u8]) -> Result<(), String> {
        let mut descriptor = [0_u8; 32];
        descriptor[..8].copy_from_slice(&(input.as_ptr() as u64).to_le_bytes());
        descriptor[8..16].copy_from_slice(&(output.as_mut_ptr() as u64).to_le_bytes());
        descriptor[16..20].copy_from_slice(&(input.len() as u32).to_le_bytes());
        descriptor[20..24].copy_from_slice(&(output.len() as u32).to_le_bytes());
        // SAFETY: both borrowed, initialized frame buffers and this descriptor
        // remain live for this synchronous ioctl. The lengths describe their
        // actual bounds. HOS2 snapshots input and copies output before return;
        // it retains no Rust reference. The File retains the process binding.
        let result =
            unsafe { libc::ioctl(self.file.as_raw_fd(), HOS2_IOCTL, descriptor.as_mut_ptr()) };
        if result != 0 {
            // EINTR is not retried: the original outbox must query D after an
            // ambiguous call, never dispatch the operation a second time.
            return Err(format!(
                "HOS2 ioctl did not return a complete result: {}",
                std::io::Error::last_os_error()
            ));
        }
        Ok(())
    }
}

impl AgentdHos2Device {
    /// Attach only through an explicitly supplied, already-open process file
    /// and an existing HOS2BOOT v2/v3 page. No environment switch enables effects
    /// and no authority, writer or signer is manufactured by this constructor.
    pub fn from_bootstrap(file: File, bootstrap: &[u8]) -> Result<Self, String> {
        Self::attach(Box::new(FileTransport { file }), bootstrap)
    }

    /// Open the control device in the final kernel-created G2 manager or
    /// recovery Process, before that same image drops its root credentials.
    /// `bootstrap` is the copied read-only AT_HEPTA_BOOT page. Its fields are
    /// discovery only: QueryAbi and every subsequent ioctl still authenticate
    /// the actual Process and image. No caller-supplied file crosses a role.
    pub fn from_kernel_bootstrap(bootstrap: &[u8]) -> Result<Self, String> {
        validate_bootstrap(bootstrap)?;
        if read64(bootstrap, /*offset*/ 8)? != 3 {
            return Err("kernel-initial Agentd requires HOS2BOOT v3".to_string());
        }
        let expected_pid = match read64(bootstrap, /*offset*/ 16)? {
            1 => read64(bootstrap, /*offset*/ 144)?,
            3 => read64(bootstrap, /*offset*/ 160)?,
            _ => return Err("kernel-initial role is not an Agentd owner".to_string()),
        };
        // SAFETY: these process/credential queries take no pointer arguments.
        let identity_matches = unsafe {
            u64::from(std::process::id()) == expected_pid
                && libc::getppid() == 1
                && libc::getuid() == 0
                && libc::geteuid() == 0
                && libc::getgid() == 0
                && libc::getegid() == 0
        };
        if !identity_matches {
            return Err(
                "kernel-initial Agentd must open in its actual final root image".to_string(),
            );
        }
        use std::os::unix::fs::OpenOptionsExt;
        let file = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .custom_flags(libc::O_CLOEXEC | libc::O_NOFOLLOW)
            .open("/dev/hepta-control")
            .map_err(|error| format!("opening this Process's HOS2 control device: {error}"))?;
        Self::attach(Box::new(FileTransport { file }), bootstrap)
    }

    fn attach(transport: Box<dyn ControlTransport>, bootstrap: &[u8]) -> Result<Self, String> {
        validate_bootstrap(bootstrap)?;
        let manager_space = read16(bootstrap, /*offset*/ 112)?;
        let recovery_space = read16(bootstrap, /*offset*/ 128)?;
        let local_space = match read64(bootstrap, /*offset*/ 16)? {
            1 => manager_space,
            3 => recovery_space,
            _ => return Err("this bootstrap role has no native management slot".to_string()),
        };
        let device = Self {
            transport,
            boot_id: read16(bootstrap, /*offset*/ 96)?,
            local_space,
            manager_space,
            recovery_space,
            observe_slot: read64(bootstrap, /*offset*/ 32)?,
            observe_generation: read64(bootstrap, /*offset*/ 40)?,
            manage_slot: read64(bootstrap, /*offset*/ 48)?,
            manage_generation: read64(bootstrap, /*offset*/ 56)?,
            manager_history: (
                read64(bootstrap, /*offset*/ 64)?,
                read64(bootstrap, /*offset*/ 72)?,
            ),
            recovery_history: (
                read64(bootstrap, /*offset*/ 80)?,
                read64(bootstrap, /*offset*/ 88)?,
            ),
            maximum_cap_ns: read64(bootstrap, /*offset*/ 168)?,
        };
        if device.boot_id == [0; 16]
            || device.local_space == [0; 16]
            || device.manager_space == [0; 16]
            || device.recovery_space == [0; 16]
            || device.manager_space == device.recovery_space
            || device.observe_slot == 0
            || device.observe_generation == 0
            || device.manage_slot == 0
            || device.manage_generation == 0
            || device.maximum_cap_ns > HOS2_CPU_PERIOD_NS
        {
            return Err("invalid HOS2 bootstrap management binding".to_string());
        }
        let response = device.exchange(
            /*opcode*/ 1,
            /*sequence*/ 1,
            /*slot*/ 0,
            /*generation*/ 0,
            &[],
        )?;
        if response.status != 0
            || response.revision != 0
            || response.payload.len() != 48
            || read16(&response.payload, /*offset*/ 0)? != device.local_space
            || read32(&response.payload, /*offset*/ 16)? != 4096
            || read32(&response.payload, /*offset*/ 20)? != 40
            || read32(&response.payload, /*offset*/ 24)? != 64
            || read32(&response.payload, /*offset*/ 28)? != 0
            || read64(&response.payload, /*offset*/ 32)? != 62
            || read64(&response.payload, /*offset*/ 40)? != 0
        {
            return Err("native QueryAbi differs from HOS2BOOT discovery".to_string());
        }
        Ok(device)
    }

    /// Read the already-delegated CPU object once, without allocating D,
    /// retrying transport, publishing an outcome or sending a management call.
    /// `request_id` is only a nonzero read correlation ID. Its value does not
    /// consume the original owner's delivery sequence. The snapshot can supply
    /// an observed revision for a new intent; it cannot settle an existing K.
    pub fn read_usage(&self, request_id: u64) -> Result<AgentdHos2Usage, String> {
        let response = self.exchange(
            /*opcode*/ 2,
            request_id,
            self.observe_slot,
            self.observe_generation,
            &[],
        )?;
        if response.status != 0 || response.revision == 0 || response.payload.len() != 64 {
            return Err("native CPU usage observation is unavailable".to_string());
        }
        let bytes = &response.payload;
        let usage = AgentdHos2Usage {
            boot_id: self.boot_id,
            observer_space_id: self.local_space,
            revision: response.revision,
            sample_boottime_ns: read64(bytes, /*offset*/ 0)?,
            cumulative_cpu_ns: read64(bytes, /*offset*/ 8)?,
            window_start_ns: read64(bytes, /*offset*/ 16)?,
            window_consumed_ns: read64(bytes, /*offset*/ 24)?,
            active_cap_ns: read64(bytes, /*offset*/ 32)?,
            active_period_ns: read64(bytes, /*offset*/ 40)?,
            event_sequence: read64(bytes, /*offset*/ 48)?,
            dropped_events: read64(bytes, /*offset*/ 56)?,
        };
        let elapsed = usage
            .sample_boottime_ns
            .checked_sub(usage.window_start_ns)
            .ok_or_else(|| "native CPU usage window starts after its sample".to_string())?;
        let expected_start =
            usage.sample_boottime_ns - usage.sample_boottime_ns % HOS2_CPU_PERIOD_NS;
        if usage.active_period_ns != HOS2_CPU_PERIOD_NS
            || usage.window_start_ns != expected_start
            || usage.window_consumed_ns > elapsed
            || usage.window_consumed_ns > usage.cumulative_cpu_ns
            || usage.cumulative_cpu_ns - usage.window_consumed_ns > usage.window_start_ns
            || usage.cumulative_cpu_ns > usage.sample_boottime_ns
            || usage.active_cap_ns > usage.active_period_ns
            || usage.dropped_events > usage.event_sequence
        {
            return Err("native CPU usage violates the single-CPU accounting profile".to_string());
        }
        // Lowering the cap preserves already-consumed time. In particular,
        // consumed > cap and cap == 0 are valid observations. A delegation's
        // write ceiling also does not bound the state it is allowed to read.
        Ok(usage)
    }

    /// Discover the value to persist before dispatch. The sequence is allocated
    /// by the original operation owner, never by this process-local adapter.
    pub fn install_request(
        &self,
        sequence: u64,
        expected_revision: u64,
        cap_ns: u64,
    ) -> Result<Hos2InstallBudgetV1, String> {
        if cap_ns > self.maximum_cap_ns {
            return Err("requested budget exceeds the native bootstrap grant".to_string());
        }
        let request = Hos2InstallBudgetV1 {
            schema_version: 1,
            delivery: Hos2DeliveryId::new(self.boot_id, self.local_space, sequence)?,
            manage_slot: self.manage_slot,
            manage_generation: self.manage_generation,
            expected_revision,
            period_ns: HOS2_CPU_PERIOD_NS,
            cap_ns,
        };
        request.to_json()?;
        Ok(request)
    }

    fn history_slot(&self, delivery: &Hos2DeliveryId) -> Result<(u64, u64), String> {
        delivery.sequence()?;
        if delivery.boot_id != self.boot_id {
            return Err("native boot changed; the old D remains unknown".to_string());
        }
        let slot = if delivery.space_id == self.manager_space {
            self.manager_history
        } else if delivery.space_id == self.recovery_space {
            self.recovery_history
        } else {
            return Err("no retained history capability for this native namespace".to_string());
        };
        if slot.0 == 0 || slot.1 == 0 {
            return Err("this process has no matching native history slot".to_string());
        }
        Ok(slot)
    }

    fn exchange(
        &self,
        opcode: u16,
        sequence: u64,
        slot: u64,
        generation: u64,
        payload: &[u8],
    ) -> Result<Response, String> {
        if payload.len() > 40 || sequence == 0 || (sequence == u64::MAX && opcode != 2) {
            return Err("invalid bounded HOS2 frame".to_string());
        }
        let mut input = [0_u8; HEADER_BYTES + 40];
        input[..4].copy_from_slice(b"HOS2");
        input[4..6].copy_from_slice(&2_u16.to_le_bytes());
        input[8..10].copy_from_slice(&opcode.to_le_bytes());
        input[12..16].copy_from_slice(&64_u32.to_le_bytes());
        input[16..20].copy_from_slice(&(payload.len() as u32).to_le_bytes());
        input[24..32].copy_from_slice(&sequence.to_le_bytes());
        input[40..48].copy_from_slice(&slot.to_le_bytes());
        input[48..56].copy_from_slice(&generation.to_le_bytes());
        input[HEADER_BYTES..HEADER_BYTES + payload.len()].copy_from_slice(payload);
        let mut output = [0_u8; HEADER_BYTES + 64];
        self.transport
            .exchange(&input[..HEADER_BYTES + payload.len()], &mut output)?;
        let length = read32(&output, /*offset*/ 16)? as usize;
        let status = read_u16(&output, /*offset*/ 10)?;
        if &output[..4] != b"HOSR"
            || read_u16(&output, /*offset*/ 4)? != 2
            || read_u16(&output, /*offset*/ 6)? != 0
            || read_u16(&output, /*offset*/ 8)? != opcode
            || read32(&output, /*offset*/ 12)? != 64
            || read32(&output, /*offset*/ 20)? != 0
            || output[24..40] != input[24..40]
            || read16(&output, /*offset*/ 40)? != self.boot_id
            || status > 11
            || length > 64
            || (status != 0 && (length != 0 || read64(&output, /*offset*/ 56)? != 0))
        {
            return Err("uncorrelated or malformed HOS2 response".to_string());
        }
        Ok(Response {
            status,
            revision: read64(&output, /*offset*/ 56)?,
            payload: output[HEADER_BYTES..HEADER_BYTES + length].to_vec(),
        })
    }
}

impl Hos2Device for AgentdHos2Device {
    fn install(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        request.to_json()?;
        if request.delivery.boot_id != self.boot_id
            || request.delivery.space_id != self.local_space
            || request.manage_slot != self.manage_slot
            || request.manage_generation != self.manage_generation
        {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::RequestBindingMismatch,
            ));
        }
        if request.cap_ns > self.maximum_cap_ns {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: self.maximum_cap_ns,
                },
            ));
        }
        let mut payload = [0_u8; 32];
        payload[..8].copy_from_slice(&request.expected_revision.to_le_bytes());
        payload[8..16].copy_from_slice(&request.period_ns.to_le_bytes());
        payload[16..24].copy_from_slice(&request.cap_ns.to_le_bytes());
        let response = self.exchange(
            /*opcode*/ 3,
            request.delivery.sequence()?,
            request.manage_slot,
            request.manage_generation,
            &payload,
        )?;
        if response.status == 5 {
            // Conflict can mean this D already belongs to different request
            // bytes. QueryDelivery would return that older receipt without a
            // cap/digest binding, so it cannot repair this contradiction.
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::ConflictStatus,
            ));
        }
        if response.status == 0
            && (response.payload.len() != 24
                || read64(&response.payload, /*offset*/ 0)? != request.expected_revision
                || request.expected_revision.checked_add(1) != Some(response.revision)
                || read64(&response.payload, /*offset*/ 16)?
                    > read64(&response.payload, /*offset*/ 8)? % HOS2_CPU_PERIOD_NS)
        {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::InvalidAcknowledgement {
                    revision: response.revision,
                    payload: response.payload,
                },
            ));
        }
        // Even a transport-level rejection is not evidence that a D was
        // consumed. Only the original history owner can report terminality.
        let observation = self.query(&request.delivery)?;
        if response.status == 0 {
            let previous_revision = read64(&response.payload, /*offset*/ 0)?;
            let revision = response.revision;
            let effective_ns = read64(&response.payload, /*offset*/ 8)?;
            let consumed_ns = read64(&response.payload, /*offset*/ 16)?;
            let matches = matches!(&observation, Hos2DeliveryObservation::Applied {
                previous_revision: observed_previous, revision: observed_revision,
                effective_ns: observed_effective, consumed_ns: observed_consumed, ..
            } if *observed_previous == previous_revision && *observed_revision == revision
                && *observed_effective == effective_ns && *observed_consumed == consumed_ns);
            if !matches {
                return Ok(Hos2InstallOutcome::Contradiction(
                    Hos2InstallContradiction::AcknowledgementMismatch {
                        previous_revision,
                        revision,
                        effective_ns,
                        consumed_ns,
                        observation,
                    },
                ));
            }
        }
        Ok(Hos2InstallOutcome::Observed(observation))
    }

    fn observe(&self, request: &Hos2InstallBudgetV1) -> Result<Hos2InstallOutcome, String> {
        request.to_json()?;
        // Availability is not a contradiction: a changed boot or inaccessible
        // namespace still leaves the original effect unknown. This also
        // permits a recovery image's retained manager-history capability.
        self.history_slot(&request.delivery)?;
        if request.manage_slot != self.manage_slot
            || request.manage_generation != self.manage_generation
        {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::RequestBindingMismatch,
            ));
        }
        if request.cap_ns > self.maximum_cap_ns {
            return Ok(Hos2InstallOutcome::Contradiction(
                Hos2InstallContradiction::BudgetExceedsGrant {
                    maximum_cap_ns: self.maximum_cap_ns,
                },
            ));
        }
        self.query(&request.delivery)
            .map(Hos2InstallOutcome::Observed)
    }

    fn query(&self, delivery: &Hos2DeliveryId) -> Result<Hos2DeliveryObservation, String> {
        let (slot, generation) = self.history_slot(delivery)?;
        let sequence = delivery.sequence()?;
        let mut payload = [0_u8; 40];
        payload[..16].copy_from_slice(&delivery.boot_id);
        payload[16..32].copy_from_slice(&delivery.space_id);
        payload[32..40].copy_from_slice(&sequence.to_le_bytes());
        let response = self.exchange(/*opcode*/ 4, sequence, slot, generation, &payload)?;
        if response.status != 0 || response.revision != 0 || response.payload.len() != 64 {
            return Err("native history query is unavailable".to_string());
        }
        let bytes = &response.payload;
        let state = read_u16(bytes, /*offset*/ 0)?;
        let status = read_u16(bytes, /*offset*/ 2)?;
        if read32(bytes, /*offset*/ 4)? != 0
            || read64(bytes, /*offset*/ 8)? != sequence
            || status > 11
        {
            return Err("native history response does not match D".to_string());
        }
        match (state, status) {
            (1, 0)
                if read16(bytes, /*offset*/ 16)? != [0; 16]
                    && read64(bytes, /*offset*/ 40)? != 0
                    && read64(bytes, /*offset*/ 40)?.checked_add(1)
                        == Some(read64(bytes, /*offset*/ 32)?)
                    && read64(bytes, /*offset*/ 56)?
                        <= read64(bytes, /*offset*/ 48)? % HOS2_CPU_PERIOD_NS =>
            {
                Ok(Hos2DeliveryObservation::Applied {
                    stable_object_id: read16(bytes, /*offset*/ 16)?,
                    revision: read64(bytes, /*offset*/ 32)?,
                    previous_revision: read64(bytes, /*offset*/ 40)?,
                    effective_ns: read64(bytes, /*offset*/ 48)?,
                    consumed_ns: read64(bytes, /*offset*/ 56)?,
                })
            }
            (1, 1..=7) if bytes[16..].iter().all(|byte| *byte == 0) => {
                Ok(Hos2DeliveryObservation::NotApplied { status })
            }
            (0, 0) if bytes[16..].iter().all(|byte| *byte == 0) => {
                Ok(Hos2DeliveryObservation::Reserved)
            }
            (2, 0) if bytes[16..].iter().all(|byte| *byte == 0) => {
                Ok(Hos2DeliveryObservation::Retired)
            }
            (3, 0) if bytes[16..].iter().all(|byte| *byte == 0) => {
                Ok(Hos2DeliveryObservation::NotSeen)
            }
            (4, 0) if bytes[16..].iter().all(|byte| *byte == 0) => {
                Ok(Hos2DeliveryObservation::HistoryLost)
            }
            _ => Err("native history result has an invalid state/status combination".to_string()),
        }
    }

    fn retire(&self, permit: &Hos2RetirementPermit) -> Result<Hos2RetirementObservation, String> {
        let delivery = permit.through();
        let (slot, generation) = self.history_slot(delivery)?;
        let sequence = delivery.sequence()?;
        let mut payload = [0_u8; 40];
        payload[..16].copy_from_slice(&delivery.boot_id);
        payload[16..32].copy_from_slice(&delivery.space_id);
        payload[32..].copy_from_slice(&sequence.to_le_bytes());
        let response = self.exchange(/*opcode*/ 5, sequence, slot, generation, &payload)?;
        if response.status != 0 || response.revision != 0 || response.payload.len() != 16 {
            return Err("native retirement acknowledgement is unavailable".to_string());
        }
        let retired_through = read64(&response.payload, /*offset*/ 0)?;
        let next_sequence = read64(&response.payload, /*offset*/ 8)?;
        if retired_through < sequence || next_sequence <= retired_through {
            return Err("native retirement acknowledgement has an invalid frontier".to_string());
        }
        Ok(Hos2RetirementObservation {
            retired_through,
            next_sequence,
        })
    }
}

fn read_u16(bytes: &[u8], offset: usize) -> Result<u16, String> {
    let value: [u8; 2] = bytes
        .get(offset..offset + 2)
        .ok_or_else(|| "truncated HOS2 field".to_string())?
        .try_into()
        .map_err(|_| "invalid HOS2 field length".to_string())?;
    Ok(u16::from_le_bytes(value))
}

fn read32(bytes: &[u8], offset: usize) -> Result<u32, String> {
    let value: [u8; 4] = bytes
        .get(offset..offset + 4)
        .ok_or_else(|| "truncated HOS2 field".to_string())?
        .try_into()
        .map_err(|_| "invalid HOS2 field length".to_string())?;
    Ok(u32::from_le_bytes(value))
}

fn read64(bytes: &[u8], offset: usize) -> Result<u64, String> {
    let value: [u8; 8] = bytes
        .get(offset..offset + 8)
        .ok_or_else(|| "truncated HOS2 field".to_string())?
        .try_into()
        .map_err(|_| "invalid HOS2 field length".to_string())?;
    Ok(u64::from_le_bytes(value))
}

fn read16(bytes: &[u8], offset: usize) -> Result<[u8; 16], String> {
    bytes
        .get(offset..offset + 16)
        .ok_or_else(|| "truncated HOS2 identity".to_string())?
        .try_into()
        .map_err(|_| "invalid HOS2 identity length".to_string())
}

// The v2 profile remains byte-for-byte compatible with the three-role G1d
// consumer. G2 is a distinct four-role initial transaction, never inferred from
// a new PID, an environment variable or a transferred file descriptor.
fn validate_bootstrap(bootstrap: &[u8]) -> Result<(), String> {
    if bootstrap.len() < 192
        || &bootstrap[..8] != b"HOS2BOOT"
        || read64(bootstrap, /*offset*/ 176)? != HOS2_CPU_PERIOD_NS
    {
        return Err("invalid sealed HOS2 bootstrap discovery page".to_string());
    }
    let bytes = match read64(bootstrap, /*offset*/ 8)? {
        2 => 192,
        3 => {
            if !matches!(bootstrap.len(), 200 | 4096)
                || read64(bootstrap, /*offset*/ 144)? != 2
                || read64(bootstrap, /*offset*/ 152)? != 3
                || read64(bootstrap, /*offset*/ 160)? != 4
                || read64(bootstrap, /*offset*/ 192)? != 1
            {
                return Err("invalid G2 kernel-initial process topology".to_string());
            }
            200
        }
        _ => return Err("unsupported HOS2 bootstrap version".to_string()),
    };
    if read64(bootstrap, /*offset*/ 24)? != bytes as u64
        || bootstrap[bytes..].iter().any(|byte| *byte != 0)
    {
        return Err("invalid sealed HOS2 bootstrap discovery page".to_string());
    }
    Ok(())
}

#[cfg(test)]
#[path = "hos2_device_tests.rs"]
mod tests;
