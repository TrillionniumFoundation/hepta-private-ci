//! CLI separation keeps the default plan free of configuration/authentication I/O.

use crate::Args;
use anyhow::Result;
use anyhow::anyhow;
use clap::Parser;
use std::path::PathBuf;

#[derive(Debug, Parser)]
pub(crate) struct CommandLine {
    /// Send exactly one provider request. Without an action flag, only report the plan.
    #[arg(long, conflicts_with = "inspect")]
    run: bool,
    /// Inspect installed owners with an Offline model catalog; auth may initialize/refresh.
    #[arg(long, conflicts_with_all = ["run", "maximum_provider_input_tokens", "maximum_output_tokens", "maximum_elapsed_seconds"])]
    inspect: bool,
    /// New private evidence directory; existing paths fail closed for either action.
    #[arg(long)]
    evidence_dir: PathBuf,
    /// Must equal the model resolved by the installed configuration.
    #[arg(long)]
    expected_model: String,
    /// Local input reservation for the generation plan/run, not a provider hard cap.
    #[arg(long, required_unless_present = "inspect")]
    maximum_provider_input_tokens: Option<u64>,
    /// Local output reservation for the generation plan/run, not a provider hard cap.
    #[arg(long, required_unless_present = "inspect")]
    maximum_output_tokens: Option<u64>,
    /// Local generation-stream deadline, at most 120 seconds.
    #[arg(long, required_unless_present = "inspect")]
    maximum_elapsed_seconds: Option<u64>,
    /// Wait bound for each inspection owner setup step (default 20; at most 60 seconds).
    #[arg(long, requires = "inspect")]
    inspection_setup_seconds: Option<u64>,
}

pub(crate) enum Command {
    Qualification(Args),
    Inspect(InspectionArgs),
}

pub(crate) struct InspectionArgs {
    pub(crate) evidence_dir: PathBuf,
    pub(crate) expected_model: String,
    pub(crate) setup_seconds: u64,
}

impl CommandLine {
    pub(crate) fn into_command(self) -> Result<Command> {
        if self.inspect {
            let setup_seconds = self.inspection_setup_seconds.unwrap_or(20);
            if !self.evidence_dir.is_absolute()
                || self.expected_model.trim().is_empty()
                || !(1..=60).contains(&setup_seconds)
            {
                return Err(anyhow!(
                    "invalid explicit inspection model, path or setup deadline"
                ));
            }
            return Ok(Command::Inspect(InspectionArgs {
                evidence_dir: self.evidence_dir,
                expected_model: self.expected_model,
                setup_seconds,
            }));
        }
        let missing = || anyhow!("generation plan/run requires explicit reservations and deadline");
        Ok(Command::Qualification(Args {
            run: self.run,
            evidence_dir: self.evidence_dir,
            expected_model: self.expected_model,
            maximum_provider_input_tokens: self
                .maximum_provider_input_tokens
                .ok_or_else(missing)?,
            maximum_output_tokens: self.maximum_output_tokens.ok_or_else(missing)?,
            maximum_elapsed_seconds: self.maximum_elapsed_seconds.ok_or_else(missing)?,
        }))
    }
}
