//! Explicit per-user shortcut registration. Never invoked by notification send.
use std::ffi::OsString;
use std::fs::File;
use std::os::windows::ffi::OsStrExt as _;
use std::os::windows::ffi::OsStringExt as _;
use std::os::windows::fs::MetadataExt as _;
use std::os::windows::fs::OpenOptionsExt as _;
use std::os::windows::io::AsRawHandle as _;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;
use std::path::Prefix;

use windows::Win32::Foundation::HANDLE;
use windows::Win32::Foundation::PROPERTYKEY;
use windows::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows::Win32::Storage::FileSystem::FILE_ID_INFO;
use windows::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows::Win32::Storage::FileSystem::FileIdInfo;
use windows::Win32::Storage::FileSystem::GetFileInformationByHandleEx;
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

fn registration_error(stage: &'static str, error: windows::core::Error) -> windows::core::Error {
    // Retain the HRESULT and a bounded operation label, never input paths or IDs.
    windows::core::Error::new(error.code(), stage)
}

fn open_registration_target(path: &Path) -> windows::core::Result<File> {
    // File IDs identify the base file, not individual alternate data streams.
    // Admit only ordinary absolute disk/UNC paths and the unnamed stream before
    // any filesystem call; device/pipe/GLOBALROOT namespaces are not executables.
    let contains_colon =
        |value: &std::ffi::OsStr| value.encode_wide().any(|unit| unit == u16::from(b':'));
    let ordinary_prefix = if let Some(Component::Prefix(prefix)) = path.components().next() {
        match prefix.kind() {
            Prefix::Disk(_) | Prefix::VerbatimDisk(_) => true,
            Prefix::UNC(server, share) | Prefix::VerbatimUNC(server, share) => {
                !contains_colon(server) && !contains_colon(share)
            }
            Prefix::DeviceNS(_) | Prefix::Verbatim(_) => false,
        }
    } else {
        false
    };
    let stream_component = path
        .components()
        .any(|component| matches!(component, Component::Normal(value) if contains_colon(value)));
    if !path.is_absolute() || !ordinary_prefix || stream_component {
        return Err(windows::core::Error::new(
            windows::Win32::Foundation::E_FAIL,
            "registrar target requires an ordinary absolute default-stream file path",
        ));
    }
    let metadata = std::fs::symlink_metadata(path)?;
    if !metadata.is_file() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT.0 != 0 {
        return Err(windows::core::Error::new(
            windows::Win32::Foundation::E_FAIL,
            "registrar target requires an absolute regular non-reparse file",
        ));
    }
    // Retain a read-only handle that denies write/delete sharing. The final
    // component is opened without following a reparse point, then checked on
    // that same handle so a replacement after the path check is not admitted.
    let file = std::fs::OpenOptions::new()
        .read(true)
        .share_mode(FILE_SHARE_READ.0)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT.0)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT.0 != 0 {
        return Err(windows::core::Error::new(
            windows::Win32::Foundation::E_FAIL,
            "registrar opened target is not a regular non-reparse file",
        ));
    }
    Ok(file)
}

fn file_identity(file: &File) -> windows::core::Result<FILE_ID_INFO> {
    let mut identity = FILE_ID_INFO::default();
    // SAFETY: The borrowed File keeps the handle live. The SDK structure and
    // exact size match FileIdInfo. Compare its volume and all 128 identifier bits.
    unsafe {
        GetFileInformationByHandleEx(
            HANDLE(file.as_raw_handle()),
            FileIdInfo,
            (&raw mut identity).cast(),
            std::mem::size_of::<FILE_ID_INFO>() as u32,
        )?;
    }
    Ok(identity)
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
    // Keep the admitted executable pinned across shortcut creation and readback.
    let executable_file = open_registration_target(executable)
        .map_err(|error| registration_error("registrar expected target open", error).to_string())?;
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
                CoCreateInstance(&ShellLink, /*punkouter*/ None, CLSCTX_INPROC_SERVER)
                    .map_err(|error| registration_error("registrar CoCreateInstance", error))?;
            link.SetPath(PCWSTR(executable_text.as_ptr()))
                .map_err(|error| registration_error("registrar SetPath", error))?;
            link.SetWorkingDirectory(PCWSTR(directory_text.as_ptr()))
                .map_err(|error| registration_error("registrar SetWorkingDirectory", error))?;
            link.SetDescription(PCWSTR(description.as_ptr()))
                .map_err(|error| registration_error("registrar SetDescription", error))?;
            link.SetIconLocation(PCWSTR(executable_text.as_ptr()), /*iicon*/ 0)
                .map_err(|error| registration_error("registrar SetIconLocation", error))?;
            let store: IPropertyStore = link
                .cast()
                .map_err(|error| registration_error("registrar IPropertyStore", error))?;
            store
                .SetValue(
                    &APP_USER_MODEL_ID_KEY,
                    &app_id_value()
                        .map_err(|error| registration_error("registrar identity value", error))?,
                )
                .map_err(|error| registration_error("registrar SetValue", error))?;
            store
                .Commit()
                .map_err(|error| registration_error("registrar Commit", error))?;
            let persist: IPersistFile = link
                .cast()
                .map_err(|error| registration_error("registrar IPersistFile", error))?;
            persist
                .Save(PCWSTR(shortcut_text.as_ptr()), /*fremember*/ true)
                .map_err(|error| registration_error("registrar Save", error))?;
            Ok(())
        })()
    };
    result.map_err(|error| format!("native notification identity registration: {error}"))?;
    verify_saved_shortcut(&executable_file, &shortcut)?;
    std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .open(&shortcut)
        .and_then(|file| file.sync_all())
        .map_err(|error| error.to_string())?;
    Ok(shortcut)
}

fn verify_saved_shortcut(executable: &File, shortcut: &Path) -> Result<(), String> {
    let shortcut_text = wide(shortcut.as_os_str())?;
    // SAFETY: The caller holds the apartment and each interface remains on this
    // thread. Reopen persisted bytes; all strings and output buffers stay live.
    let result: windows::core::Result<()> = unsafe {
        (|| {
            let observed: IShellLinkW =
                CoCreateInstance(&ShellLink, /*punkouter*/ None, CLSCTX_INPROC_SERVER)
                    .map_err(|error| registration_error("registrar CoCreateInstance", error))?;
            let persist: IPersistFile = observed
                .cast()
                .map_err(|error| registration_error("registrar reopened IPersistFile", error))?;
            persist
                .Load(PCWSTR(shortcut_text.as_ptr()), STGM_READ)
                .map_err(|error| registration_error("registrar Load", error))?;
            let store: IPropertyStore = observed
                .cast()
                .map_err(|error| registration_error("registrar reopened IPropertyStore", error))?;
            let identity = store
                .GetValue(&APP_USER_MODEL_ID_KEY)
                .map_err(|error| registration_error("registrar GetValue", error))?;
            if BSTR::try_from(&identity)
                .map_err(|error| registration_error("registrar identity conversion", error))?
                != APP_USER_MODEL_ID
            {
                return Err(windows::core::Error::new(
                    windows::Win32::Foundation::E_FAIL,
                    "registrar persisted identity mismatch",
                ));
            }
            let mut target = [0_u16; 32_768];
            observed
                .GetPath(&mut target, std::ptr::null_mut(), /*fflags*/ 0)
                .map_err(|error| registration_error("registrar GetPath", error))?;
            let length = target.iter().position(|value| *value == 0).ok_or_else(|| {
                windows::core::Error::new(
                    windows::Win32::Foundation::E_FAIL,
                    "registrar persisted target path is unterminated",
                )
            })?;
            let target = PathBuf::from(OsString::from_wide(&target[..length]));
            let target_file = open_registration_target(&target)
                .map_err(|error| registration_error("registrar observed target open", error))?;
            let expected = file_identity(executable)
                .map_err(|error| registration_error("registrar expected file identity", error))?;
            let observed = file_identity(&target_file)
                .map_err(|error| registration_error("registrar observed file identity", error))?;
            // Shell links may normalize case or expand 8.3 names. Only matching
            // retained file identities, never equivalent-looking strings, pass.
            if observed != expected {
                return Err(windows::core::Error::new(
                    windows::Win32::Foundation::E_FAIL,
                    "registrar persisted target file identity mismatch",
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
