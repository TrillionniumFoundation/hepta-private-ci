//! Linux observation of one process blocked on its exact inherited input pipe.
//!
//! This is read-only execution evidence. It owns no dispatch, cancellation,
//! retry, settlement or input-delivery authority. A destination-specific
//! observer may use a positive sample as one input to `WaitingForInput`; every
//! other condition stays unknown. In particular, a live process, a sleeping
//! process, an exited process, or a process blocked on network I/O is not an
//! input-wait observation.

use std::fs;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::BorrowedFd;
use std::path::Path;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::ActionSkillBindingV1;
use crate::action_skill::evidence_digest;

const EVIDENCE_SCHEMA_VERSION: u32 = 1;
const MAX_PROC_BYTES: u64 = 16 * 1024;

#[derive(Debug, Error)]
pub enum NativeProcessWaitError {
    #[error("invalid native process wait binding: {0}")]
    Invalid(&'static str),
    #[error("native process wait observation unavailable: {0}")]
    Unavailable(#[from] io::Error),
    #[error("native process wait kernel observation unavailable: {0}")]
    Kernel(#[from] rustix::io::Errno),
}

/// One exact positive kernel sample. It grants no right to write the retained
/// input pipe and does not establish the destination goal or termination.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeProcessInputWaitEvidenceV1 {
    pub schema_version: u32,
    pub binding: ActionSkillBindingV1,
    pub process_id: u32,
    pub process_start_ticks: u64,
    pub boot_id: String,
    pub input_reader_fd: u32,
    pub input_pipe_sha256: Sha256Digest,
    pub evidence_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "state", rename_all = "snake_case", deny_unknown_fields)]
pub enum NativeProcessInputWaitObservationV1 {
    WaitingForInput {
        evidence: Box<NativeProcessInputWaitEvidenceV1>,
    },
    Unknown,
}

/// Non-cloneable borrower of the owner's process pin and input writer. The
/// writer is borrowed only to bind the sampled read syscall to the original
/// input object; this type cannot close, write, or extract either descriptor.
pub struct NativeProcessInputWaitObserver<'owner> {
    process_pidfd: BorrowedFd<'owner>,
    input_writer: BorrowedFd<'owner>,
    process_id: u32,
    process_start_ticks: u64,
    boot_id: String,
    input_reader_fd: u32,
    input_pipe_target: String,
    binding: ActionSkillBindingV1,
}

impl<'owner> NativeProcessInputWaitObserver<'owner> {
    /// Borrow only descriptors already held by the process owner. The input
    /// descriptor must be write-only and the child reader must already name
    /// the same pipe. No PID lookup, process spawn, input send, or descriptor
    /// ownership transfer occurs here.
    pub fn from_inherited(
        process_pidfd: BorrowedFd<'owner>,
        input_writer: BorrowedFd<'owner>,
        process_id: u32,
        input_reader_fd: u32,
        binding: ActionSkillBindingV1,
    ) -> Result<Self, NativeProcessWaitError> {
        if process_id == 0
            || input_reader_fd > 1_048_576
            || binding.destination_id.is_empty()
            || binding.provider_intent.validate().is_err()
            || Sha256Digest::parse(binding.effect_intent_digest.as_str()).is_err()
            || Sha256Digest::parse(binding.contract_digest.as_str()).is_err()
        {
            return Err(NativeProcessWaitError::Invalid("identity or binding"));
        }
        let pidfd_number = process_pidfd.as_raw_fd();
        if fs::read_link(format!("/proc/self/fd/{pidfd_number}"))?
            != Path::new("anon_inode:[pidfd]")
            || pidfd_process_id(pidfd_number)? != process_id
            || !pidfd_alive(process_pidfd)?
        {
            return Err(NativeProcessWaitError::Invalid("process pidfd"));
        }
        let writer_number = input_writer.as_raw_fd();
        let writer_target = fs::read_link(format!("/proc/self/fd/{writer_number}"))?;
        let input_pipe_target = writer_target
            .to_str()
            .filter(|target| target.starts_with("pipe:[") && target.ends_with(']'))
            .ok_or(NativeProcessWaitError::Invalid("input writer pipe"))?
            .to_owned();
        if fd_access_mode(writer_number)? != 1
            || fs::read_link(format!("/proc/{process_id}/fd/{input_reader_fd}"))? != writer_target
        {
            return Err(NativeProcessWaitError::Invalid("input pipe ends"));
        }
        let (process_start_ticks, _) = process_snapshot(process_id)?;
        let boot_id = bounded_text(Path::new("/proc/sys/kernel/random/boot_id"))?
            .trim()
            .to_owned();
        if process_start_ticks == 0 || boot_id.is_empty() || boot_id.len() > 128 {
            return Err(NativeProcessWaitError::Invalid("process lifetime"));
        }
        Ok(Self {
            process_pidfd,
            input_writer,
            process_id,
            process_start_ticks,
            boot_id,
            input_reader_fd,
            input_pipe_target,
            binding,
        })
    }

    /// Sample the exact process once. Only a single-threaded process inside
    /// the `read(2)` syscall on the retained pipe becomes WaitingForInput.
    /// All other live or changing states stay UNKNOWN.
    pub fn observe(&self) -> Result<NativeProcessInputWaitObservationV1, NativeProcessWaitError> {
        if !pidfd_alive(self.process_pidfd)?
            || bounded_text(Path::new("/proc/sys/kernel/random/boot_id"))?.trim() != self.boot_id
        {
            return Ok(NativeProcessInputWaitObservationV1::Unknown);
        }
        let before = process_snapshot(self.process_id)?;
        let task_path = format!("/proc/{}/task", self.process_id);
        let task_count = fs::read_dir(task_path)?.take(2).count();
        let child_input = fs::read_link(format!(
            "/proc/{}/fd/{}",
            self.process_id, self.input_reader_fd
        ))?;
        let writer_number = self.input_writer.as_raw_fd();
        let current_writer = fs::read_link(format!("/proc/self/fd/{writer_number}"))?;
        if before.0 != self.process_start_ticks
            || task_count != 1
            || child_input.to_str() != Some(self.input_pipe_target.as_str())
            || current_writer.to_str() != Some(self.input_pipe_target.as_str())
            || !blocked_in_read(self.process_id, self.input_reader_fd)?
        {
            return Ok(NativeProcessInputWaitObservationV1::Unknown);
        }
        let after = process_snapshot(self.process_id)?;
        if after != before || !pidfd_alive(self.process_pidfd)? {
            return Ok(NativeProcessInputWaitObservationV1::Unknown);
        }
        let input_pipe_sha256 = Sha256Digest::for_bytes(self.input_pipe_target.as_bytes());
        let evidence_digest = evidence_digest(
            b"hepta.action.native-process-input-wait.v1\0",
            &(
                &self.binding,
                self.process_id,
                self.process_start_ticks,
                &self.boot_id,
                self.input_reader_fd,
                &input_pipe_sha256,
            ),
        )
        .map_err(|_| NativeProcessWaitError::Invalid("evidence encoding"))?;
        Ok(NativeProcessInputWaitObservationV1::WaitingForInput {
            evidence: Box::new(NativeProcessInputWaitEvidenceV1 {
                schema_version: EVIDENCE_SCHEMA_VERSION,
                binding: self.binding.clone(),
                process_id: self.process_id,
                process_start_ticks: self.process_start_ticks,
                boot_id: self.boot_id.clone(),
                input_reader_fd: self.input_reader_fd,
                input_pipe_sha256,
                evidence_digest,
            }),
        })
    }
}

fn pidfd_alive(pidfd: BorrowedFd<'_>) -> Result<bool, NativeProcessWaitError> {
    let mut descriptors = [rustix::event::PollFd::new(
        &pidfd,
        rustix::event::PollFlags::IN,
    )];
    Ok(rustix::event::poll(&mut descriptors, Some(&rustix::event::Timespec::default()))? == 0)
}

fn pidfd_process_id(fd: i32) -> Result<u32, NativeProcessWaitError> {
    let text = bounded_text(Path::new(&format!("/proc/self/fdinfo/{fd}")))?;
    text.lines()
        .find_map(|line| line.strip_prefix("Pid:\t"))
        .and_then(|value| value.parse().ok())
        .ok_or(NativeProcessWaitError::Invalid("pidfd identity"))
}

fn fd_access_mode(fd: i32) -> Result<u32, NativeProcessWaitError> {
    let text = bounded_text(Path::new(&format!("/proc/self/fdinfo/{fd}")))?;
    let flags = text
        .lines()
        .find_map(|line| line.strip_prefix("flags:\t"))
        .and_then(|value| u32::from_str_radix(value, 8).ok())
        .ok_or(NativeProcessWaitError::Invalid("input writer flags"))?;
    Ok(flags & 3)
}

fn process_snapshot(process_id: u32) -> Result<(u64, char), NativeProcessWaitError> {
    let text = bounded_text(Path::new(&format!("/proc/{process_id}/stat")))?;
    let tail = text
        .rfind(')')
        .and_then(|end| text.get(end + 2..))
        .ok_or(NativeProcessWaitError::Invalid("process stat"))?;
    let fields = tail.split_whitespace().collect::<Vec<_>>();
    let state = fields
        .first()
        .and_then(|value| value.chars().next())
        .ok_or(NativeProcessWaitError::Invalid("process state"))?;
    let start_ticks = fields
        .get(19)
        .and_then(|value| value.parse().ok())
        .ok_or(NativeProcessWaitError::Invalid("process start ticks"))?;
    Ok((start_ticks, state))
}

fn blocked_in_read(process_id: u32, input_reader_fd: u32) -> Result<bool, NativeProcessWaitError> {
    let text = bounded_text(Path::new(&format!("/proc/{process_id}/syscall")))?;
    if text.trim() == "running" {
        return Ok(false);
    }
    let mut fields = text.split_whitespace();
    let syscall = fields.next().and_then(parse_integer);
    let descriptor = fields.next().and_then(parse_integer);
    Ok(syscall == Some(read_syscall_number()) && descriptor == Some(u64::from(input_reader_fd)))
}

fn parse_integer(value: &str) -> Option<u64> {
    value.strip_prefix("0x").map_or_else(
        || value.parse().ok(),
        |value| u64::from_str_radix(value, 16).ok(),
    )
}

#[cfg(target_arch = "x86_64")]
const fn read_syscall_number() -> u64 {
    0
}

#[cfg(any(target_arch = "aarch64", target_arch = "riscv64"))]
const fn read_syscall_number() -> u64 {
    63
}

#[cfg(any(
    target_arch = "arm",
    target_arch = "powerpc",
    target_arch = "powerpc64",
    target_arch = "s390x",
    target_arch = "x86"
))]
const fn read_syscall_number() -> u64 {
    3
}

fn bounded_text(path: &Path) -> Result<String, NativeProcessWaitError> {
    let file = fs::File::open(path)?;
    let metadata = file.metadata()?;
    if metadata.len() > MAX_PROC_BYTES {
        return Err(NativeProcessWaitError::Invalid("proc record bound"));
    }
    use std::io::Read;
    let mut bytes = Vec::new();
    file.take(MAX_PROC_BYTES + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_PROC_BYTES {
        return Err(NativeProcessWaitError::Invalid("proc record bound"));
    }
    String::from_utf8(bytes).map_err(|_| NativeProcessWaitError::Invalid("proc record UTF-8"))
}

#[cfg(test)]
#[path = "native_process_wait_tests.rs"]
mod tests;
