//! Explicit original descriptors and bounded operation inputs for one launch.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::ffi::OsString;
use std::fs::File;
use std::io::Read;
use std::io::Seek;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;
use std::os::unix::net::UnixDatagram;
use std::time::Duration;
use std::time::Instant;

use crate::AgentdError;

const FLAGS: [&str; 15] = [
    "--root-production-profile",
    "--root-production-handoff-fd", "--root-production-uid", "--root-production-gid",
    "--root-production-control-fd", "--root-production-app-server-fd",
    "--android-runtime-server", "--android-runtime-environment",
    "--android-original-payload-fd", "--android-original-deadline-ns",
    "--notes-production-handoff-fd", "--root-production-lifetime-ms",
    "--notes-literal-deployment-fd", "--notes-literal-ui-fd", "--notes-session-pidfd",
];

pub(super) struct LaunchInputs {
    pub(super) handoff: UnixDatagram,
    pub(super) uid: u32,
    pub(super) gid: u32,
    pub(super) control: OwnedFd,
    pub(super) app_server: OwnedFd,
    pub(super) primary: PrimaryInputs,
    pub(super) bootstrap_deadline: Instant,
    pub(super) notes: Option<UnixDatagram>,
    pub(super) notes_ui: Option<NotesUiInputs>,
    pub(super) lifetime: Duration,
}

pub(super) enum PrimaryInputs {
    Android { server: String, environment: String, payload: File, deadline: Instant },
    Notes,
}

pub(super) struct NotesUiInputs {
    pub(super) deployment: File,
    pub(super) listener: OwnedFd,
    pub(super) session_pidfd: OwnedFd,
}

/// Ordinary daemon arguments remain byte-for-byte intact. Partial production
/// selections fail before taking any descriptor or dropping credentials.
pub(super) fn parse(
    arguments: Vec<OsString>,
) -> Result<(Option<LaunchInputs>, Vec<OsString>), AgentdError> {
    let mut selected = BTreeMap::new();
    let mut ordinary = Vec::new();
    let mut arguments = arguments.into_iter();
    while let Some(flag) = arguments.next() {
        let value = arguments.next()
            .ok_or_else(|| invalid("Agentd arguments require a value"))?;
        match flag.to_str().filter(|flag| FLAGS.contains(flag)) {
            Some(name) => {
                if selected.insert(name.to_string(), value).is_some() {
                    return Err(invalid("duplicate original production launch flag"));
                }
            }
            None => ordinary.extend([flag, value]),
        }
    }
    if selected.is_empty() {
        return Ok((None, ordinary));
    }
    let profile = selected.remove("--root-production-profile")
        .unwrap_or_else(|| OsString::from("android"));
    let notes_primary = match profile.to_str() {
        Some("android") => false,
        Some("notes") => true,
        _ => return Err(invalid("original production profile must be android or notes")),
    };
    let mut take = |name: &str| selected.remove(name)
        .ok_or_else(|| invalid(format!("missing {name} for original production launch")));
    let handoff = descriptor_number(take("--root-production-handoff-fd")?)?;
    let uid = number(take("--root-production-uid")?, "original owner UID")?;
    let gid = number(take("--root-production-gid")?, "original owner GID")?;
    if matches!(uid, 0 | u32::MAX) || matches!(gid, 0 | u32::MAX) {
        return Err(invalid("original production launch requires a dedicated non-Root owner"));
    }
    let control = descriptor_number(take("--root-production-control-fd")?)?;
    let app_server = descriptor_number(take("--root-production-app-server-fd")?)?;
    let android = if notes_primary {
        None
    } else {
        let server = identifier(take("--android-runtime-server")?)?;
        let environment = identifier(take("--android-runtime-environment")?)?;
        let payload = descriptor_number(take("--android-original-payload-fd")?)?;
        let end = number::<u64>(take("--android-original-deadline-ns")?, "original monotonic deadline")?;
        Some((server, environment, payload, original_deadline(end)?))
    };
    let notes = selected.remove("--notes-production-handoff-fd").map(descriptor_number).transpose()?;
    let notes_deployment = selected.remove("--notes-literal-deployment-fd").map(descriptor_number).transpose()?;
    let notes_listener = selected.remove("--notes-literal-ui-fd").map(descriptor_number).transpose()?;
    let notes_session = selected.remove("--notes-session-pidfd").map(descriptor_number).transpose()?;
    let notes_ui = match (notes_deployment, notes_listener, notes_session) {
        (None, None, None) => None,
        (Some(deployment), Some(listener), Some(session)) if notes.is_some() => Some((deployment, listener, session)),
        _ => return Err(invalid("original Notes UI requires all three descriptors and the application handoff")),
    };
    if notes_primary && (notes.is_none() || notes_ui.is_none()) {
        return Err(invalid("original Notes profile requires its real application and UI capabilities"));
    }
    let lifetime = selected.remove("--root-production-lifetime-ms")
        .map(|value| number::<u64>(value, "original Root lifetime"))
        .transpose()?.unwrap_or(300_000);
    if lifetime == 0 || lifetime > 300_000 {
        return Err(invalid("original Root lifetime exceeds its bound"));
    }
    if !selected.is_empty() {
        return Err(invalid("original profile contains incompatible production inputs"));
    }
    let payload = android.as_ref().map(|(_, _, payload, _)| *payload);
    let numbers = [Some(handoff), Some(control), Some(app_server), payload, notes,
        notes_deployment, notes_listener, notes_session]
        .into_iter().flatten().collect::<Vec<_>>();
    if numbers.iter().copied().collect::<BTreeSet<_>>().len() != numbers.len() {
        return Err(invalid("original production descriptors must be distinct"));
    }
    // Notes has no Android effect expiry to borrow or renew. Its startup uses
    // the existing handoff's fixed 30-second bound; each later Notes action has
    // its own original protected source/sender deadline.
    let bootstrap_deadline = android.as_ref().map(|(_, _, _, deadline)| *deadline)
        .unwrap_or_else(|| Instant::now() + Duration::from_secs(30));
    // All numeric and pairing checks precede ownership transfer. CLOEXEC keeps
    // inherited authority out of unrelated App Server helper re-executions.
    let handoff = UnixDatagram::from(take_descriptor(handoff)?);
    let control = take_descriptor(control)?;
    let app_server = take_descriptor(app_server)?;
    let primary = match android {
        Some((server, environment, payload, deadline)) => PrimaryInputs::Android {
            server, environment, payload: File::from(take_descriptor(payload)?), deadline,
        },
        None => PrimaryInputs::Notes,
    };
    let notes = notes.map(take_descriptor).transpose()?.map(UnixDatagram::from);
    let notes_ui = notes_ui.map(|(deployment, listener, session)| {
        Ok::<_, AgentdError>(NotesUiInputs {
            deployment: File::from(take_descriptor(deployment)?),
            listener: take_descriptor(listener)?,
            session_pidfd: take_descriptor(session)?,
        })
    }).transpose()?;
    Ok((Some(LaunchInputs {
        handoff, uid, gid, control, app_server, primary, bootstrap_deadline,
        notes, notes_ui, lifetime: Duration::from_millis(lifetime),
    }), ordinary))
}

fn descriptor_number(value: OsString) -> Result<i32, AgentdError> {
    let value = number::<i32>(value, "original descriptor")?;
    if value < 3 { return Err(invalid("standard streams are not production capabilities")); }
    Ok(value)
}

fn number<T: std::str::FromStr>(value: OsString, label: &str) -> Result<T, AgentdError> {
    value.to_str().and_then(|value| value.parse().ok())
        .ok_or_else(|| invalid(format!("invalid {label}")))
}

fn identifier(value: OsString) -> Result<String, AgentdError> {
    let value = value.into_string().map_err(|_| invalid("MCP selection must be UTF-8"))?;
    if value.is_empty() || value.len() > 128
        || !value.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._-".contains(&byte))
    {
        return Err(invalid("MCP selection must name an existing server and environment"));
    }
    Ok(value)
}

fn take_descriptor(number: i32) -> Result<OwnedFd, AgentdError> {
    // SAFETY: F_GETFD/F_SETFD inspect and tighten the validated inherited FD.
    // The trusted launcher transfers its ownership exactly once through CLI;
    // duplicates and standard streams were rejected before this function.
    let flags = unsafe { libc::fcntl(number, libc::F_GETFD) };
    if flags < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the same validated inherited descriptor remains live; setting
    // CLOEXEC only narrows its inheritance and does not take ownership.
    if unsafe { libc::fcntl(number, libc::F_SETFD, flags | libc::FD_CLOEXEC) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the trusted launcher transferred this descriptor to this entry;
    // all duplicate numbers were rejected before any ownership was taken.
    Ok(unsafe { OwnedFd::from_raw_fd(number) })
}

fn original_deadline(end: u64) -> Result<Instant, AgentdError> {
    // Sample Instant first, so conversion may shorten but cannot renew the
    // original launcher's absolute CLOCK_MONOTONIC deadline.
    let local = Instant::now();
    let mut clock = libc::timespec { tv_sec: 0, tv_nsec: 0 };
    // SAFETY: clock_gettime initializes one correctly sized stack timespec.
    if unsafe { libc::clock_gettime(libc::CLOCK_MONOTONIC, &mut clock) } != 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    let now = u64::try_from(clock.tv_sec).ok()
        .and_then(|seconds| seconds.checked_mul(1_000_000_000))
        .and_then(|seconds| u64::try_from(clock.tv_nsec).ok().and_then(|ns| seconds.checked_add(ns)))
        .ok_or_else(|| invalid("original monotonic clock is unavailable"))?;
    let remaining = end.checked_sub(now).filter(|value| *value > 0 && *value <= 30_000_000_000)
        .ok_or_else(|| invalid("original Android deadline expired or exceeds 30 seconds"))?;
    Ok(local + Duration::from_nanos(remaining))
}

pub(super) fn read_payload(mut file: File) -> Result<String, AgentdError> {
    let size = file.metadata()?.len();
    if size == 0 || size > 16 * 1024 { return Err(invalid("original Android payload exceeds its bound")); }
    crate::authority_host_bootstrap_seal::validate_sealed(&file, size)?;
    file.rewind()?;
    let mut bytes = Vec::with_capacity(size as usize);
    file.take(size + 1).read_to_end(&mut bytes)?;
    if bytes.len() as u64 != size { return Err(invalid("original Android payload changed while reading")); }
    let payload = String::from_utf8(bytes).map_err(|_| invalid("original Android payload is not UTF-8"))?;
    codex_hepta_memory::AndroidSetTextV1::from_json(&payload).map_err(AgentdError::Invalid)?;
    Ok(payload)
}

fn invalid(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}

#[cfg(test)]
#[path = "production_launcher_inputs_tests.rs"]
mod tests;
