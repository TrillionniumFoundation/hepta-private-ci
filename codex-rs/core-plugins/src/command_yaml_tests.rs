use super::CommandDescriptionMode;
use super::CommandMigrationProfile;
use super::RewriteProfile;
use super::import_commands_with_profile;
use super::parse_command_content;
use codex_skills::ParsedSkillFrontmatter;
use codex_skills::parse_skill_frontmatter_metadata;
use pretty_assertions::assert_eq;
use std::fs;

#[test]
fn yaml_description_keeps_scalar_and_mapping_key_semantics() {
    for (frontmatter, expected) in [
        ("description: true", Some("true")),
        ("description: 0x2a", Some("42")),
        ("description: 'null'", Some("null")),
        ("description: null", None),
        ("description: !custom tagged", None),
        ("description: [one, two]", None),
        ("description: {nested: value}", None),
        ("description: first\ndescription: second", None),
        (
            "summary: &summary '中文 café 💡'\ndescription: *summary",
            Some("中文 café 💡"),
        ),
        (
            "? [ignored, key]\n: ignored\n42: ignored\n' description ': keep",
            Some("keep"),
        ),
        (
            "defaults: &defaults {description: merged}\n<<: *defaults",
            None,
        ),
    ] {
        let parsed = parse_command_content(&format!("---\n{frontmatter}\n---\nBody\n"));
        assert_eq!(
            (parsed.description.as_deref(), parsed.body.as_str()),
            (expected, "Body\n")
        );
    }
}

#[test]
fn imported_command_yaml_roundtrips_unicode_quotes_and_colons()
-> Result<(), Box<dyn std::error::Error>> {
    let directory = tempfile::tempdir()?;
    let source = directory.path().join("source");
    let target = directory.path().join("skills");
    fs::create_dir(&source)?;
    fs::write(
        source.join("review.md"),
        "---\ndescription: |-\n  Review 'quoted': 中文 café 💡\n---\nReview the change.\n",
    )?;
    let profile = CommandMigrationProfile::new(
        RewriteProfile::new("AGENTS.md", &[]),
        CommandDescriptionMode::RequireFrontmatter,
    );
    assert_eq!(
        import_commands_with_profile(&source, &target, profile)?,
        vec!["source-command-review"]
    );
    let skill = fs::read_to_string(target.join("source-command-review/SKILL.md"))?;
    assert_eq!(
        parse_skill_frontmatter_metadata(&skill, || "fallback".to_string())?,
        ParsedSkillFrontmatter {
            name: "source-command-review".to_string(),
            description: "Review 'quoted': 中文 café 💡".to_string(),
            short_description: None,
        }
    );
    assert!(skill.contains("Review the change."));
    Ok(())
}
