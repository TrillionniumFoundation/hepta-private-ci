//! Process isolation for fixtures that intentionally retain global owners or bind Codex home.

use std::process::Command;

const CHILD_TEST: &str = "HEPTA_INFER_WORKER_ISOLATED_TEST";

/// Run the same original test in a fresh copy of this test binary.
///
/// The child preserves the original body and its deadlines. Only the parent
/// returns early, after proving that exactly this one test actually passed.
pub(crate) fn completed_in_fresh_process(qualified_name: &str) -> bool {
    let (_, name) = qualified_name
        .split_once("::")
        .expect("test name includes its crate");
    if let Some(child) = std::env::var_os(CHILD_TEST) {
        assert_eq!(
            child, name,
            "isolated child must run its exact original test"
        );
        return false;
    }

    let output = Command::new(std::env::current_exe().expect("locate current test binary"))
        .args(["--exact", name, "--format=pretty", "--color=never"])
        .env(CHILD_TEST, name)
        .output()
        .expect("run original test in a fresh process");
    let stdout = String::from_utf8_lossy(&output.stdout);
    assert!(
        output.status.success() && reports_exactly_one_pass(&stdout, name),
        "isolated original test {name} did not pass exactly once ({}):\nstdout:\n{stdout}\nstderr:\n{}",
        output.status,
        String::from_utf8_lossy(&output.stderr),
    );
    true
}

fn reports_exactly_one_pass(stdout: &str, name: &str) -> bool {
    let expected = format!("test {name} ... ok");
    let statuses: Vec<_> = stdout
        .lines()
        .filter(|line| line.starts_with("test ") && line.contains(" ... "))
        .collect();
    let summaries: Vec<_> = stdout
        .lines()
        .filter(|line| line.starts_with("test result: "))
        .collect();
    statuses == [expected.as_str()]
        && stdout
            .lines()
            .filter(|line| *line == "running 1 test")
            .count()
            == 1
        && summaries.len() == 1
        && summaries[0].starts_with("test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; ")
}

#[cfg(test)]
mod tests {
    use super::reports_exactly_one_pass;

    #[test]
    fn requires_the_exact_original_case_and_one_pass() {
        let output = "running 1 test\ntest module::case ... ok\n\ntest result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 173 filtered out; finished in 0.01s\n";
        assert!(reports_exactly_one_pass(output, "module::case"));
        assert!(!reports_exactly_one_pass(output, "module::different_case"));
    }

    #[test]
    fn rejects_successful_zero_case_and_ignored_case_runs() {
        let zero = "running 0 tests\n\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 174 filtered out; finished in 0.00s\n";
        let ignored = "running 1 test\ntest module::case ... ignored\n\ntest result: ok. 0 passed; 0 failed; 1 ignored; 0 measured; 173 filtered out; finished in 0.00s\n";
        assert!(!reports_exactly_one_pass(zero, "module::case"));
        assert!(!reports_exactly_one_pass(ignored, "module::case"));
    }

    #[test]
    fn rejects_multiple_cases_and_failed_or_missing_completion() {
        let multiple = "running 2 tests\ntest module::case ... ok\ntest module::other ... ok\n\ntest result: ok. 2 passed; 0 failed; 0 ignored; 0 measured; 172 filtered out; finished in 0.01s\n";
        let failed = "running 1 test\ntest module::case ... FAILED\n\ntest result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 173 filtered out; finished in 0.01s\n";
        let incomplete = "running 1 test\ntest module::case ... ok\n";
        assert!(!reports_exactly_one_pass(multiple, "module::case"));
        assert!(!reports_exactly_one_pass(failed, "module::case"));
        assert!(!reports_exactly_one_pass(incomplete, "module::case"));
    }
}
