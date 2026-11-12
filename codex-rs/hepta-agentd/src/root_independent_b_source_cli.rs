//! Independent source product entry. All three inputs are existing signed data
//! files; this command cannot select a trusted root, role, key or evaluation.

use std::collections::BTreeMap;
use std::ffi::OsStr;
use std::ffi::OsString;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::fd::FromRawFd;
use std::os::unix::fs::FileExt;
use std::os::unix::fs::MetadataExt;
use std::os::unix::fs::OpenOptionsExt;
use std::os::unix::net::UnixDatagram;
use std::path::Path;
use std::path::PathBuf;
use std::time::Duration;

use crate::AgentdError;
use crate::OriginalBSourceIngressStatusV1;
use crate::OriginalBSourceSignedDataV1;

pub fn run_original_independent_b_source_cli(arguments: Vec<OsString>) -> Result<(), AgentdError> {
    let mut arguments = arguments.into_iter();
    let mut options = BTreeMap::new();
    while let Some(key) = arguments.next() {
        let value = arguments
            .next()
            .ok_or_else(|| invalid("missing B source option value"))?;
        if options.insert(key, value).is_some() {
            return Err(invalid("duplicate B source option"));
        }
    }
    let fd = options
        .remove(OsStr::new("--handoff-fd"))
        .and_then(|value| value.into_string().ok())
        .and_then(|value| value.parse::<i32>().ok())
        .filter(|value| *value >= 3)
        .ok_or_else(|| invalid("one inherited B source datagram descriptor is required"))?;
    let source = take(&mut options, "--source-file")?;
    let observed = take(&mut options, "--observer-statement-file")?;
    let policy = take(&mut options, "--generator-policy-file")?;
    if !options.is_empty() {
        return Err(invalid("unknown B source option"));
    }
    // SAFETY: F_GETFD observes the explicitly supplied inherited descriptor.
    if unsafe { libc::fcntl(fd, libc::F_GETFD) } < 0 {
        return Err(io::Error::last_os_error().into());
    }
    // SAFETY: this standalone CLI consumes its one explicitly inherited FD;
    // no other owner is constructed. The receiver checks the actual Root pair.
    let socket = unsafe { UnixDatagram::from_raw_fd(fd) };
    let handoff =
        crate::receive_root_independent_b_source_handoff(socket, Duration::from_secs(30))?;
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let status = runtime.block_on(crate::submit_original_root_b_source(handoff, || {
        // In Retained/NoUpdate this closure is never called: no source bytes
        // are opened, supplied or fabricated to satisfy a skipped B stage.
        Ok(OriginalBSourceSignedDataV1 {
            source: read_existing(&source, 1_048_576)?,
            observed_statement: read_existing(&observed, 16_384)?,
            policy_statement: read_existing(&policy, 16_384)?,
        })
    }))?;
    let result = match status {
        OriginalBSourceIngressStatusV1::RetainedInput { source_digest } => serde_json::json!({
            "source_ingress": "retained_input", "source_digest": source_digest.to_string(),
        }),
        OriginalBSourceIngressStatusV1::AlreadyRetained => serde_json::json!({
            "source_ingress": "already_retained_without_write_right",
        }),
        OriginalBSourceIngressStatusV1::NoUpdate => serde_json::json!({
            "source_ingress": "no_update_without_source_read",
        }),
    };
    let mut output = std::io::stdout().lock();
    writeln!(output, "{result}")?;
    output.flush()?;
    Ok(())
}

fn take(options: &mut BTreeMap<OsString, OsString>, name: &str) -> Result<PathBuf, AgentdError> {
    let path = options
        .remove(OsStr::new(name))
        .map(PathBuf::from)
        .ok_or_else(|| invalid("original B source file path is required"))?;
    if !path.is_absolute() {
        return Err(invalid("absolute B source paths required"));
    }
    Ok(path)
}

fn read_existing(path: &Path, maximum: usize) -> io::Result<Vec<u8>> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK)
        .open(path)?;
    let identity = file.metadata()?;
    // SAFETY: getuid only observes this independent process's actual UID.
    if !identity.is_file()
        || identity.uid() != unsafe { libc::getuid() }
        || identity.mode() & 0o7777 != 0o600
        || identity.nlink() != 1
        || identity.len() == 0
        || identity.len() > maximum as u64
    {
        return Err(io::Error::other(
            "existing private bounded B signed input required",
        ));
    }
    file.try_lock_shared().map_err(io::Error::other)?;
    let result = (|| {
        let mut previous = None;
        for _ in 0..2 {
            let before = file.metadata()?;
            let mut bytes = vec![0; identity.len() as usize];
            file.read_exact_at(&mut bytes, /*offset*/ 0)?;
            let after = file.metadata()?;
            let named = std::fs::symlink_metadata(path)?;
            if image(&before) != image(&identity)
                || image(&after) != image(&identity)
                || image(&named) != image(&identity)
                || previous.as_ref().is_some_and(|old| old != &bytes)
            {
                return Err(io::Error::other(
                    "original B signed input changed during read",
                ));
            }
            previous = Some(bytes);
        }
        previous.ok_or_else(|| io::Error::other("B source input was not read"))
    })();
    let unlocked = file.unlock();
    drop(file);
    let bytes = result?;
    unlocked?;
    Ok(bytes)
}

fn image(meta: &std::fs::Metadata) -> (u64, u64, u64, u32, u32, u64, i64, i64, i64, i64) {
    (
        meta.dev(),
        meta.ino(),
        meta.len(),
        meta.uid(),
        meta.mode(),
        meta.nlink(),
        meta.mtime(),
        meta.mtime_nsec(),
        meta.ctime(),
        meta.ctime_nsec(),
    )
}

fn invalid(message: &str) -> AgentdError {
    AgentdError::Protocol(message.into())
}
