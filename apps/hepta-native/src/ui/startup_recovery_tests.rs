use super::*;

fn collect(shape: &egui::Shape, clip: egui::Rect, lines: &mut Vec<String>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                collect(shape, clip, lines);
            }
        }
        egui::Shape::Text(text) if clip.intersects(text.visual_bounding_rect()) => {
            lines.push(text.galley.text().to_owned())
        }
        _ => {}
    }
}

#[test]
fn startup_recovery_distinguishes_input_retry_from_exit_only() {
    for (name, retry, stage) in [
        (
            "inputs",
            StartupRetry::InputsOnly,
            StartupStage::Configuration,
        ),
        (
            "advanced",
            StartupRetry::ExitOnly,
            StartupStage::Initialization,
        ),
    ] {
        let ctx = egui::Context::default();
        theme::ensure_initialized(&ctx);
        let failure = StartupFailure::new(
            stage,
            "fixture: configured input /operator/config.json is unavailable",
        );
        let output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    egui::Pos2::ZERO,
                    egui::vec2(800.0, 560.0),
                )),
                ..Default::default()
            },
            |ui| {
                assert!(recovery_view(ui, &failure, retry, Locale::English).is_none());
            },
        );
        let mut lines = Vec::new();
        for shape in &output.shapes {
            collect(&shape.shape, shape.clip_rect, &mut lines);
        }
        let rendered = lines.join("\n");
        assert_eq!(
            rendered.contains("Retry setup"),
            retry == StartupRetry::InputsOnly
        );
        assert!(rendered.contains("Exit"));
        insta::with_settings!({prepend_module_to_snapshot => false}, { insta::assert_snapshot!(format!("startup_recovery_{name}"), rendered); });
        output.drop_without_applying_deltas();
    }
}

#[test]
fn recovery_details_bound_untrusted_unicode() {
    let failure = StartupFailure::new(StartupStage::Configuration, "错".repeat(20_000));
    assert!(failure.detail.len() < 4200);
    assert!(failure.detail.ends_with("[details truncated]"));
}

#[test]
fn long_failure_keeps_recovery_controls_visible() {
    let ctx = egui::Context::default();
    theme::ensure_initialized(&ctx);
    let failure = StartupFailure::new(StartupStage::Configuration, "diagnostic line\n".repeat(400));
    let output = ctx.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(800.0, 560.0),
            )),
            ..Default::default()
        },
        |ui| {
            recovery_view(ui, &failure, StartupRetry::InputsOnly, Locale::English);
        },
    );
    let mut lines = Vec::new();
    for shape in &output.shapes {
        collect(&shape.shape, shape.clip_rect, &mut lines);
    }
    assert!(lines.iter().any(|line| line == "Retry setup"));
    assert!(lines.iter().any(|line| line == "Exit"));
    output.drop_without_applying_deltas();
}
