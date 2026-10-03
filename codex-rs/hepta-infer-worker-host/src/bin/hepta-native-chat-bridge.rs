//! The Root chat composition has one protected config, never an execution command.
#[cfg(all(target_os = "linux", feature = "native-chat-bridge"))]
#[path = "../chat_root.rs"]
mod root;

#[cfg(all(target_os = "linux", feature = "native-chat-bridge"))]
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let mut args = std::env::args_os().skip(1);
    let option = args.next();
    #[cfg(feature = "root-frozen-generator")]
    if option.as_deref() == Some(std::ffi::OsStr::new("--generator-configuration")) {
        let path = args
            .next()
            .ok_or_else(|| anyhow::anyhow!("missing Generator configuration"))?;
        anyhow::ensure!(
            args.next().is_none(),
            "unsupported Generator bridge argument"
        );
        return codex_hepta_infer_worker_host::RootFrozenGeneratorServiceV1::open(path.into())
            .await?
            .serve()
            .await;
    }
    anyhow::ensure!(
        option.as_deref() == Some(std::ffi::OsStr::new("--configuration")),
        "expected --configuration ROOT_CONFIG"
    );
    let path = args
        .next()
        .ok_or_else(|| anyhow::anyhow!("missing Root configuration"))?;
    anyhow::ensure!(args.next().is_none(), "unsupported chat bridge argument");
    let host = std::sync::Arc::new(root::RootChatHost::open(path.into())?);
    host.serve().await
}

#[cfg(not(all(target_os = "linux", feature = "native-chat-bridge")))]
fn main() -> anyhow::Result<()> {
    anyhow::bail!("native chat bridge requires the explicit Linux product feature")
}
