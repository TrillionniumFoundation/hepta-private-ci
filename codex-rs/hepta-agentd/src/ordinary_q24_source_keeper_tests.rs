//! The same independent process receives the original B offer and produces
//! input only in the product's actual candidate callback. This transports
//! DATA; neither the parent nor this report can certify B or a whole result.

use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::net::UnixDatagram;
use std::os::unix::process::CommandExt;
use std::process::Command;
use std::time::Duration;
use std::time::Instant;

use base64::Engine;
use base64::engine::general_purpose::STANDARD_NO_PAD;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use serde_json::Value;

use crate::OriginalBSourceIngressStatusV1;
use crate::OriginalBSourceSignedDataV1;
use crate::OriginalRootBCandidateDataV1;
use crate::ordinary_q24_process_child_tests::ExitedOriginalProcess;
use crate::ordinary_q24_process_child_tests::OriginalChild;
use crate::ordinary_q24_process_child_tests::OriginalChildDescriptors;
use crate::ordinary_q24_process_child_tests::OriginalProcessLifetime;

pub(super) const CHILD_TEST: &str = "neuron_generation_current::initial_root_tests::ordinary::post_a_source::original_independent_b_source_child";
const HANDOFF_ENV: &str = "HEPTA_ORDINARY_B_SOURCE_HANDOFF_FD";
const INPUT_ENV: &str = "HEPTA_ORDINARY_B_SOURCE_INPUT_FD";
const RESULT_ENV: &str = "HEPTA_ORDINARY_B_SOURCE_RESULT_FD";
const INPUT_BOUND: usize = 1_048_576;
const RESULT_BOUND: usize = 65_536;

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct SourceInputs {
    schema: u8,
    initial: String,
    absolute_end_monotonic_ns: u64,
    producer: Value,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct OriginalSourceObservation {
    schema: u8,
    pub(super) initial: String,
    pub(super) binding: String,
    pub(super) scope: String,
    pub(super) training_head: String,
    pub(super) registered_at_seconds: u64,
    pub(super) candidate_bundle: String,
    pub(super) baseline_bundle: String,
    pub(super) candidate_heads: String,
    pub(super) source_digest: String,
}

pub(super) struct OriginalSourceReport {
    file: File,
    process: OriginalProcessLifetime,
}

impl OriginalSourceReport {
    pub(super) fn read_after_actual_exit(
        &mut self,
        exited: &ExitedOriginalProcess,
    ) -> anyhow::Result<OriginalSourceObservation> {
        exited.require_dead()?;
        anyhow::ensure!(
            exited.lifetime() == &self.process,
            "actual original source exit differs"
        );
        let length = self.file.metadata()?.len();
        anyhow::ensure!(
            (1..=RESULT_BOUND as u64).contains(&length),
            "actual source report bound"
        );
        self.file.rewind()?;
        let mut bytes = Vec::new();
        Read::by_ref(&mut self.file)
            .take(RESULT_BOUND as u64 + 1)
            .read_to_end(&mut bytes)?;
        anyhow::ensure!(
            bytes.len() as u64 == length && self.file.metadata()?.len() == length,
            "source report changed"
        );
        let value: OriginalSourceObservation = serde_json::from_slice(&bytes)?;
        anyhow::ensure!(
            value.schema == 1 && serde_json::to_vec(&value)? == bytes,
            "actual source report schema/encoding"
        );
        Ok(value)
    }
}

pub(super) fn spawn_original_source(
    handoff: UnixDatagram,
    initial: Digest32,
    end: Instant,
    producer: Value,
) -> anyhow::Result<(OriginalChild, OriginalSourceReport)> {
    // Open the actual already-built test executable before dropping identity.
    // Exec through this original descriptor avoids relaxing private ancestors
    // of the qualified build tree just to let the independent peer execute it.
    let executable = File::open(std::env::current_exe()?)?;
    let input = serde_json::to_vec(&SourceInputs {
        schema: 1,
        initial: initial.to_string(),
        absolute_end_monotonic_ns: crate::root_independent_b_source_protocol::seal_original_end(
            end,
        )?,
        producer,
    })?;
    anyhow::ensure!(
        input.len() <= INPUT_BOUND && !initial.is_zero(),
        "bounded fixed source inputs"
    );
    eprintln!(
        "ORDINARY_Q24_SOURCE_INPUT_BYTES={} DATA_BOUND={} AUTHORITY_BOOTSTRAP_BOUND={}",
        input.len(),
        INPUT_BOUND,
        crate::HOST_AUTHORITY_BOOTSTRAP_BOUND
    );
    let input = seal_original_source_input(&input)?;
    let result = tempfile::tempfile()?;
    let mut command = Command::new(format!("/proc/self/fd/{}", executable.as_raw_fd()));
    command
        .current_dir("/run")
        .args(["--ignored", "--exact", CHILD_TEST, "--nocapture"])
        .env(HANDOFF_ENV, handoff.as_raw_fd().to_string())
        .env(INPUT_ENV, input.as_raw_fd().to_string())
        .env(RESULT_ENV, result.as_raw_fd().to_string());
    // SAFETY: this hook uses only fixed stack storage and raw process syscalls.
    // It performs no Rust allocation, locks, parsing or file IO after fork.
    unsafe {
        command.pre_exec(drop_original_source_credentials);
    }
    let child = OriginalChild::spawn(
        &mut command,
        OriginalChildDescriptors {
            inherited: vec![
                executable.as_raw_fd(),
                handoff.as_raw_fd(),
                input.as_raw_fd(),
                result.as_raw_fd(),
            ],
            own_pidfd_slot: None,
        },
    )?;
    crate::authority_host_runtime::verify_process_credentials(child.lifetime().pid, 60002, 60001)?;
    drop((executable, handoff, input));
    let process = child.lifetime().clone();
    Ok((
        child,
        OriginalSourceReport {
            file: result,
            process,
        },
    ))
}

// DATA uses the already-declared source input bound, not the authority
// bootstrap's 64 KiB envelope. This private fixture helper grants no authority.
fn seal_original_source_input(bytes: &[u8]) -> io::Result<File> {
    // SAFETY: geteuid reads this actual producer's kernel identity.
    if unsafe { libc::geteuid() } != 0 {
        return Err(io::Error::new(
            io::ErrorKind::PermissionDenied,
            "original source DATA producer requires Root",
        ));
    }
    if bytes.is_empty() || bytes.len() > INPUT_BOUND {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "original source DATA exceeds its fixed input bound",
        ));
    }
    // SAFETY: the static name is terminated; a successful call creates one
    // fresh owned descriptor that has not been exposed to any receiver.
    let raw = unsafe {
        libc::memfd_create(
            c"hepta-ordinary-source-data".as_ptr(),
            libc::MFD_CLOEXEC | libc::MFD_ALLOW_SEALING,
        )
    };
    if raw < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: take unique ownership of exactly the fresh descriptor above.
    let mut file = unsafe { File::from_raw_fd(raw) };
    file.write_all(bytes)?;
    let seals = libc::F_SEAL_WRITE | libc::F_SEAL_GROW | libc::F_SEAL_SHRINK | libc::F_SEAL_SEAL;
    // SAFETY: both operations act only on this live owned descriptor.
    if unsafe { libc::fchmod(raw, 0o400) } != 0
        || unsafe { libc::fcntl(raw, libc::F_ADD_SEALS, seals) } != 0
    {
        return Err(io::Error::last_os_error());
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, bytes.len() as u64)?;
    file.rewind()?;
    let mut retained = Vec::with_capacity(bytes.len());
    Read::by_ref(&mut file)
        .take(INPUT_BOUND as u64 + 1)
        .read_to_end(&mut retained)?;
    if retained != bytes {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "original sealed source DATA readback differs",
        ));
    }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, bytes.len() as u64)?;
    file.rewind()?;
    Ok(file)
}

pub(super) fn run_original_source(
    produce: impl FnOnce(
        &Value,
        &OriginalRootBCandidateDataV1,
    ) -> io::Result<OriginalBSourceSignedDataV1>,
) -> anyhow::Result<()> {
    crate::authority_host_runtime::verify_process_credentials(std::process::id(), 60002, 60001)?;
    let descriptors = [
        original_descriptor(HANDOFF_ENV)?,
        original_descriptor(INPUT_ENV)?,
        original_descriptor(RESULT_ENV)?,
    ];
    anyhow::ensure!(
        descriptors[0] != descriptors[1]
            && descriptors[0] != descriptors[2]
            && descriptors[1] != descriptors[2],
        "three distinct inherited source descriptors"
    );
    // SAFETY: the exact standalone child owns these three inherited handles.
    // Each is taken once, after distinctness/range checks; no process-local
    // Config/owner has been opened that could reuse an absent argument.
    let (handoff, mut input, mut result) = unsafe {
        (
            UnixDatagram::from_raw_fd(descriptors[0]),
            File::from_raw_fd(descriptors[1]),
            File::from_raw_fd(descriptors[2]),
        )
    };
    let length = input.metadata()?.len();
    anyhow::ensure!(
        (1..=INPUT_BOUND as u64).contains(&length),
        "bounded original source inputs"
    );
    crate::authority_host_bootstrap_seal::validate_sealed(&input, length)?;
    input.rewind()?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut input)
        .take(INPUT_BOUND as u64 + 1)
        .read_to_end(&mut bytes)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&input, length)?;
    let inputs: SourceInputs = serde_json::from_slice(&bytes)?;
    anyhow::ensure!(
        bytes.len() as u64 == length && inputs.schema == 1 && serde_json::to_vec(&inputs)? == bytes,
        "original source input schema/encoding"
    );
    let initial: Digest32 = inputs.initial.parse()?;
    let end = crate::root_independent_b_source_protocol::receive_original_end(
        inputs.absolute_end_monotonic_ns,
    )?;
    let binding = Digest32::of_parts(&[
        b"hepta.root.independent-b.custodian.v1\0",
        initial.as_array(),
    ]);
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let mut observed = None;
    let status = runtime.block_on(async {
        let remaining = end.checked_duration_since(Instant::now()).ok_or_else(|| {
            io::Error::new(io::ErrorKind::TimedOut, "original source handoff deadline")
        })?;
        let original = crate::receive_root_independent_b_source_handoff(
            handoff,
            remaining.min(Duration::from_secs(30)),
        )?;
        crate::submit_original_root_b_source_with_candidate(original, |candidate| {
            if candidate.initial() != initial
                || candidate.binding() != binding
                || observed.is_some()
                || Instant::now() >= end
            {
                return Err(io::Error::other(
                    "actual source candidate belongs to another original iteration",
                ));
            }
            let original = produce(&inputs.producer, candidate)?;
            let source_digest = Digest32::of_bytes(&original.source);
            observed = Some(OriginalSourceObservation {
                schema: 1,
                initial: candidate.initial().to_string(),
                binding: candidate.binding().to_string(),
                scope: candidate.scope().to_string(),
                training_head: candidate.training_head().to_string(),
                registered_at_seconds: candidate.registered_at_seconds(),
                candidate_bundle: STANDARD_NO_PAD.encode(
                    crate::learning_iteration_checkpoint::encode_original_bundle_data(
                        candidate.candidate_bundle(),
                    )
                    .map_err(io::Error::other)?,
                ),
                baseline_bundle: STANDARD_NO_PAD.encode(
                    crate::learning_iteration_checkpoint::encode_original_bundle_data(
                        candidate.baseline_bundle(),
                    )
                    .map_err(io::Error::other)?,
                ),
                candidate_heads: STANDARD_NO_PAD.encode(candidate.candidate_heads()),
                source_digest: source_digest.to_string(),
            });
            Ok(original)
        })
        .await
    })?;
    anyhow::ensure!(
        Instant::now() < end,
        "original independent source deadline elapsed"
    );
    let observed = observed.ok_or_else(|| {
        anyhow::anyhow!("actual candidate callback did not execute; no Evaluate input")
    })?;
    anyhow::ensure!(
        matches!(status, OriginalBSourceIngressStatusV1::RetainedInput { source_digest } if source_digest.to_string() == observed.source_digest),
        "fresh actual Evaluate source was not durably acknowledged"
    );
    let encoded = serde_json::to_vec(&observed)?;
    anyhow::ensure!(
        encoded.len() <= RESULT_BOUND && result.metadata()?.len() == 0,
        "single bounded original source report"
    );
    result.write_all(&encoded)?;
    result.sync_all()?;
    Ok(())
}

fn original_descriptor(name: &str) -> anyhow::Result<i32> {
    let raw = std::env::var(name)?.parse::<i32>()?;
    anyhow::ensure!(raw >= 3, "explicit inherited descriptor required: {name}");
    Ok(raw)
}

fn drop_original_source_credentials() -> io::Result<()> {
    // SAFETY: only scalar process attributes and fixed capability ABI buffers
    // are passed to raw Linux syscalls in the sole post-fork child thread.
    unsafe {
        if libc::prctl(libc::PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0
            || libc::prctl(
                libc::PR_CAP_AMBIENT,
                libc::PR_CAP_AMBIENT_CLEAR_ALL,
                0,
                0,
                0,
            ) != 0
        {
            return Err(io::Error::last_os_error());
        }
        for capability in 0..64 {
            let current = libc::prctl(libc::PR_CAPBSET_READ, capability, 0, 0, 0);
            if current < 0 {
                let error = io::Error::last_os_error();
                if capability > 0 && error.raw_os_error() == Some(libc::EINVAL) {
                    break;
                }
                return Err(error);
            }
            if current != 0 && libc::prctl(libc::PR_CAPBSET_DROP, capability, 0, 0, 0) != 0 {
                return Err(io::Error::last_os_error());
            }
        }
        if libc::syscall(libc::SYS_setgroups, 0, std::ptr::null::<u32>()) != 0
            || libc::syscall(libc::SYS_setresgid, 60001, 60001, 60001) != 0
            || libc::syscall(libc::SYS_setresuid, 60002, 60002, 60002) != 0
        {
            return Err(io::Error::last_os_error());
        }
        #[repr(C)]
        struct Header {
            version: u32,
            pid: i32,
        }
        #[repr(C)]
        #[derive(Clone, Copy)]
        struct Data {
            effective: u32,
            permitted: u32,
            inheritable: u32,
        }
        let header = Header {
            version: 0x2008_0522,
            pid: 0,
        };
        let data = [Data {
            effective: 0,
            permitted: 0,
            inheritable: 0,
        }; 2];
        if libc::syscall(libc::SYS_capset, &header, data.as_ptr()) != 0 {
            return Err(io::Error::last_os_error());
        }
    }
    Ok(())
}

#[test]
#[ignore = "explicit actual Root source DATA descriptor custody qualification"]
fn root_source_data_descriptor_preserves_its_bound_and_all_seals() -> anyhow::Result<()> {
    use std::os::unix::fs::FileExt;

    // This proves only DATA custody, never an issuer, receipt or successful B.
    let bytes = vec![17; INPUT_BOUND];
    anyhow::ensure!(
        crate::authority_host_bootstrap_seal::seal_bytes(&bytes).is_err(),
        "source DATA must not expand the authority bootstrap envelope"
    );
    let mut file = seal_original_source_input(&bytes)?;
    crate::authority_host_bootstrap_seal::validate_sealed(&file, bytes.len() as u64)?;
    let mut observed = Vec::new();
    file.read_to_end(&mut observed)?;
    pretty_assertions::assert_eq!(observed, bytes);
    for error in [
        file.write_at(b"x", 0).unwrap_err(),
        file.set_len(0).unwrap_err(),
        file.set_len(bytes.len() as u64 + 1).unwrap_err(),
    ] {
        pretty_assertions::assert_eq!(error.raw_os_error(), Some(libc::EPERM));
    }
    // SAFETY: this is the live original descriptor; all four seals are final.
    pretty_assertions::assert_eq!(
        unsafe { libc::fcntl(file.as_raw_fd(), libc::F_ADD_SEALS, 0) },
        -1
    );
    pretty_assertions::assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EPERM));
    crate::authority_host_bootstrap_seal::validate_sealed(&file, bytes.len() as u64)?;
    anyhow::ensure!(
        seal_original_source_input(&[]).is_err(),
        "empty source DATA accepted"
    );
    anyhow::ensure!(
        seal_original_source_input(&vec![0; INPUT_BOUND + 1]).is_err(),
        "oversized source DATA accepted"
    );
    Ok(())
}
