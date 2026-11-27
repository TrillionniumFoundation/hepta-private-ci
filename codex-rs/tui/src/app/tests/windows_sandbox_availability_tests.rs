use super::*;
use codex_utils_approval_presets::builtin_approval_presets;

#[tokio::test]
async fn unavailable_enable_events_preserve_config_and_report_failure() -> Result<()> {
    for mode in [
        WindowsSandboxEnableMode::Legacy,
        WindowsSandboxEnableMode::Elevated,
    ] {
        let (mut app, mut events, mut operations) = make_test_app_with_channels().await;
        let home = tempdir()?;
        app.config.codex_home = home.path().to_path_buf().abs();
        let config_path = home.path().join("config.toml");
        std::fs::write(&config_path, "# retain the original configuration\n")?;
        let mut app_server = start_config_write_test_app_server(&app).await?;
        let mut tui = crate::tui::test_support::make_test_tui()?;
        let config_before = std::fs::read(&config_path)?;
        let state_before = (
            app.config.permissions.windows_sandbox_mode,
            crate::windows_sandbox::level_from_config(&app.config),
            RuntimePermissionProfileOverride::from_config(app.chat_widget.config_ref()),
            app.config.approvals_reviewer,
        );
        app.chat_widget.show_windows_sandbox_setup_status();
        app.windows_sandbox.setup_started_at = Some(Instant::now());
        while events.try_recv().is_ok() {}
        while operations.try_recv().is_ok() {}
        let preset = builtin_approval_presets()
            .into_iter()
            .find(|preset| preset.id == "auto")
            .expect("auto permissions preset");

        let control = Box::pin(app.handle_event(
            &mut tui,
            &mut app_server,
            AppEvent::EnableWindowsSandboxForAgentMode {
                preset,
                mode,
                profile_selection: None,
            },
        ))
        .await?;

        assert!(matches!(control, AppRunControl::Continue));
        assert_eq!(
            (
                app.config.permissions.windows_sandbox_mode,
                crate::windows_sandbox::level_from_config(&app.config),
                RuntimePermissionProfileOverride::from_config(app.chat_widget.config_ref()),
                app.config.approvals_reviewer,
            ),
            state_before
        );
        assert_eq!(std::fs::read(config_path)?, config_before);
        assert!(app.windows_sandbox.setup_started_at.is_none());
        let cell = match events.try_recv()? {
            AppEvent::InsertHistoryCell(cell) => cell,
            other => panic!("expected refusal notice, got {other:?}"),
        };
        let rendered = lines_to_single_string(&cell.display_lines(/*width*/ 512));
        insta::assert_snapshot!(rendered, @"■ Windows managed filesystem execution is unavailable: the current token backends cannot enforce deletion restrictions; the requested child was not launched and no elevation or unsandboxed fallback is permitted");
        assert!(
            events.try_recv().is_err(),
            "no success or permission-update event"
        );
        assert!(operations.try_recv().is_err(), "no turn-context change");
        app_server.shutdown().await?;
    }
    Ok(())
}
