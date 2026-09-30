use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_supervisor::read_signed_intent;

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .and_then(|value| value.into_string().ok())
        .context(
            "usage: hepta-supervisor-intent-recovery <inspect|abort> <run-root> [intent-sha256]",
        )?;
    let run_root = PathBuf::from(args.next().context(
        "usage: hepta-supervisor-intent-recovery <inspect|abort> <run-root> [intent-sha256]",
    )?);

    match command.as_str() {
        "inspect" => {
            if args.next().is_some() {
                bail!("inspect accepts only <run-root>");
            }
            let intent = read_signed_intent(&run_root)?
                .context("no signed supervisor intent exists at this run root")?;
            println!("{}", serde_json::to_string_pretty(&intent)?);
        }
        "abort" => {
            bail!(
                "unsigned abort directives cannot resolve an ambiguous signed effect; use supervisord's independently signed recovery ceremony"
            )
        }
        _ => bail!("unknown command {command:?}; expected inspect or abort"),
    }
    Ok(())
}
