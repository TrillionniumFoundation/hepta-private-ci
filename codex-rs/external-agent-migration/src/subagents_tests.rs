use super::*;
use pretty_assertions::assert_eq;

const PROFILE: RewriteProfile = RewriteProfile::new("CLAUDE.md", &[]);

#[test]
fn safe_yaml_string_keys_keep_trim_and_scalar_semantics() -> io::Result<()> {
    let document = parse_document_content(
        "---\n' name ': analyst\n' description ': 42\npermissionMode: readOnly\neffort: max\nignored: [a, b]\n---\nDo the task.\n",
    );
    assert!(document.frontmatter_error.is_none());
    let metadata = agent_metadata(&document).ok_or_else(|| io::Error::other("valid metadata"))?;
    assert_eq!(metadata.name, "analyst");
    assert_eq!(metadata.description, "42");
    let rendered = render_agent_toml(&document.body, &metadata, PROFILE)?;
    let parsed: TomlValue = toml::from_str(&rendered).map_err(io::Error::other)?;
    assert_eq!(parsed["name"].as_str(), Some("analyst"));
    assert_eq!(parsed["description"].as_str(), Some("42"));
    assert_eq!(parsed["sandbox_mode"].as_str(), Some("read-only"));
    assert_eq!(parsed["model_reasoning_effort"].as_str(), Some("xhigh"));
    assert_eq!(
        parsed["developer_instructions"].as_str(),
        Some("Do the task.")
    );
    Ok(())
}

#[test]
fn safe_yaml_trim_collisions_discard_all_identity_and_permission_fields() {
    for (key, value) in [
        ("name", "analyst"),
        ("description", "Review"),
        ("permissionMode", "readOnly"),
        ("effort", "low"),
    ] {
        for (left, right) in [
            (key.to_string(), format!(" {key} ")),
            (format!("{key} "), key.to_string()),
        ] {
            let raw = format!("'{left}': {value}\n'{right}': substituted");
            let (frontmatter, error) = parse_frontmatter(&raw);
            assert!(frontmatter.is_empty(), "{raw}");
            assert!(error.is_some(), "{raw}");
        }
    }
}

#[test]
fn safe_yaml_equal_and_unicode_trim_collisions_are_also_errors() {
    for raw in [
        "name: same\n' name ': same",
        "name: original\n'name\u{00a0}': other",
        "permissionMode: readOnly\n' permissionMode ': acceptEdits",
    ] {
        let document = parse_document_content(&format!("---\n{raw}\n---\nBody.\n"));
        assert!(document.frontmatter_error.is_some(), "{raw}");
        assert!(document.frontmatter.is_empty(), "{raw}");
        assert!(agent_metadata(&document).is_none(), "{raw}");
    }
}

#[test]
fn safe_yaml_raw_duplicates_tags_and_nonmapping_roots_are_rejected() {
    for raw in [
        "name: first\nname: second\ndescription: Review",
        "name: analyst\ndescription: &d safe\ndescription: *d",
        "name: analyst\ndescription: !unreviewed tagged",
        "name: !unreviewed analyst\ndescription: Review",
        "[name, description]",
    ] {
        let document = parse_document_content(&format!("---\n{raw}\n---\nBody.\n"));
        assert!(document.frontmatter_error.is_some(), "{raw}");
        assert!(document.frontmatter.is_empty(), "{raw}");
        assert!(agent_metadata(&document).is_none(), "{raw}");
    }
}

#[test]
fn safe_yaml_quoted_syntax_is_data_and_unsupported_fields_stay_ignored() {
    let document = parse_document_content(
        "---\nname: analyst\ndescription: '!literal &text *text: value'\nignored: [a, b]\n---\nBody.\n",
    );
    assert!(document.frontmatter_error.is_none());
    assert_eq!(
        document
            .frontmatter
            .get("description")
            .and_then(FrontmatterValue::as_scalar),
        Some("!literal &text *text: value"),
    );
    assert!(agent_metadata(&document).is_some());
}

#[test]
fn safe_yaml_nonscalar_required_fields_cannot_supply_agent_identity() {
    for raw in [
        "name: analyst\ndescription: null",
        "name: analyst\ndescription: [a, b]",
        "name: {nested: identity}\ndescription: Review",
    ] {
        let document = parse_document_content(&format!("---\n{raw}\n---\nBody.\n"));
        assert!(agent_metadata(&document).is_none(), "{raw}");
    }
}

#[test]
fn safe_yaml_public_subagent_import_skips_invalid_without_writing_targets() -> io::Result<()> {
    let root = tempfile::TempDir::new()?;
    let source = root.path().join("agents");
    let target = root.path().join("target");
    fs::create_dir_all(&source)?;
    for (index, raw) in [
        "name: analyst\n' name ': replaced\ndescription: Review",
        "name: analyst\ndescription: Review\n' description ': replaced",
        "name: analyst\ndescription: Review\npermissionMode: readOnly\n' permissionMode ': acceptEdits",
        "name: analyst\ndescription: !unreviewed tagged",
        "name: analyst\ndescription: [nested]",
    ]
    .into_iter()
    .enumerate()
    {
        fs::write(
            source.join(format!("invalid-{index}.md")),
            format!("---\n{raw}\n---\nBody.\n"),
        )?;
    }
    fs::write(
        source.join("valid.md"),
        "---\nname: valid\ndescription: Review\n---\nValid body.\n",
    )?;
    assert_eq!(count_missing_subagents(&source, &target)?, 1);
    assert_eq!(
        missing_subagent_names(&source, &target)?,
        vec!["valid".to_string()],
    );
    assert_eq!(
        import_subagents_with_rewrite_profile(&source, &target, PROFILE)?,
        vec!["valid".to_string()],
    );
    let entries = fs::read_dir(&target)?.collect::<io::Result<Vec<_>>>()?;
    assert_eq!(entries.len(), 1);
    let installed = fs::read_to_string(target.join("valid.toml"))?;
    assert!(installed.contains("Valid body."));
    assert_eq!(
        import_subagents_with_rewrite_profile(&source, &target, PROFILE)?,
        Vec::<String>::new(),
    );
    assert_eq!(fs::read_to_string(target.join("valid.toml"))?, installed);
    Ok(())
}
