use std::time::Instant;

use clap::Parser;

#[derive(Debug, Parser)]
struct Cli {
    /// Transport endpoint: `stdio`, `stdio://`, `ws://IP:PORT`, or `grpc://IP:PORT`.
    #[arg(
        long,
        value_name = "URL",
        default_value = codex_code_mode_host::DEFAULT_LISTEN_URL
    )]
    listen: String,
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    // The Tokio runtime has already been constructed before this body starts.
    let startup_started = Instant::now();
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .with_writer(std::io::stderr)
        .with_ansi(false)
        .init();
    tracing::info!(
        phase = "tracing_ready",
        elapsed_ms = startup_started.elapsed().as_millis(),
        "code-mode host startup phase"
    );

    let cli = Cli::parse();
    tracing::info!(
        phase = "arguments_ready",
        elapsed_ms = startup_started.elapsed().as_millis(),
        "code-mode host startup phase"
    );
    codex_code_mode_host::run_main(&cli.listen).await
}
