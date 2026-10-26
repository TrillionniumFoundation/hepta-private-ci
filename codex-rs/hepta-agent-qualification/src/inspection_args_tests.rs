#![allow(clippy::expect_used)]

use super::*;

fn base(directory: &str) -> Vec<String> {
    vec![
        "qualification".into(),
        "--evidence-dir".into(),
        directory.into(),
        "--expected-model".into(),
        "gpt-6.1-sol".into(),
    ]
}

#[test]
fn inspection_cli_requires_distinct_action_and_no_generation_budget() {
    let temp = tempfile::tempdir().expect("owned directory");
    let path = temp.path().join("new-inspection");
    let mut args = base(path.to_str().expect("fixture path"));
    args.push("--inspect".into());
    let command = CommandLine::try_parse_from(&args)
        .expect("inspect args")
        .into_command()
        .expect("valid inspect args");
    assert!(matches!(
        command,
        Command::Inspect(InspectionArgs {
            setup_seconds: 20,
            ..
        })
    ));
    assert!(
        !path.exists(),
        "parsing must not load owners or create evidence"
    );
    for conflicting in [vec!["--run"], vec!["--maximum-output-tokens", "8"]] {
        let mut invalid = args.clone();
        invalid.extend(conflicting.into_iter().map(str::to_string));
        assert_eq!(
            CommandLine::try_parse_from(invalid)
                .expect_err("action conflict")
                .kind(),
            clap::error::ErrorKind::ArgumentConflict
        );
    }
}

#[test]
fn inspection_cli_preserves_explicit_default_plan_reservations() {
    let temp = tempfile::tempdir().expect("owned directory");
    let path = temp.path().join("plan-only");
    let mut args = base(path.to_str().expect("fixture path"));
    assert_eq!(
        CommandLine::try_parse_from(&args)
            .expect_err("plan still needs explicit bounds")
            .kind(),
        clap::error::ErrorKind::MissingRequiredArgument
    );
    args.extend(
        [
            "--maximum-provider-input-tokens",
            "8192",
            "--maximum-output-tokens",
            "1024",
            "--maximum-elapsed-seconds",
            "60",
        ]
        .into_iter()
        .map(str::to_string),
    );
    let Command::Qualification(parsed) = CommandLine::try_parse_from(args)
        .expect("plan args")
        .into_command()
        .expect("plan command")
    else {
        panic!("plan must not inspect owners")
    };
    parsed.validate().expect("original plan validation");
    assert!(!parsed.run);
    assert_eq!(parsed.maximum_provider_input_tokens, 8192);
    assert_eq!(parsed.maximum_bootstrap_seconds, 60);
    assert_eq!(parsed.maximum_elapsed_seconds, 60);
    assert!(!path.exists());
}

#[test]
fn generation_bootstrap_allowance_is_separate_bounded_and_plan_only() {
    let temp = tempfile::tempdir().expect("owned directory");
    let path = temp.path().join("cold-bootstrap-plan");
    let mut args = base(path.to_str().expect("fixture path"));
    args.extend(
        [
            "--maximum-provider-input-tokens",
            "8192",
            "--maximum-output-tokens",
            "1024",
            "--maximum-elapsed-seconds",
            "60",
            "--maximum-bootstrap-seconds",
        ]
        .into_iter()
        .map(str::to_string),
    );
    for (allowance, allowed) in [("0", false), ("1", true), ("300", true), ("301", false)] {
        let mut argv = args.clone();
        argv.push(allowance.into());
        let Command::Qualification(parsed) = CommandLine::try_parse_from(argv)
            .expect("syntactic generation plan")
            .into_command()
            .expect("generation command")
        else {
            panic!("generation plan");
        };
        assert_eq!(parsed.validate().is_ok(), allowed);
        assert_eq!(parsed.maximum_elapsed_seconds, 60);
        assert_eq!(parsed.maximum_output_tokens, 1024);
        assert!(!parsed.run);
    }
    assert!(
        !path.exists(),
        "plan parsing cannot initialize owners or send requests"
    );
    let mut inspect = base(path.to_str().expect("fixture path"));
    inspect.extend(
        ["--inspect", "--maximum-bootstrap-seconds", "60"]
            .into_iter()
            .map(str::to_string),
    );
    assert_eq!(
        CommandLine::try_parse_from(inspect)
            .expect_err("bootstrap belongs to generation setup")
            .kind(),
        clap::error::ErrorKind::ArgumentConflict
    );
}

#[test]
fn inspection_cli_bounds_owner_waits_and_requires_explicit_absolute_path() {
    for (path, deadline) in [
        ("relative-path", "20"),
        ("/inspection", "0"),
        ("/inspection", "61"),
    ] {
        let mut args = base(path);
        args.extend(
            ["--inspect", "--inspection-setup-seconds", deadline]
                .into_iter()
                .map(str::to_string),
        );
        assert!(
            CommandLine::try_parse_from(args)
                .expect("syntactically valid")
                .into_command()
                .is_err()
        );
    }
}
