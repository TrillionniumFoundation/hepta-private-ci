use std::path::PathBuf;

use anyhow::Result;
use codex_hepta_native_app::update::run_update_helper;

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let flag = args.next();
    let job = args.next();
    if flag.as_deref() != Some(std::ffi::OsStr::new("--job")) || args.next().is_some() {
        anyhow::bail!("usage: hepta-native-updater --job <absolute-job-path>");
    }
    let job = job
        .map(PathBuf::from)
        .ok_or_else(|| anyhow::anyhow!("missing update job path"))?;
    if !job.is_absolute() {
        anyhow::bail!("update job path must be absolute");
    }
    run_update_helper(&job).map_err(|error| anyhow::anyhow!(error.to_string()))
}
