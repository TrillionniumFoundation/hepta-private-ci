use super::*;
use pretty_assertions::assert_eq;
use std::fs;
use std::path::Path;

const TEST_REWRITE_PROFILE: RewriteProfile = RewriteProfile::new(
    "CLAUDE.md",
    &[
        "claude code",
        "claude-code",
        "claude_code",
        "claudecode",
        "claude",
    ],
);

#[test]
fn command_skill_names_must_fit_codex_skill_loader_limit() {
    let source_name = "this-is-a-deeply-nested-command-with-a-very-long-name";
    let file = Path::new("commands/this/is/a/deeply/nested/command/with/a/very/long/name.md");
    let document = parse_command_content("---\ndescription: Review PR\n---\nReview\n");

    assert!(
        command_skill_name_if_supported(
            source_name,
            file,
            &document,
            CommandDescriptionMode::RequireFrontmatter,
        )
        .is_none()
    );
}

#[test]
fn commands_with_overlong_descriptions_are_preserved() {
    let description = "x".repeat(1025);
    let document =
        parse_command_content(&format!("---\ndescription: {description}\n---\nReview\n"));

    assert_eq!(
        command_skill_name_if_supported(
            "review",
            Path::new("commands/review.md"),
            &document,
            CommandDescriptionMode::RequireFrontmatter,
        ),
        Some("source-command-review".to_string())
    );

    let rendered = render_command_skill(
        &document.body,
        "source-command-review",
        &description,
        "review",
        TEST_REWRITE_PROFILE,
    );
    assert_eq!(
        parse_command_content(&rendered)
            .description
            .as_ref()
            .map(|value| value.as_deref()),
        Ok(Some(description.as_str()))
    );
}

#[test]
fn commands_with_provider_runtime_expansion_are_skipped() {
    let document = parse_command_content(
        "---\ndescription: Deploy\n---\nDeploy $ARGUMENTS from @release.yaml\n",
    );

    assert!(
        command_skill_name_if_supported(
            "deploy",
            Path::new("commands/deploy.md"),
            &document,
            CommandDescriptionMode::RequireFrontmatter,
        )
        .is_none()
    );
}

#[test]
fn commands_without_description_are_skipped() {
    let document = parse_command_content("Review the current change.\n");

    assert!(
        command_skill_name_if_supported(
            "review",
            Path::new("commands/review.md"),
            &document,
            CommandDescriptionMode::RequireFrontmatter,
        )
        .is_none()
    );
}

#[test]
fn commands_can_derive_descriptions_from_source_names() {
    let root = tempfile::TempDir::new().expect("tempdir");
    let commands = root.path().join("commands");
    let target_skills = root.path().join("skills");
    fs::create_dir_all(&commands).expect("create commands");
    fs::write(
        commands.join("review-code.md"),
        "Review the current change.\n",
    )
    .expect("write command");
    let profile = CommandMigrationProfile::new(
        TEST_REWRITE_PROFILE,
        CommandDescriptionMode::UseSourceNameFallback,
    );

    assert_eq!(
        import_commands_with_profile(&commands, &target_skills, profile).unwrap(),
        vec!["source-command-review-code".to_string()]
    );
    let rendered = fs::read_to_string(
        target_skills
            .join("source-command-review-code")
            .join("SKILL.md"),
    )
    .expect("read migrated command");
    assert!(rendered.contains("description: \"Migrated source command `review-code`\""));
    assert!(rendered.contains("Review the current change."));
}

#[test]
fn command_slug_collisions_are_skipped() {
    let root = tempfile::TempDir::new().expect("tempdir");
    let commands = root.path().join("commands");
    fs::create_dir_all(&commands).expect("create commands");
    fs::write(
        commands.join("foo-bar.md"),
        "---\ndescription: First\n---\nRun the first command.\n",
    )
    .expect("write first command");
    fs::write(
        commands.join("foo_bar.md"),
        "---\ndescription: Second\n---\nRun the second command.\n",
    )
    .expect("write second command");

    assert_eq!(
        unique_supported_command_sources(&commands, CommandDescriptionMode::RequireFrontmatter,)
            .unwrap(),
        Vec::<CommandSource>::new()
    );
}

#[test]
fn safe_yaml_command_description_rejects_duplicate_or_aliased_identity() {
    assert_eq!(
        parse_command_description("description: trusted\ndescription: substituted"),
        Err(InvalidCommandFrontmatter),
    );
    assert_eq!(
        parse_command_description("description: &d trusted\ndescription: *d"),
        Err(InvalidCommandFrontmatter),
    );
    assert_eq!(
        parse_command_description("description: !invoke arbitrary-constructor"),
        Err(InvalidCommandFrontmatter),
    );
}

#[test]
fn safe_yaml_command_migration_only_accepts_scalar_description() {
    assert_eq!(
        parse_command_description("description: 'a safe: command'"),
        Ok(Some("a safe: command".to_string())),
    );
    assert_eq!(
        parse_command_description("description:\n  - dangerous\n  - runtime"),
        Err(InvalidCommandFrontmatter),
    );
    assert_eq!(
        parse_command_description("description: !unknown custom-typed-content"),
        Err(InvalidCommandFrontmatter),
    );
}

#[test]
fn safe_yaml_normalized_description_collisions_are_errors() {
    for raw in [
        "description: first\n' description ': second",
        "' description ': second\ndescription: first",
        "'description ': first\n' description': second",
        "description: same\n' description ': same",
        "description: valid\n' description ': []",
        "description: valid\n'description\u{00a0}': other",
    ] {
        assert_eq!(
            parse_command_description(raw),
            Err(InvalidCommandFrontmatter),
            "{raw}"
        );
    }
}

#[test]
fn safe_yaml_absent_and_rejected_descriptions_stay_distinct() {
    assert_eq!(parse_command_description("other: value"), Ok(None));
    assert_eq!(
        parse_command_description("' description ': 42"),
        Ok(Some("42".to_string())),
    );
    assert_eq!(
        parse_command_description("description: null"),
        Err(InvalidCommandFrontmatter)
    );
    assert_eq!(
        parse_command_description("[not, a, mapping]"),
        Err(InvalidCommandFrontmatter)
    );
}

#[test]
fn safe_yaml_fallback_cannot_import_rejected_frontmatter() -> io::Result<()> {
    let root = tempfile::TempDir::new()?;
    let source = root.path().join("commands");
    let target = root.path().join("skills");
    fs::create_dir_all(&source)?;
    for (index, raw) in [
        "description: trusted\ndescription: substituted",
        "description: !unreviewed tagged",
        "description: &d trusted\ndescription: *d",
        "description: trusted\n' description ': substituted",
        "description: [nested, values]",
        "[not, a, mapping]",
        "description: 'unterminated",
    ]
    .into_iter()
    .enumerate()
    {
        fs::write(
            source.join(format!("invalid-{index}.md")),
            format!("---\n{raw}\n---\nUnaccepted command body.\n"),
        )?;
    }
    fs::write(
        source.join("valid.md"),
        "Ordinary command without frontmatter.\n",
    )?;
    let profile = CommandMigrationProfile::new(
        TEST_REWRITE_PROFILE,
        CommandDescriptionMode::UseSourceNameFallback,
    );
    assert_eq!(
        missing_command_names_with_profile(&source, &target, profile)?,
        vec!["source-command-valid".to_string()],
    );
    assert_eq!(
        import_commands_with_profile(&source, &target, profile)?,
        vec!["source-command-valid".to_string()],
    );
    let entries = fs::read_dir(&target)?.collect::<io::Result<Vec<_>>>()?;
    assert_eq!(entries.len(), 1);
    let contents = fs::read_to_string(target.join("source-command-valid/SKILL.md"))?;
    assert!(contents.contains("Ordinary command without frontmatter."));
    Ok(())
}

#[test]
fn safe_yaml_valid_missing_description_retains_original_fallback() {
    for source in [
        "A body without a header.",
        "---\nother: value\n---\nA body.",
    ] {
        let document = parse_command_content(source);
        assert!(document.description.is_ok());
        assert_eq!(
            command_skill_description(
                &document,
                "valid",
                CommandDescriptionMode::UseSourceNameFallback,
            ),
            Some("Migrated source command `valid`".to_string()),
        );
        assert_eq!(
            command_skill_description(
                &document,
                "valid",
                CommandDescriptionMode::RequireFrontmatter,
            ),
            None,
        );
    }
}

#[test]
fn safe_yaml_unterminated_header_is_not_absent_frontmatter() {
    let document = parse_command_content("---\ndescription: unfinished\nA body.");
    assert!(document.description.is_err());
    assert_eq!(
        command_skill_description(
            &document,
            "unfinished",
            CommandDescriptionMode::UseSourceNameFallback,
        ),
        None,
    );
}

#[test]
fn safe_yaml_import_rechecks_rejection_after_source_discovery() -> io::Result<()> {
    let root = tempfile::TempDir::new()?;
    let source = root.path().join("commands");
    let target = root.path().join("skills");
    fs::create_dir_all(&source)?;
    fs::create_dir_all(&target)?;
    let path = source.join("changed.md");
    fs::write(&path, "Ordinary body.\n")?;
    let sources =
        unique_supported_command_sources(&source, CommandDescriptionMode::UseSourceNameFallback)?;
    assert_eq!(sources.len(), 1);
    fs::write(
        &path,
        "---\ndescription: !unreviewed changed\n---\nNew body.\n",
    )?;
    let profile = CommandMigrationProfile::new(
        TEST_REWRITE_PROFILE,
        CommandDescriptionMode::UseSourceNameFallback,
    );
    assert_eq!(
        import_command_sources(sources, &target, profile, CommandSkillSizeLimit::Unbounded)?,
        Vec::<String>::new(),
    );
    assert_eq!(fs::read_dir(&target)?.count(), 0);
    Ok(())
}
