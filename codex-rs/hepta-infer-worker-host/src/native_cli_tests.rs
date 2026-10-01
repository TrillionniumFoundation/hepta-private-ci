use super::IntelligenceCliOptions;
use super::Invocation;
use super::NativeCliOptions;
use super::parse;
use std::path::PathBuf;

fn required_arguments() -> Vec<String> {
    [
        "--profile",
        "native-app-server",
        "--agentd-socket",
        "/agent.sock",
        "--agent-id",
        "agent-1",
        "--generation",
        "7",
        "--model",
        "model-1",
        "--journal",
        "/journal",
        "--request-id",
        "request-1",
        "--maximum-in-flight",
        "2",
        "--final-use-authority-config",
        "/authority.json",
    ]
    .into_iter()
    .map(str::to_string)
    .collect()
}

#[test]
fn complete_invocation_is_parsed_before_external_io() {
    let mut arguments = required_arguments();
    arguments.extend(
        [
            "--intelligence-run-id",
            "run-1",
            "--intelligence-revision",
            "3",
            "--intelligence-context-digest",
            "context-digest",
            "--intelligence-envelope-digest",
            "envelope-digest",
            "--timeout-ms",
            "5000",
        ]
        .into_iter()
        .map(str::to_string),
    );
    assert_eq!(
        parse(arguments).unwrap(),
        Invocation::Run(Box::new(NativeCliOptions {
            agentd_socket: PathBuf::from("/agent.sock"),
            agent_id: "agent-1".into(),
            generation: 7,
            model: "model-1".into(),
            journal: PathBuf::from("/journal"),
            request_id: "request-1".into(),
            maximum_in_flight: 2,
            context_query: None,
            final_use_authority_config: PathBuf::from("/authority.json"),
            intelligence: Some(IntelligenceCliOptions {
                run_id: "run-1".into(),
                expected_revision: 3,
                context_digest: "context-digest".into(),
                envelope_digest: "envelope-digest".into(),
            }),
            timeout_ms: 5000,
        }))
    );
}

#[test]
fn independent_context_and_intelligence_cannot_be_combined() {
    let mut arguments = required_arguments();
    arguments.extend(
        ["--context-query", "question"]
            .into_iter()
            .map(str::to_string),
    );
    let Invocation::Run(options) = parse(arguments.clone()).unwrap() else {
        panic!("memory-only invocation should run");
    };
    assert_eq!(options.context_query, Some("question".into()));
    assert_eq!(options.intelligence, None);
    arguments.extend(
        [
            "--intelligence-run-id",
            "run-1",
            "--intelligence-revision",
            "3",
            "--intelligence-context-digest",
            "context-digest",
            "--intelligence-envelope-digest",
            "envelope-digest",
        ]
        .into_iter()
        .map(str::to_string),
    );
    assert_eq!(
        parse(arguments).unwrap_err().to_string(),
        "optional context query with intelligence requires a combined owner final-use port"
    );
}

#[test]
fn every_partial_intelligence_group_is_rejected_before_external_io() {
    let fields = [
        ["--intelligence-run-id", "run-1"],
        ["--intelligence-revision", "3"],
        ["--intelligence-context-digest", "context-digest"],
        ["--intelligence-envelope-digest", "envelope-digest"],
    ];
    for mask in 1..15 {
        let mut arguments = required_arguments();
        for (index, field) in fields.iter().enumerate() {
            if mask & (1 << index) != 0 {
                arguments.extend(field.iter().map(|value| (*value).to_string()));
            }
        }
        assert_eq!(
            parse(arguments).unwrap_err().to_string(),
            "all four --intelligence-* arguments must be supplied together"
        );
    }
}

#[test]
fn missing_required_arguments_and_invalid_flags_fail_during_parsing() {
    for flag in [
        "--request-id",
        "--maximum-in-flight",
        "--final-use-authority-config",
    ] {
        let mut arguments = required_arguments();
        let position = arguments.iter().position(|value| value == flag).unwrap();
        arguments.drain(position..position + 2);
        assert_eq!(
            parse(arguments).unwrap_err().to_string(),
            format!("{flag} is required")
        );
    }
    let mut arguments = required_arguments();
    arguments.extend(["--timeout-ms".to_string(), "invalid".to_string()]);
    assert!(parse(arguments).is_err());
    assert!(parse(["--unknown".to_string(), "value".to_string()]).is_err());
    assert_eq!(parse(["--help".to_string()]).unwrap(), Invocation::Help);
}
