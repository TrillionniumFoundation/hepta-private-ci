//! Explicit root administrator bootstrap / open-only private session entry.

#[cfg(target_os = "linux")]
fn main() -> Result<(), Box<dyn std::error::Error>> {
    use std::os::fd::AsFd;
    use std::path::PathBuf;
    let mut args = std::env::args_os().skip(1);
    let command = args.next().ok_or("initialize or serve-session required")?;
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
    } else if command == "serve-session" {
        let config = take("--config")?;
        let registration = take("--registration")?;
        if !options.is_empty() || !pidfd_stdin {
            return Err("unknown option or missing pre-held owner pidfd".into());
        }
        let owner = std::io::stdin().as_fd().try_clone_to_owned()?;
        codex_hepta_agentd::serve_host_authority_session(&config, &registration, owner)?;
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
