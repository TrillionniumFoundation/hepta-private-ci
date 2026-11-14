use super::SkillMetadataFile;
use super::resolve_dependencies;
use super::resolve_policy;
use codex_skills::SkillDependencies;
use codex_skills::SkillPolicy;
use codex_skills::SkillToolDependency;
use pretty_assertions::assert_eq;

#[test]
fn yaml_metadata_keeps_optional_strings_oauth_aliases_and_policy() -> Result<(), yaml_serde::Error>
{
    for port_name in ["callbackPort", "callback_port"] {
        let input = format!(
            "dependencies:\n  tools:\n    - type: mcp\n      value: 42\n      description: &summary '中文 café 💡'\n      command: *summary\n      transport: true\n      url: null\n      oauth:\n        {port_name}: 12345\npolicy:\n  allow_implicit_invocation: false\n"
        );
        let parsed: SkillMetadataFile = yaml_serde::from_str(&input)?;
        assert_eq!(
            (
                resolve_dependencies(parsed.dependencies),
                resolve_policy(parsed.policy)
            ),
            (
                Some(SkillDependencies {
                    tools: vec![SkillToolDependency {
                        r#type: "mcp".to_string(),
                        value: "42".to_string(),
                        description: Some("中文 café 💡".to_string()),
                        transport: Some("true".to_string()),
                        command: Some("中文 café 💡".to_string()),
                        url: None,
                        oauth_callback_port: Some(12345),
                    }],
                }),
                Some(SkillPolicy {
                    allow_implicit_invocation: Some(false),
                    products: vec![]
                }),
            )
        );
    }
    Ok(())
}

#[test]
fn yaml_metadata_keeps_absent_sections_and_rejects_wrong_types() -> Result<(), yaml_serde::Error> {
    let parsed: SkillMetadataFile =
        yaml_serde::from_str("interface: null\ndependencies: null\npolicy: null\n")?;
    assert_eq!(
        (
            parsed.interface.is_none(),
            resolve_dependencies(parsed.dependencies),
            resolve_policy(parsed.policy)
        ),
        (true, None, None)
    );
    for input in [
        "dependencies:\n  tools:\n    - type: first\n      type: second\n      value: tool\n",
        "dependencies:\n  tools:\n    - type: mcp\n      value: tool\n      oauth: {callbackPort: 65536}\n",
        "policy: {allow_implicit_invocation: 'false'}\n",
        "dependencies: {tools: not-a-list}\n",
    ] {
        assert!(yaml_serde::from_str::<SkillMetadataFile>(input).is_err());
    }
    Ok(())
}
