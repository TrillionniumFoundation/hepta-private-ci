mod common;

use std::path::Path;

use anyhow::Result;
use anyhow::bail;
use base64::Engine as _;
use base64::engine::general_purpose::STANDARD;
use codex_exec_server::ExecServerClient;
use codex_exec_server::ExecServerError;
use codex_exec_server::FileSystemSandboxContext;
use codex_exec_server::FsReadFileAuthorizedParams;
use codex_exec_server::RemoteExecServerConnectArgs;
use codex_http_client::HttpClientFactory;
use codex_http_client::OutboundProxyPolicy;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_path_uri::PathUri;

use common::exec_server::exec_server;

const ALLOWED: &[u8] = b"ALLOWED";
const SECRET: &[u8] = b"SECRET";

fn read_only_sandbox(root: &Path) -> Result<FileSystemSandboxContext> {
    let root = AbsolutePathBuf::from_absolute_path(root)?;
    let policy = FileSystemSandboxPolicy::restricted(vec![FileSystemSandboxEntry::new(
        FileSystemPath::Path {
            path: PathUri::from_abs_path(&root),
        },
        FileSystemAccessMode::Read,
    )]);
    let permissions =
        PermissionProfile::from_runtime_permissions(&policy, NetworkSandboxPolicy::Restricted);
    Ok(FileSystemSandboxContext::from_permission_profile_with_cwd(
        permissions,
        PathUri::from_abs_path(&root),
    ))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn authorized_read_rpc_is_capability_gated_and_denies_outside_root() -> Result<()> {
    let mut server = exec_server().await?;
    let client = ExecServerClient::connect_websocket(RemoteExecServerConnectArgs::new(
        server.websocket_url().to_string(),
        "authorized-read-rpc-test".to_string(),
        HttpClientFactory::new(OutboundProxyPolicy::ReqwestDefault),
    ))
    .await?;

    let temp = tempfile::tempdir()?;
    let allowed_dir = temp.path().join("allowed");
    let denied_dir = temp.path().join("denied");
    std::fs::create_dir_all(&allowed_dir)?;
    std::fs::create_dir_all(&denied_dir)?;
    let allowed_file = allowed_dir.join("allowed.txt");
    let denied_file = denied_dir.join("secret.txt");
    std::fs::write(&allowed_file, ALLOWED)?;
    std::fs::write(&denied_file, SECRET)?;

    let sandbox = read_only_sandbox(&allowed_dir)?;
    let info = client.environment_info().await?;
    let allowed = client
        .fs_read_file_authorized(FsReadFileAuthorizedParams {
            path: PathUri::from_host_native_path(&allowed_file)?,
            sandbox: sandbox.clone(),
            max_bytes: ALLOWED.len() as u64,
        })
        .await;

    assert_eq!(
        info.capabilities.stable_handle_authorized_read,
        allowed.is_ok(),
        "capability advertisement must match a valid authorized-read RPC"
    );
    match allowed {
        Ok(response) => assert_eq!(STANDARD.decode(response.data_base64)?, ALLOWED),
        Err(ExecServerError::Server { code, message }) => {
            assert_eq!(code, -32603);
            assert_eq!(message, "bounded authorized file reads are unsupported");
        }
        Err(error) => bail!("unexpected authorized-read failure: {error:?}"),
    }

    let denied = client
        .fs_read_file_authorized(FsReadFileAuthorizedParams {
            path: PathUri::from_host_native_path(&denied_file)?,
            sandbox,
            max_bytes: SECRET.len() as u64,
        })
        .await
        .expect_err("outside-root read must fail closed");
    if info.capabilities.stable_handle_authorized_read {
        let ExecServerError::Server { code, message } = &denied else {
            bail!("expected policy rejection, got {denied:?}");
        };
        assert_eq!(*code, -32600);
        assert_eq!(message, "Permission denied");
    }
    assert!(!denied.to_string().contains("secret.txt"));

    drop(client);
    server.shutdown().await?;
    Ok(())
}
