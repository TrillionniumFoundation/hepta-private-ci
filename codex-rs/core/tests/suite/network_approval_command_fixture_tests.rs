//! Complete network commands without assuming that approval precedes exec's first yield.

use super::decoded_request_body;
use super::guardian_request_is_for;
use anyhow::Context;
use anyhow::Result;
use core_test_support::responses::ResponseMock;
use core_test_support::responses::ev_assistant_message;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_function_call;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::sse;
use core_test_support::responses::sse_response;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Request;
use wiremock::matchers::method;
use wiremock::matchers::path_regex;

const MAX_POLLS: usize = 9;

#[derive(Clone, Copy, Debug)]
pub(super) enum ExpectedCompletion {
    ProcessExit,
    GuardianDenial(&'static str),
}

#[derive(Debug, PartialEq, Eq)]
enum CommandProgress {
    Running(i32),
    Completed,
}

#[path = "network_approval_command_progress_tests.rs"]
mod progress_tests;

fn latest_output(body: &Value, call_id: &str) -> Option<(String, String)> {
    if body
        .pointer("/client_metadata/x-openai-subagent")
        .and_then(Value::as_str)
        == Some("guardian")
    {
        return None;
    }
    let input = body.get("input")?.as_array()?;
    for item in input.iter().rev() {
        // A new user turn must not consume a previous turn's command completion.
        if item.get("role").and_then(Value::as_str) == Some("user") {
            return None;
        }
        if item.get("type").and_then(Value::as_str) != Some("function_call_output") {
            continue;
        }
        let output_id = item.get("call_id")?.as_str()?;
        if output_id != call_id && !output_id.starts_with(&format!("{call_id}-poll-")) {
            return None;
        }
        return Some((
            output_id.to_string(),
            item.get("output")?.as_str()?.to_string(),
        ));
    }
    None
}

fn request_output(request: &Request, call_id: &str) -> Option<(String, String)> {
    let body = decoded_request_body(request)?;
    let body: Value = serde_json::from_slice(&body).ok()?;
    latest_output(&body, call_id)
}

fn process_header_value(output: &str, prefix: &str) -> Option<i32> {
    let (header, _) = output.split_once("\nOutput:")?;
    // ExecCommandToolOutput starts with an optional chunk ID, then wall time.
    // Status-looking lines inside an unrelated tool error are not process headers.
    if !header.starts_with("Chunk ID: ") && !header.starts_with("Wall time: ") {
        return None;
    }
    header
        .lines()
        .find_map(|line| line.strip_prefix(prefix)?.parse().ok())
}

fn command_progress(
    output: &str,
    output_id: &str,
    call_id: &str,
    expected: ExpectedCompletion,
) -> Option<CommandProgress> {
    if output_id != call_id {
        let poll = output_id
            .strip_prefix(&format!("{call_id}-poll-"))?
            .parse::<usize>()
            .ok()?;
        if !(1..=MAX_POLLS).contains(&poll) {
            return None;
        }
    }
    let session_id = process_header_value(output, "Process running with session ID ");
    let exit_code = process_header_value(output, "Process exited with code ");
    match (session_id, exit_code) {
        (Some(session_id), None) => Some(CommandProgress::Running(session_id)),
        (None, Some(_)) if matches!(expected, ExpectedCompletion::ProcessExit) => {
            Some(CommandProgress::Completed)
        }
        (None, None) => {
            let ExpectedCompletion::GuardianDenial(rationale) = expected else {
                return None;
            };
            // exec_command formats ProcessFailed with Debug; write_stdin uses Display.
            // Neither an arbitrary dispatch error nor words in process stdout are a denial.
            let message = if output_id == call_id {
                let (_, encoded_message) = output
                    .strip_prefix("exec_command failed for `")?
                    .rsplit_once("`: ProcessFailed { message: ")?;
                serde_json::from_str::<String>(encoded_message.strip_suffix(" }")?).ok()?
            } else {
                output
                    .strip_prefix("write_stdin failed: Unified exec process failed: ")?
                    .to_string()
            };
            message
                .starts_with(&format!(
                    "This action was rejected due to unacceptable risk.\nReason: {rationale}\n"
                ))
                .then_some(CommandProgress::Completed)
        }
        (Some(_), Some(_)) | (None, Some(_)) => None,
    }
}

pub(super) async fn mount_command_followups(
    server: &MockServer,
    responses: &ResponseMock,
    call_id: &'static str,
    expected: ExpectedCompletion,
    guardian_response: String,
    completion: &'static str,
) {
    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .and(move |request: &Request| guardian_request_is_for(request, call_id))
        // Record only requests that matched this route, using the original invariant checks.
        .and(responses.clone())
        .respond_with(sse_response(guardian_response))
        .up_to_n_times(1)
        .expect(1)
        .mount(server)
        .await;

    Mock::given(method("POST"))
        .and(path_regex(".*/responses$"))
        .and(move |request: &Request| request_output(request, call_id).is_some())
        .and(responses.clone())
        .respond_with(move |request: &Request| {
            let (output_id, output) =
                request_output(request, call_id).expect("matched current network command output");
            let response_id = format!("response-after-{output_id}");
            let progress = command_progress(&output, &output_id, call_id, expected)
                .expect("expected a live process or the specified terminal network outcome");
            let item = if let CommandProgress::Running(session_id) = progress {
                let body: Value = serde_json::from_slice(
                    &decoded_request_body(request).expect("decoded parent request"),
                )
                .expect("parent request JSON");
                let original_session = body["input"]
                    .as_array()
                    .expect("parent input history")
                    .iter()
                    .find(|item| {
                        item["type"] == "function_call_output" && item["call_id"] == call_id
                    })
                    .and_then(|item| item["output"].as_str())
                    .and_then(|output| {
                        process_header_value(output, "Process running with session ID ")
                    });
                assert_eq!(
                    Some(session_id),
                    original_session,
                    "poll must retain the original exec session"
                );
                let poll = if output_id == call_id {
                    1
                } else {
                    output_id
                        .strip_prefix(&format!("{call_id}-poll-"))
                        .expect("poll belongs to the original network command")
                        .parse::<usize>()
                        .expect("numeric poll ordinal")
                        + 1
                };
                assert!(
                    poll <= MAX_POLLS,
                    "network command did not finish within the fixture poll limit"
                );
                ev_function_call(
                    &format!("{call_id}-poll-{poll}"),
                    "write_stdin",
                    &json!({"session_id": session_id, "chars": "", "yield_time_ms": 1_000})
                        .to_string(),
                )
            } else {
                ev_assistant_message(&format!("message-after-{output_id}"), completion)
            };
            sse_response(sse(vec![
                ev_response_created(&response_id),
                item,
                ev_completed(&response_id),
            ]))
        })
        .up_to_n_times((MAX_POLLS + 1) as u64)
        .expect(1..=(MAX_POLLS + 1) as u64)
        .mount(server)
        .await;
}

pub(super) fn completed_output(
    responses: &ResponseMock,
    call_id: &str,
    expected: ExpectedCompletion,
) -> Result<String> {
    responses
        .requests()
        .iter()
        .rev()
        .find_map(|request| latest_output(&request.body_json(), call_id))
        .filter(|(output_id, output)| {
            command_progress(output, output_id, call_id, expected)
                == Some(CommandProgress::Completed)
        })
        .map(|(_, output)| output)
        .context("expected the network command's specified terminal outcome")
}
