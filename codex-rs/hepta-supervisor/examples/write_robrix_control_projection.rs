use std::path::PathBuf;

fn main() -> anyhow::Result<()> {
    let mut arguments = std::env::args_os();
    let program = arguments.next().unwrap_or_default();
    let output_dir = arguments.next().map(PathBuf::from).ok_or_else(|| {
        anyhow::anyhow!(
            "usage: {} OUTPUT_DIRECTORY",
            PathBuf::from(&program).display()
        )
    })?;
    if arguments.next().is_some() {
        anyhow::bail!(
            "usage: {} OUTPUT_DIRECTORY",
            PathBuf::from(program).display()
        );
    }
    codex_hepta_supervisor::write_robrix_control_projection(&output_dir)
}
