//! Explicit root administrator bootstrap / open-only private session entry.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::fd::AsFd;
    use std::path::PathBuf;
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .ok_or("initialize, register-writer or serve-session required")?;
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
    if command == "initialize" {
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
    } else if command == "serve-session" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        let text_file = options
            .remove(std::ffi::OsStr::new("--text-ui-registration"))
            .map(PathBuf::from);
        let ui_fd = options.remove(std::ffi::OsStr::new("--text-ui-pidfd"));
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
        codex_hepta_agentd::serve_host_authority_session_with_text(
            &config,
            &registration,
            owner,
            text,
        )?;
    } else {
        return Err("unknown authority command".into());
    }
    Ok(())
}

#[cfg(not(target_os = "linux"))]
fn main() {
    eprintln!("hepta-authority-host requires Linux");
    std::process::exit(1);
}
