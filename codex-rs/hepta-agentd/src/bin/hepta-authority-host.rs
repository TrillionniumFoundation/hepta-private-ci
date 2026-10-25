//! Explicit Root administration, fresh publication and open-only session entry.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::fd::AsFd;
    use std::path::PathBuf;
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .ok_or("initialize, register-writer, serve-session, serve-fresh-session, diagnose-native, launch-native, provider-status or provider-login required")?;
    let mut options = std::collections::BTreeMap::new();
    let mut pidfd_stdin = false;
    while let Some(option) = args.next() {
        if option == "--owner-pidfd-stdin" {
            if pidfd_stdin {
                return Err("duplicate owner pidfd option".into());
            }
            pidfd_stdin = true;
        } else {
            let value = args.next().ok_or("missing option value")?;
            if options.insert(option, value).is_some() {
                return Err("duplicate option".into());
            }
        }
    }
    let mut take = |key: &str| {
        options
            .remove(std::ffi::OsStr::new(key))
            .map(PathBuf::from)
            .ok_or("missing required option")
    };
    if command == "provider-status" || command == "provider-login" {
        let route = take("--route")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("provider command accepts only the original --route file".into());
        }
        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()?;
        let result = if command == "provider-status" {
            runtime
                .block_on(codex_hepta_agentd::text_session::diagnose_existing_provider(&route))?
        } else {
            runtime.block_on(codex_hepta_agentd::text_session::login_existing_provider(
                &route,
                |challenge| {
                    // Only the original one-time login challenge is displayed.
                    // No credential file, token, email or account ID is printed.
                    if let Ok(json) = serde_json::to_string(&challenge) {
                        println!("{json}");
                    }
                },
            ))?
        };
        println!("{}", serde_json::to_string(&result)?);
    } else if command == "diagnose-native" || command == "launch-native" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let profile = take("--native-profile")?;
        if !options.is_empty() || !pidfd_stdin {
            return Err("existing config, registration, native profile and pre-held owner pidfd are required".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        if command == "diagnose-native" {
            println!(
                "{}",
                serde_json::to_string(&codex_hepta_agentd::diagnose_native_launch(
                    &config,
                    &registration,
                    &profile,
                    &owner
                )?)?
            );
        } else {
            codex_hepta_agentd::launch_host_authority_native_session(
                &config,
                &registration,
                &profile,
                owner,
            )?;
        }
    } else if command == "initialize" {
        let state = take("--state")?;
        let bootstrap = take("--bootstrap")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("unknown initialize option".into());
        }
        let initialized = codex_hepta_agentd::initialize_host_authority(&state, &bootstrap)?;
        println!("{}", serde_json::to_string(&initialized)?);
    } else if command == "register-writer" {
        let config = take("--config")?;
        if !options.is_empty() || pidfd_stdin {
            return Err("unknown register-writer option".into());
        }
        let proof = codex_hepta_agentd::register_host_writer_authorization(&config)?;
        println!("{}", serde_json::to_string(&proof)?);
    } else if command == "serve-session" || command == "serve-fresh-session" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let text_file = options
            .remove(std::ffi::OsStr::new("--text-ui-registration"))
            .map(PathBuf::from);
        let ui_fd = options.remove(std::ffi::OsStr::new("--text-ui-pidfd"));
        let handoff = options.remove(std::ffi::OsStr::new("--root-handoff-fd"));
        let root_fd = options.remove(std::ffi::OsStr::new("--root-pidfd"));
        let notes_profile = options
            .remove(std::ffi::OsStr::new("--notes-launch-profile"))
            .map(PathBuf::from);
        let notes_reservation = options.remove(std::ffi::OsStr::new("--notes-reservation-fd"));
        let notes_session = options.remove(std::ffi::OsStr::new("--notes-session-pidfd"));
        let notes_deployment = options.remove(std::ffi::OsStr::new("--notes-deployment-fd"));
        if !options.is_empty() || !pidfd_stdin {
            return Err("unknown option or missing pre-held owner pidfd".into());
        }
        // Claim every numeric inherited FD before any clone/open/runtime can
        // reuse a missing number. One slot owns each FD and closes the original.
        let mut claimed = std::collections::BTreeSet::new();
        let handoff = handoff
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let root_fd = root_fd
            .as_deref()
            .map(|fd| inherited_descriptor(fd, &mut claimed))
            .transpose()?;
        let notes = match (notes_profile, notes_reservation, notes_session, notes_deployment) {
            (None, None, None, None) => None,
            (Some(profile), Some(reservation), Some(session), Some(deployment))
                if command == "serve-fresh-session" => Some((
                    profile, inherited_descriptor(&reservation, &mut claimed)?,
                    inherited_descriptor(&session, &mut claimed)?, inherited_descriptor(&deployment, &mut claimed)?,
                )),
            _ => return Err("fresh Notes requires its complete inherited reservation, Session pidfd, deployment memfd and Root profile".into()),
        };
        let text = match (text_file.as_deref(), ui_fd) {
            (None, None) => None,
            (Some(file), Some(fd)) => Some((file, inherited_descriptor(&fd, &mut claimed)?)),
            _ => {
                return Err("text UI registration and pre-held pidfd are required together".into());
            }
        };
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        let prepared = if command == "serve-fresh-session" {
            let handoff =
                handoff.ok_or("fresh session requires the original Root handoff descriptor")?;
            let root = root_fd.ok_or("fresh session requires the pre-held current Root pidfd")?;
            let runtime = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()?;
            let prepared = runtime.block_on(
                codex_hepta_agentd::PreparedHostAuthoritySession::prepare_fresh_from_registered(
                    &config,
                    &registration,
                    owner,
                ),
            )?;
            let (prepared, consumers) = prepared.handoff_fresh_agent_filesystem()?;
            let prepared = match notes {
                Some((profile, reservation, session, deployment)) => prepared
                    .with_notes_startup_from_session(
                        &profile,
                        std::os::unix::net::UnixDatagram::from(reservation),
                        session,
                        std::fs::File::from(deployment),
                    )?,
                None => prepared,
            };
            let bootstrap = prepared.seal_bootstrap(&consumers)?;
            codex_hepta_agentd::send_root_production_handoff(
                std::os::unix::net::UnixDatagram::from(handoff),
                &bootstrap,
                &root,
                std::time::Duration::from_secs(30),
            )?;
            prepared
        } else {
            if handoff.is_some() || root_fd.is_some() {
                return Err("open-only serving does not accept fresh handoff inputs".into());
            }
            codex_hepta_agentd::PreparedHostAuthoritySession::open(&config, &registration, owner)?
        };
        match text {
            Some((file, pidfd)) => prepared.serve_with_text(file, pidfd)?,
            None => prepared.serve()?,
        }
    } else {
        return Err("unknown authority command".into());
    }
    Ok(())
}

#[cfg(target_os = "linux")]
fn inherited_descriptor(
    value: &std::ffi::OsStr,
    claimed: &mut std::collections::BTreeSet<i32>,
) -> Result<std::os::fd::OwnedFd, Box<dyn std::error::Error>> {
    use std::os::fd::FromRawFd;
    let fd: i32 = value
        .to_str()
        .ok_or("invalid inherited descriptor")?
        .parse()?;
    if fd < 3 || !claimed.insert(fd) {
        return Err(
            "one distinct inherited descriptor numbered at least 3 is required per slot".into(),
        );
    }
    // SAFETY: all numeric descriptors are claimed before any runtime, open or
    // stdin clone. No Rust owner exists for these inherited descriptors yet.
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: this is the first and only owner of the checked inherited FD;
    // the per-parse set rejects aliases before a second adoption is possible.
    let descriptor = unsafe { std::os::fd::OwnedFd::from_raw_fd(fd) };
    // SAFETY: the now-owned descriptor remains live across this flags update.
    if unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    Ok(descriptor)
}

#[cfg(all(test, target_os = "linux"))]
#[path = "../root_cli_descriptor_tests.rs"]
mod descriptor_tests;

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("hepta-authority-host requires Linux");
    std::process::exit(1);
}
