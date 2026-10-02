use super::*;

fn observed_text(shape: &egui::Shape, output: &mut Vec<String>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                observed_text(shape, output);
            }
        }
        egui::Shape::Text(text) => output.push(text.galley.text().into()),
        _ => {}
    }
}

#[test]
fn failed_console_can_render_chat_and_cannot_expose_privileged_controls() {
    let mut app = ChatOnlyApp {
        chat: ChatShell::default(),
        console_failure: "Signed console endpoint is unavailable".into(),
    };
    app.chat.locale = Locale::English;
    let ctx = egui::Context::default();
    for (tab, expected, forbidden) in [
        (
            chat_model::AppTab::Chat,
            "Conversations",
            "Signed console endpoint is unavailable",
        ),
        (
            chat_model::AppTab::Console,
            "Console unavailable",
            "Execute with signed grant",
        ),
    ] {
        app.chat.chat.tab = tab;
        let output = ctx.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(
                    egui::Pos2::ZERO,
                    egui::vec2(1180.0, 760.0),
                )),
                ..Default::default()
            },
            |ui| app.show(ui),
        );
        let mut text = Vec::new();
        for shape in &output.shapes {
            observed_text(&shape.shape, &mut text);
        }
        let text = text.join("\n");
        assert!(text.contains(expected), "{text}");
        assert!(!text.contains(forbidden), "{text}");
        assert!(!app.chat.chat_transport_ready());
        output.drop_without_applying_deltas();
    }
    assert!(!app.chat.chat.can_send());
}
