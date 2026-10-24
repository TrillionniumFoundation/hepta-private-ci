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
        if !options.is_empty() || !pidfd_stdin {
            return Err("unknown option or missing pre-held owner pidfd".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        let text = match (text_file.as_deref(), ui_fd) {
            (None, None) => None,
            (Some(file), Some(fd)) => {
                let fd: i32 = fd.to_str().ok_or("invalid UI pidfd")?.parse()?;
                if fd < 3 {
                    return Err("UI pidfd must be a separately inherited descriptor".into());
                }
                // SAFETY: F_GETFD only checks a numeric descriptor; startup is
                // single-threaded and nothing closes it before the clone.
                if unsafe { libc::fcntl(fd, libc::F_GETFD) } < 0 {
                    return Err(std::io::Error::last_os_error().into());
                }
                // SAFETY: the existence check above precedes this immediate
                // clone. The original channel independently checks pidfd type,
                // actual PID and liveness against the Root registration.
                let borrowed = unsafe { std::os::fd::BorrowedFd::borrow_raw(fd) };
                Some((file, borrowed.try_clone_to_owned()?))
            }
            _ => {
                return Err("text UI registration and pre-held pidfd are required together".into());
            }
        };
        let prepared = if command == "serve-fresh-session" {
            let handoff = inherited_descriptor(handoff.as_deref().ok_or("fresh session requires the original Root handoff descriptor")?)?;
            let root = inherited_descriptor(root_fd.as_deref().ok_or("fresh session requires the pre-held current Root pidfd")?)?;
            let runtime = tokio::runtime::Builder::new_current_thread().enable_all().build()?;
            let prepared = runtime.block_on(codex_hepta_agentd::PreparedHostAuthoritySession::prepare_fresh_from_registered(
                &config, &registration, owner,
            ))?;
            let (prepared, consumers) = prepared.handoff_fresh_agent_filesystem()?;
            let bootstrap = prepared.seal_bootstrap(&consumers)?;
            codex_hepta_agentd::send_root_production_handoff(
                std::os::unix::net::UnixDatagram::from(handoff), &bootstrap, &root,
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
fn inherited_descriptor(value: &std::ffi::OsStr) -> Result<std::os::fd::OwnedFd, Box<dyn std::error::Error>> {
    let fd: i32 = value.to_str().ok_or("invalid inherited descriptor")?.parse()?;
    if fd < 3 {
        return Err("a separately inherited descriptor numbered at least 3 is required".into());
    }
    // SAFETY: F_GETFD checks only a descriptor number. Parsing occurs before
    // runtime threads, and no operation closes this descriptor before cloning.
    if unsafe { libc::fcntl(fd, libc::F_GETFD) } < 0 {
        return Err(std::io::Error::last_os_error().into());
    }
    // SAFETY: the live inherited descriptor is immediately cloned. The
    // original handoff independently checks socket type, Root creator, sealed
    // file and pidfd lifetime before any authenticated bootstrap is accepted.
    let borrowed = unsafe { std::os::fd::BorrowedFd::borrow_raw(fd) };
    Ok(borrowed.try_clone_to_owned()?)
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("hepta-authority-host requires Linux");
    std::process::exit(1);
}
