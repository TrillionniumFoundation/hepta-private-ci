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
fn yaml_scalars_anchors_and_null_options_keep_frontmatter_contract()
-> Result<(), super::SkillParseError> {
    for (frontmatter, expected) in [
        (
            "name: 42\ndescription: true\nmetadata:\n  short-description: 0x2a\n",
            ParsedSkillFrontmatter {
                name: "42".to_string(),
                description: "true".to_string(),
                short_description: Some("0x2a".to_string()),
            },
        ),
        (
            "name: null\ndescription: &summary '中文 café 💡'\nmetadata:\n  short-description: *summary\n",
            ParsedSkillFrontmatter {
                name: "fallback".to_string(),
                description: "中文 café 💡".to_string(),
                short_description: Some("中文 café 💡".to_string()),
            },
        ),
        (
            "name: demo\ndescription: 'null'\nmetadata:\n  short-description: null\n",
            ParsedSkillFrontmatter {
                name: "demo".to_string(),
                description: "null".to_string(),
                short_description: None,
            },
        ),
    ] {
        let parsed =
            parse_skill_frontmatter_metadata(&format!("---\n{frontmatter}---\nBody\n"), || {
                "fallback".to_string()
            })?;
        assert_eq!(parsed, expected);
    }
    Ok(())
}

#[test]
fn yaml_duplicate_fields_and_null_descriptions_keep_validation_errors() {
    for frontmatter in [
        "name: first\nname: second\ndescription: Demo\n",
        "name: demo\ndescription: [one, two]\n",
        "name: demo\ndescription: Demo\nmetadata: null\n",
    ] {
        assert!(matches!(
            parse_skill_frontmatter_metadata(&format!("---\n{frontmatter}---\n"), || "fallback"
                .to_string()),
            Err(super::SkillParseError::InvalidYaml(_))
        ));
    }
    assert!(matches!(
        parse_skill_frontmatter_metadata("---\nname: demo\ndescription: null\n---\n", || {
            "fallback".to_string()
        }),
        Err(super::SkillParseError::MissingField("description"))
    ));
}

#[test]
fn yaml_values_roundtrip_tags_aliases_and_non_string_mapping_keys() -> Result<(), yaml_serde::Error>
{
    let source = "defaults: &defaults {description: '中文 café 💡'}\n<<: *defaults\n? [one, two]\n: !custom [42, true, null]\n";
    let value: yaml_serde::Value = yaml_serde::from_str(source)?;
    let encoded = yaml_serde::to_string(&value)?;
    let decoded: yaml_serde::Value = yaml_serde::from_slice(encoded.as_bytes())?;
    assert_eq!(decoded, value);
    assert!(value.get("<<").is_some());
    assert!(value.get("description").is_none());
    Ok(())
}
