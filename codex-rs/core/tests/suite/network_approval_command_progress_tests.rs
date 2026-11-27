use super::CommandProgress;
use super::ExpectedCompletion;
use super::command_progress;
use pretty_assertions::assert_eq;

const CALL_ID: &str = "network-command";
const RATIONALE: &str = "The destination is outside the approved test boundary.";

fn exec_denial(rationale: &str) -> String {
    let message = format!(
        "This action was rejected due to unacceptable risk.\nReason: {rationale}\nRejection instructions."
    );
    format!(
        "exec_command failed for `python3 network.py`: ProcessFailed {{ message: {message:?} }}"
    )
}

fn poll_denial(rationale: &str) -> String {
    format!(
        "write_stdin failed: Unified exec process failed: This action was rejected due to unacceptable risk.\nReason: {rationale}\nRejection instructions."
    )
}

#[test]
fn accepts_running_processes_and_each_expected_terminal_form() {
    let cases = [
        (
            "Chunk ID: 4ace2a\nWall time: 1.0000 seconds\nProcess running with session ID 42\nOutput:\nwaiting".to_string(),
            CALL_ID,
            ExpectedCompletion::ProcessExit,
            CommandProgress::Running(42),
        ),
        (
            "Wall time: 1.0000 seconds\nProcess running with session ID 42\nOutput:\nwaiting".to_string(),
            "network-command-poll-1",
            ExpectedCompletion::GuardianDenial(RATIONALE),
            CommandProgress::Running(42),
        ),
        (
            "Chunk ID: 4ace2a\nWall time: 0.2752 seconds\nProcess exited with code 1\nOutput:\nHTTP Error 502".to_string(),
            CALL_ID,
            ExpectedCompletion::ProcessExit,
            CommandProgress::Completed,
        ),
        (
            "Wall time: 1.0000 seconds\nProcess exited with code 0\nOutput:\nok".to_string(),
            "network-command-poll-9",
            ExpectedCompletion::ProcessExit,
            CommandProgress::Completed,
        ),
        (
            exec_denial(RATIONALE),
            CALL_ID,
            ExpectedCompletion::GuardianDenial(RATIONALE),
            CommandProgress::Completed,
        ),
        (
            poll_denial(RATIONALE),
            "network-command-poll-1",
            ExpectedCompletion::GuardianDenial(RATIONALE),
            CommandProgress::Completed,
        ),
        (
            exec_denial("Auto-reviewer denied the action without a specific rationale."),
            CALL_ID,
            ExpectedCompletion::GuardianDenial(
                "Auto-reviewer denied the action without a specific rationale.",
            ),
            CommandProgress::Completed,
        ),
    ];
    for (output, output_id, expected, progress) in cases {
        assert_eq!(
            command_progress(&output, output_id, CALL_ID, expected),
            Some(progress),
            "{output_id}: {output}"
        );
    }
}

#[test]
fn rejects_wrong_outcomes_errors_and_unrelated_or_malformed_polls() {
    let denial = ExpectedCompletion::GuardianDenial(RATIONALE);
    let exited = "Wall time: 1.0000 seconds\nProcess exited with code 0\nOutput:\nok";
    let cases = [
        (
            exec_denial(RATIONALE),
            CALL_ID,
            ExpectedCompletion::ProcessExit,
        ),
        (exited.to_string(), CALL_ID, denial),
        (exec_denial("a different request"), CALL_ID, denial),
        (
            poll_denial("a different request"),
            "network-command-poll-1",
            denial,
        ),
        (exec_denial(RATIONALE), "network-command-poll-1", denial),
        (poll_denial(RATIONALE), CALL_ID, denial),
        (
            "exec_command failed: unavailable".to_string(),
            CALL_ID,
            denial,
        ),
        (
            "write_stdin failed: Unknown process id 42".to_string(),
            "network-command-poll-1",
            denial,
        ),
        (
            "write_stdin failed: stdin is closed for this session".to_string(),
            "network-command-poll-1",
            denial,
        ),
        (
            format!(
                "Wall time: 1.0000 seconds\nProcess exited with code 0\nOutput:\n{}",
                exec_denial(RATIONALE)
            ),
            CALL_ID,
            denial,
        ),
        (
            format!(
                "Wall time: 1.0000 seconds\nProcess running with session ID 42\nProcess exited with code 0\nOutput:\n{}",
                exec_denial(RATIONALE)
            ),
            CALL_ID,
            denial,
        ),
        (
            format!("Output:\n{}", exec_denial(RATIONALE)),
            CALL_ID,
            denial,
        ),
        (exec_denial(RATIONALE), "unrelated-command", denial),
        (poll_denial(RATIONALE), "network-command-poll-0", denial),
        (poll_denial(RATIONALE), "network-command-poll-10", denial),
        (poll_denial(RATIONALE), "network-command-poll-x", denial),
        (
            format!("{} trailing error", exec_denial(RATIONALE)),
            CALL_ID,
            denial,
        ),
        (
            exec_denial(RATIONALE).replace("ProcessFailed", "CreateProcess"),
            CALL_ID,
            denial,
        ),
        (
            "write_stdin failed: Unified exec process failed: unrelated error\nProcess exited with code 0\nOutput:\n...".to_string(),
            "network-command-poll-1",
            ExpectedCompletion::ProcessExit,
        ),
        (
            "exec_command failed for `command`: unrelated error\nProcess running with session ID 42\nOutput:\n...".to_string(),
            CALL_ID,
            ExpectedCompletion::ProcessExit,
        ),
    ];
    for (output, output_id, expected) in cases {
        assert_eq!(
            command_progress(&output, output_id, CALL_ID, expected),
            None,
            "{output_id}: {output}"
        );
    }
}
