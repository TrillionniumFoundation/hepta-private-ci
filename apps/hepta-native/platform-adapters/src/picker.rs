//! One native modal file picker. Call from the isolated helper's main thread.
//! Returned paths are untrusted input; no file is opened or authorized here.
use std::path::PathBuf;

#[cfg(target_os = "macos")]
#[path = "picker_macos.rs"]
mod native;
#[cfg(target_os = "windows")]
#[path = "picker_windows.rs"]
mod native;

pub fn choose_file() -> Result<Option<PathBuf>, String> {
    native::choose_file()
}
