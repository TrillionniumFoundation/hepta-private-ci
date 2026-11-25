//! A real child process for the unit test's stdio JSON-RPC handshake. The
//! constructor dispatch pattern is also used by tests/common; this avoids
//! timing a PowerShell runtime startup as part of a one-second protocol test.

use std::io::BufRead;
use std::io::Read as _;
use std::io::Write as _;

pub(crate) const ARGUMENT: &str = "--codex-test-stdio-initialize-fixture";

#[ctor::ctor]
fn dispatch_stdio_fixture() {
    if std::env::args().nth(1).as_deref() != Some(ARGUMENT) {
        return;
    }
    let mut input = std::io::stdin().lock();
    let request = read_message(&mut input);
    assert_eq!(request["method"], crate::protocol::INITIALIZE_METHOD);
    let id = request.get("id").expect("initialize request has an id");
    let response = serde_json::json!({
        "id": id,
        "result": {"sessionId": "stdio-test"},
    });
    let mut output = std::io::stdout().lock();
    writeln!(output, "{response}").expect("write actual JSON-RPC response");
    output.flush().expect("flush actual JSON-RPC pipe");
    let initialized = read_message(&mut input);
    assert_eq!(initialized["method"], crate::protocol::INITIALIZED_METHOD);
    // Stay alive while the client owns the pipe, just like the old shell child.
    std::io::copy(&mut input, &mut std::io::sink()).expect("wait for client EOF");
    std::process::exit(0);
}

fn read_message(input: &mut impl BufRead) -> serde_json::Value {
    let mut line = String::new();
    let length = input
        .take(/*limit*/ 4097)
        .read_line(&mut line)
        .expect("read JSON-RPC fixture message");
    assert!(length > 0 && length <= 4096 && line.ends_with('\n'));
    serde_json::from_str(&line).expect("parse actual JSON-RPC request")
}
