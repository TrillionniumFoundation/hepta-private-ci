//! One diagnostic test, six new fixtures; never substitutes for the original gate.

#[path = "token_delete_integrity_observations.rs"]
mod integrity;

use super::authorization::AuthorizationSnapshot;
use super::support;
use super::support::Dacl;
use super::support::Kind;
use super::support::RestrictedToken;
use super::support::Restriction;
use anyhow::Context;
use anyhow::Result;
use anyhow::ensure;
use pretty_assertions::assert_eq;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ACCESS_DENIED;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OVERLAPPED;
use windows_sys::Win32::Storage::FileSystem::FILE_LIST_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;

#[derive(Clone, Copy, Debug)]
enum Scenario {
    Target,
    NullParent,
    Neither,
}

#[test]
fn directory_list_bit_observations() -> Result<()> {
    let token = RestrictedToken::new(Restriction::Full)?;
    let mut observed = 0;
    for scenario in [Scenario::Target, Scenario::NullParent, Scenario::Neither] {
        let mut metadata = Vec::new();
        for with_list in [false, true] {
            let fixture = tempfile::tempdir()?;
            let parent = fixture.path().join("parent");
            let target = parent.join("target");
            std::fs::create_dir(&parent)?;
            let parent_policy = match scenario {
                Scenario::NullParent => Dacl::Null,
                _ => Dacl::Identity(FILE_ALL_ACCESS & !FILE_DELETE_CHILD),
            };
            support::set_dacl(&parent, parent_policy).with_context(|| {
                format!("configure LIST parent: scenario={scenario:?} list={with_list}")
            })?;
            support::create_target(&target, Kind::Directory)?;
            let identity = match scenario {
                Scenario::Target => FILE_ALL_ACCESS,
                _ => FILE_ALL_ACCESS & !DELETE,
            };
            let base_capability = if matches!(scenario, Scenario::Target) {
                DELETE
            } else {
                0
            };
            let capability = base_capability | if with_list { FILE_LIST_DIRECTORY } else { 0 };
            let capability_sid = support::CAPABILITY;
            let target_sddl =
                format!("D:P(A;;0x{identity:08x};;;WD)(A;;0x{capability:08x};;;{capability_sid})");
            support::set_dacl_sddl(&target, &target_sddl).with_context(|| {
                format!("configure LIST target: scenario={scenario:?} list={with_list}")
            })?;
            let objects = (
                integrity::object_facts(&parent)?,
                integrity::object_facts(&target)?,
            );
            let name = format!("list-factor-{scenario:?}-{with_list}");
            let snapshot = AuthorizationSnapshot::capture(&parent, &target, &name, "before")?;
            let (facts, open_error, delete_error) = token.run(|| -> Result<_> {
                let facts = integrity::current_token_facts()?;
                snapshot.observe_current_token(&name, "before")?;
                let open_error = open_delete_only(&target)?;
                let delete_error = support::delete(&target, Kind::Directory)
                    .err()
                    .map(|error| {
                        error
                            .raw_os_error()
                            .context("missing native deletion error")
                    })
                    .transpose()?;
                Ok((facts, open_error, delete_error))
            })??;
            let exists = target.try_exists()?;
            eprintln!(
                "HEPTA_DELETE_LIST_METADATA scenario={scenario:?} list={with_list} token={facts:?} objects={objects:?}"
            );
            eprintln!(
                "HEPTA_DELETE_LIST scenario={scenario:?} list={with_list} identity=0x{identity:08x} capability=0x{capability:08x} open={open_error:?} delete={delete_error:?} exists={exists}"
            );
            assert_eq!(
                exists,
                delete_error.is_some(),
                "namespace disagrees with deletion result"
            );
            if !with_list || matches!(scenario, Scenario::Neither) {
                assert_eq!(
                    (open_error, delete_error),
                    (
                        Some(ERROR_ACCESS_DENIED as i32),
                        Some(ERROR_ACCESS_DENIED as i32)
                    ),
                    "baseline/negative control changed: {scenario:?} list={with_list}"
                );
            } else {
                ensure!(
                    [open_error, delete_error]
                        .into_iter()
                        .all(|error| error.is_none() || error == Some(ERROR_ACCESS_DENIED as i32)),
                    "unexpected native outcome"
                );
            }
            metadata.push((facts, objects));
            if matches!(scenario, Scenario::Neither) {
                // All observations and assertions completed, and token.run already
                // restored the original identity. Only this owned target needs
                // deletion rights restored so explicit cleanup can succeed.
                support::ensure_unimpersonated()?;
                support::set_dacl(&target, Dacl::Identity(FILE_ALL_ACCESS))
                    .context("restore only the measured owned Neither target for cleanup")?;
                eprintln!("HEPTA_DELETE_LIST_TEARDOWN scenario={scenario:?} list={with_list}");
            }
            fixture
                .close()
                .with_context(|| format!("cleanup factor fixture {name}"))?;
            observed += 1;
        }
        assert_eq!(
            metadata[0], metadata[1],
            "metadata differs across LIST-only pair: {scenario:?}"
        );
    }
    assert_eq!(observed, 6);
    Ok(())
}

fn open_delete_only(path: &Path) -> Result<Option<i32>> {
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    let handle = unsafe {
        CreateFileW(
            name.as_ptr(),
            DELETE,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
            std::ptr::null(),
            OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT | FILE_FLAG_OVERLAPPED,
            /*htemplatefile*/ 0,
        )
    };
    if handle == INVALID_HANDLE_VALUE {
        return Ok(Some(
            std::io::Error::last_os_error()
                .raw_os_error()
                .context("missing native open error")?,
        ));
    }
    ensure!(
        unsafe { CloseHandle(handle) } != 0,
        "close factor query handle before deletion: {}",
        std::io::Error::last_os_error()
    );
    Ok(None)
}
