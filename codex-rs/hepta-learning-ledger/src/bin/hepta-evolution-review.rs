//! Root-custody calibration refusal entry point. This program has no promotion API.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() != 2 || args[0] != "--request" {
            return Err("usage: hepta-evolution-review --request ROOT_PROTECTED_JSON".into());
        }
        codex_hepta_learning_ledger::run_local_calibration_review(std::path::Path::new(&args[1]))
    }
    #[cfg(not(target_os = "linux"))]
    Err("the protected local calibration host requires Linux".into())
}
