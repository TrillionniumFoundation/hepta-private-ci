use eframe::egui;
use hepta_native::APP_NAME;
use hepta_native::app::AppOptions;
use hepta_native::app::HeptaApp;
use std::path::PathBuf;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args_os().skip(1);
    let mut post_update_ready: Option<PathBuf> = None;
    while let Some(argument) = args.next() {
        if argument == "--self-test" {
            println!("{}", serde_json::to_string(&hepta_native::self_test()?)?);
            return Ok(());
        }
        if argument == "--version" {
            println!("{}", env!("CARGO_PKG_VERSION"));
            return Ok(());
        }
        if argument == "--post-update-ready" {
            post_update_ready = Some(
                args.next()
                    .map(PathBuf::from)
                    .ok_or("--post-update-ready requires PATH")?,
            );
            continue;
        }
        return Err(format!("unexpected argument: {}", argument.to_string_lossy()).into());
    }

    let native_options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_inner_size([1180.0, 760.0])
            .with_min_inner_size([840.0, 600.0]),
        centered: true,
        ..Default::default()
    };
    eframe::run_native(
        APP_NAME,
        native_options,
        Box::new(move |_cc| {
            let app = HeptaApp::new(AppOptions {
                post_update_ready: post_update_ready.clone(),
            })
            .map_err(|error| -> Box<dyn std::error::Error + Send + Sync> {
                std::io::Error::other(error.to_string()).into()
            })?;
            Ok(Box::new(app))
        }),
    )?;
    Ok(())
}
