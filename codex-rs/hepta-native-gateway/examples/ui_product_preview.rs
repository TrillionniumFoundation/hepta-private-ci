//! Developer entry for the actual gateway. This never initializes owner state.
fn main() -> anyhow::Result<()> {
    let args = std::env::args().skip(1).collect::<Vec<_>>();
    anyhow::ensure!(
        codex_hepta_native_gateway::run_serve_ui_if_requested(&args)?,
        "Pass --serve-ui with explicit bundle, manifest digest, state root and loopback address"
    );
    Ok(())
}
