use codex_skills::ParsedSkillFrontmatter;
use codex_skills::parse_skill_frontmatter_metadata;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

#[test]
fn anchors_and_unicode_preserve_skill_frontmatter() -> Result<(), Box<dyn std::error::Error>> {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname: unicode\ndescription: &text '部署: café 漢字'\nmetadata:\n  short-description: *text\n---\n",
        || "fallback".to_owned(),
    )?;
    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "unicode".to_owned(),
            description: "部署: café 漢字".to_owned(),
            short_description: Some("部署: café 漢字".to_owned()),
        }
    );
    Ok(())
}

#[test]
fn scalar_repair_and_block_text_keep_their_meaning() -> Result<(), Box<dyn std::error::Error>> {
    let parsed = parse_skill_frontmatter_metadata(
        "---\nname: block\ndescription: >-\n  Build for AWS: ECS\n  and test safely\nmetadata:\n  short-description: What's included: builds and tests\n---\n",
        || "fallback".to_owned(),
    )?;
    assert_eq!(
        parsed,
        ParsedSkillFrontmatter {
            name: "block".to_owned(),
            description: "Build for AWS: ECS and test safely".to_owned(),
            short_description: Some("What's included: builds and tests".to_owned()),
        }
    );
    Ok(())
}

#[test]
fn duplicate_fields_and_malformed_documents_remain_errors() {
    for text in [
        "---\nname: first\nname: second\ndescription: valid\n---\n",
        "---\nname: broken\ndescription: 'unterminated\n---\n",
        "---\nname: wrong-type\ndescription: [one, two]\n---\n",
    ] {
        assert!(
            parse_skill_frontmatter_metadata(text, || "fallback".to_owned()).is_err(),
            "accepted malformed frontmatter {text:?}"
        );
    }
    assert!(serde_yaml::from_str::<serde_yaml::Value>("---\na: 1\n---\nb: 2\n").is_err());
}

#[derive(Debug, Deserialize, PartialEq, Serialize)]
enum CompatibilityValue {
    Text(String),
    Coordinates { x: i64, y: i64 },
}

#[test]
fn tagged_values_and_quoted_scalars_round_trip() -> Result<(), Box<dyn std::error::Error>> {
    let values: Vec<CompatibilityValue> =
        serde_yaml::from_str("- !Text 'true'\n- !Text '0012'\n- !Coordinates {x: -2, y: 9}\n")?;
    assert_eq!(
        values,
        vec![
            CompatibilityValue::Text("true".to_owned()),
            CompatibilityValue::Text("0012".to_owned()),
            CompatibilityValue::Coordinates { x: -2, y: 9 },
        ]
    );
    let serialized = serde_yaml::to_string(&values)?;
    assert_eq!(
        serde_yaml::from_str::<Vec<CompatibilityValue>>(&serialized)?,
        values
    );
    Ok(())
}
