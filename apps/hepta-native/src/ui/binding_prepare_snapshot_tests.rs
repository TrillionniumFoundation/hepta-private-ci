use super::*;

fn collect_visible_text(shape: &egui::Shape, clip: egui::Rect, text: &mut Vec<String>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                collect_visible_text(shape, clip, text);
            }
        }
        egui::Shape::Text(shape)
            if !shape.galley.is_empty()
                && shape.opacity_factor > 0.0
                && clip.intersects(shape.visual_bounding_rect()) =>
        {
            text.push(shape.galley.text().to_owned());
        }
        _ => {}
    }
}

fn render_operations(context: &egui::Context, app: &mut HeptaNativeApp) -> String {
    let output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1600.0, 1600.0),
            )),
            ..Default::default()
        },
        |ui| {
            app.top_bar(ui);
            app.operations_view(ui);
        },
    );
    let mut text = Vec::new();
    for clipped in &output.shapes {
        collect_visible_text(&clipped.shape, clipped.clip_rect, &mut text);
    }
    output.drop_without_applying_deltas();
    // Capacity telemetry is unrelated to the binding projection and disappears
    // while the admitted worker holds the owner. Keep all other painted text.
    text.retain(|line| !line.starts_with("active="));
    text.join("\n")
}

#[test]
fn pending_and_stale_binding_rendered_output() {
    let mut fixture = fixture();
    fixture.app.operation_action = PlatformAction::CopyText;
    fixture.app.operation_text = "original clipboard payload".to_owned();
    fixture.app.prepare_operation_binding();
    assert_eq!(
        fixture
            .entered
            .recv_timeout(Duration::from_secs(5))
            .unwrap(),
        PlatformPayload::CopyText {
            text: "original clipboard payload".to_owned(),
        }
    );

    // Exercise the real widgets and painter without a native window, GPU,
    // compositor or OS effect. The owned worker is still blocked in its adapter.
    let context = egui::Context::default();
    context.set_visuals(egui::Visuals::dark());
    let pending = render_operations(&context, &mut fixture.app);
    fixture.app.operation_text = "edited clipboard payload".to_owned();
    fixture.release.send(()).unwrap();
    finish_runtime_task(&mut fixture.app);
    let stale = render_operations(&context, &mut fixture.app);
    let rendered = format!("=== Preparing ===\n{pending}\n\n=== Stale result ===\n{stale}");
    insta::with_settings!({prepend_module_to_snapshot => false}, {
        insta::assert_snapshot!("binding_preparation_and_stale_projection", rendered);
    });
}
