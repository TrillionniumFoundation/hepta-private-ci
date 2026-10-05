//! Existing authenticated gateway with distinct enrolled lifecycle and chat purposes.
//! Domain effects and authorization remain with the original Supervisor owner.
fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native-gateway: {error:#}");
        std::process::exit(1);
    }
}

fn run() -> anyhow::Result<()> {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    if arguments == ["--help"] || arguments == ["-h"] {
        println!(
            "Usage: hepta-native-gateway --listen 127.0.0.1:PORT --auth-keyring-account ACCOUNT [--observer-socket ABSOLUTE_PATH --observer-owner-uid UID | --state-root ABSOLUTE_PATH]\nOptional Fleet lifecycle: --controller-socket ABSOLUTE_PATH --controller-owner-uid UID --lifecycle-auth-keyring-account ACCOUNT.\nOptional Fleet chat: --chat-socket ABSOLUTE_PATH --chat-owner-uid 0 --chat-auth-keyring-account ACCOUNT. Dedicated service may use --auth-capability-file PATH, --lifecycle-capability-file PATH and --chat-capability-file PATH.\nReads the enrolled Fleet observer or the existing immutable legacy runtime through OS-keyring authentication. Each effect purpose requires its own capability."
        );
        return Ok(());
    }
    let mut gateway = vec!["--serve-ui".to_owned()];
    gateway.extend(arguments);
    if !codex_hepta_native_gateway::run_serve_ui_if_requested(&gateway)? {
        anyhow::bail!("native gateway invocation was not accepted");
    }
    Ok(())
}
