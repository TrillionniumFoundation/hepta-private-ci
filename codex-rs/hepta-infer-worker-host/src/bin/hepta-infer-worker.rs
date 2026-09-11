#[cfg(feature = "native-app-server")]
#[path = "../native_cli.rs"]
mod native_cli;

#[cfg(feature = "native-app-server")]
#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    native_cli::run().await
}

#[cfg(not(feature = "native-app-server"))]
fn main() {
    eprintln!(
        "hepta-infer-worker requires the native-app-server feature; use --features native-app-server"
    );
    std::process::exit(64);
}
