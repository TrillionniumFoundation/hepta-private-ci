// Shared public-owner fixtures; no normalization implementation lives here.

pub fn host_samples() -> Vec<(&'static str, String)> {
    vec![
        ("lowercase", "example.com".into()),
        ("uppercase", "Api.Example.COM.".into()),
        ("unicode-trim", "\u{85}\u{a0}ÄBC.\u{2003}".into()),
        ("ascii-port", "Example.COM.:443".into()),
        ("bracket-port", " [2001:DB8::A]:999999 ".into()),
        ("trim-order", "[AbC. ]:80".into()),
        ("non-numeric-port", "EXAMPLE:abc".into()),
        ("nul", "A\0B".into()),
        ("empty", String::new()),
        ("all-whitespace", " \t\u{85}\u{3000}".into()),
        ("suffix-error", " [A]oops ".into()),
        ("wildcard-before-whitespace", "A* B".into()),
        ("internal-whitespace", "A\u{2003}B".into()),
        ("large-valid", "A".repeat(2_097_153)),
        (
            "large-early-scheme",
            format!("http://{}", "A".repeat(2_097_153)),
        ),
        (
            "large-missing-bracket",
            format!("[{}", "A".repeat(2_097_153)),
        ),
        (
            "large-early-wildcard",
            format!("*{}", "A".repeat(2_097_153)),
        ),
        ("large-late-wildcard", format!("{}*", "A".repeat(2_097_153))),
        (
            "large-trimmed",
            format!(
                "{}AbC.{}",
                "\u{2003}".repeat(65_537),
                "\u{2003}".repeat(65_537)
            ),
        ),
    ]
}

macro_rules! network_host_owner {
    ($module:ident, $api:ident) => {
        mod $module {
            use $api as api;

            pub fn prepared() -> api::Policy {
                api::Policy::from_parts(Default::default(), Vec::with_capacity(1), Default::default())
            }

            pub fn append(policy: &mut api::Policy, raw: &str, justification: Option<String>) -> api::Result<()> {
                policy.add_network_rule(raw, api::NetworkRuleProtocol::Https, api::Decision::Forbidden, justification)
            }

            pub fn snapshot(policy: &api::Policy) -> serde_json::Value {
                serde_json::json!(policy.network_rules().iter().map(|rule| {
                    serde_json::json!([rule.host, rule.protocol.as_policy_string(), rule.decision, rule.justification])
                }).collect::<Vec<_>>())
            }

            pub fn error(error: api::Error) -> serde_json::Value {
                let kind = match &error {
                    api::Error::InvalidDecision(_) => "InvalidDecision",
                    api::Error::InvalidPattern(_) => "InvalidPattern",
                    api::Error::InvalidExample(_) => "InvalidExample",
                    api::Error::InvalidRule(_) => "InvalidRule",
                    api::Error::ExampleDidNotMatch { .. } => "ExampleDidNotMatch",
                    api::Error::ExampleDidMatch { .. } => "ExampleDidMatch",
                    api::Error::Starlark(_) => "Starlark",
                };
                let location = error.location().map(|location| serde_json::json!({
                    "path": location.path,
                    "start": [location.range.start.line, location.range.start.column],
                    "end": [location.range.end.line, location.range.end.column],
                }));
                serde_json::json!({"kind": kind, "display": error.to_string(), "location": location})
            }

            pub fn direct(raw: &str, justification: Option<&str>) -> serde_json::Value {
                let mut policy = api::Policy::from_parts(Default::default(), vec![api::rule::NetworkRule {
                    host: " RAW.*:abc ".into(), protocol: api::NetworkRuleProtocol::Socks5Udp,
                    decision: api::Decision::Prompt, justification: Some("prior\0metadata".into()),
                }], Default::default());
                let before = snapshot(&policy);
                let result = append(&mut policy, raw, justification.map(str::to_string)).map_err(error);
                serde_json::json!({"before": before, "result": result, "after": snapshot(&policy)})
            }

            pub fn parse(raw: &str, protocol: &str, decision: &str, justification: Option<&str>) -> serde_json::Value {
                let mut parser = api::PolicyParser::new();
                parser.parse("initial.rules", "network_rule(host=\"before.example\", protocol=\"http\", decision=\"allow\")")
                    .unwrap_or_else(|error| panic!("initial parser fixture failed: {error}"));
                let quote = |value: &str| serde_json::to_string(value).unwrap_or_else(|error| panic!("fixture serialization failed: {error}"));
                let optional = justification.map(|value| format!(", justification={}", quote(value))).unwrap_or_default();
                let text = format!("network_rule(host={}, protocol={}, decision={}{optional})", quote(raw), quote(protocol), quote(decision));
                let result = parser.parse("candidate.rules", &text).map_err(error);
                let following = parser.parse("following.rules", "network_rule(host=\"AFTER.example.:443\", protocol=\"socks5_tcp\", decision=\"deny\")")
                    .map_err(error);
                serde_json::json!({"result": result, "following": following, "rules": snapshot(&parser.build())})
            }

            pub fn amend(path: &std::path::Path, raw: &str, justification: Option<&str>) -> serde_json::Value {
                let result = api::blocking_append_network_rule(path, raw, api::NetworkRuleProtocol::Https,
                    api::Decision::Forbidden, justification).map_err(|error| error.to_string());
                let contents = match std::fs::read(path) {
                    Ok(bytes) => Some(bytes),
                    Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
                    Err(error) => panic!("failed to observe fixture file: {error}"),
                };
                serde_json::json!({"result": result, "contents": contents,
                    "parent_exists": path.parent().unwrap_or_else(|| panic!("fixture path has no parent")).exists()})
            }
        }
    };
}
