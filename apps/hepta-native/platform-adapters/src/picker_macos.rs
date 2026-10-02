use std::ffi::CStr;
use std::ffi::OsString;
use std::os::unix::ffi::OsStringExt as _;
use std::path::PathBuf;
use std::ptr::NonNull;

use objc2::MainThreadMarker;
use objc2_app_kit::NSApplication;
use objc2_app_kit::NSApplicationActivationPolicy;
use objc2_app_kit::NSModalResponseCancel;
use objc2_app_kit::NSModalResponseOK;
use objc2_app_kit::NSOpenPanel;
use objc2_foundation::NSString;

pub(super) fn choose_file() -> Result<Option<PathBuf>, String> {
    let main = MainThreadMarker::new().ok_or("native picker requires the AppKit main thread")?;
    let application = NSApplication::sharedApplication(main);
    application.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    let panel = NSOpenPanel::openPanel(main);
    panel.setTitle(Some(&NSString::from_str("Select a Hepta input file")));
    panel.setAllowsMultipleSelection(false);
    panel.setCanChooseDirectories(false);
    panel.setCanChooseFiles(true);
    panel.setCanCreateDirectories(false);
    panel.setResolvesAliases(false);
    let response = panel.runModal();
    if response == NSModalResponseCancel {
        return Ok(None);
    }
    if response != NSModalResponseOK {
        return Err("AppKit could not complete the file picker".into());
    }
    let urls = panel.URLs();
    if urls.count() != 1 {
        return Err("AppKit picker did not return exactly one file".into());
    }
    let url = urls.objectAtIndex(0);
    if !url.isFileURL() {
        return Err("AppKit picker returned a non-file URL".into());
    }
    let mut buffer = [0_u8; 16 * 1024 + 1];
    // SAFETY: The initialized writable buffer is alive for the complete call,
    // has the supplied capacity, and no Objective-C pointer is retained. The
    // bounded C-string parse below also requires the documented terminator.
    let represented = unsafe {
        url.getFileSystemRepresentation_maxLength(
            NonNull::new(buffer.as_mut_ptr().cast()).expect("array storage is non-null"),
            buffer.len(),
        )
    };
    if !represented {
        return Err("AppKit file path exceeds its representation bound".into());
    }
    let bytes = CStr::from_bytes_until_nul(&buffer)
        .map_err(|_| "AppKit returned an unterminated file path")?
        .to_bytes();
    Ok(Some(PathBuf::from(OsString::from_vec(bytes.to_vec()))))
}
