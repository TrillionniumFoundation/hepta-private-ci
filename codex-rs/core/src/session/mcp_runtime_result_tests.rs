use std::sync::Arc;

use pretty_assertions::assert_eq;

#[tokio::test]
async fn closed_refresh_gate_rejects_runtime_reads_and_dispatch_preparation() {
    let (session, turn_context) = super::tests::make_session_and_context().await;
    let session = Arc::new(session);
    session.mcp_refresh.close();

    let refresh = session.refresh_mcp_if_dirty().await;
    let readiness = session.wait_for_mcp_server("closed-gate-server").await;
    let prepared = session
        .prepare_mcp_call("closed-gate-server", "closed-gate-tool")
        .await;
    let step = session.mcp_runtime_for_step(&turn_context, &[], &[]).await;

    let errors = [
        refresh.err().map(|error| error.to_string()),
        readiness.err().map(|error| error.to_string()),
        prepared.err().map(|error| error.to_string()),
        step.err().map(|error| error.to_string()),
    ];
    let expected: [Option<String>; 4] =
        std::array::from_fn(|_| Some("MCP runtime refresh semaphore closed".to_string()));
    assert_eq!(errors, expected);
}
