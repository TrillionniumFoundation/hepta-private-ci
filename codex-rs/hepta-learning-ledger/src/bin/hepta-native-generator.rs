//! Unprivileged native decision generator; no outcome or activation API.
fn main() -> Result<(), Box<dyn std::error::Error>> {
    #[cfg(target_os = "linux")]
    {
        let args = std::env::args_os().skip(1).collect::<Vec<_>>();
        if args.len() == 2 && args[0] == "--request" {
            return codex_hepta_learning_ledger::run_native_generator(std::path::Path::new(
                &args[1],
            ));
        }
        if args.len() == 4 && args[0] == "--initialize-key" && args[2] == "--uid" {
            return codex_hepta_learning_ledger::initialize_native_generator_key(
                std::path::Path::new(&args[1]),
                args[3].to_str().ok_or("UID encoding")?.parse()?,
            );
        }
        Err("usage: hepta-native-generator --request ROOT_PUBLIC_CONTRACT | --initialize-key USER_PRIVATE_KEY --uid UID".into())
    }
    #[cfg(not(target_os = "linux"))]
    Err("the fixed evaluation controllers require Linux".into())
}
