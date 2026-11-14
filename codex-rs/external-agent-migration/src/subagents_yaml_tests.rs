use super::FrontmatterValue;
use super::agent_metadata;
use super::parse_document_content;
use super::render_agent_toml;
use crate::RewriteProfile;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

#[test]
fn yaml_frontmatter_preserves_scalars_ignores_complex_keys_and_keeps_tags()
-> Result<(), Box<dyn std::error::Error>> {
    let parsed = parse_document_content(
        "---\n42: ignored\n? [ignored, key]\n: ignored\nname: 42\ndescription: &summary true\nalias: *summary\ntagged: !custom hello\nnil: null\nsequence: [one, two]\nmapping: {nested: value}\npermissionMode: readOnly\neffort: max\n---\nAgent instructions.\n",
    );
    let scalars = parsed
        .frontmatter
        .iter()
        .map(|(key, value)| (key.as_str(), value.as_scalar()))
        .collect::<BTreeMap<_, _>>();
    assert_eq!(
        scalars,
        BTreeMap::from([
            ("alias", Some("true")),
            ("description", Some("true")),
            ("effort", Some("max")),
            ("mapping", None),
            ("name", Some("42")),
            ("nil", None),
            ("permissionMode", Some("readOnly")),
            ("sequence", None),
            ("tagged", None),
        ])
    );
    assert!(matches!(
        parsed.frontmatter.get("tagged"),
        Some(FrontmatterValue::Other)
    ));
    let metadata = agent_metadata(&parsed).ok_or("agent metadata was rejected")?;
    let rendered = render_agent_toml(
        &parsed.body,
        &metadata,
        RewriteProfile::new("AGENTS.md", &[]),
    )?;
    let actual: toml::Value = toml::from_str(&rendered)?;
    let expected: toml::Value = toml::from_str(
        "name = '42'\ndescription = 'true'\nmodel_reasoning_effort = 'xhigh'\nsandbox_mode = 'read-only'\ndeveloper_instructions = 'Agent instructions.'\n",
    )?;
    assert_eq!(actual, expected);
    Ok(())
}

#[test]
fn yaml_rejections_preserve_document_body_and_disable_agent_import() {
    for frontmatter in [
        "name: first\nname: second\ndescription: Demo",
        "[not, a, mapping]",
        "name: demo\ndescription: [unterminated",
    ] {
        let parsed = parse_document_content(&format!("---\n{frontmatter}\n---\nBody\n"));
        assert_eq!(
            (parsed.frontmatter.is_empty(), parsed.body.as_str()),
            (true, "Body\n")
        );
        assert!(parsed.frontmatter_error.is_some());
        assert!(agent_metadata(&parsed).is_none());
    }
}
