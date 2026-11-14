#![cfg(target_os = "windows")]

use anyhow::Context;
use anyhow::Result;
use std::io;
use std::io::BufRead;
use std::os::windows::ffi::OsStrExt;
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

/// Bazel's unsharded rust_test can receive a CARGO_BIN_EXE value expressed as
/// an rlocation key. On Windows with --noenable_runfiles, that key is not a
/// filesystem path: use the actual manifest entry rather than guessing a
/// sibling executable, ignoring the test, or treating absence as success.
fn locate_setup_executable() -> Result<PathBuf> {
    let declared = std::env::var_os("CARGO_BIN_EXE_codex-windows-sandbox-setup")
        .or_else(|| std::env::var_os("CARGO_BIN_EXE_codex_windows_sandbox_setup"))
        .map(PathBuf::from)
        .or_else(|| option_env!("CARGO_BIN_EXE_codex-windows-sandbox-setup").map(PathBuf::from))
        .context("locate the Windows sandbox setup executable")?;

    if declared.is_file() {
        return Ok(declared);
    }

    if let Some(manifest) = std::env::var_os("RUNFILES_MANIFEST_FILE") {
        if let Some(resolved) = find_exact_manifest_runfile(&PathBuf::from(manifest), &declared)? {
            return Ok(resolved);
        }
    }

    anyhow::bail!(
        "Windows sandbox setup helper {} is missing: CARGO_BIN_EXE path and exact Bazel runfiles manifest lookup both failed",
        declared.display()
    )
}

/// No filename suffix matching or directory scans: a similarly named binary
/// cannot stand in for the exact linked and manifest-bearing setup executable.
fn find_exact_manifest_runfile(
    manifest_path: &std::path::Path,
    declared: &std::path::Path,
) -> Result<Option<PathBuf>> {
    if declared.is_absolute() {
        return Ok(None);
    }
    let logical_path = declared.to_string_lossy().replace('\\', "/");
    if logical_path.is_empty() || logical_path.contains("../") {
        return Ok(None);
    }
    // Windows Bazel can expose a very large manifest; stream it rather than
    // materializing the entire runfiles graph just to validate one executable.
    let manifest = std::fs::File::open(manifest_path)
        .with_context(|| format!("open Bazel runfiles manifest {}", manifest_path.display()))?;
    for entry in std::io::BufReader::new(manifest).lines() {
        let entry = entry.context("read Bazel runfiles manifest entry")?;
        let Some((logical, actual)) = entry.split_once(' ') else {
            continue;
        };
        if logical == logical_path {
            let result = PathBuf::from(actual);
            if result.is_file() {
                return Ok(Some(result));
            }
            anyhow::bail!(
                "Bazel manifest mapped {} to a missing setup helper {}",
                logical,
                result.display()
            );
        }
    }
    Ok(None)
}

#[test]
fn manifest_only_runfiles_resolve_the_exact_helper_with_spaces_in_physical_path() -> Result<()> {
    let scratch = tempfile::tempdir()?;
    let directory = scratch.path().join("with spaces");
    std::fs::create_dir_all(&directory)?;
    let physical = directory.join("codex-windows-sandbox-setup.exe");
    std::fs::write(
        &physical,
        b"test fixture (never used as a production binary)",
    )?;
    let manifest = scratch.path().join("MANIFEST");
    let logical = "_main/codex-rs/windows-sandbox-rs/codex-windows-sandbox-setup.exe";
    std::fs::write(
        &manifest,
        format!(
            "_main/codex-rs/windows-sandbox-rs/other-setup.exe {}\n{logical} {}\n",
            physical.display(),
            physical.display(),
        ),
    )?;
    assert_eq!(
        find_exact_manifest_runfile(&manifest, std::path::Path::new(logical))?,
        Some(physical),
    );
    assert!(
        find_exact_manifest_runfile(
            &manifest,
            std::path::Path::new("_main/codex-rs/windows-sandbox-rs/nonexistent.exe"),
        )?
        .is_none()
    );
    Ok(())
}

/// The setup executable must expose an asInvoker manifest through the Windows resource API.
#[test]
fn setup_helper_embeds_as_invoker_manifest() -> Result<()> {
    let setup_executable = locate_setup_executable()?;
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
