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
            if ["Runtime", "Operations", "Updates", "Accessibility"]
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
