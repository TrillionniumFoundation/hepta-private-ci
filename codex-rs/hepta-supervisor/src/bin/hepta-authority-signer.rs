//! Offline external-authority signer.
//!
//! This binary is intentionally separate from `hepta-supervisord`.  It never
//! starts a daemon, never generates a key, and refuses to sign unless the
//! caller supplies the explicit `--sign` acknowledgement plus an external key
//! file/FD.  Signed material is emitted only to stdout.

use std::io::Write;
use std::path::PathBuf;

use anyhow::Context;
use codex_hepta_supervisor::load_signing_key_from_fd;
use codex_hepta_supervisor::load_signing_key_from_path;
use codex_hepta_supervisor::read_request;
use codex_hepta_supervisor::sign_request;

const USAGE: &str = "usage: hepta-authority-signer --sign [--key-file ABSOLUTE_PATH | --key-fd FD] [--request ABSOLUTE_PATH|-]";

fn main() -> anyhow::Result<()> {
    let options = parse_options()?;
    if !options.sign {
        anyhow::bail!(
            "refusing to sign: pass explicit --sign (this tool never signs by default)\n{USAGE}"
        );
    }
    if options.key_file.is_some() == options.key_fd.is_some() {
        anyhow::bail!(
            "exactly one external key source (--key-file or --key-fd) is required\n{USAGE}"
        );
    }
    if options.key_fd == Some(0)
        && options
            .request
            .as_deref()
            .is_none_or(|path| path == std::path::Path::new("-"))
    {
        anyhow::bail!("--key-fd 0 cannot be combined with request stdin");
    }

    let request = read_request(options.request.as_deref()).context("read signing request")?;
    let key = match (options.key_file, options.key_fd) {
        (Some(path), None) => load_signing_key_from_path(&path),
        (None, Some(fd)) => load_signing_key_from_fd(fd),
        _ => anyhow::bail!("exactly one external key source is required"),
    }
    .context("load external signing key")?;
    let response = sign_request(&request, &key).context("sign request")?;

    let stdout = std::io::stdout();
    let mut locked = stdout.lock();
    serde_json::to_writer(&mut locked, &response).context("serialize signed response")?;
    locked.write_all(b"\n").context("write signed response")?;
    locked.flush().context("flush signed response")?;
    Ok(())
}

struct Options {
    sign: bool,
    key_file: Option<PathBuf>,
    key_fd: Option<i32>,
    request: Option<PathBuf>,
}

fn parse_options() -> anyhow::Result<Options> {
    let mut arguments = std::env::args_os().skip(1);
    let mut options = Options {
        sign: false,
        key_file: None,
        key_fd: None,
        request: None,
    };
    while let Some(argument) = arguments.next() {
        match argument.to_str() {
            Some("--sign") if !options.sign => options.sign = true,
            Some("--key-file") if options.key_file.is_none() => {
                let value = arguments
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("--key-file requires a value\n{USAGE}"))?;
                options.key_file = Some(PathBuf::from(value));
            }
            Some("--key-fd") if options.key_fd.is_none() => {
                let value = arguments
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("--key-fd requires a value\n{USAGE}"))?;
                let value = value
                    .to_str()
                    .ok_or_else(|| anyhow::anyhow!("--key-fd is not UTF-8\n{USAGE}"))?;
                options.key_fd = Some(
                    value
                        .parse::<i32>()
                        .map_err(|error| anyhow::anyhow!("invalid --key-fd: {error}\n{USAGE}"))?,
                );
            }
            Some("--request") if options.request.is_none() => {
                let value = arguments
                    .next()
                    .ok_or_else(|| anyhow::anyhow!("--request requires a value\n{USAGE}"))?;
                options.request = Some(PathBuf::from(value));
            }
            Some("--help") | Some("-h") => {
                println!("{USAGE}");
                std::process::exit(0);
            }
            _ => anyhow::bail!("unknown or duplicate option {argument:?}\n{USAGE}"),
        }
    }
    Ok(options)
}
