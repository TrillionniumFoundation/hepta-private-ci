#![cfg(target_os = "windows")]

use anyhow::Context;
use anyhow::Result;
use std::io;
use std::io::BufRead;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::FreeLibrary;
use windows_sys::Win32::System::LibraryLoader::FindResourceW;
use windows_sys::Win32::System::LibraryLoader::LOAD_LIBRARY_AS_DATAFILE;
use windows_sys::Win32::System::LibraryLoader::LOAD_LIBRARY_AS_IMAGE_RESOURCE;
use windows_sys::Win32::System::LibraryLoader::LoadLibraryExW;
use windows_sys::Win32::System::LibraryLoader::LoadResource;
use windows_sys::Win32::System::LibraryLoader::LockResource;
use windows_sys::Win32::System::LibraryLoader::SizeofResource;
use windows_sys::Win32::UI::WindowsAndMessaging::CREATEPROCESS_MANIFEST_RESOURCE_ID;
use windows_sys::Win32::UI::WindowsAndMessaging::RT_MANIFEST;

/// Locate exactly the Bazel/Cargo test data binary, never an arbitrary
/// installed helper. Windows Bazel commonly exposes only a runfiles MANIFEST
/// entry instead of physically materializing the _main/... relative path.
fn manifest_entry<R: BufRead>(reader: R, logical_path: &str) -> io::Result<Option<PathBuf>> {
    for line in reader.lines() {
        let line = line?;
        if let Some((logical, physical)) = line.split_once(' ') {
            if logical == logical_path {
                return Ok(Some(PathBuf::from(physical)));
            }
        }
    }
    Ok(None)
}

fn resolve_setup_helper(candidate: &Path) -> Result<PathBuf> {
    if candidate.is_file() {
        return Ok(candidate.to_path_buf());
    }
    if !candidate.is_absolute() {
        for key in ["RUNFILES_DIR", "TEST_SRCDIR"] {
            if let Some(base) = std::env::var_os(key) {
                let joined = PathBuf::from(base).join(candidate);
                if joined.is_file() {
                    return Ok(joined);
                }
            }
        }
        if let Some(manifest) = std::env::var_os("RUNFILES_MANIFEST_FILE") {
            let path = PathBuf::from(manifest);
            let logical = candidate.to_string_lossy().replace('\\', "/");
            let file = std::fs::File::open(&path)
                .with_context(|| format!("open Bazel runfiles manifest {}", path.display()))?;
            if let Some(physical) = manifest_entry(io::BufReader::new(file), &logical)?
                && physical.is_file()
            {
                return Ok(physical);
            }
        }
    }
    anyhow::bail!("setup helper missing from exact Cargo/Bazel runfiles: {}", candidate.display())
}

#[test]
fn runfiles_manifest_resolves_only_the_exact_setup_binary() -> Result<()> {
    let logical = "_main/codex-rs/windows-sandbox-rs/codex-windows-sandbox-setup.exe";
    let file = format!(
        "{logical}.tampered C:\\different\\setup.exe\n{logical} C:\\runfiles\\setup.exe\n"
    );
    assert_eq!(
        manifest_entry(io::Cursor::new(file), logical)?,
        Some(PathBuf::from(r"C:\runfiles\setup.exe"))
    );
    assert_eq!(
        manifest_entry(io::Cursor::new("wrong/path C:\\bin\\setup.exe\n"), logical)?,
        None
    );
    Ok(())
}

/// The setup executable must expose an asInvoker manifest through the Windows resource API.
#[test]
fn setup_helper_embeds_as_invoker_manifest() -> Result<()> {
    let setup_executable = std::env::var_os("CARGO_BIN_EXE_codex-windows-sandbox-setup")
        .or_else(|| std::env::var_os("CARGO_BIN_EXE_codex_windows_sandbox_setup"))
        .map(PathBuf::from)
        .or_else(|| option_env!("CARGO_BIN_EXE_codex-windows-sandbox-setup").map(PathBuf::from))
        .context("locate the Windows sandbox setup executable")?;
    let setup_executable = resolve_setup_helper(&setup_executable)?;
    std::fs::metadata(&setup_executable)
        .with_context(|| format!("find setup helper {}", setup_executable.display()))?;
    let setup_path = setup_executable
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect::<Vec<_>>();
    let module = unsafe {
        LoadLibraryExW(
            setup_path.as_ptr(),
            /*hfile*/ 0,
            LOAD_LIBRARY_AS_DATAFILE | LOAD_LIBRARY_AS_IMAGE_RESOURCE,
        )
    };
    if module == 0 {
        return Err(io::Error::last_os_error())
            .with_context(|| format!("load setup helper {}", setup_executable.display()));
    }

    let resource = unsafe {
        FindResourceW(
            module,
            std::ptr::without_provenance(CREATEPROCESS_MANIFEST_RESOURCE_ID as usize),
            std::ptr::without_provenance(RT_MANIFEST as usize),
        )
    };
    if resource == 0 {
        return Err(io::Error::last_os_error()).context("find numeric RT_MANIFEST resource ID 1");
    }

    let resource_size = unsafe { SizeofResource(module, resource) };
    let loaded_resource = unsafe { LoadResource(module, resource) };
    if loaded_resource.is_null() {
        return Err(io::Error::last_os_error()).context("load setup helper manifest resource");
    }
    let resource_data = unsafe { LockResource(loaded_resource) };
    if resource_data.is_null() {
        return Err(io::Error::last_os_error()).context("read setup helper manifest resource");
    }
    let manifest_bytes =
        unsafe { std::slice::from_raw_parts(resource_data.cast::<u8>(), resource_size as usize) };
    let manifest = std::str::from_utf8(manifest_bytes).context("decode setup helper manifest")?;
    assert!(
        manifest.contains("requestedExecutionLevel level=\"asInvoker\""),
        "setup helper manifest does not request asInvoker: {manifest}",
    );
    assert!(
        manifest.contains("uiAccess=\"false\""),
        "setup helper manifest does not disable UI access: {manifest}",
    );

    if unsafe { FreeLibrary(module) } == 0 {
        return Err(io::Error::last_os_error()).context("unload setup helper resource module");
    }

    Ok(())
}
