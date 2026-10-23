use pretty_assertions::assert_eq;

use super::ParsedSkillFrontmatter;
use super::parse_skill_frontmatter_metadata;

#[test]
fn parses_repairs_and_sanitizes_frontmatter() {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname:  deploy  service\ndescription: Build for AWS: ECS\nmetadata:\n  short-description:  Deploy   safely\n---\n",
        || "fallback".to_string(),
    )
    .expect("valid frontmatter");

    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "deploy service".to_string(),
            description: "Build for AWS: ECS".to_string(),
            short_description: Some("Deploy safely".to_string()),
        }
    );
}

#[test]
fn uses_default_name_and_requires_description() {
    let parsed = parse_skill_frontmatter_metadata("---\ndescription: Demo skill\n---\n", || {
        "demo".to_string()
    })
    .expect("valid frontmatter");
    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "demo".to_string(),
            description: "Demo skill".to_string(),
            short_description: None,
        }
    );

    let error =
        parse_skill_frontmatter_metadata("---\nname: demo\n---\n", || "fallback".to_string())
            .expect_err("description should be required");
    assert_eq!(error.to_string(), "missing field `description`");
}

#[test]
fn repairs_short_descriptions_containing_colons_and_apostrophes() {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname: short\ndescription: Short skill\nmetadata:\n  short-description: What's included: builds and tests\n---\n",
        || "fallback".to_string(),
    )
    .expect("frontmatter with an unquoted short description should be repaired");

    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "short".to_string(),
            description: "Short skill".to_string(),
            short_description: Some("What's included: builds and tests".to_string()),
        }
    );
}

#[test]
fn repairs_unrecognized_frontmatter_fields_that_need_quotes() {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname: unknown\ndescription: Unknown fields\nargument-hint: <duration: e.g. 7d, 2w>\ntags: [next,@supabase/ssr]\n---\n",
        || "fallback".to_string(),
    )
    .expect("frontmatter with unrecognized fields should be repaired");

    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "unknown".to_string(),
            description: "Unknown fields".to_string(),
            short_description: None,
        }
    );
}

#[test]
fn preserves_block_scalar_bodies_while_repairing_other_fields() {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname: block\ndescription: |-\n  Build for AWS: ECS\nargument-hint: <duration: e.g. 7d>\n---\n",
        || "fallback".to_string(),
    )
    .expect("frontmatter repair should preserve block scalar bodies");

    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "block".to_string(),
            description: "Build for AWS: ECS".to_string(),
            short_description: None,
        }
    );
}

#[test]
fn preserves_overlong_descriptions_and_short_descriptions() {
    let description = "💡".repeat(/*n*/ 1_025);
    let short_description = "x".repeat(/*n*/ 1_025);
    let parsed = parse_skill_frontmatter_metadata(
        &format!(
            "---\nname: long\ndescription: {description}\nmetadata:\n  short-description: {short_description}\n---\n"
        ),
        || "fallback".to_string(),
    )
    .expect("descriptions should not be truncated during frontmatter parsing");

    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "long".to_string(),
            description,
            short_description: Some(short_description),
        }
    );
}

#[test]
fn safe_yaml_frontmatter_parser_rejects_nested_description_or_unknown_tag() {
    let nested = parse_skill_frontmatter_metadata(
        "---\nname: unsafe\ndescription:\n  - command\n  - executable\n---\n",
        || "fallback".to_string(),
    );
    assert!(nested.is_err(), "descriptions must remain scalar strings");

    let custom_tag = parse_skill_frontmatter_metadata(
        "---\nname: unsafe\ndescription: !unreviewed tagged content\n---\n",
        || "fallback".to_string(),
    );
    assert!(
        custom_tag.is_err(),
        "unknown YAML tags must not become trusted skill metadata"
    );
}

#[test]
fn safe_yaml_rejects_duplicate_skill_identity_and_alias_overrides() {
    for source in [
        "---\nname: first\nname: second\ndescription: basic\n---\n",
        "---\nname: first\ndescription: safe\ndescription: unsafe\n---\n",
        "---\nname: first\ndescription: &alias safe\ndescription: *alias\n---\n",
        "---\nname: !executor malicious\ndescription: safe\n---\n",
        // A colon in the untrusted tag must not cause the scalar repair
        // fallback to turn executable tag syntax into an accepted string.
        "---\nname: unsafe\ndescription: !executor payload: arguments\n---\n",
        "---\nname: unsafe\ndescription: *undefined alias: arguments\n---\n",
    ] {
        let result = parse_skill_frontmatter_metadata(source, || "default".to_string());
        assert!(
            result.is_err(),
            "untrusted frontmatter must not override identity"
        );
    }
}

#[test]
fn safe_yaml_preserves_bounded_basic_skill_frontmatter() {
    let document = "---\nname: yaml-migration\ndescription: 'run safely: audited'\nmetadata:\n  short-description: 'basic # safe'\n---\n";
    let parsed = parse_skill_frontmatter_metadata(document, || "fallback".to_string())
        .expect("simple YAML metadata remains usable");
    assert_eq!(parsed.name, "yaml-migration");
    assert_eq!(parsed.description, "run safely: audited");
    assert_eq!(parsed.short_description.as_deref(), Some("basic # safe"));
}
