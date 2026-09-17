use std::path::PathBuf;

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_hepta_supervisor::SignedIntentRecoveryDirective;
use codex_hepta_supervisor::SignedIntentStatus;
use codex_hepta_supervisor::read_signed_intent;
use codex_hepta_supervisor::write_signed_intent_recovery_directive;

fn main() -> Result<()> {
    let mut args = std::env::args_os().skip(1);
    let command = args
        .next()
        .and_then(|value| value.into_string().ok())
        .context("usage: hepta-supervisor-intent-recovery <inspect|abort> <run-root> [intent-sha256]")?;
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
            let expected_digest = args
                .next()
                .and_then(|value| value.into_string().ok())
                .context("abort requires the exact intent-sha256 shown by inspect")?;
            if args.next().is_some() {
                bail!("abort accepts <run-root> <intent-sha256>");
            }
            let intent = read_signed_intent(&run_root)?
                .context("no signed supervisor intent exists at this run root")?;
            if !matches!(
                intent.status,
                SignedIntentStatus::Prepared
                    | SignedIntentStatus::Queued
                    | SignedIntentStatus::RecoveryRequired
            ) {
                bail!("signed supervisor intent is already terminal: {:?}", intent.status);
            }
            if intent.intent_sha256.as_str() != expected_digest {
                bail!(
                    "intent digest changed; inspect again before issuing an abort directive"
                );
            }
            let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
            write_signed_intent_recovery_directive(&run_root, &directive)?;
            println!("{}", serde_json::to_string_pretty(&directive)?);
        }
        _ => bail!("unknown command {command:?}; expected inspect or abort"),
    }
    Ok(())
}
