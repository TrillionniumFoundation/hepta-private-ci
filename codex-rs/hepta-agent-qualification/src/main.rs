//! Isolated live qualification executable. Core is linked solely to bootstrap
//! the installed configuration; this executable is not a Core-free RSS sample.

mod evidence;
mod policy;
mod probe;

use anyhow::Result;
use anyhow::anyhow;
use clap::Parser;
use evidence::Evidence;
use serde_json::json;
use std::path::PathBuf;

#[derive(Debug, Parser)]
struct Args {
    /// Send exactly one provider request. Without this flag, only report the plan.
    #[arg(long)]
    run: bool,
    /// New private directory for qualification evidence; existing paths fail closed.
    #[arg(long)]
    evidence_dir: PathBuf,
    /// Must equal the actual model resolved by the installed configuration.
    #[arg(long)]
    expected_model: String,
    /// Local reservation, not a provider wire-level input-token cap.
    #[arg(long)]
    maximum_provider_input_tokens: u64,
    /// Local reservation, not a provider wire-level output-token cap.
    #[arg(long)]
    maximum_output_tokens: u64,
    /// Local stream deadline, bounded to at most 120 seconds.
    #[arg(long)]
    maximum_elapsed_seconds: u64,
}

impl Args {
    fn validate(&self) -> Result<()> {
        if !self.evidence_dir.is_absolute()
            || self.expected_model.trim().is_empty()
            || !(1..=65_536).contains(&self.maximum_provider_input_tokens)
            || !(1..=4_096).contains(&self.maximum_output_tokens)
            || !(1..=120).contains(&self.maximum_elapsed_seconds)
        {
            return Err(anyhow!(
                "invalid explicit qualification model, path or budget"
            ));
        }
        Ok(())
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let args = Args::parse();
    args.validate()?;
    let plan = json!({
        "schema":"hepta-native-provider-qualification:v1",
        "configured_model_must_equal":args.expected_model,
        "maximum_provider_calls":1,
        "maximum_provider_input_tokens_reservation":args.maximum_provider_input_tokens,
        "maximum_output_tokens_reservation":args.maximum_output_tokens,
        "maximum_stream_seconds":args.maximum_elapsed_seconds,
        "provider_hard_token_caps":"not_exposed_by_current_request_schema",
        "auth":"existing Core ConfigBuilder + AuthManager + scoped ModelProvider",
        "policy":"existing Hepta governance Enforce contributor, isolated evidence",
        "compiled_context":"empty; fixed qualification task resides in admitted API template",
        "tool_execution":false, "production_turn_owner":false,
        "core_linked_for_config_bootstrap":true, "core_free_memory_comparison":false,
    });
    if !args.run {
        println!("{}", serde_json::to_string(&plan)?);
        return Ok(());
    }
    let evidence = Evidence::create(&args.evidence_dir)?;
    evidence.record("plan.json", &plan)?;
    let result = probe::run(&args, evidence.clone()).await;
    let report = match result {
        Ok(report) => report,
        Err(error) => json!({
            "schema":"hepta-native-provider-qualification-result:v1",
            "qualified":false, "status":"setup_or_owner_failure",
            "reason_code":"qualification_setup_or_owner_failed",
            // Auth, config, endpoint and provider errors are mapped to static
            // strings at their boundary; no credentials enter this message.
            "reason":error.to_string(),
            "automatic_retry":false,
            "note":"Inspect original private evidence; absence of a terminal receipt is unresolved.",
        }),
    };
    evidence.record("report.json", &report)?;
    println!("{}", serde_json::to_string(&report)?);
    if report.get("qualified").and_then(serde_json::Value::as_bool) != Some(true) {
        return Err(anyhow!(
            "native provider qualification did not complete successfully"
        ));
    }
    Ok(())
}
