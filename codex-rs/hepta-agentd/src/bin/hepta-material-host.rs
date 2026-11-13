//! Ordinary Material process for supervisor-provisioned original descriptors.
//! No fixture, path fallback, key generation, owner discovery or reconnect.

#[cfg(target_os = "linux")]
fn main() {
    if let Err(error) = linux::run() {
        eprintln!("hepta-material-host: {error}");
        std::process::exit(1);
    }
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("hepta-material-host requires the original Linux protected transport");
    std::process::exit(1);
}

#[cfg(target_os = "linux")]
mod linux {
    use std::collections::{BTreeMap, BTreeSet};
    use std::fs::File;
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
    use std::os::unix::net::UnixStream;
    use codex_hepta_agentd::{CellQ24ModelFilesV1, OriginalMaterialChannelFilesV1,
        OriginalMaterialHostFilesV1, serve_original_material_host_from_files};

    const REQUIRED: [&str; 31] = [
        "--config-fd", "--evidence-trust-fd", "--trust-root-fd", "--trust-distribution-fd",
        "--ledger-fd", "--ledger-witness-fd", "--ledger-directory-fd", "--ledger-witness-directory-fd",
        "--experience-fd", "--experience-witness-fd", "--dataset-fd", "--dataset-witness-fd",
        "--experience-key-fd", "--dataset-key-fd", "--model-base-fd", "--model-encoder-fd", "--model-heads-fd",
        "--source-stream-fd", "--source-root-pidfd", "--workflow-stream-fd", "--workflow-root-pidfd",
        "--experience-command-stream-fd", "--experience-command-peer-pidfd",
        "--dataset-command-stream-fd", "--dataset-command-peer-pidfd",
        "--experience-readback-stream-fd", "--experience-readback-peer-pidfd",
        "--dataset-readback-stream-fd", "--dataset-readback-peer-pidfd",
        "--dataset-source-stream-fd", "--dataset-source-peer-pidfd",
    ];
    const OPTIONAL: [&str; 2] = ["--model-organ-fd", "--model-cell-fd"];

    pub(super) fn run() -> Result<(), String> {
        let arguments = std::env::args_os().skip(1).map(|value| value.into_string()
            .map_err(|_| "Material descriptor argument is not UTF-8".to_owned()))
            .collect::<Result<Vec<_>, _>>()?;
        let raw = parse(&arguments)?;
        let mut held = claim(raw)?;
        let files = OriginalMaterialHostFilesV1 {
            configuration: file(&mut held, "--config-fd")?,
            evidence_trust: file(&mut held, "--evidence-trust-fd")?,
            trust_root: file(&mut held, "--trust-root-fd")?,
            signed_distribution: file(&mut held, "--trust-distribution-fd")?,
            ledger: file(&mut held, "--ledger-fd")?,
            ledger_witness: file(&mut held, "--ledger-witness-fd")?,
            ledger_directory: file(&mut held, "--ledger-directory-fd")?,
            witness_directory: file(&mut held, "--ledger-witness-directory-fd")?,
            experience: file(&mut held, "--experience-fd")?,
            experience_witness: file(&mut held, "--experience-witness-fd")?,
            dataset: file(&mut held, "--dataset-fd")?,
            dataset_witness: file(&mut held, "--dataset-witness-fd")?,
            experience_key: file(&mut held, "--experience-key-fd")?,
            dataset_key: file(&mut held, "--dataset-key-fd")?,
            baseline: CellQ24ModelFilesV1 {
                base: file(&mut held, "--model-base-fd")?,
                organ_adapter: held.remove("--model-organ-fd").map(File::from),
                cell_adapter: held.remove("--model-cell-fd").map(File::from),
                encoder: file(&mut held, "--model-encoder-fd")?,
                heads: file(&mut held, "--model-heads-fd")?,
            },
            source: channel(&mut held, "--source-stream-fd", "--source-root-pidfd")?,
            workflow: channel(&mut held, "--workflow-stream-fd", "--workflow-root-pidfd")?,
            experience_command: channel(&mut held, "--experience-command-stream-fd", "--experience-command-peer-pidfd")?,
            dataset_command: channel(&mut held, "--dataset-command-stream-fd", "--dataset-command-peer-pidfd")?,
            experience_readback: channel(&mut held, "--experience-readback-stream-fd", "--experience-readback-peer-pidfd")?,
            dataset_readback: channel(&mut held, "--dataset-readback-stream-fd", "--dataset-readback-peer-pidfd")?,
            dataset_source: channel(&mut held, "--dataset-source-stream-fd", "--dataset-source-peer-pidfd")?,
        };
        if !held.is_empty() { return Err("unconsumed original Material descriptors".to_owned()); }
        serve_original_material_host_from_files(files).map_err(|error| error.to_string())
    }

    fn parse(arguments: &[String]) -> Result<BTreeMap<String, RawFd>, String> {
        if arguments.len() < REQUIRED.len() * 2 || arguments.len() > (REQUIRED.len() + OPTIONAL.len()) * 2
            || arguments.len() % 2 != 0
        { return Err("all original Material descriptor flags are required exactly once".to_owned()); }
        let mut result = BTreeMap::new();
        let mut descriptors = BTreeSet::new();
        for pair in arguments.chunks_exact(2) {
            let name = &pair[0];
            let text = &pair[1];
            if !REQUIRED.contains(&name.as_str()) && !OPTIONAL.contains(&name.as_str()) {
                return Err("unknown original Material descriptor flag".to_owned());
            }
            if text.is_empty() || text.len() > 10 || !text.bytes().all(|byte| byte.is_ascii_digit()) {
                return Err("original Material descriptor is not canonical numeric input".to_owned());
            }
            let fd = text.parse::<RawFd>().map_err(|_| "invalid Material descriptor".to_owned())?;
            if fd < 3 || fd.to_string() != *text || !descriptors.insert(fd) || result.insert(name.clone(), fd).is_some() {
                return Err("aliased or repeated original Material descriptor".to_owned());
            }
        }
        if REQUIRED.iter().any(|name| !result.contains_key(*name)) {
            return Err("missing original Material descriptor".to_owned());
        }
        Ok(result)
    }

    fn claim(raw: BTreeMap<String, RawFd>) -> Result<BTreeMap<String, OwnedFd>, String> {
        for fd in raw.values() {
            // SAFETY: F_GETFD observes this proposed integer; no ownership is
            // claimed until the complete distinct set is present and open.
            if unsafe { libc::fcntl(*fd, libc::F_GETFD) } < 0 {
                return Err("one original Material descriptor is not open".to_owned());
            }
        }
        let held = raw.into_iter().map(|(name, fd)| {
            // SAFETY: the supervisor transferred this open fd to this process;
            // parse checked the complete set and distinct integers. This is
            // its only ownership conversion; there is no inherited alias API.
            (name, unsafe { OwnedFd::from_raw_fd(fd) })
        }).collect::<BTreeMap<_, _>>();
        for fd in held.values() {
            // SAFETY: these calls only set close-on-exec on owned live fds.
            let flags = unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_GETFD) };
            if flags < 0 || unsafe { libc::fcntl(fd.as_raw_fd(), libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
                return Err("could not retain original Material descriptors privately".to_owned());
            }
        }
        Ok(held)
    }

    fn take(held: &mut BTreeMap<String, OwnedFd>, name: &str) -> Result<OwnedFd, String> {
        held.remove(name).ok_or_else(|| "original Material descriptor was already consumed".to_owned())
    }
    fn file(held: &mut BTreeMap<String, OwnedFd>, name: &str) -> Result<File, String> {
        take(held, name).map(File::from)
    }
    fn channel(held: &mut BTreeMap<String, OwnedFd>, stream: &str, peer: &str) -> Result<OriginalMaterialChannelFilesV1, String> {
        Ok(OriginalMaterialChannelFilesV1 { stream: UnixStream::from(take(held, stream)?), original_peer_pidfd: take(held, peer)? })
    }
}
