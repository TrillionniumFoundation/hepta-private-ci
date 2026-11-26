use super::*;
use pretty_assertions::assert_eq;
use tokio::io::AsyncReadExt;

#[tokio::test]
async fn issuer_diagnostics_report_real_disconnected_body_without_error_text() -> anyhow::Result<()>
{
    let (mut server, client) = tokio::net::UnixStream::pair()?;
    drop(client);
    let progress = Progress::new();
    progress.enter(Stage::ReadBody);
    let mut bytes = [0; 4];
    let result = server
        .read_exact(&mut bytes)
        .await
        .map(|_| ())
        .map_err(anyhow::Error::from);
    assert_eq!(
        progress.diagnostic(Ok(result)),
        Some(
            "ordinary model issuer rejection stage=request-body-read category=unexpected-eof"
                .into()
        )
    );
    Ok(())
}

#[test]
fn issuer_diagnostics_discard_caller_json_and_nested_error_displays() -> anyhow::Result<()> {
    let progress = Progress::new();
    progress.enter(Stage::Decode);
    let error = serde_json::from_slice::<u64>(b"\"private-caller-text\"")
        .err()
        .ok_or_else(|| anyhow::anyhow!("expected rejected input"))?;
    let error = anyhow::Error::from(error).context("private-authority-context");
    assert_eq!(
        progress.diagnostic(Ok(Err(error))),
        Some("ordinary model issuer rejection stage=request-decode category=json-data".into())
    );
    progress.enter(Stage::TrustLoad);
    let error = anyhow::Error::from(std::io::Error::new(
        std::io::ErrorKind::PermissionDenied,
        "private-file-and-key-name",
    ))
    .context("private-request-context");
    assert_eq!(
        progress.diagnostic(Ok(Err(error))),
        Some("ordinary model issuer rejection stage=trust-load category=permission-denied".into())
    );
    Ok(())
}

#[tokio::test]
async fn issuer_diagnostics_keep_the_blocked_stage_at_the_original_timeout() {
    let progress = Progress::new();
    progress.enter(Stage::PeerRecheck);
    let result = tokio::time::timeout(
        std::time::Duration::from_millis(1),
        std::future::pending::<anyhow::Result<()>>(),
    )
    .await;
    assert_eq!(
        progress.diagnostic(result),
        Some("ordinary model issuer rejection stage=peer-recheck category=timeout".into())
    );
}

#[test]
fn issuer_diagnostics_preserve_policy_rejection_and_success_without_details() {
    let progress = Progress::new();
    progress.enter(Stage::TrustMutation);
    assert_eq!(
        progress.diagnostic(Ok(Err(anyhow::anyhow!("private-state-rejected")))),
        Some(
            "ordinary model issuer rejection stage=trust-mutation category=policy-or-state".into()
        )
    );
    assert_eq!(progress.diagnostic(Ok(Ok(()))), None);
}
