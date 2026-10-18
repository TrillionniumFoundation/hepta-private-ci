//! Fixed-purpose local evaluation controller; no selection or activation API.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() != 2 || args[0] != "--request" {
            return Err("usage: hepta-custody-evaluator --request ROOT_PRIVATE_REQUEST".into());
        }
        codex_hepta_learning_ledger::run_fixed_custody_evaluator(std::path::Path::new(&args[1]))
    }
    #[cfg(not(target_os = "linux"))]
    Err("the fixed evaluation controllers require Linux".into())
}
