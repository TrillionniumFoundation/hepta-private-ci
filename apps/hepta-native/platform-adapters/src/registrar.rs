//! Explicit per-user shortcut registration. Never invoked by notification send.
use std::ffi::OsString;
use std::os::windows::ffi::OsStrExt as _;
use std::os::windows::ffi::OsStringExt as _;
use std::os::windows::fs::MetadataExt as _;
use std::path::Path;
use std::path::PathBuf;

use windows::Win32::Foundation::PROPERTYKEY;
use windows::Win32::System::Com::CLSCTX_INPROC_SERVER;
use windows::Win32::System::Com::COINIT_APARTMENTTHREADED;
use windows::Win32::System::Com::CoCreateInstance;
use windows::Win32::System::Com::CoInitializeEx;
use windows::Win32::System::Com::CoTaskMemFree;
use windows::Win32::System::Com::CoUninitialize;
use windows::Win32::System::Com::IPersistFile;
use windows::Win32::System::Com::STGM_READ;
use windows::Win32::System::Com::StructuredStorage::InitPropVariantFromPropVariantVectorElem;
use windows::Win32::System::Com::StructuredStorage::InitPropVariantFromStringVector;
use windows::Win32::System::Com::StructuredStorage::PROPVARIANT;
use windows::Win32::UI::Shell::FOLDERID_Programs;
use windows::Win32::UI::Shell::IShellLinkW;
use windows::Win32::UI::Shell::KF_FLAG_DEFAULT;
use windows::Win32::UI::Shell::PropertiesSystem::IPropertyStore;
use windows::Win32::UI::Shell::SHGetKnownFolderPath;
use windows::Win32::UI::Shell::ShellLink;
use windows::core::BSTR;
use windows::core::GUID;
use windows::core::Interface as _;
use windows::core::PCWSTR;

pub const APP_USER_MODEL_ID: &str = "Trillionnium.Hepta.Native";
const APP_USER_MODEL_ID_KEY: PROPERTYKEY = PROPERTYKEY {
    fmtid: GUID::from_u128(0x9f4c2855_9f79_4b39_a8d0_e1d42de1d5f3),
    pid: 5,
};

struct Apartment;
impl Drop for Apartment {
    fn drop(&mut self) {
        // SAFETY: Created only after successful CoInitializeEx on this thread;
        // all COM objects declared after the guard are dropped before it.
        unsafe { CoUninitialize() };
    }
}

fn wide(value: &std::ffi::OsStr) -> Result<Vec<u16>, String> {
    let mut value: Vec<u16> = value.encode_wide().collect();
    if value.contains(&0) || value.len() >= 32_767 {
        return Err("notification identity path is invalid or exceeds its bound".into());
    }
    value.push(0);
    Ok(value)
}

fn app_id_value() -> windows::core::Result<PROPVARIANT> {
    let text: Vec<u16> = APP_USER_MODEL_ID.encode_utf16().chain([0]).collect();
    // SAFETY: Input is a live NUL-terminated string. SDK functions allocate the
    // exact native PROPVARIANT layout and the projection owns its cleanup.
    unsafe {
        let vector = InitPropVariantFromStringVector(Some(&[PCWSTR(text.as_ptr())]))?;
        InitPropVariantFromPropVariantVectorElem(&vector, /*ielem*/ 0)
    }
}

/// Register and read back the fixed Hepta shortcut for the supplied installed
/// executable. Call only for an explicit installer/user registration request.
/// No elevation, registry permission changes, or notification effects occur.
pub fn register(executable: &Path) -> Result<PathBuf, String> {
    register_in(executable, || {
        // SAFETY: Called after apartment initialization. The known-folder API
        // returns an owned CoTaskMem string; copy and release it exactly once.
        unsafe {
            let raw =
                SHGetKnownFolderPath(&FOLDERID_Programs, KF_FLAG_DEFAULT, /*htoken*/ None)
                    .map_err(|error| error.to_string())?;
            let path = PathBuf::from(OsString::from_wide(raw.as_wide()));
            CoTaskMemFree(Some(raw.as_ptr().cast()));
            Ok(path)
        }
    })
}

fn register_in(
    executable: &Path,
    programs: impl FnOnce() -> Result<PathBuf, String>,
) -> Result<PathBuf, String> {
    let metadata = std::fs::symlink_metadata(executable).map_err(|error| error.to_string())?;
    if !executable.is_absolute() || !metadata.is_file() || metadata.file_attributes() & 0x400 != 0 {
        return Err(
            "identity registration requires an absolute regular executable, not a reparse point"
                .into(),
        );
    }
    let directory = executable.parent().ok_or("executable has no parent")?;
    let executable_text = wide(executable.as_os_str())?;
    let directory_text = wide(directory.as_os_str())?;
    let description = wide(std::ffi::OsStr::new("Hepta Native"))?;
    // SAFETY: Registration runs in a fresh explicit main-thread command. No COM
    // object escapes this apartment; a changed apartment is rejected by .ok().
    unsafe {
        CoInitializeEx(/*pvreserved*/ None, COINIT_APARTMENTTHREADED).ok()
    }
    .map_err(|error| error.to_string())?;
    let _apartment = Apartment;
    let programs = programs()?;
    if !programs.is_absolute() || !programs.is_dir() {
        return Err("per-user Start Menu directory is unavailable".into());
    }
    let shortcut = programs.join("Hepta Native.lnk");
    match std::fs::symlink_metadata(&shortcut) {
        Ok(metadata) if !metadata.is_file() || metadata.file_attributes() & 0x400 != 0 => {
            return Err("notification shortcut cannot replace a directory or reparse point".into());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(error.to_string()),
    }
    let shortcut_text = wide(shortcut.as_os_str())?;
    // SAFETY: All pointers reference live bounded NUL-terminated strings or SDK
    // values. Interface owners stay in this apartment and outlive each call.
    let result: windows::core::Result<()> = unsafe {
        (|| {
            let link: IShellLinkW =
                CoCreateInstance(&ShellLink, /*punkouter*/ None, CLSCTX_INPROC_SERVER)?;
            link.SetPath(PCWSTR(executable_text.as_ptr()))?;
            link.SetWorkingDirectory(PCWSTR(directory_text.as_ptr()))?;
            link.SetDescription(PCWSTR(description.as_ptr()))?;
            link.SetIconLocation(PCWSTR(executable_text.as_ptr()), /*iicon*/ 0)?;
            let store: IPropertyStore = link.cast()?;
            store.SetValue(&APP_USER_MODEL_ID_KEY, &app_id_value()?)?;
            store.Commit()?;
            let persist: IPersistFile = link.cast()?;
            persist.Save(PCWSTR(shortcut_text.as_ptr()), /*fremember*/ true)?;
            Ok(())
        })()
    };
    result.map_err(|error| format!("native notification identity registration: {error}"))?;
    verify_saved_shortcut(executable, &shortcut)?;
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&shortcut)
        .and_then(|file| file.sync_all())
        .map_err(|error| error.to_string())?;
    Ok(shortcut)
}

fn verify_saved_shortcut(executable: &Path, shortcut: &Path) -> Result<(), String> {
    let shortcut_text = wide(shortcut.as_os_str())?;
    // SAFETY: The caller holds the apartment and each interface remains on this
    // thread. Reopen persisted bytes; all strings and output buffers stay live.
    let result: windows::core::Result<()> = unsafe {
        (|| {
            let observed: IShellLinkW =
                CoCreateInstance(&ShellLink, /*punkouter*/ None, CLSCTX_INPROC_SERVER)?;
            let persist: IPersistFile = observed.cast()?;
            persist.Load(PCWSTR(shortcut_text.as_ptr()), STGM_READ)?;
            let store: IPropertyStore = observed.cast()?;
            let identity = store.GetValue(&APP_USER_MODEL_ID_KEY)?;
            if BSTR::try_from(&identity)? != APP_USER_MODEL_ID {
                return Err(windows::core::Error::from_hresult(
                    windows::Win32::Foundation::E_FAIL,
                ));
            }
            let mut target = [0_u16; 32_768];
            observed.GetPath(&mut target, std::ptr::null_mut(), /*fflags*/ 0)?;
            let length = target
                .iter()
                .position(|value| *value == 0)
                .unwrap_or(target.len());
            if OsString::from_wide(&target[..length]) != executable.as_os_str() {
                return Err(windows::core::Error::from_hresult(
                    windows::Win32::Foundation::E_FAIL,
                ));
            }
            Ok(())
        })()
    };
    result.map_err(|error| format!("native notification identity registration: {error}"))
}

#[cfg(test)]
#[path = "registrar_tests.rs"]
mod tests;
