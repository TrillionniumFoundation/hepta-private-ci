#![allow(clippy::expect_used)]

// Original-Rust oracle for example-validation behavior. These assertions must
// remain active in both default and hia-native execpolicy test profiles.
use codex_execpolicy::Error;
use codex_execpolicy::PolicyParser;
use pretty_assertions::assert_eq;

const POLICY_NAME: &str = "example-validation-contract.rules";

fn parse_failure(source: &str) -> Error {
    let mut parser = PolicyParser::new();
    parser
        .parse(POLICY_NAME, source)
        .expect_err("policy must reject the specified example")
}

fn parse_success(source: &str) {
    let mut parser = PolicyParser::new();
    parser
        .parse(POLICY_NAME, source)
        .expect("the specified examples must validate");
}

#[test]
fn unmatched_positive_examples_preserve_order_and_duplicates() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", "status"], match = [["git", "push"], "git push", ["git", "diff"]])"#,
    );
    match error {
        Error::ExampleDidNotMatch {
            rules,
            examples,
            location,
        } => {
            assert_eq!(rules.len(), 1);
            assert_eq!(
                examples,
                vec![
                    "git push".to_string(),
                    "git push".to_string(),
                    "git diff".to_string(),
                ]
            );
            assert_eq!(location.expect("source location").path, POLICY_NAME);
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}

#[test]
fn negative_examples_are_validated_before_unmatched_positives() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", "status"], match = ["git push"], not_match = ["git status"])"#,
    );
    match error {
        Error::ExampleDidMatch {
            rule,
            example,
            location,
        } => {
            assert!(rule.contains("git"));
            assert_eq!(example, "git status");
            assert_eq!(location.expect("source location").path, POLICY_NAME);
        }
        other => panic!("expected ExampleDidMatch, got {other:?}"),
    }
}

#[test]
fn negative_examples_report_first_offending_match() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", ["status", "log"]], not_match = ["git push", "git log", "git status"])"#,
    );
    match error {
        Error::ExampleDidMatch { example, .. } => assert_eq!(example, "git log"),
        other => panic!("expected ExampleDidMatch, got {other:?}"),
    }
}

#[test]
fn quoted_command_example_is_tokenized_before_matching() {
    parse_success(
        r#"prefix_rule(pattern = ["echo", "hello world"], match = ["echo \"hello world\""], not_match = ["echo hello world"])"#,
    );
}

#[test]
fn alternative_first_tokens_validate_without_expanding_tail_combinations() {
    parse_success(
        r#"prefix_rule(pattern = [["git", "hg"], "status"], match = ["git status", ["hg", "status"]], not_match = ["hg log"])"#,
    );
}

#[test]
fn empty_string_and_empty_list_examples_are_rejected() {
    for (source, expected) in [
        (
            r#"prefix_rule(pattern = ["git"], match = [""])"#,
            "example cannot be an empty string",
        ),
        (
            r#"prefix_rule(pattern = ["git"], match = [[]])"#,
            "example cannot be an empty list",
        ),
    ] {
        let error = parse_failure(source);
        assert!(
            error.to_string().contains(expected),
            "expected {expected:?} in {error}"
        );
    }
}

#[test]
fn invalid_shell_syntax_and_non_string_list_tokens_are_rejected() {
    for (source, expected) in [
        (
            r#"prefix_rule(pattern = ["git"], match = ["git 'unfinished"])"#,
            "example string has invalid shell syntax",
        ),
        (
            r#"prefix_rule(pattern = ["git"], match = [["git", 12]])"#,
            "example tokens must be strings",
        ),
    ] {
        let error = parse_failure(source);
        assert!(
            error.to_string().contains(expected),
            "expected {expected:?} in {error}"
        );
    }
}

#[test]
fn empty_positive_and_negative_collections_are_valid() {
    parse_success(r#"prefix_rule(pattern = ["git", "status"], match = [], not_match = [])"#);
}

#[test]
fn interleaved_positive_hits_preserve_all_unmatched_examples_in_order() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", "status"], match = [["git", "push"], ["git", "status"], ["git", "diff"], ["git", "status"], ["git", "push"]])"#,
    );
    match error {
        Error::ExampleDidNotMatch { examples, .. } => {
            assert_eq!(
                examples,
                vec![
                    "git push".to_string(),
                    "git diff".to_string(),
                    "git push".to_string(),
                ]
            );
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}

#[test]
fn an_earlier_rule_positive_error_precedes_a_later_rule_negative_error() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", "status"], match = ["git push"])
prefix_rule(pattern = ["hg", "status"], not_match = ["hg status"])"#,
    );
    match error {
        Error::ExampleDidNotMatch { examples, .. } => {
            assert_eq!(examples, vec!["git push".to_string()]);
        }
        other => panic!("expected the earlier rule's positive error, got {other:?}"),
    }
}

#[test]
fn empty_positive_examples_do_not_hide_a_matching_negative_example() {
    let error = parse_failure(
        r#"prefix_rule(pattern = ["git", "status"], match = [], not_match = ["git status"])"#,
    );
    match error {
        Error::ExampleDidMatch { example, .. } => assert_eq!(example, "git status"),
        other => panic!("expected ExampleDidMatch, got {other:?}"),
    }
}

#[test]
fn separate_parse_calls_keep_the_new_example_source_location() {
    let mut parser = PolicyParser::new();
    parser
        .parse(
            "first-policy.rules",
            r#"prefix_rule(pattern = ["git", "status"], match = ["git status"])"#,
        )
        .expect("the first policy's examples must validate");
    let error = parser
        .parse(
            "second-policy.rules",
            r#"prefix_rule(pattern = ["hg", "status"], match = ["hg log"])"#,
        )
        .expect_err("the second policy's examples must fail");
    match error {
        Error::ExampleDidNotMatch {
            examples, location, ..
        } => {
            assert_eq!(examples, vec!["hg log".to_string()]);
            assert_eq!(
                location.expect("second policy source location").path,
                "second-policy.rules"
            );
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}
