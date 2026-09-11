#[path = "../native_cli.rs"]
mod native_cli;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    native_cli::run().await
}
