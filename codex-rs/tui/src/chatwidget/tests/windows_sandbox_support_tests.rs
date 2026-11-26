use super::permissions::windows_sandbox_requirements_stack;
use super::*;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn windows_supported_enable_prompt_waits_for_explicit_selection() {
    let (mut chat, mut rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    chat.config.permissions.windows_sandbox_mode = None;
    let preset = builtin_approval_presets()
        .into_iter()
        .find(|preset| preset.id == "auto")
        .expect("auto preset");

    chat.open_windows_sandbox_enable_prompt(preset, /*profile_selection*/ None);

    let popup = render_bottom_popup(&chat, /*width*/ 200);
    assert!(popup.contains("non-admin sandbox is unavailable"));
    assert!(popup.contains("requires Administrator permissions"));
    assert!(!popup.contains("Use non-admin sandbox"));
    while let Ok(event) = rx.try_recv() {
        assert!(!matches!(
            event,
            AppEvent::BeginWindowsSandboxElevatedSetup { .. }
                | AppEvent::BeginWindowsSandboxLegacySetup { .. }
        ));
    }
    assert_eq!(chat.config.permissions.windows_sandbox_mode, None);

    chat.handle_key_event(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));

    assert!(matches!(
        rx.try_recv(),
        Ok(AppEvent::BeginWindowsSandboxElevatedSetup { .. })
    ));
    assert_eq!(chat.config.permissions.windows_sandbox_mode, None);
}

#[tokio::test]
async fn windows_supported_fallback_prompt_waits_for_explicit_retry() {
    let (mut chat, mut rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    let preset = builtin_approval_presets()
        .into_iter()
        .find(|preset| preset.id == "auto")
        .expect("auto preset");

    chat.open_windows_sandbox_fallback_prompt(preset, /*profile_selection*/ None);

    let popup = render_bottom_popup(&chat, /*width*/ 200);
    assert!(popup.contains("non-admin sandbox is unavailable"));
    assert!(popup.contains("Administrator permissions and your approval"));
    assert!(!popup.contains("Use Codex with non-admin sandbox"));
    while let Ok(event) = rx.try_recv() {
        assert!(!matches!(
            event,
            AppEvent::BeginWindowsSandboxElevatedSetup { .. }
                | AppEvent::BeginWindowsSandboxLegacySetup { .. }
        ));
    }

    chat.handle_key_event(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));

    assert!(matches!(
        rx.try_recv(),
        Ok(AppEvent::BeginWindowsSandboxElevatedSetup { .. })
    ));
}

#[tokio::test]
async fn windows_unavailable_prompts_respect_organization_mode_restrictions() {
    for fallback in [false, true] {
        let (mut chat, mut rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
        chat.config.permissions.windows_sandbox_mode = Some(WindowsSandboxModeToml::Unelevated);
        chat.config.config_layer_stack =
            windows_sandbox_requirements_stack(vec![WindowsSandboxModeToml::Unelevated]);
        let preset = builtin_approval_presets()
            .into_iter()
            .find(|preset| preset.id == "auto")
            .expect("auto preset");

        if fallback {
            chat.open_windows_sandbox_fallback_prompt(preset, /*profile_selection*/ None);
        } else {
            chat.open_windows_sandbox_enable_prompt(preset, /*profile_selection*/ None);
        }

        let popup = render_bottom_popup(&chat, /*width*/ 200);
        assert!(popup.contains("your organization does not permit the default sandbox"));
        assert!(popup.contains("Contact your administrator"));
        assert!(!popup.contains("Set up default sandbox"));
        assert!(!popup.contains("Try setting up admin sandbox again"));
        assert!(!popup.contains("Use non-admin sandbox"));
        assert!(!popup.contains("Use Codex with non-admin sandbox"));
        while let Ok(event) = rx.try_recv() {
            assert!(!matches!(
                event,
                AppEvent::BeginWindowsSandboxElevatedSetup { .. }
                    | AppEvent::BeginWindowsSandboxLegacySetup { .. }
            ));
        }

        chat.handle_key_event(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));

        assert!(matches!(
            rx.try_recv(),
            Ok(AppEvent::Exit(ExitMode::ShutdownFirst))
        ));
        assert_eq!(
            chat.config.permissions.windows_sandbox_mode,
            Some(WindowsSandboxModeToml::Unelevated)
        );
    }
}

#[tokio::test]
async fn windows_supported_enable_prompt_quit_does_not_start_setup() {
    let (mut chat, mut rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    let preset = builtin_approval_presets()
        .into_iter()
        .find(|preset| preset.id == "auto")
        .expect("auto preset");
    chat.open_windows_sandbox_enable_prompt(preset, /*profile_selection*/ None);
    while let Ok(event) = rx.try_recv() {
        assert!(!matches!(
            event,
            AppEvent::BeginWindowsSandboxElevatedSetup { .. }
                | AppEvent::BeginWindowsSandboxLegacySetup { .. }
        ));
    }

    chat.handle_key_event(KeyEvent::new(KeyCode::Down, KeyModifiers::NONE));
    chat.handle_key_event(KeyEvent::new(KeyCode::Enter, KeyModifiers::NONE));

    assert!(matches!(
        rx.try_recv(),
        Ok(AppEvent::Exit(ExitMode::ShutdownFirst))
    ));
}

#[cfg(target_os = "windows")]
#[tokio::test]
async fn startup_reprompts_for_unavailable_non_admin_sandbox() {
    let (mut chat, _rx, _op_rx) = make_chatwidget_manual(/*model_override*/ None).await;
    chat.set_feature_enabled(Feature::WindowsSandbox, /*enabled*/ true);
    chat.set_feature_enabled(Feature::WindowsSandboxElevated, /*enabled*/ false);

    chat.maybe_prompt_windows_sandbox_enable(/*show_now*/ true);

    let popup = render_bottom_popup(&chat, /*width*/ 200);
    assert!(popup.contains("Set up default sandbox"));
    assert!(popup.contains("non-admin sandbox is unavailable"));
    assert!(!popup.contains("Use non-admin sandbox"));
}
