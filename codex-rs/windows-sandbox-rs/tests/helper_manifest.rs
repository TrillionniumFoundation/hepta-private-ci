#![cfg(target_os = "windows")]

use anyhow::Context;
use anyhow::Result;
use std::io;
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

const MAX_RUNFILES_MANIFEST_BYTES: u64 = 32 * 1024 * 1024;

/// Match a Bazel runfile name byte-for-byte. Only the *first* separator
/// separates the logical name from the physical filename, which may contain
/// spaces on hosted Windows runners.
fn find_runfile_entry<'a>(contents: &'a str, exact_key: &str) -> Option<&'a str> {
    contents.lines().find_map(|entry| {
        let (key, physical_path) = entry.split_once(' ')?;
        (key == exact_key && !physical_path.is_empty()).then_some(physical_path)
    })
}

/// Bazel on Windows commonly uses manifest-only runfiles. In that profile
/// CARGO_BIN_EXE_* is an rlocation key, not an ordinary filesystem path.
/// Look up the *exact declared* helper in the runfiles manifest; never
/// substitute a PATH search or another arbitrary executable.
fn resolve_helper_executable(candidate: PathBuf) -> Result<PathBuf> {
    if candidate.is_file() {
        return Ok(candidate);
    }
    if candidate.is_absolute() {
        anyhow::bail!(
            "configured absolute setup helper is absent: {}",
            candidate.display()
        );
    }
    let runfiles_manifest = std::env::var_os("RUNFILES_MANIFEST_FILE")
        .context("relative Bazel helper requires RUNFILES_MANIFEST_FILE")?;
    let manifest_path = Path::new(&runfiles_manifest);
    let metadata = std::fs::metadata(manifest_path)
        .with_context(|| format!("read Bazel runfiles manifest {}", manifest_path.display()))?;
    anyhow::ensure!(
        metadata.is_file() && metadata.len() <= MAX_RUNFILES_MANIFEST_BYTES,
        "runfiles manifest is missing, nonregular or exceeds its bound"
    );
    let contents = std::fs::read_to_string(manifest_path)?;
    let runfile_key = candidate.to_string_lossy().replace('\\', "/");
    let mapped = find_runfile_entry(&contents, &runfile_key)
        .with_context(|| format!("setup helper runfile not declared in manifest: {runfile_key}"))?;
    let resolved = PathBuf::from(mapped);
    anyhow::ensure!(
        resolved.is_absolute() && resolved.is_file(),
        "declared helper runfile is not an existing absolute regular file: {}",
        resolved.display()
    );
    Ok(resolved)
}

/// The setup executable must expose an asInvoker manifest through the Windows resource API.
#[test]
fn setup_helper_embeds_as_invoker_manifest() -> Result<()> {
    let setup_executable = std::env::var_os("CARGO_BIN_EXE_codex-windows-sandbox-setup")
        .or_else(|| std::env::var_os("CARGO_BIN_EXE_codex_windows_sandbox_setup"))
        .map(PathBuf::from)
        .or_else(|| option_env!("CARGO_BIN_EXE_codex-windows-sandbox-setup").map(PathBuf::from))
        .context("locate the Windows sandbox setup executable")?;
    let setup_executable = resolve_helper_executable(setup_executable)?;
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

#[test]
fn exact_windows_runfile_resolution_preserves_paths_with_spaces_and_rejects_near_matches() {
    let fixture = concat!(
        "_main/codex-rs/windows-sandbox-rs/other.exe C:\\temp\\other.exe\n",
        "_main/codex-rs/windows-sandbox-rs/codex-windows-sandbox-setup.exe ",
        "C:\\Program Files\\sandbox tools\\codex-windows-sandbox-setup.exe\n",
    );
    let key = "_main/codex-rs/windows-sandbox-rs/codex-windows-sandbox-setup.exe";
    assert_eq!(
        find_runfile_entry(fixture, key),
        Some(r"C:\Program Files\sandbox tools\codex-windows-sandbox-setup.exe")
    );
    assert_eq!(
        find_runfile_entry(fixture, "codex-windows-sandbox-setup.exe"),
        None
    );
    assert_eq!(
        find_runfile_entry(
            fixture,
            "_main/codex-rs/windows-sandbox-rs/other.exe.backup"
        ),
        None
    );
}
