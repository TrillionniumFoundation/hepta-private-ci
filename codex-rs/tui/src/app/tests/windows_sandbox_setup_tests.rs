use super::*;

#[tokio::test]
async fn legacy_preflight_failure_preserves_permissions_and_restores_input() -> Result<()> {
    let (mut app, mut events, mut operations) = make_test_app_with_channels().await;
    let codex_home = tempdir()?;
    app.config.codex_home = codex_home.path().to_path_buf().abs();
    let config_path = codex_home.path().join("config.toml");
    std::fs::write(&config_path, "approvals_reviewer = \"auto_review\"\n")?;
    let original_app_permissions = (
        app.config.permissions.windows_sandbox_mode,
        RuntimePermissionProfileOverride::from_config(&app.config),
        app.config.approvals_reviewer,
    );
    let original_widget_permissions = (
        app.chat_widget
            .config_ref()
            .permissions
            .windows_sandbox_mode,
        RuntimePermissionProfileOverride::from_config(app.chat_widget.config_ref()),
        app.chat_widget.config_ref().approvals_reviewer,
    );
    let mut app_server = start_config_write_test_app_server(&app).await?;
    let mut tui = crate::tui::test_support::make_test_tui()?;
    let original_config = std::fs::read(&config_path)?;
    while events.try_recv().is_ok() {}
    while operations.try_recv().is_ok() {}

    app.chat_widget.show_windows_sandbox_setup_status();
    let setup = render_bottom_popup(&app.chat_widget, /*width*/ 80);
    assert!(setup.contains("Setting up sandbox..."));

    app.handle_event(
        &mut tui,
        &mut app_server,
        AppEvent::WindowsSandboxLegacySetupFailed {
            error: "The requested permissions require the elevated Windows sandbox.".to_string(),
        },
    )
    .await?;

    assert_eq!(
        (
            app.config.permissions.windows_sandbox_mode,
            RuntimePermissionProfileOverride::from_config(&app.config),
            app.config.approvals_reviewer,
        ),
        original_app_permissions
    );
    assert_eq!(
        (
            app.chat_widget
                .config_ref()
                .permissions
                .windows_sandbox_mode,
            RuntimePermissionProfileOverride::from_config(app.chat_widget.config_ref()),
            app.chat_widget.config_ref().approvals_reviewer,
        ),
        original_widget_permissions
    );
    assert_eq!(std::fs::read(&config_path)?, original_config);
    let cell = match events.try_recv() {
        Ok(AppEvent::InsertHistoryCell(cell)) => cell,
        other => panic!("expected setup failure history event, got {other:?}"),
    };
    insta::assert_snapshot!(lines_to_single_string(&cell.display_lines(/*width*/ 80)));
    assert!(events.try_recv().is_err());
    assert!(operations.try_recv().is_err());
    let restored = render_bottom_popup(&app.chat_widget, /*width*/ 80);
    assert!(!restored.contains("Setting up sandbox..."));
    assert!(!restored.contains("Input disabled until setup completes."));
    app.handle_tui_event(
        &mut tui,
        &mut app_server,
        TuiEvent::Paste("input restored".to_string()),
    )
    .await?;
    assert_eq!(
        app.chat_widget.composer_text_with_pending(),
        "input restored"
    );
    app_server.shutdown().await?;
    Ok(())
}
