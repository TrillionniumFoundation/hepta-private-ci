//! Optional local CJK font fallback. Font files are neither embedded nor shipped.
use crate::error::ShellError;
use eframe::egui;
use std::path::{Path, PathBuf};

pub fn load_fallback(explicit: Option<&Path>) -> Result<Option<egui::FontDefinitions>, ShellError> {
    let candidates: &[&str] = if cfg!(windows) {
        &[r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simsun.ttc"]
    } else if cfg!(target_os = "macos") {
        &["/System/Library/Fonts/PingFang.ttc"]
    } else {
        &[
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        ]
    };
    let selected = explicit
        .map(Path::to_path_buf)
        .or_else(|| candidates.iter().map(PathBuf::from).find(|p| p.is_file()));
    let Some(path) = selected else {
        return Ok(None);
    };
    let bytes = crate::file_input::read_bytes(&path, 32 * 1024 * 1024)?;
    if !matches!(
        bytes.get(..4),
        Some(b"\x00\x01\x00\x00" | b"OTTO" | b"ttcf")
    ) {
        return Err(ShellError::InvalidInput(
            "font-file must be a bounded TrueType/OpenType font".into(),
        ));
    }
    let mut fonts = egui::FontDefinitions::default();
    fonts.font_data.insert(
        "hepta-local-cjk".into(),
        std::sync::Arc::new(egui::FontData::from_owned(bytes)),
    );
    for family in [egui::FontFamily::Proportional, egui::FontFamily::Monospace] {
        fonts
            .families
            .entry(family)
            .or_default()
            .push("hepta-local-cjk".into());
    }
    Ok(Some(fonts))
}
