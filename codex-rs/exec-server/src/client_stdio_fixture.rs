//! A real child process for the unit test's stdio JSON-RPC handshake. The
//! constructor dispatch pattern is also used by tests/common; this avoids
//! timing a PowerShell runtime startup as part of a one-second protocol test.

use std::io::BufRead;
use std::io::Read as _;
use std::io::Write as _;

use anyhow::Context;

pub(crate) const ARGUMENT: &str = "--codex-test-stdio-initialize-fixture";

#[ctor::ctor]
fn dispatch_stdio_fixture() {
    if std::env::args().nth(1).as_deref() != Some(ARGUMENT) {
        return;
    }
    if let Err(error) = run_stdio_fixture() {
        let _ = writeln!(std::io::stderr().lock(), "{error:#}");
        std::process::exit(1);
    }
    std::process::exit(0);
}

fn run_stdio_fixture() -> anyhow::Result<()> {
    let mut input = std::io::stdin().lock();
    let request = read_message(&mut input)?;
    assert_eq!(request["method"], crate::protocol::INITIALIZE_METHOD);
    let id = request.get("id").context("initialize request has an id")?;
    let response = serde_json::json!({
        "id": id,
        "result": {"sessionId": "stdio-test"},
    });
    let mut output = std::io::stdout().lock();
    writeln!(output, "{response}").context("write actual JSON-RPC response")?;
    output.flush().context("flush actual JSON-RPC pipe")?;
    let initialized = read_message(&mut input)?;
    assert_eq!(initialized["method"], crate::protocol::INITIALIZED_METHOD);
    // Stay alive while the client owns the pipe, just like the old shell child.
    std::io::copy(&mut input, &mut std::io::sink()).context("wait for client EOF")?;
    Ok(())
}

fn read_message(input: &mut impl BufRead) -> anyhow::Result<serde_json::Value> {
    let mut line = String::new();
    let length = input
        .take(/*limit*/ 4097)
        .read_line(&mut line)
        .context("read JSON-RPC fixture message")?;
    assert!(length > 0 && length <= 4096 && line.ends_with('\n'));
    serde_json::from_str(&line).context("parse actual JSON-RPC request")
}
