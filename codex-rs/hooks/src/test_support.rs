//! Passive, explicitly installed observers for cross-crate integration tests.
//!
//! Ordinary hook runtimes have no observer. These records are not public hook
//! events, execution permission, or a guarantee that a background task was joined.

use async_channel::Sender;
use serde_json::Value;

use crate::engine::ConfiguredHandler;
use crate::engine::HandlerRunResult;

pub(crate) const EXECUTOR_COMPLETION_CAPACITY: usize = 8;

/// The actual terminal fields returned by one executor-scoped handler.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutorHookTerminal {
    pub exit_code: Option<i32>,
    pub stdout: String,
    pub stderr: String,
    pub error: Option<String>,
}

/// Identifies one completed handler without manufacturing missing event identity.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ExecutorHookCompletion {
    pub session_id: Option<String>,
    pub turn_id: Option<String>,
    pub handler_id: String,
    pub terminal: ExecutorHookTerminal,
}

pub(crate) fn record_executor_completion(
    observer: &Sender<ExecutorHookCompletion>,
    handler: &ConfiguredHandler,
    input_json: &str,
    turn_id: Option<String>,
    result: &HandlerRunResult,
) {
    let session_id = serde_json::from_str::<Value>(input_json)
        .ok()
        .and_then(|input| {
            input
                .get("session_id")
                .and_then(Value::as_str)
                .map(str::to_owned)
        });
    // try_send never waits for observer capacity or changes the returned result.
    // A missing record causes the observing test's bounded wait to fail.
    let _ = observer.try_send(ExecutorHookCompletion {
        session_id,
        turn_id,
        handler_id: handler.run_id(),
        terminal: ExecutorHookTerminal {
            exit_code: result.exit_code,
            stdout: result.stdout.clone(),
            stderr: result.stderr.clone(),
            error: result.error.clone(),
        },
    });
}
