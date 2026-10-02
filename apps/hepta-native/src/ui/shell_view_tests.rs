use super::*;
use crate::ui::input_event_tests::app_fixture;

fn visible_text(shape: &egui::Shape, clip: egui::Rect, output: &mut Vec<String>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                visible_text(shape, clip, output);
            }
        }
        egui::Shape::Text(text)
            if text.opacity_factor > 0.0 && clip.intersects(text.visual_bounding_rect()) =>
        {
            output.push(text.galley.text().to_owned());
        }
        _ => {}
    }
}

fn assert_navigation_galleys(shape: &egui::Shape, clip: egui::Rect, viewport: egui::Rect) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                assert_navigation_galleys(shape, clip, viewport);
            }
        }
        egui::Shape::Text(text)
            if [
                "Chat",
                "Console",
                "Runtime",
                "Operations",
                "Updates",
                "Accessibility",
                "New conversation",
                "Refresh",
            ]
            .contains(&text.galley.text()) =>
        {
            assert_eq!(
                text.galley.rows.len(),
                1,
                "navigation label wrapped: {}",
                text.galley.text()
            );
            let bounds = text.visual_bounding_rect();
            assert!(
                clip.expand(1.0).contains_rect(bounds),
                "navigation label clipped: {}",
                text.galley.text()
            );
            assert!(
                viewport.contains_rect(bounds),
                "navigation label outside viewport: {}",
                text.galley.text()
            );
        }
        _ => {}
    }
}

fn render(
    app: &mut HeptaNativeApp,
    ctx: &egui::Context,
    size: egui::Vec2,
    events: Vec<egui::Event>,
) -> egui::FullOutput {
    ctx.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
            events,
            ..Default::default()
        },
        |ui| app.shell_view(ui),
    )
}

fn text(output: &egui::FullOutput) -> String {
    let mut text = Vec::new();
    for shape in &output.shapes {
        visible_text(&shape.shape, shape.clip_rect, &mut text);
    }
    text.join("\n")
}

#[test]
fn native_shell_normal_and_minimum_viewports() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.screen = Screen::Runtime;
    for (name, size) in [
        ("normal", egui::vec2(1180.0, 760.0)),
        ("minimum", egui::vec2(800.0, 560.0)),
        ("large_text", egui::vec2(800.0 / 1.5, 560.0 / 1.5)),
    ] {
        let ctx = egui::Context::default();
        theme::ensure_initialized(&ctx);
        render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
        let output = render(&mut app, &ctx, size, Vec::new());
        let observed = text(&output);
        let viewport = egui::Rect::from_min_size(egui::Pos2::ZERO, size);
        for shape in &output.shapes {
            assert_navigation_galleys(&shape.shape, shape.clip_rect, viewport);
        }
        for expected in [
            "HEPTA",
            "Runtime",
            "Operations",
            "Updates",
            "Accessibility",
            "No runtime snapshot.",
        ] {
            assert!(
                observed.contains(expected),
                "{name} lost {expected}: {observed}"
            );
        }
        let stable = observed
            .lines()
            .map(|line| {
                if line.starts_with("Platform:") {
                    "Platform: <host>"
                } else {
                    line
                }
            })
            .collect::<Vec<_>>()
            .join("\n");
        insta::with_settings!({prepend_module_to_snapshot => false}, {
            insta::assert_snapshot!(format!("native_shell_{name}"), stable);
        });
        output.drop_without_applying_deltas();
    }
}

#[test]
fn minimum_operations_can_scroll_to_authorization_and_receipts() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(800.0, 560.0);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    let mut observed = String::new();
    for _ in 0..20 {
        let output = render(
            &mut app,
            &ctx,
            size,
            vec![
                egui::Event::PointerMoved(egui::pos2(650.0, 450.0)),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    phase: egui::TouchPhase::Move,
                    delta: egui::vec2(0.0, -300.0),
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        );
        observed.push_str(&text(&output));
        output.drop_without_applying_deltas();
    }
    for expected in [
        "Signed grant path",
        "Prepare exact binding",
        "Execute with signed grant",
        "No operation receipts.",
    ] {
        assert!(
            observed.contains(expected),
            "scroll never exposed {expected}"
        );
    }
    assert!(!app.connected);
    assert!(app.pending_runtime.is_none());
}

#[test]
fn editable_fields_expose_accessible_label_relationships() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    let ctx = egui::Context::default();
    ctx.enable_accesskit();
    let output = render(&mut app, &ctx, egui::vec2(1180.0, 1600.0), Vec::new());
    let tree = output.platform_output.accesskit_update.as_ref().unwrap();
    for field in [
        "native-operation-subject",
        "native-operation-id",
        "native-notification-title",
        "native-notification-body",
        "native-operation-grant",
    ] {
        let id = egui::Id::new(field).accesskit_id();
        let node = &tree
            .nodes
            .iter()
            .find(|(candidate, _)| *candidate == id)
            .unwrap()
            .1;
        assert!(
            !node.labelled_by().is_empty(),
            "missing accessible label for {field}"
        );
    }
    output.drop_without_applying_deltas();
}

#[test]
fn diagnostics_preview_is_bounded_without_splitting_unicode_or_changing_source() {
    let original = "观测".repeat(400_000);
    let (preview, truncated) = diagnostic_preview(&original);
    assert!(truncated);
    assert!(preview.len() <= DIAGNOSTIC_PREVIEW_BYTES);
    assert!(original.starts_with(preview));
    assert_eq!(original.len(), 2_400_000);
    assert_eq!(
        diagnostic_preview("{\"ready\":true}"),
        ("{\"ready\":true}", false)
    );
}

#[test]
fn chat_is_default_and_unavailable_never_fabricates_content() {
    use chat_model::{AppTab, ChatState};
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat = ChatState::default();
    assert_eq!(app.chat_shell.chat.tab, AppTab::Chat);
    for (name, size) in [
        ("wide", egui::vec2(1180.0, 760.0)),
        ("narrow", egui::vec2(520.0, 560.0)),
    ] {
        let ctx = egui::Context::default();
        theme::ensure_initialized(&ctx);
        render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
        let output = render(&mut app, &ctx, size, Vec::new());
        let observed = text(&output);
        let viewport = egui::Rect::from_min_size(egui::Pos2::ZERO, size);
        for shape in &output.shapes {
            assert_navigation_galleys(&shape.shape, shape.clip_rect, viewport);
        }
        for expected in [
            "Chat",
            "Console",
            "Conversations",
            "No conversations to show",
            "Messaging is not connected",
        ] {
            assert!(observed.contains(expected), "{name}: {observed}");
        }
        assert!(!observed.contains("Runtime overview"));
        assert!(!observed.contains("Execute with signed grant"));
        assert!(app.chat_shell.chat.messages.is_empty());
        assert!(!app.chat_shell.chat.can_send());
        insta::with_settings!({prepend_module_to_snapshot => false}, {
            insta::assert_snapshot!(format!("native_chat_{name}"), observed);
        });
        output.drop_without_applying_deltas();
    }
}

#[test]
fn selected_chat_exposes_composer_and_observed_timeline_at_narrow_width() {
    use chat_model::{AppTab, ChatAvailability, ChatState, Conversation, Message};
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat = ChatState {
        tab: AppTab::Chat,
        availability: ChatAvailability::Offline,
        conversations: vec![Conversation {
            id: "fixture".into(),
            title: "Local fixture".into(),
            preview: String::new(),
            unread: 0,
        }],
        selected: Some("fixture".into()),
        messages: vec![Message {
            id: "m1".into(),
            sender: "Fixture sender".into(),
            body: "Observed fixture message".into(),
            timestamp: "12:00".into(),
        }],
        draft: "Unsent draft".into(),
        ..Default::default()
    };
    app.chat_shell.chat_show_list = false;
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    ctx.enable_accesskit();
    let size = egui::vec2(520.0, 560.0);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    let output = render(&mut app, &ctx, size, Vec::new());
    let observed = text(&output);
    for expected in [
        "Back to conversations",
        "Local fixture",
        "Messaging is offline",
        "Observed fixture message",
        "Unsent draft",
        "Send",
    ] {
        assert!(observed.contains(expected), "{observed}");
    }
    assert!(!app.chat_shell.chat.can_send());
    let tree = output.platform_output.accesskit_update.as_ref().unwrap();
    let node = &tree
        .nodes
        .iter()
        .find(|(id, _)| *id == egui::Id::new("chat-composer").accesskit_id())
        .unwrap()
        .1;
    assert!(!node.labelled_by().is_empty());
    insta::with_settings!({prepend_module_to_snapshot => false}, {
        insta::assert_snapshot!("native_chat_selected_offline", observed);
    });
    output.drop_without_applying_deltas();
}

#[test]
fn console_switch_and_back_preserve_unsent_draft_without_runtime_effects() {
    fn target(shape: &egui::Shape, label: &str) -> Option<egui::Pos2> {
        match shape {
            egui::Shape::Vec(shapes) => shapes.iter().find_map(|shape| target(shape, label)),
            egui::Shape::Text(text) if text.galley.text() == label => {
                Some(text.visual_bounding_rect().center())
            }
            _ => None,
        }
    }
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat.tab = chat_model::AppTab::Chat;
    app.chat_shell.chat.draft = "Keep my unsent thought".into();
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(1180.0, 760.0);
    for (label, expected_tab) in [
        ("Console", chat_model::AppTab::Console),
        ("Chat", chat_model::AppTab::Chat),
    ] {
        render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
        let output = render(&mut app, &ctx, size, Vec::new());
        let pos = output
            .shapes
            .iter()
            .find_map(|shape| target(&shape.shape, label))
            .unwrap();
        output.drop_without_applying_deltas();
        render(
            &mut app,
            &ctx,
            size,
            vec![
                egui::Event::PointerMoved(pos),
                egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: true,
                    modifiers: egui::Modifiers::NONE,
                },
                egui::Event::PointerButton {
                    pos,
                    button: egui::PointerButton::Primary,
                    pressed: false,
                    modifiers: egui::Modifiers::NONE,
                },
            ],
        )
        .drop_without_applying_deltas();
        assert_eq!(app.chat_shell.chat.tab, expected_tab);
        assert_eq!(app.chat_shell.chat.draft, "Keep my unsent thought");
        assert!(app.pending_runtime.is_none());
    }
}

#[test]
fn selected_chat_large_text_keeps_send_visible_without_activating_it() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat.tab = chat_model::AppTab::Chat;
    app.chat_shell
        .chat
        .conversations
        .push(chat_model::Conversation {
            id: "fixture".into(),
            title: "Local fixture".into(),
            preview: String::new(),
            unread: 0,
        });
    app.chat_shell.chat.selected = Some("fixture".into());
    app.chat_shell.chat_show_list = false;
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(800.0 / 1.5, 560.0 / 1.5);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    let output = render(&mut app, &ctx, size, Vec::new());
    let observed = text(&output);
    assert!(observed.contains("Send"), "{observed}");
    assert!(observed.contains("Write a message…"), "{observed}");
    assert!(app.pending_runtime.is_none());
    insta::with_settings!({prepend_module_to_snapshot => false}, { insta::assert_snapshot!("native_chat_large_text", observed); });
    output.drop_without_applying_deltas();
}

#[test]
fn keyboard_composer_input_is_a_local_draft_when_disconnected() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat.tab = chat_model::AppTab::Chat;
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(1180.0, 760.0);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    ctx.memory_mut(|memory| memory.request_focus(egui::Id::new("chat-composer")));
    render(
        &mut app,
        &ctx,
        size,
        vec![egui::Event::Text("Local thought".into())],
    )
    .drop_without_applying_deltas();
    render(
        &mut app,
        &ctx,
        size,
        vec![egui::Event::Key {
            key: egui::Key::Enter,
            physical_key: None,
            pressed: true,
            repeat: false,
            modifiers: egui::Modifiers::NONE,
        }],
    )
    .drop_without_applying_deltas();
    assert!(app.chat_shell.chat.draft.starts_with("Local thought"));
    assert!(app.chat_shell.chat.messages.is_empty());
    assert!(!app.chat_shell.chat.sending);
    assert!(app.pending_runtime.is_none());
}

#[test]
fn older_page_exposes_bounded_navigation_and_preserves_composer() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat.tab = chat_model::AppTab::Chat;
    app.chat_shell
        .chat
        .conversations
        .push(chat_model::Conversation {
            id: "room".into(),
            title: "Fixture history".into(),
            preview: String::new(),
            unread: 0,
        });
    app.chat_shell.chat.select("room");
    app.chat_shell.chat_show_list = false;
    let selection_epoch = app.chat_shell.chat.selection_epoch;
    let page_epoch = app.chat_shell.chat.page.begin();
    assert!(app.chat_shell.chat.observe_timeline_page(
        "room",
        selection_epoch,
        page_epoch,
        Some("older".into()),
        Some("earlier".into()),
        vec![chat_model::Message {
            id: "historical".into(),
            sender: "Fixture".into(),
            body: "Previously observed message".into(),
            timestamp: String::new()
        }]
    ));
    app.chat_shell.chat.draft = "Unsent thought".into();
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(520.0, 760.0);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    let output = render(&mut app, &ctx, size, Vec::new());
    let observed = text(&output);
    for expected in [
        "Older messages",
        "Back to latest",
        "Previously observed message",
        "Unsent thought",
        "Send",
    ] {
        assert!(observed.contains(expected), "{observed}");
    }
    insta::with_settings!({prepend_module_to_snapshot => false}, { insta::assert_snapshot!("native_chat_older_page", observed); });
    output.drop_without_applying_deltas();
}

#[test]
fn an_observed_untitled_conversation_is_named_without_inventing_messages() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = app_fixture(root.path());
    app.chat_shell.chat.tab = chat_model::AppTab::Chat;
    app.chat_shell
        .chat
        .conversations
        .push(chat_model::Conversation {
            id: "observed-thread".into(),
            title: String::new(),
            preview: String::new(),
            unread: 0,
        });
    app.chat_shell.chat.select("observed-thread");
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let size = egui::vec2(1180.0, 760.0);
    render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
    let output = render(&mut app, &ctx, size, Vec::new());
    let observed = text(&output);
    assert!(observed.contains("New conversation"), "{observed}");
    assert!(observed.contains("Open conversation"), "{observed}");
    assert!(app.chat_shell.chat.messages.is_empty());
    assert!(app.chat_shell.chat.conversations[0].title.is_empty());
    output.drop_without_applying_deltas();
}

#[test]
fn short_zoomed_chat_reserves_readable_timeline_with_multiline_composer() {
    fn clips(shape: &egui::Shape, clip: egui::Rect, body: &str, heights: &mut Vec<f32>) {
        match shape {
            egui::Shape::Vec(shapes) => {
                for shape in shapes {
                    clips(shape, clip, body, heights);
                }
            }
            egui::Shape::Text(text) if text.galley.text() == body => heights.push(clip.height()),
            _ => {}
        }
    }
    let body = "Timeline reading fixture. This paragraph remains in a usable scrollable message region even with a long multiline draft and history controls.\nSecond line of the observed message.\nLast line of the observed message.";
    for (width, history, draft_rows) in [
        (800.0, false, 1),
        (520.0, false, 1),
        (800.0, true, 1),
        (520.0, true, 1),
        (800.0, false, 80),
        (520.0, false, 80),
        (800.0, true, 80),
        (520.0, true, 80),
    ] {
        let root = tempfile::TempDir::new().unwrap();
        let mut app = app_fixture(root.path());
        app.chat_shell.chat.tab = chat_model::AppTab::Chat;
        app.chat_shell
            .chat
            .conversations
            .push(chat_model::Conversation {
                id: "room".into(),
                title: "Fixture conversation with a longer title".into(),
                preview: String::new(),
                unread: 0,
            });
        app.chat_shell.chat.select("room");
        app.chat_shell.chat_show_list = false;
        app.chat_shell.chat.messages.push(chat_model::Message {
            id: "message".into(),
            sender: "Fixture sender".into(),
            body: body.into(),
            timestamp: "12:00".into(),
        });
        app.chat_shell.chat.draft = "draft line\n".repeat(draft_rows);
        app.chat_shell.chat.sending = true;
        app.chat_shell.chat_bridge.active_turn = Some("fixture-turn".into());
        if history {
            app.chat_shell.chat.page.cursor = Some("older".into());
            app.chat_shell.chat.page.next_cursor = Some("earlier".into());
        }
        let ctx = egui::Context::default();
        ctx.enable_accesskit();
        theme::ensure_initialized(&ctx);
        let size = egui::vec2(width / 1.5, 560.0 / 1.5);
        render(&mut app, &ctx, size, Vec::new()).drop_without_applying_deltas();
        let output = render(&mut app, &ctx, size, Vec::new());
        let mut heights = Vec::new();
        for shape in &output.shapes {
            clips(&shape.shape, shape.clip_rect, body, &mut heights);
        }
        assert!(!heights.is_empty(), "message must remain rendered");
        assert!(
            heights
                .iter()
                .all(|height| *height >= chat_model::design::MIN_TIMELINE_HEIGHT),
            "width={width}, history={history}, draft_rows={draft_rows}, timeline={heights:?}"
        );
        let visible = text(&output);
        for label in ["Message", "Send", "Stop", "Waiting…"] {
            assert!(visible.contains(label), "{label} absent: {visible}");
        }
        let tree = output.platform_output.accesskit_update.as_ref().unwrap();
        let composer = &tree
            .nodes
            .iter()
            .find(|(id, _)| *id == egui::Id::new("chat-composer").accesskit_id())
            .unwrap()
            .1;
        assert!(!composer.labelled_by().is_empty());
        assert_eq!(app.chat_shell.chat.draft.lines().count(), draft_rows);
        output.drop_without_applying_deltas();
    }
}
