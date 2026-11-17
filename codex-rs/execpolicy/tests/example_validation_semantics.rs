//! Original Rust public-entry oracle for the HIA example-validation migration.
//!
//! These tests deliberately execute the real PolicyParser, Policy, rule
//! callbacks, Starlark evaluation, and error presentation. They are not a
//! substitute for an eventual Rust-versus-HIA differential test.

use codex_execpolicy::Error;
use codex_execpolicy::PolicyParser;
use pretty_assertions::assert_eq;

#[test]
fn matching_negative_precedes_unmatched_positive() {
    let mut parser = PolicyParser::new();
    let error = match parser.parse(
        "negative-first.rules",
        r#"
prefix_rule(
    pattern = ["git"],
    match = [["does-not-match"]],
    not_match = [["git", "status"]],
)
"#,
    ) {
        Ok(()) => panic!("matching negative example must fail before positive validation"),
        Err(error) => error,
    };

    match error {
        Error::ExampleDidMatch {
            rule,
            example,
            location,
        } => {
            assert_eq!(example, "git status");
            assert!(rule.contains("PrefixRuleMatch"));
            assert_eq!(
                location.map(|location| location.path),
                Some("negative-first.rules".into())
            );
        }
        other => panic!("expected ExampleDidMatch, got {other:?}"),
    }
}

#[test]
fn positive_examples_collect_each_unmatched_entry_in_order() {
    let mut parser = PolicyParser::new();
    let error = match parser.parse(
        "collect-positives.rules",
        r#"
prefix_rule(
    pattern = ["git"],
    match = [
        ["missing"],
        ["git", "status"],
        ["unknown", "run"],
        ["missing"],
    ],
)
"#,
    ) {
        Ok(()) => panic!("multiple unmatched positive examples must fail"),
        Err(error) => error,
    };

    match error {
        Error::ExampleDidNotMatch {
            rules,
            examples,
            location,
        } => {
            assert_eq!(examples, vec!["missing", "unknown run", "missing"]);
            assert_eq!(rules.len(), 1);
            assert_eq!(
                location.map(|location| location.path),
                Some("collect-positives.rules".into())
            );
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}

#[test]
fn the_first_matching_negative_is_reported_without_looking_ahead() {
    let mut parser = PolicyParser::new();
    let error = match parser.parse(
        "first-negative.rules",
        r#"
prefix_rule(
    pattern = ["git"],
    not_match = [
        ["git", "status"],
        ["git", "commit"],
    ],
)
"#,
    ) {
        Ok(()) => panic!("matching negative examples must fail"),
        Err(error) => error,
    };

    match error {
        Error::ExampleDidMatch {
            example,
            location,
            ..
        } => {
            assert_eq!(example, "git status");
            assert_eq!(
                location.map(|location| location.path),
                Some("first-negative.rules".into())
            );
        }
        other => panic!("expected ExampleDidMatch, got {other:?}"),
    }
}

#[test]
fn an_unrelated_rule_from_a_prior_parse_cannot_validate_new_examples() {
    let mut parser = PolicyParser::new();
    if let Err(error) = parser.parse("prior.rules", r#"prefix_rule(pattern = ["git"])"#) {
        panic!("initial policy must parse: {error:?}");
    }

    let error = match parser.parse(
        "new.rules",
        r#"prefix_rule(pattern = ["echo"], match = [["git"]])"#,
    ) {
        Ok(()) => panic!("only the new rule group should validate its own examples"),
        Err(error) => error,
    };

    match error {
        Error::ExampleDidNotMatch {
            examples,
            location,
            ..
        } => {
            assert_eq!(examples, vec!["git"]);
            assert_eq!(
                location.map(|location| location.path),
                Some("new.rules".into())
            );
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}

#[test]
fn the_first_pending_group_fails_before_later_groups_are_accepted() {
    let mut parser = PolicyParser::new();
    let error = match parser.parse(
        "group-order.rules",
        r#"
prefix_rule(pattern = ["git"], match = [["missing-first"]])
prefix_rule(pattern = ["echo"], match = [["missing-second"]])
"#,
    ) {
        Ok(()) => panic!("first pending group must fail"),
        Err(error) => error,
    };

    match error {
        Error::ExampleDidNotMatch {
            examples,
            location,
            ..
        } => {
            assert_eq!(examples, vec!["missing-first"]);
            assert_eq!(
                location.map(|location| location.path),
                Some("group-order.rules".into())
            );
        }
        other => panic!("expected ExampleDidNotMatch, got {other:?}"),
    }
}
