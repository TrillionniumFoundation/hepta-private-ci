//! Headless evidence from the real eframe app callback, with no live backend or OS effects.
use super::*;
use base64::Engine as _;
use eframe::App as _;
use serde_json::json;

#[derive(Clone, Copy)]
enum Presentation {
    Disconnected,
    AuthenticatedFixture,
    LongInputError,
    ManyModules,
    ScrolledBottom,
    FocusedGrant,
    MaximumCounters,
}

#[derive(Clone, Copy)]
enum CaptureMode {
    BundledFontSnapshot,
    NativeFontExport,
}

fn text_runs(shape: &egui::Shape, clip: egui::Rect, output: &mut Vec<serde_json::Value>) {
    match shape {
        egui::Shape::Vec(shapes) => {
            for shape in shapes {
                text_runs(shape, clip, output);
            }
        }
        egui::Shape::Text(shape) if !shape.galley.is_empty() && shape.opacity_factor > 0.0 => {
            let rect = shape.visual_bounding_rect();
            output.push(json!({
                "text": shape.galley.text(),
                "rect": [rect.min.x, rect.min.y, rect.max.x, rect.max.y],
                "clip": [clip.min.x, clip.min.y, clip.max.x, clip.max.y],
                "visible": clip.intersects(rect),
            }));
        }
        _ => {}
    }
}

fn capture(
    name: &str,
    screen: Screen,
    locale: Locale,
    size: egui::Vec2,
    scale: f32,
    presentation: Presentation,
) {
    capture_frame(
        name,
        screen,
        locale,
        size,
        scale,
        presentation,
        CaptureMode::BundledFontSnapshot,
    );
    if std::env::var_os("HEPTA_NATIVE_VISUAL_QA_DIR").is_some() {
        capture_frame(
            name,
            screen,
            locale,
            size,
            scale,
            presentation,
            CaptureMode::NativeFontExport,
        );
    }
}

fn capture_frame(
    name: &str,
    screen: Screen,
    locale: Locale,
    size: egui::Vec2,
    scale: f32,
    presentation: Presentation,
    mode: CaptureMode,
) {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = input_event_tests::app_fixture(root.path());
    app.screen = screen;
    app.locale = locale;
    app.manifest.address = "127.0.0.1:8765".to_owned();
    // This path is presentation-only; the updater and private-state owner retain
    // the isolated temporary root. No prepare, execute, or update action occurs.
    app.pending_update_path = PathBuf::from("/fixture/hepta-native/updates/pending.json");
    match presentation {
        Presentation::Disconnected | Presentation::ScrolledBottom | Presentation::FocusedGrant => {}
        Presentation::AuthenticatedFixture
        | Presentation::ManyModules
        | Presentation::MaximumCounters => {
            app.connected = true;
            let counter = if matches!(presentation, Presentation::MaximumCounters) {
                u64::MAX
            } else {
                42
            };
            app.view_revision = Some(counter);
            app.ready_view = Some(RuntimeView {
                session_id: "fixture.session".to_owned(),
                session_generation: counter,
                generation: counter,
                revision: counter,
                digest: "2".repeat(64),
                modules: if matches!(presentation, Presentation::ManyModules) {
                    (0..1000)
                        .map(|index| format!("fixture.module.{index:04}.{}", "long".repeat(27)))
                        .collect()
                } else {
                    vec![
                        "runtime.agentd".to_owned(),
                        "ui.native".to_owned(),
                        "control.runtime".to_owned(),
                    ]
                },
            });
            app.status_rendered = Some(
                serde_json::to_string_pretty(&json!({
                    "fixture": true,
                    "state": {"runtime_snapshot_generation": 42},
                    "modules": app.ready_view.as_ref().unwrap().modules,
                    "note": "Synthetic presentation only. No live runtime is connected."
                }))
                .unwrap(),
            );
            app.operation_subject_id = "fixture.authority".to_owned();
            app.operation_id = "fixture.operation.42".to_owned();
            app.notification_title = "Visual QA fixture".to_owned();
            app.notification_body =
                "This state is local test data; no notification is sent.".to_owned();
        }
        Presentation::LongInputError => {
            app.operation_subject_id =
                "fixture.authority.subject.with.a.long.identifier.for.narrow.layouts".to_owned();
            app.operation_id =
                "fixture.operation.with.a.long.identifier.for.keyboard.and.scroll.review"
                    .to_owned();
            app.operation_grant_path = "/fixture/independent-authority/long-directory-name/another-long-directory/signed-final-use-grant-for-exact-operation.json".to_owned();
            app.last_error = Some("Fixture validation error: the selected signed grant does not match the current operation binding. Refresh the runtime and prepare a new exact binding before trying again.".to_owned());
            app.notification_title = "Long-input validation fixture".to_owned();
            app.notification_body = "A test-only body with enough content to check text field wrapping and viewport clipping without creating an external notification.".to_owned();
        }
    }
    if let Some(view) = &app.ready_view {
        app.control_projection =
            Some(project_native_runtime_view(&app.manifest.endpoint_id, view).unwrap());
    }
    let context = egui::Context::default();
    context.set_visuals(egui::Visuals::dark());
    context.set_pixels_per_point(scale);
    if matches!(mode, CaptureMode::NativeFontExport)
        && let Some(fonts) = crate::fonts::load_fallback(None).unwrap()
    {
        context.set_fonts(fonts);
    }
    let mut frame = eframe::Frame::_new_kittest();
    let mut textures = Vec::new();
    let mut final_output = None;
    // Panels and font atlas settle before capture. Fixed timestamps make
    // animation and cursor state reproducible; this fixture has no worker.
    let frame_count = if matches!(presentation, Presentation::FocusedGrant) {
        24
    } else {
        6
    };
    for tick in 0..frame_count {
        let mut events = Vec::new();
        if matches!(presentation, Presentation::FocusedGrant) {
            if tick == 2 {
                context.memory_mut(|memory| {
                    memory.request_focus(egui::Id::new("native-operation-subject"))
                });
            }
            if tick >= 3
                && context.memory(|memory| memory.focused())
                    != Some(egui::Id::new("native-operation-grant"))
            {
                events.push(egui::Event::Key {
                    key: egui::Key::Tab,
                    physical_key: Some(egui::Key::Tab),
                    pressed: true,
                    repeat: false,
                    modifiers: egui::Modifiers::NONE,
                });
            }
        }
        if tick == 3 && matches!(presentation, Presentation::ScrolledBottom) {
            events = vec![
                egui::Event::PointerMoved(egui::pos2(size.x / 2.0, size.y / 2.0)),
                egui::Event::MouseWheel {
                    unit: egui::MouseWheelUnit::Point,
                    delta: egui::vec2(0.0, -2000.0),
                    phase: egui::TouchPhase::Move,
                    modifiers: egui::Modifiers::NONE,
                },
            ];
        }
        let mut output = context.run_ui(
            egui::RawInput {
                screen_rect: Some(egui::Rect::from_min_size(egui::Pos2::ZERO, size)),
                time: Some(tick as f64 / 60.0),
                events,
                ..Default::default()
            },
            |ui| app.ui(ui, &mut frame),
        );
        for (id, deltas) in output.textures_delta.set.drain() {
            for delta in deltas {
                let egui::ImageData::Color(image) = delta.image;
                let pixels: Vec<u8> = image
                    .pixels
                    .iter()
                    .flat_map(|pixel| pixel.to_array())
                    .collect();
                textures.push(json!({
                    "id": format!("{id:?}"),
                    "size": image.size,
                    "position": delta.pos,
                    "rgba_base64": base64::engine::general_purpose::STANDARD.encode(pixels),
                    "filter": format!("{:?}", delta.options.magnification),
                }));
            }
        }
        assert!(output.textures_delta.free.is_empty());
        output.textures_delta.clear();
        if let Some(previous) = final_output.replace(output) {
            let previous: egui::FullOutput = previous;
            previous.drop_without_applying_deltas();
        }
    }
    let output = final_output.unwrap();
    let mut runs = Vec::new();
    for clipped in &output.shapes {
        text_runs(&clipped.shape, clipped.clip_rect, &mut runs);
    }
    let visible = runs
        .iter()
        .filter(|run| run["visible"] == true)
        .map(|run| run["text"].as_str().unwrap())
        .collect::<Vec<_>>()
        .join("\n");
    if matches!(presentation, Presentation::ScrolledBottom) {
        assert!(
            visible.contains("No operation receipts."),
            "The bottom of the real form must be reachable by scrolling"
        );
    }
    if matches!(presentation, Presentation::FocusedGrant) {
        assert_eq!(
            context.memory(|memory| memory.focused()),
            Some(egui::Id::new("native-operation-grant"))
        );
        assert!(
            visible.contains("Signed grant path"),
            "Keyboard focus must reveal the offscreen grant field"
        );
    }
    if matches!(mode, CaptureMode::BundledFontSnapshot) {
        let visible = visible
            .replace(
                &format!("{} / {}", std::env::consts::OS, std::env::consts::ARCH),
                "<platform> / <architecture>",
            )
            .replace(
                &format!("{}/{}", std::env::consts::OS, std::env::consts::ARCH),
                "<platform>/<architecture>",
            );
        insta::with_settings!({prepend_module_to_snapshot => false}, {
            insta::assert_snapshot!(name, visible);
        });
    }
    if matches!(mode, CaptureMode::NativeFontExport)
        && let Some(directory) = std::env::var_os("HEPTA_NATIVE_VISUAL_QA_DIR")
    {
        let directory = PathBuf::from(directory);
        std::fs::create_dir_all(&directory).unwrap();
        let primitives = context.tessellate(output.shapes.clone(), output.pixels_per_point);
        let meshes: Vec<_> = primitives
            .into_iter()
            .map(|clipped| {
                let egui::epaint::Primitive::Mesh(mesh) = clipped.primitive else {
                    panic!("headless exporter does not support paint callbacks");
                };
                json!({
                    "clip": [clipped.clip_rect.min.x, clipped.clip_rect.min.y,
                        clipped.clip_rect.max.x, clipped.clip_rect.max.y],
                    "texture": format!("{:?}", mesh.texture_id),
                    "indices": mesh.indices,
                    "vertices": mesh.vertices.iter().map(|vertex| json!({
                        "position": [vertex.pos.x, vertex.pos.y],
                        "uv": [vertex.uv.x, vertex.uv.y],
                        "color": vertex.color.to_array(),
                    })).collect::<Vec<_>>(),
                })
            })
            .collect();
        let evidence = json!({
            "schema": "hepta.native-headless-visual-qa.v1",
            "fixture": "synthetic presentation; no runtime connection, grant, or OS effect",
            "renderer_input": "real eframe::App::ui callback and egui 0.36.2 tessellation",
            "name": name,
            "logical_size": [size.x, size.y],
            "pixels_per_point": output.pixels_per_point,
            "clear_color": app.clear_color(&context.style_of(egui::Theme::Dark).visuals),
            "textures": textures,
            "meshes": meshes,
            "text_runs": runs,
            "focused_widget": context.memory(|memory| memory.focused()).map(|id| format!("{id:?}")),
        });
        std::fs::write(
            directory.join(format!("{name}.json")),
            serde_json::to_vec(&evidence).unwrap(),
        )
        .unwrap();
    }
    output.drop_without_applying_deltas();
    assert!(app.all_tasks_idle());
}

#[test]
fn native_workspace_headless_snapshots() {
    let desktop = egui::vec2(1180.0, 760.0);
    for (name, screen) in [
        ("native_runtime", Screen::Runtime),
        ("native_operations", Screen::Operations),
        ("native_updates", Screen::Updates),
        ("native_accessibility", Screen::Accessibility),
    ] {
        capture(
            name,
            screen,
            Locale::English,
            desktop,
            1.0,
            Presentation::Disconnected,
        );
    }
    capture(
        "native_operations_narrow",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0),
        1.0,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_150",
        Screen::Operations,
        Locale::English,
        desktop,
        1.5,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_zh",
        Screen::Operations,
        Locale::Chinese,
        desktop,
        1.0,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_zh_150",
        Screen::Operations,
        Locale::Chinese,
        desktop,
        1.5,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_scaled_viewport",
        Screen::Operations,
        Locale::English,
        desktop / 1.5,
        1.5,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_zh_scaled_viewport",
        Screen::Operations,
        Locale::Chinese,
        desktop / 1.5,
        1.5,
        Presentation::Disconnected,
    );
    capture(
        "native_runtime_authenticated_fixture",
        Screen::Runtime,
        Locale::English,
        desktop,
        1.0,
        Presentation::AuthenticatedFixture,
    );
    capture(
        "native_operations_authenticated_fixture",
        Screen::Operations,
        Locale::English,
        desktop,
        1.0,
        Presentation::AuthenticatedFixture,
    );
    capture(
        "native_operations_error_narrow",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0),
        1.0,
        Presentation::LongInputError,
    );
    capture(
        "native_runtime_many_modules",
        Screen::Runtime,
        Locale::English,
        desktop,
        1.0,
        Presentation::ManyModules,
    );
    capture(
        "native_operations_scrolled_narrow",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0),
        1.0,
        Presentation::ScrolledBottom,
    );
    capture(
        "native_operations_focus_narrow",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0),
        1.0,
        Presentation::FocusedGrant,
    );
    capture(
        "native_operations_640",
        Screen::Operations,
        Locale::English,
        egui::vec2(640.0, 560.0),
        1.0,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_min_scaled",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0) / 1.5,
        1.5,
        Presentation::Disconnected,
    );
    capture(
        "native_operations_min_scaled_scrolled",
        Screen::Operations,
        Locale::English,
        egui::vec2(800.0, 560.0) / 1.5,
        1.5,
        Presentation::ScrolledBottom,
    );
    capture(
        "native_runtime_maximum_counters",
        Screen::Runtime,
        Locale::English,
        desktop,
        1.0,
        Presentation::MaximumCounters,
    );
}

#[test]
fn native_form_keyboard_tab_and_unicode_input() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = input_event_tests::app_fixture(root.path());
    let context = egui::Context::default();
    let mut frame = eframe::Frame::_new_kittest();
    let render = |app: &mut HeptaNativeApp, frame: &mut eframe::Frame, events: Vec<egui::Event>| {
        context
            .run_ui(
                egui::RawInput {
                    screen_rect: Some(egui::Rect::from_min_size(
                        egui::Pos2::ZERO,
                        egui::vec2(800.0, 560.0),
                    )),
                    events,
                    ..Default::default()
                },
                |ui| app.ui(ui, frame),
            )
            .drop_without_applying_deltas();
    };
    render(&mut app, &mut frame, Vec::new());
    context.memory_mut(|memory| memory.request_focus(egui::Id::new("native-operation-subject")));
    render(
        &mut app,
        &mut frame,
        vec![egui::Event::Text("fixture.subject".to_owned())],
    );
    assert_eq!(app.operation_subject_id, "fixture.subject");
    let tab = |modifiers| egui::Event::Key {
        key: egui::Key::Tab,
        physical_key: Some(egui::Key::Tab),
        pressed: true,
        repeat: false,
        modifiers,
    };
    render(&mut app, &mut frame, vec![tab(egui::Modifiers::NONE)]);
    assert_eq!(
        context.memory(|memory| memory.focused()),
        Some(egui::Id::new("native-operation-id"))
    );
    render(
        &mut app,
        &mut frame,
        vec![egui::Event::Text("fixture.operation".to_owned())],
    );
    assert_eq!(app.operation_id, "fixture.operation");
    render(&mut app, &mut frame, vec![tab(egui::Modifiers::SHIFT)]);
    render(&mut app, &mut frame, Vec::new());
    assert_eq!(
        context.memory(|memory| memory.focused()),
        Some(egui::Id::new("native-operation-subject"))
    );
    context.memory_mut(|memory| memory.request_focus(egui::Id::new("native-notification-body")));
    render(
        &mut app,
        &mut frame,
        vec![egui::Event::Text("中文输入 fixture".to_owned())],
    );
    assert_eq!(app.notification_body, "中文输入 fixture");
    assert!(app.all_tasks_idle());
}

#[test]
fn native_diagnostic_preview_is_utf8_bounded_and_preserves_full_source() {
    let root = tempfile::TempDir::new().unwrap();
    let mut app = input_event_tests::app_fixture(root.path());
    let source = format!("{}中{}", "a".repeat(16 * 1024 - 1), "tail".repeat(5000));
    app.status_rendered = Some(source.clone());
    let context = egui::Context::default();
    theme::install(&context);
    context.memory_mut(|memory| memory.set_everything_is_visible(true));
    let mut output = context.run_ui(
        egui::RawInput {
            screen_rect: Some(egui::Rect::from_min_size(
                egui::Pos2::ZERO,
                egui::vec2(1180.0, 1600.0),
            )),
            ..Default::default()
        },
        |ui| {
            app.runtime_view(ui);
        },
    );
    output.textures_delta.clear();
    let mut runs = Vec::new();
    for clipped in &output.shapes {
        text_runs(&clipped.shape, clipped.clip_rect, &mut runs);
    }
    assert!(runs.iter().any(|run| {
        run["text"]
            .as_str()
            .unwrap()
            .starts_with("Preview limited to 16 KiB")
    }));
    assert!(
        runs.iter()
            .all(|run| run["text"].as_str().unwrap().len() <= 16 * 1024)
    );
    assert_eq!(app.status_rendered, Some(source));
    output.drop_without_applying_deltas();
}
