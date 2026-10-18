//! Finite original G purposes composed without adding reverse domain dependencies.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        use codex_hepta_agent_components::intelligence_eval as eval;
        use codex_hepta_agent_components::learning_ledger as ledger;
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 {
            let path = std::path::Path::new(&args[1]);
            if args[0] == "--request" {
                return ledger::run_native_generator(path);
            }
            if args[0] == "--freeze-iteration" {
                return ledger::run_native_frozen_generator(path);
            }
            if args[0] == "--paired-preregister" {
                return eval::run_fixed_paired_generator(path);
            }
            if args[0] == "--parameter-profile" {
                return eval::run_fixed_parameter_generator_v3(path);
            }
        }
        if args.len() == 4 && args[0] == "--initialize-key" && args[2] == "--uid" {
            return ledger::initialize_native_generator_key(
                std::path::Path::new(&args[1]),
                args[3].to_str().ok_or("UID encoding")?.parse()?,
            );
        }
    }
    Err("usage: hepta-native-role-generator --request ROOT_PUBLIC_CONTRACT | --freeze-iteration ROOT_FROZEN_REQUEST | --paired-preregister ROOT_G_CONFIG | --parameter-profile ROOT_PARAMETER_CONFIG | --initialize-key USER_PRIVATE_KEY --uid UID".into())
}
