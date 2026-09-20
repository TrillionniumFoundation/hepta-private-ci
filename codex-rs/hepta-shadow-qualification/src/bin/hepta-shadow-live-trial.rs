use std::path::PathBuf;
use std::time::Duration;

use codex_hepta_shadow_qualification::QualificationClosure;

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut arguments = std::env::args_os();
    let program = arguments.next().unwrap_or_default();
    let product = required_argument(&mut arguments, &program, "FROZEN_PRODUCT")?;
    let runtime_root = required_argument(&mut arguments, &program, "ABSENT_RUNTIME_ROOT")?;
    if arguments.next().is_some() {
        return Err(argument_error(usage(&program)).into());
    }
    let outcome =
        QualificationClosure::run(product, &runtime_root, Duration::from_secs(120)).await?;
    let trial = outcome.trial();
    let document = serde_json::json!({
        "app_server": {
            "exit_code": trial.app_server_child().exit_code(),
            "http_exchange_count": trial.app_server_http().len(),
            "inbound_message_count": trial.app_server_child().inbound_message_count(),
            "stderr_sha256": trial.app_server_child().stderr_sha256(),
            "stderr_size_bytes": trial.app_server_child().stderr_size_bytes(),
            "stderr_truncated": trial.app_server_child().stderr_truncated(),
            "thread_id": trial.app_server_thread_id(),
            "turn_ids": trial.app_server_turn_ids(),
        },
        "authority": false,
        "enforce": false,
        "exact_closure": outcome.report().exact_closure(),
        "mcp": {
            "exit_code": trial.mcp_child().exit_code(),
            "http_exchange_count": trial.mcp_http().len(),
            "inbound_message_count": trial.mcp_child().inbound_message_count(),
            "stderr_sha256": trial.mcp_child().stderr_sha256(),
            "stderr_size_bytes": trial.mcp_child().stderr_size_bytes(),
            "stderr_truncated": trial.mcp_child().stderr_truncated(),
            "thread_id": trial.mcp_thread_id(),
        },
        "outbound": false,
        "product_receipt_failure_count": outcome.product_receipts().failures().len(),
        "promotion": false,
        "qualification_report_sha256": outcome.report().file_sha256(),
        "report_failures": outcome.report().failures(),
        "run_id": trial.completed().run_id(),
        "run_root": trial.completed().run_root(),
        "runtime_root": runtime_root,
        "terminal_seal_file_sha256": outcome.seal().seal_file_sha256(),
        "terminal_seal_sha256": outcome.seal().terminal_seal_sha256(),
        "terminal_status": outcome.seal().status(),
        "transport_artifact_count": outcome.seal().transport_artifact_count(),
        "transport_evidence_sha256": outcome.seal().transport_evidence_sha256(),
    });
    println!("{}", serde_json::to_string(&document)?);
    if !outcome.report().exact_closure() {
        return Err(std::io::Error::other("qualification did not reach exact closure").into());
    }
    Ok(())
}

fn required_argument(
    arguments: &mut impl Iterator<Item = std::ffi::OsString>,
    program: &std::ffi::OsStr,
    name: &str,
) -> Result<PathBuf, std::io::Error> {
    arguments
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| argument_error(format!("missing {name}; {}", usage(program))))
}

fn argument_error(message: impl Into<String>) -> std::io::Error {
    std::io::Error::new(std::io::ErrorKind::InvalidInput, message.into())
}

fn usage(program: &std::ffi::OsStr) -> String {
    format!(
        "usage: {} FROZEN_PRODUCT ABSENT_RUNTIME_ROOT",
        PathBuf::from(program).display()
    )
}
