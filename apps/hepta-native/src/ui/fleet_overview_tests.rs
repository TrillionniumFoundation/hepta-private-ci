use super::*;

fn visible_text(shape: &egui::Shape, clip: egui::Rect, text: &mut Vec<String>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                visible_text(shape, clip, text);
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

fn paint(overview: &RuntimeOverview, locale: Locale) -> String {
    let context = egui::Context::default();
    let output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1500.0, 1500.0),
            )),
            ..Default::default()
        },
        |ui| {
            overview.render(ui, locale);
        },
    );
    let mut text = Vec::new();
    for clipped in &output.shapes {
        visible_text(&clipped.shape, clipped.clip_rect, &mut text);
    }
    output.drop_without_applying_deltas();
    text.join("\n")
}

#[test]
fn real_widgets_show_agent_failure_and_recovery_in_both_languages() {
    let value = serde_json::json!({
        "schema": "hepta_fleet_observation_v1", "observation_revision": 1,
        "health": {"ready": false, "supervisor_epoch": "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12",
            "process_id": 2233, "registered_agents": 2, "observed_faults": 2},
        "agents": [
            {"agent_id": "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "lifecycle": "failed",
                "lifecycle_generation": 9, "active": false, "healthy": false,
                "process_id": null, "current_release": "agentd-real-owner",
                "control_fence": {"supervisor_epoch": "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12"},
                "matrix": {"configured": true, "healthy": false, "degraded": true,
                    "last_error": "companion process exited"}},
            {"agent_id": "028f4f72-5f8f-7cc1-8f55-df9fb3aa2c12", "lifecycle": "running",
                "lifecycle_generation": 4, "active": true, "healthy": true,
                "process_id": 2456, "current_release": "agentd-real-owner",
                "control_fence": {"supervisor_epoch": "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12"},
                "matrix": {"configured": false, "healthy": false, "degraded": false,
                    "last_error": null}},
        ],
    });
    let overview = RuntimeOverview::prepare(&value).unwrap();
    let rendered = format!(
        "=== English ===\n{}\n\n=== 中文 ===\n{}\n\n=== Legacy ===\n{}",
        paint(&overview, Locale::English),
        paint(&overview, Locale::Chinese),
        paint(&RuntimeOverview::Legacy, Locale::English)
    );
    assert!(!rendered.contains("runtime_snapshot_generation"));
    assert!(!rendered.contains("observation_revision"));
    insta::with_settings!({prepend_module_to_snapshot => false}, {
        insta::assert_snapshot!("fleet_product_overview", rendered);
    });
}

#[test]
fn actual_agent_start_widget_requires_enabled_control_and_returns_exact_agent() {
    let value = serde_json::json!({"schema":"hepta_fleet_observation_v1","observation_revision":1,
        "health":{"ready":true,"supervisor_epoch":"018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12","process_id":2233,"registered_agents":1,"observed_faults":0},
        "agents":[{"agent_id":"018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12","lifecycle":"stopped","lifecycle_generation":7,
            "active":false,"healthy":false,"process_id":null,"current_release":"agentd-v1",
            "control_fence":{"supervisor_epoch":"018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12"},
            "matrix":{"configured":false,"healthy":false,"degraded":false,"last_error":null}}]});
    let overview = RuntimeOverview::prepare(&value).unwrap();
    for enabled in [false, true] {
        let context = egui::Context::default();
        let raw = || egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1500.0, 1500.0),
            )),
            ..Default::default()
        };
        let output = context.run_ui(raw(), |ui| {
            overview.render_controls(ui, Locale::English, enabled);
        });
        let position = output
            .shapes
            .iter()
            .find_map(|clipped| match &clipped.shape {
                egui::Shape::Text(text) if text.galley.text() == "Start" => {
                    Some(text.visual_bounding_rect().center())
                }
                _ => None,
            })
            .expect("actual Start widget");
        output.drop_without_applying_deltas();
        let mut result = None;
        let mut input = raw();
        input.events = vec![
            egui::Event::PointerMoved(position),
            egui::Event::PointerButton {
                pos: position,
                button: egui::PointerButton::Primary,
                pressed: true,
                modifiers: Default::default(),
            },
        ];
        context
            .run_ui(input, |ui| {
                result = overview.render_controls(ui, Locale::English, enabled);
            })
            .drop_without_applying_deltas();
        assert!(result.is_none());
        let mut input = raw();
        input.events = vec![egui::Event::PointerButton {
            pos: position,
            button: egui::PointerButton::Primary,
            pressed: false,
            modifiers: Default::default(),
        }];
        context
            .run_ui(input, |ui| {
                result = overview.render_controls(ui, Locale::English, enabled);
            })
            .drop_without_applying_deltas();
        assert_eq!(
            result,
            enabled.then(|| (
                "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12".into(),
                crate::fleet_lifecycle::FleetLifecycleOperation::Start
            ))
        );
    }
}
