use std::path::PathBuf;

use codex_hepta_contracts::Sha256Digest;
use codex_hepta_supervisor::RecoveryDiagnosticContext;
use codex_hepta_supervisor::diagnose_recovery;

fn main() -> anyhow::Result<()> {
    let options = parse_options()?;
    let diagnostic = diagnose_recovery(
        &options.run_root,
        &RecoveryDiagnosticContext {
            live_process_present: options.live_process_present,
            observed_release: options.observed_release,
            current_authority_epoch: options.current_authority_epoch,
            current_admission_frontier_sha256: options.current_admission_frontier_sha256,
        },
    );
    println!("{}", serde_json::to_string_pretty(&diagnostic)?);
    if diagnostic.recovery_required {
        std::process::exit(2);
    }
    Ok(())
}

struct Options {
    run_root: PathBuf,
    live_process_present: bool,
    observed_release: Option<String>,
    current_authority_epoch: Option<u64>,
    current_admission_frontier_sha256: Option<Sha256Digest>,
}

fn parse_options() -> anyhow::Result<Options> {
    let mut arguments = std::env::args_os().skip(1);
    let run_root = arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| anyhow::anyhow!(usage()))?;
    if !run_root.is_absolute() {
        anyhow::bail!("run root must be absolute");
    }
    let mut live_process_present = false;
    let mut observed_release = None;
    let mut current_authority_epoch = None;
    let mut current_admission_frontier_sha256 = None;
    while let Some(flag) = arguments.next() {
        match flag.to_str() {
            Some("--live-process-present") if !live_process_present => {
                live_process_present = true;
            }
            Some("--observed-release") if observed_release.is_none() => {
                observed_release = Some(next_utf8(&mut arguments, "observed release")?);
            }
            Some("--authority-epoch") if current_authority_epoch.is_none() => {
                current_authority_epoch = Some(
                    next_utf8(&mut arguments, "authority epoch")?
                        .parse::<u64>()
                        .map_err(|error| anyhow::anyhow!("invalid authority epoch: {error}"))?,
                );
            }
            Some("--admission-frontier-sha256")
                if current_admission_frontier_sha256.is_none() =>
            {
                current_admission_frontier_sha256 = Some(
                    Sha256Digest::parse(next_utf8(&mut arguments, "admission frontier")?)
                        .map_err(|error| anyhow::anyhow!(error.to_string()))?,
                );
            }
            _ => anyhow::bail!(usage()),
        }
    }
    Ok(Options {
        run_root,
        live_process_present,
        observed_release,
        current_authority_epoch,
        current_admission_frontier_sha256,
    })
}

fn next_utf8(
    arguments: &mut impl Iterator<Item = std::ffi::OsString>,
    label: &str,
) -> anyhow::Result<String> {
    arguments
        .next()
        .ok_or_else(|| anyhow::anyhow!("missing {label}"))?
        .into_string()
        .map_err(|_| anyhow::anyhow!("{label} is not UTF-8"))
}

fn usage() -> &'static str {
    "usage: hepta-supervisor-recovery-diagnose ABSOLUTE_RUN_ROOT [--live-process-present] [--observed-release RELEASE] [--authority-epoch N] [--admission-frontier-sha256 SHA256]"
}
