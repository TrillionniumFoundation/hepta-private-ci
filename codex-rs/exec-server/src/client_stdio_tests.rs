use crate::client_api::StdioExecServerCommand;
use std::collections::HashMap;
use std::io::BufRead;
use std::io::Write;

const STDIO_FIXTURE_ARG: &str = "--codex-test-stdio-json-rpc-peer";

pub(crate) fn stdio_command() -> StdioExecServerCommand {
    StdioExecServerCommand {
        program: std::env::current_exe()
            .expect("resolve native test executable")
            .to_string_lossy()
            .into_owned(),
        args: vec![STDIO_FIXTURE_ARG.to_string()],
        env: HashMap::new(),
        cwd: None,
    }
}

// Dispatch before the test harness writes to stdout, which belongs to JSON-RPC.
// The peer performs the real pipe handshake without depending on shell startup.
#[ctor::ctor]
fn dispatch_stdio_fixture() {
    if std::env::args_os().nth(1).as_deref() != Some(std::ffi::OsStr::new(STDIO_FIXTURE_ARG)) {
        return;
    }
    if let Err(error) = run_stdio_fixture() {
        eprintln!("native stdio fixture failed: {error}");
        std::process::exit(1);
    }
    std::process::exit(0);
}

fn run_stdio_fixture() -> std::io::Result<()> {
    let mut input = std::io::stdin().lock();
    let mut output = std::io::stdout().lock();
    let mut line = String::new();
    input.read_line(&mut line)?;
    let request: serde_json::Value = serde_json::from_str(&line)?;
    if request["method"] != "initialize" || request["id"].is_null() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "expected initialize request with an id",
        ));
    }
    writeln!(
        output,
        "{}",
        serde_json::json!({"id": request["id"], "result": {"sessionId": "stdio-test"}})
    )?;
    output.flush()?;

    line.clear();
    input.read_line(&mut line)?;
    let notification: serde_json::Value = serde_json::from_str(&line)?;
    if notification["method"] != "initialized" || !notification["id"].is_null() {
        return Err(std::io::Error::new(
            std::io::ErrorKind::InvalidData,
            "expected initialized notification",
        ));
    }
    // Remain connected until the client closes its input pipe.
    std::io::copy(&mut input, &mut std::io::sink())?;
    Ok(())
}

#[cfg(not(windows))]
#[tokio::test]
async fn native_stdio_peer_initializes_json_rpc_client() {
    let client = crate::client::ExecServerClient::connect_stdio_command(
        crate::client_api::StdioExecServerConnectArgs {
            command: stdio_command(),
            client_name: "stdio-test-client".to_string(),
            initialize_timeout: std::time::Duration::from_secs(1),
            resume_session_id: None,
        },
    )
    .await
    .expect("native stdio client should connect");
    pretty_assertions::assert_eq!(client.session_id().as_deref(), Some("stdio-test"));
}
