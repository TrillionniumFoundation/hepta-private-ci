//! Standalone entry to the existing authenticated read-only gateway owner.
//! This binary creates no domain state and provides no mutation authority.
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
            "Usage: hepta-native-gateway --listen 127.0.0.1:PORT --state-root ABSOLUTE_PATH --auth-keyring-account ACCOUNT\nUses the existing immutable runtime owner and OS-keyring authentication. State must already be provisioned by its owner."
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
