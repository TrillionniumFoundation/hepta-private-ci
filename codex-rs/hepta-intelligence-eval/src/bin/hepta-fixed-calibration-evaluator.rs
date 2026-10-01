//! Fixed independent evaluator; never accepts arbitrary metrics or sign payloads.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 5 && args[0] == "--inspect-initial-operational-anchor" {
            let inspected =
                codex_hepta_intelligence_eval::inspect_initial_neuron_operational_evidence(
                    std::path::Path::new(&args[1]),
                    args[2].to_str().ok_or("config digest")?.parse()?,
                    std::path::Path::new(&args[3]),
                    args[4].to_str().ok_or("report digest")?.parse()?,
                )?;
            inspected.revalidate_current()?;
            println!(
                "{}",
                serde_json::json!({"schema":"hepta.cpu-neuron.current-initial-operational-inspection.v1",
                "authentication_digest":inspected.authentication_digest().to_string(),
                "model_manifest_digest":inspected.model_manifest_digest().to_string(),
                "weights_digest":inspected.weights_digest().to_string(),
                "qualified":false,"authority_grants_any":false,"production_activation":false})
            );
            return Ok(());
        }
        if args.len() == 2 && args[0] == "--initial-operational-anchor" {
            return codex_hepta_intelligence_eval::run_initial_neuron_operational_evaluator(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 2 && args[0] == "--request" {
            return codex_hepta_intelligence_eval::run_fixed_calibration_evaluator(
                std::path::Path::new(&args[1]),
            );
        }
        if args.len() == 6
            && args[0] == "--initialize-key"
            && args[2] == "--uid"
            && args[4] == "--gid"
        {
            return codex_hepta_intelligence_eval::initialize_fixed_evaluator_key(
                std::path::Path::new(&args[1]),
                args[3].to_str().ok_or("uid")?.parse()?,
                args[5].to_str().ok_or("gid")?.parse()?,
            );
        }
        Err("usage: hepta-fixed-calibration-evaluator --request ROOT_CONFIG | --initialize-key PRIVATE_KEY --uid UID --gid GID".into())
    }
    #[cfg(not(target_os = "linux"))]
    Err("fixed evaluation requires Linux".into())
}
