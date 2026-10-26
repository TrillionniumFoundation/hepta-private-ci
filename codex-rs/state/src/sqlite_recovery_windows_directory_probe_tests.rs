//! Native diagnostic only. A passing collector never implies every mode works.

use super::super::Kind;
use super::super::identity;
use super::super::security;
use crate::runtime::test_support::unique_temp_dir;
use serde_json::Value;
use serde_json::json;
use sha2::Digest;
use sha2::Sha256;
use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::io::Write;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;
use std::time::Instant;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetKernelObjectSecurity;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::*;

fn outcome<T>(result: io::Result<T>) -> Value {
    match result {
        Ok(_) => json!({"ok": true, "rawWin32Error": null}),
        Err(error) => json!({
            "ok": false, "rawWin32Error": error.raw_os_error(),
            "kind": format!("{:?}", error.kind()), "error": error.to_string()
        }),
    }
}

fn native_result(result: i32) -> Value {
    // GetLastError is read immediately and only when the API reports failure.
    let error = (result == 0).then(|| unsafe { GetLastError() });
    json!({"rawReturn": result, "ok": result != 0, "rawWin32Error": error})
}

fn facts(file: &File) -> Value {
    let mut id: FILE_ID_INFO = unsafe { std::mem::zeroed() };
    // SAFETY: the retained File owns the live handle and the buffer is exact.
    let query = native_result(unsafe {
        GetFileInformationByHandleEx(
            file.as_raw_handle() as _,
            FileIdInfo,
            std::ptr::from_mut(&mut id).cast(),
            std::mem::size_of::<FILE_ID_INFO>() as u32,
        )
    });
    let mut length = 0;
    let info = OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION;
    // SAFETY: this first call asks only for the required descriptor length.
    let size_query = native_result(unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            info,
            std::ptr::null_mut(),
            0,
            &mut length,
        )
    });
    let mut record = json!({
        "fileIdQuery": query, "volumeSerialNumber": id.VolumeSerialNumber,
        "fileId128": id.FileId.Identifier,
        "daclSizeQuery": size_query, "descriptorLength": length
    });
    if length == 0 || length > 64 * 1024 {
        record["descriptorRead"] = json!({"ok": false, "error": "invalid descriptor bound"});
        return record;
    }
    let mut buffer = vec![0_u64; (length as usize).div_ceil(8)];
    // SAFETY: the aligned buffer contains at least length initialized bytes.
    let read = native_result(unsafe {
        GetKernelObjectSecurity(
            file.as_raw_handle() as _,
            info,
            buffer.as_mut_ptr().cast(),
            length,
            &mut length,
        )
    });
    record["descriptorRead"] = read;
    if record["descriptorRead"]["ok"] == true {
        // SAFETY: the successful API supplied length bytes in this allocation.
        let bytes =
            unsafe { std::slice::from_raw_parts(buffer.as_ptr().cast::<u8>(), length as usize) };
        record["descriptorSha256"] = json!(format!("{:x}", Sha256::digest(bytes)));
        record["descriptorBytes"] = json!(bytes);
    }
    let privacy = security::private_security(file);
    record["statePrivateSecurity"] = match privacy {
        Ok(bytes) => json!({"ok": true, "sha256": format!("{:x}", Sha256::digest(bytes))}),
        Err(error) => json!({"ok": false, "error": error.to_string()}),
    };
    record["stateFullSnapshotAccepted"] = json!(identity::snapshot(file, Kind::Directory).is_ok());
    record
}

fn same_directory(reference: &File, candidate: &File) -> bool {
    match (
        identity::file_id(reference),
        identity::file_id(candidate),
        security::private_security(reference),
        security::private_security(candidate),
    ) {
        (Ok(a), Ok(b), Ok(c), Ok(d)) => a == b && c == d,
        _ => false,
    }
}

fn shaped_write(path: &Path, shape: &str, reference: &File) -> Value {
    let started = Instant::now();
    let mut stages = Vec::new();
    let mut options = OpenOptions::new();
    options.create_new(true).write(true);
    if shape == "operator-api-sequence" {
        options
            .read(true)
            .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
    }
    let mut file = match options.open(path) {
        Ok(file) => {
            stages.push(json!({"stage": "file.create_new", "result": outcome(Ok(())), "elapsedMicros": started.elapsed().as_micros()}));
            file
        }
        Err(error) => {
            stages.push(json!({"stage": "file.create_new", "result": outcome::<()>(Err(error)), "elapsedMicros": started.elapsed().as_micros()}));
            return json!({"shape": shape, "actualOperatorOrShadowCase": false, "stages": stages});
        }
    };
    let written = file.write_all(b"owned native directory probe\n");
    let failed = written.is_err();
    stages.push(json!({"stage": "file.write_all", "result": outcome(written), "elapsedMicros": started.elapsed().as_micros()}));
    if failed {
        return json!({"shape": shape, "actualOperatorOrShadowCase": false, "stages": stages});
    }
    let synced = file.sync_all();
    let failed = synced.is_err();
    stages.push(json!({"stage": "file.sync_all", "result": outcome(synced), "elapsedMicros": started.elapsed().as_micros()}));
    if failed {
        return json!({"shape": shape, "actualOperatorOrShadowCase": false, "stages": stages});
    }
    stages.push(json!({"stage": "private-file-state-admission", "accepted":
        super::super::require_private_created_file(&file).is_ok()}));
    let parent = path.parent().expect("owned child parent");
    let opened = File::open(parent);
    match opened {
        Ok(directory) => {
            stages.push(json!({"stage": "ordinary-parent-open", "result": {"ok": true},
                "facts": facts(&directory), "sameRetainedDirectory": same_directory(reference, &directory)}));
            stages.push(
                json!({"stage": "ordinary-parent-sync", "result": outcome(directory.sync_all())}),
            );
        }
        Err(error) => stages
            .push(json!({"stage": "ordinary-parent-open", "result": outcome::<()>(Err(error))})),
    }
    json!({"shape": shape, "actualOperatorOrShadowCase": false, "stages": stages})
}

#[test]
#[ignore = "explicit native diagnostic output and separate capability assessment required"]
fn records_native_directory_flush_capability() -> anyhow::Result<()> {
    let started = Instant::now();
    let output = std::env::var_os("HEPTA_WINDOWS_DIRECTORY_PROBE_OUTPUT")
        .map(std::path::PathBuf::from)
        .expect("explicit owned diagnostic output");
    anyhow::ensure!(
        output.is_absolute() && !output.exists(),
        "fresh absolute diagnostic output"
    );
    let root = unique_temp_dir();
    std::fs::create_dir(&root)?;
    let root = scopeguard::guard(root, |path| {
        if let Err(error) = std::fs::remove_dir_all(path) {
            eprintln!("owned probe emergency cleanup failed: {error:?}");
        }
    });
    let home = root.join("native-private-directory");
    // Same atomic private-leaf creation as existing State tests. This is an
    // absent child of this test's new root, not adoption of business state.
    drop(codex_utils_path::open_private_state_directory(&home)?);
    let (ancestors, reference) = super::super::open_home(&home)?;
    super::super::require_private_directory(&reference)?;
    let before = facts(&reference);
    let original_id = identity::file_id(&reference)?;
    let original_security = security::private_security(&reference)?;
    let mut modes = Vec::new();
    for (mode, write, flags) in [
        ("ordinary-read", false, 0),
        ("backup-read", false, FILE_FLAG_BACKUP_SEMANTICS),
        ("backup-read-write", true, FILE_FLAG_BACKUP_SEMANTICS),
        (
            "backup-read-write-reparse",
            true,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT,
        ),
    ] {
        let dirty_child = home.join(format!("{mode}-owned-child.bin"));
        super::super::super::descriptor_io::write_private_new(&dirty_child, b"owned probe bytes")?;
        let mut options = OpenOptions::new();
        options.read(true).write(write).custom_flags(flags);
        let opened = options.open(&home);
        let mut row = json!({"mode": mode, "read": true, "write": write, "customFlags": flags,
            "ownedChildFileSyncBeforeDirectoryOpen": true, "elapsedBeforeMicros": started.elapsed().as_micros()});
        match opened {
            Ok(directory) => {
                row["open"] = outcome(Ok(()));
                row["before"] = facts(&directory);
                row["sameRetainedDirectoryBefore"] = json!(same_directory(&reference, &directory));
                row["rustSyncAll"] = outcome(directory.sync_all());
                // SAFETY: a real flush request on this live, owned directory.
                row["flushFileBuffers"] =
                    native_result(unsafe { FlushFileBuffers(directory.as_raw_handle() as _) });
                row["after"] = facts(&directory);
                row["sameRetainedDirectoryAfter"] = json!(same_directory(&reference, &directory));
            }
            Err(error) => row["open"] = outcome::<()>(Err(error)),
        }
        row["elapsedAfterMicros"] = json!(started.elapsed().as_micros());
        modes.push(row);
    }
    // This calls the unchanged production State primitive, not a replacement.
    let state_sync = super::super::super::descriptor_io::sync_directory(&home);
    let state_result = match state_sync {
        Ok(()) => json!({"ok": true}),
        Err(error) => json!({"ok": false, "error": error.to_string(), "rawWin32Error": null,
            "note": "State maps its I/O error to Indeterminate; raw calls above remain separate"}),
    };
    let sequences = [
        shaped_write(
            &home.join("operator-probe.json"),
            "operator-api-sequence",
            &reference,
        ),
        shaped_write(
            &home.join("shadow-probe.json"),
            "shadow-api-sequence",
            &reference,
        ),
    ];
    let after = facts(&reference);
    let unchanged = original_id == identity::file_id(&reference)?
        && original_security == security::private_security(&reference)?;
    let mut receipt = json!({
        "schema": "hepta.windows-directory-native-probe.v1",
        "diagnosticCollectionCompleted": true,
        "productQualification": false, "originalOperator26OrShadow31Executed": false,
        "physicalPowerLossQualified": false,
        "root": root.as_path(), "privateDirectory": home,
        "retainedBefore": before, "retainedAfter": after,
        "retainedFull128IdentityAndDaclUnchanged": unchanged,
        "modes": modes, "unchangedStateDirectorySync": state_result,
        "apiSequencesOnly": sequences, "elapsedMillis": started.elapsed().as_millis()
    });
    drop(reference);
    drop(ancestors);
    let cleanup = std::fs::remove_dir_all(scopeguard::ScopeGuard::into_inner(root));
    let cleanup_succeeded = cleanup.is_ok();
    receipt["ownedScratchCleanup"] = outcome(cleanup);
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&output)?;
    file.write_all(serde_json::to_string_pretty(&receipt)?.as_bytes())?;
    file.sync_all()?;
    anyhow::ensure!(
        unchanged,
        "original directory identity/DACL changed during probe"
    );
    anyhow::ensure!(
        cleanup_succeeded,
        "owned scratch cleanup failed; evidence retained"
    );
    Ok(())
}
