use codex_hepta_matrixd::MatrixdConfig;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let config = MatrixdConfig::from_process_environment()?;
    codex_hepta_matrixd::run(config).await?;
    Ok(())
}
