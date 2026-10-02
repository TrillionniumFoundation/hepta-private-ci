//! Explicitly executed, fixture-backed native raster evidence. This is not
//! authenticated gateway, desktop accessibility, or release qualification.
use std::io::Write as _;
use std::path::Path;
use std::path::PathBuf;

use super::super::*;
use winit::platform::x11::EventLoopBuilderExtX11 as _;

struct CaptureApp {
    app: Box<dyn eframe::App>,
    output: PathBuf,
    started: Instant,
    frames: u32,
    requested: bool,
    complete: Arc<Mutex<Option<[usize; 2]>>>,
}

impl eframe::App for CaptureApp {
    fn ui(&mut self, ui: &mut egui::Ui, frame: &mut eframe::Frame) {
        self.app.ui(ui, frame);
        self.frames += 1;
        let screenshot = ui.ctx().input(|input| {
            input.events.iter().find_map(|event| match event {
                egui::Event::Screenshot { image, .. } => Some(Arc::clone(image)),
                _ => None,
            })
        });
        if let Some(image) = screenshot {
            write_ppm(&self.output, &image);
            *self.complete.lock().unwrap() = Some(image.size);
            ui.ctx().send_viewport_cmd(egui::ViewportCommand::Close);
            return;
        }
        assert!(
            self.started.elapsed() < Duration::from_secs(20),
            "native screenshot event did not arrive"
        );
        if !self.requested && self.frames >= 4 {
            ui.ctx()
                .send_viewport_cmd(egui::ViewportCommand::Screenshot(egui::UserData::default()));
            self.requested = true;
        }
        ui.ctx().request_repaint_after(Duration::from_millis(40));
    }
}

fn write_ppm(path: &Path, image: &egui::ColorImage) {
    let mut file = std::io::BufWriter::new(std::fs::File::create(path).unwrap());
    write!(file, "P6\n{} {}\n255\n", image.size[0], image.size[1]).unwrap();
    for pixel in &image.pixels {
        file.write_all(&pixel.to_srgba_unmultiplied()[..3]).unwrap();
    }
    file.flush().unwrap();
}

struct RecoveryCapture {
    failure: StartupFailure,
    retry: StartupRetry,
}

impl eframe::App for RecoveryCapture {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        let decision = super::super::startup_recovery::recovery_view(
            ui,
            &self.failure,
            self.retry,
            Locale::English,
        );
        assert!(decision.is_none(), "capture must not request retry or exit");
    }
}

fn capture_app(
    app: Box<dyn eframe::App>,
    output: PathBuf,
    fonts: egui::FontDefinitions,
    size: [usize; 2],
    zoom: f32,
) -> [usize; 2] {
    let complete = Arc::new(Mutex::new(None));
    let observed = Arc::clone(&complete);
    let options = eframe::NativeOptions {
        renderer: eframe::Renderer::Glow,
        viewport: egui::ViewportBuilder::default()
            .with_title("Hepta Native • LOCAL DISCONNECTED FIXTURE")
            .with_inner_size([size[0] as f32, size[1] as f32])
            .with_resizable(false),
        event_loop_builder: Some(Box::new(|builder| {
            builder.with_x11().with_any_thread(true);
        })),
        ..Default::default()
    };
    eframe::run_native(
        "hepta-native-fixture-capture",
        options,
        Box::new(move |context| {
            context.egui_ctx.set_fonts(fonts);
            context.egui_ctx.set_zoom_factor(zoom);
            Ok(Box::new(CaptureApp {
                app,
                output,
                started: Instant::now(),
                frames: 0,
                requested: false,
                complete,
            }))
        }),
    )
    .unwrap();
    let dimensions = observed
        .lock()
        .unwrap()
        .expect("no raster screenshot captured");
    assert_eq!(dimensions, size);
    dimensions
}

#[test]
#[ignore = "requires an explicitly provisioned Linux display and HEPTA_NATIVE_SCREENSHOT_DIR"]
fn capture_fixture_native_screens() {
    let output = PathBuf::from(
        std::env::var_os("HEPTA_NATIVE_SCREENSHOT_DIR")
            .expect("set an explicit fixture screenshot output directory"),
    );
    assert!(output.is_absolute());
    std::fs::create_dir_all(&output).unwrap();
    let fonts = crate::fonts::load_fallback(None)
        .unwrap()
        .expect("Chinese captures require the native CJK fallback");
    let mut captures = Vec::new();
    for (locale_name, locale) in [("en", Locale::English), ("zh", Locale::Chinese)] {
        for (width, height, zoom) in [(1180, 760, 1.0), (800, 560, 1.0), (1180, 760, 1.5)] {
            for (screen_name, screen) in [
                ("runtime", Screen::Runtime),
                ("operations", Screen::Operations),
                ("updates", Screen::Updates),
                ("accessibility", Screen::Accessibility),
            ] {
                let fixture = tempfile::TempDir::new().unwrap();
                let mut app = super::super::input_event_tests::app_fixture(fixture.path());
                app.screen = screen;
                app.locale = locale;
                let name =
                    format!("fixture-{screen_name}-{locale_name}-{width}x{height}-zoom{zoom}.ppm");
                let dimensions = capture_app(
                    Box::new(app),
                    output.join(&name),
                    fonts.clone(),
                    [width, height],
                    zoom,
                );
                captures.push(serde_json::json!({
                    "file": name,
                    "screen": screen_name,
                    "locale": locale_name,
                    "framebuffer": dimensions,
                    "zoom": zoom,
                }));
            }
        }
    }
    for (name, stage, retry, detail) in [
        (
            "retry-inputs",
            StartupStage::Configuration,
            StartupRetry::InputsOnly,
            "fixture: configured input /operator/config.json is unavailable",
        ),
        (
            "exit-only",
            StartupStage::Initialization,
            StartupRetry::ExitOnly,
            "fixture: local gateway connection failed after initialization began",
        ),
    ] {
        let name = format!("fixture-recovery-{name}-en-800x560-zoom1.ppm");
        let dimensions = capture_app(
            Box::new(RecoveryCapture {
                failure: StartupFailure::new(stage, detail),
                retry,
            }),
            output.join(&name),
            fonts.clone(),
            [800, 560],
            1.0,
        );
        captures.push(serde_json::json!({
            "file": name, "screen": "startup-recovery", "locale": "en",
            "framebuffer": dimensions, "zoom": 1.0,
        }));
    }
    assert_eq!(captures.len(), 26);
    std::fs::write(
        output.join("fixture-capture-manifest.json"),
        serde_json::to_vec_pretty(&serde_json::json!({
            "schema": "hepta.native-fixture-raster-evidence.v1",
            "renderer": "eframe-glow",
            "fixture": true,
            "authenticatedRuntime": false,
            "externalEffects": false,
            "releaseQualification": false,
            "captures": captures,
        }))
        .unwrap(),
    )
    .unwrap();
}
