use super::SkillMetadataFile;
use super::resolve_dependencies;
use super::resolve_policy;
use codex_protocol::protocol::Product;
use codex_skills::SkillDependencies;
use codex_skills::SkillPolicy;
use codex_skills::SkillToolDependency;
use pretty_assertions::assert_eq;

#[test]
fn preserves_metadata_aliases_boolean_case_and_oauth_field_alias() -> Result<(), serde_saphyr::Error>
{
    let parsed = SkillMetadataFile::parse(
        "tool_name: &tool_name on\ndependencies:\n  tools:\n    - type: mcp\n      value: *tool_name\n      oauth: {callback_port: 3118}\npolicy:\n  allow_implicit_invocation: FALSE\n  products: [codex, CHATGPT, atlas]\n",
    )?;
    assert_eq!(
        (
            resolve_dependencies(parsed.dependencies),
            resolve_policy(parsed.policy),
        ),
        (
            Some(SkillDependencies {
                tools: vec![SkillToolDependency {
                    r#type: "mcp".to_string(),
                    value: "on".to_string(),
                    description: None,
                    transport: None,
                    command: None,
                    url: None,
                    oauth_callback_port: Some(3118),
                }],
            }),
            Some(SkillPolicy {
                allow_implicit_invocation: Some(false),
                products: vec![Product::Codex, Product::Chatgpt, Product::Atlas],
            }),
        )
    );
    Ok(())
}

#[test]
fn metadata_rejects_yaml11_policy_booleans_and_duplicate_fields() {
    for source in [
        "policy: {allow_implicit_invocation: yes}",
        "policy: {allow_implicit_invocation: true, allow_implicit_invocation: false}",
        "dependencies: {tools: [{type: mcp, value: demo, oauth: {callbackPort: 65536}}]}",
    ] {
        assert!(SkillMetadataFile::parse(source).is_err(), "{source}");
    }
}

#[test]
fn metadata_does_not_apply_implicit_yaml_merges() -> Result<(), serde_saphyr::Error> {
    let parsed = SkillMetadataFile::parse(
        "defaults: &defaults {policy: {allow_implicit_invocation: true}}\n<<: *defaults\n",
    )?;
    assert_eq!(resolve_policy(parsed.policy), None);
    Ok(())
}
