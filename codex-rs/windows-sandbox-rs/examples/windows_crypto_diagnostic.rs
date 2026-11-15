#[cfg(windows)]
#[path = "windows_crypto_diagnostic/win.rs"]
mod win;

fn main() -> anyhow::Result<()> {
    #[cfg(windows)]
    return win::run();
    #[cfg(not(windows))]
    anyhow::bail!("this observation-only diagnostic requires native Windows");
}
