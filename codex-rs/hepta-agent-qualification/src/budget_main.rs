//! Explicit one-attempt cap witness; the ordinary marker binary is unchanged.

mod bootstrap;
mod evidence;
mod policy;
#[path = "budget_probe.rs"]
mod probe;
mod request_wire;

use anyhow::Result;
use anyhow::anyhow;
use clap::Parser;
use evidence::Evidence;
use serde_json::json;
use std::path::PathBuf;

#[derive(Debug, Parser)]
struct Args {
    /// Send one freshly admitted request; omission only displays a plan.
    #[arg(long)]
    run: bool,
    /// New private directory. Existing directories are never resumed as sends.
    #[arg(long)]
    evidence_dir: PathBuf,
    /// Must match the installed configured model; no model/auth replacement.
    #[arg(long)]
    expected_model: String,
    /// Must equal the successful marker's installed provider ID.
    #[arg(long)]
    expected_provider_id: String,
    /// Original marker's scoped-auth policy label; this is not a credential.
    #[arg(long)]
    expected_auth_policy: String,
    /// Original successful marker's exact request-settings evidence digest.
    #[arg(long)]
    expected_request_settings_sha256: String,
    /// Entire local input reservation; not a provider input-token cap.
    #[arg(long)]
    maximum_provider_input_tokens: u64,
    /// Explicit tiny max_output_tokens wire request, 16 through 64 inclusive.
    #[arg(long)]
    requested_wire_output_tokens: u64,
    /// Separate cold original StateRuntime/bootstrap allowance, 1 through 300 seconds.
    #[arg(long, default_value_t = 60)]
    maximum_bootstrap_seconds: u64,
    /// Local stream deadline, at most 120 seconds; not provider cancellation.
    #[arg(long)]
    maximum_elapsed_seconds: u64,
}

impl Args {
    fn validate(&self) -> Result<()> {
        if !self.evidence_dir.is_absolute()
            || self.expected_model.trim().is_empty()
            || self.expected_provider_id.trim().is_empty()
            || !matches!(
                self.expected_auth_policy.as_str(),
                "configured_jwt_only" | "configured_chatgpt_agent_identity"
            )
            || self.expected_request_settings_sha256.len() != 64
            || !self
                .expected_request_settings_sha256
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
            || self
                .expected_request_settings_sha256
                .bytes()
                .all(|byte| byte == b'0')
            || !(1..=65_536).contains(&self.maximum_provider_input_tokens)
            || !(16..=64).contains(&self.requested_wire_output_tokens)
            || !(1..=120).contains(&self.maximum_elapsed_seconds)
            || !(1..=300).contains(&self.maximum_bootstrap_seconds)
        {
            return Err(anyhow!(
                "invalid explicit cap-witness path, model, reservations or deadline"
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
        "schema":"hepta-native-provider-cap-witness-plan:v1",
        "configured_model_must_equal":args.expected_model,
        "configured_provider_must_equal":args.expected_provider_id,
        "auth_policy_must_equal":args.expected_auth_policy,
        "request_settings_evidence_sha256_must_equal":args.expected_request_settings_sha256,
        "maximum_provider_calls":1, "automatic_retry":false,
        "requested_wire_max_output_tokens":args.requested_wire_output_tokens,
        "maximum_provider_input_tokens_reservation":args.maximum_provider_input_tokens,
        "maximum_output_tokens_reservation":args.requested_wire_output_tokens,
        "maximum_stream_seconds":args.maximum_elapsed_seconds,
        "maximum_policy_bootstrap_seconds":args.maximum_bootstrap_seconds,
        "generation_deadline_starts_after_policy_bootstrap":true,
        "provider_cap_support":"unqualified_until_original_route_witness",
        "auth":"unchanged original ConfigBuilder/AuthManager/scoped provider",
        "model_settings":"unchanged configured effort/summary/verbosity/service tier",
        "fixed_task":"list integers 1 through 256 one per line without omissions",
        "success_requires":"original raw response.incomplete reason=max_output_tokens plus valid actual usage within reservations and both original terminal ACKs",
        "ordinary_short_completion_is_proof":false,
        "rejected_cap_may_be_removed":false,
        "incomplete_policy_disposition":"indeterminate_with_original_private_receipt",
        "reservation_release":false,
        "tool_execution":false, "production_token_quota_ledger":false,
        "primary_ab_admission":"not_admitted", "core_linked_for_config_bootstrap":true,
    });
    if !args.run {
        println!("{}", serde_json::to_string(&plan)?);
        return Ok(());
    }
    let evidence = Evidence::create(&args.evidence_dir)?;
    evidence.record("plan.json", &plan)?;
    let report = match probe::run(&args, evidence.clone()).await {
        Ok(report) => report,
        Err(error) => json!({
            "schema":"hepta-native-provider-cap-witness-result:v1",
            "cap_witness_qualified":false, "status":"setup_or_owner_failure",
            "reason":error.to_string(), "automatic_retry":false,
            "failure_phase":error.downcast_ref::<bootstrap::BootstrapFailure>().map(|_| "policy_bootstrap"),
            "provider_transport_invoked":error.downcast_ref::<bootstrap::BootstrapFailure>().map(|_| false),
            "provider_attempt_admitted":error.downcast_ref::<bootstrap::BootstrapFailure>().map(|_| false),
            "primary_ab_admission":"not_admitted", "provider_hard_budget_qualified":false,
        }),
    };
    evidence.record("report.json", &report)?;
    println!("{}", serde_json::to_string(&report)?);
    if report["cap_witness_qualified"] != true {
        return Err(anyhow!(
            "cap witness was refused, inconclusive, contradicted or unresolved; no retry"
        ));
    }
    Ok(())
}
