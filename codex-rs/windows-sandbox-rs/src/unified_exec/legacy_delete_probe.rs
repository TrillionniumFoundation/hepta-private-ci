//! Read-only diagnostics for this test's stdin-blocked, actual legacy cmd child.
//! Never emit real SID bytes or change an ACL, token, process, or production policy.

use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::mem::size_of;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_NO_MORE_FILES;
use windows_sys::Win32::Foundation::ERROR_SUCCESS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT;
use windows_sys::Win32::Security::CopySid;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::GetSecurityDescriptorControl;
use windows_sys::Win32::Security::GetSidSubAuthority;
use windows_sys::Win32::Security::GetSidSubAuthorityCount;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Security::TOKEN_USER;
use windows_sys::Win32::Security::TokenGroups;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenRestrictedSids;
use windows_sys::Win32::Security::TokenUser;
use windows_sys::Win32::System::Diagnostics::ToolHelp::CreateToolhelp32Snapshot;
use windows_sys::Win32::System::Diagnostics::ToolHelp::PROCESSENTRY32W;
use windows_sys::Win32::System::Diagnostics::ToolHelp::Process32FirstW;
use windows_sys::Win32::System::Diagnostics::ToolHelp::Process32NextW;
use windows_sys::Win32::System::Diagnostics::ToolHelp::TH32CS_SNAPPROCESS;
use windows_sys::Win32::System::Threading::GetCurrentProcess;
use windows_sys::Win32::System::Threading::GetProcessId;
use windows_sys::Win32::System::Threading::OpenProcess;
use windows_sys::Win32::System::Threading::OpenProcessToken;
use windows_sys::Win32::System::Threading::PROCESS_QUERY_LIMITED_INFORMATION;
use windows_sys::Win32::System::Threading::QueryFullProcessImageNameW;

struct Handle(HANDLE);
impl Drop for Handle {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.0) };
    }
}
struct Descriptor(*mut c_void);
impl Drop for Descriptor {
    fn drop(&mut self) {
        if !self.0.is_null() {
            unsafe { LocalFree(self.0 as HLOCAL) };
        }
    }
}

#[derive(Default)]
struct Aliases(Vec<(Vec<u8>, String)>);
impl Aliases {
    unsafe fn name(&mut self, sid: *mut c_void) -> Result<String> {
        ensure!(!sid.is_null(), "missing diagnostic SID");
        let n = unsafe { GetLengthSid(sid) };
        ensure!((8..=68).contains(&n), "invalid diagnostic SID size");
        let mut b = vec![0; n as usize];
        ensure!(
            unsafe { CopySid(n, b.as_mut_ptr().cast(), sid) } != 0,
            "copy diagnostic SID failed"
        );
        if let Some((_, name)) = self.0.iter().find(|(known, _)| *known == b) {
            return Ok(name.clone());
        }
        let name = format!("sid_{}", self.0.len());
        self.0.push((b, name.clone()));
        Ok(name)
    }
}

fn token_buffer(token: HANDLE, class: i32) -> Result<Vec<usize>> {
    let mut n = 0;
    unsafe {
        GetTokenInformation(
            token,
            class,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut n,
        )
    };
    ensure!((4..=65_536).contains(&n), "token record size bound");
    let capacity = n;
    let mut words = vec![0_usize; (n as usize).div_ceil(size_of::<usize>())];
    ensure!(
        unsafe { GetTokenInformation(token, class, words.as_mut_ptr().cast(), capacity, &mut n) }
            != 0
            && n <= capacity,
        "read token record failed"
    );
    Ok(words)
}

fn token_groups(token: HANDLE, class: i32, aliases: &mut Aliases) -> Result<Vec<Value>> {
    let b = token_buffer(token, class)?;
    let p = b.as_ptr().cast::<u8>();
    let count = unsafe { std::ptr::read_unaligned(p.cast::<u32>()) } as usize;
    let offset = std::mem::offset_of!(TOKEN_GROUPS, Groups);
    ensure!(
        count <= (b.len() * size_of::<usize>() - offset) / size_of::<SID_AND_ATTRIBUTES>(),
        "group record bounds"
    );
    let entries = unsafe { p.add(offset).cast::<SID_AND_ATTRIBUTES>() };
    (0..count)
        .map(|i| {
            let e = unsafe { std::ptr::read_unaligned(entries.add(i)) };
            Ok(json!({"sid_alias": unsafe { aliases.name(e.Sid)? }, "attributes": e.Attributes}))
        })
        .collect()
}

fn token_snapshot(process: HANDLE, aliases: &mut Aliases) -> Result<Value> {
    let mut raw = 0;
    ensure!(
        unsafe { OpenProcessToken(process, TOKEN_QUERY, &mut raw) } != 0,
        "open exact process token failed"
    );
    let token = Handle(raw);
    let user = token_buffer(token.0, TokenUser)?;
    ensure!(
        user.len() * size_of::<usize>() >= size_of::<TOKEN_USER>(),
        "short token user record"
    );
    let user = unsafe { &*user.as_ptr().cast::<TOKEN_USER>() };
    let user_alias = unsafe { aliases.name(user.User.Sid)? };
    let label = token_buffer(token.0, TokenIntegrityLevel)?;
    ensure!(
        label.len() * size_of::<usize>() >= size_of::<TOKEN_MANDATORY_LABEL>(),
        "short token label record"
    );
    let label = unsafe { &*label.as_ptr().cast::<TOKEN_MANDATORY_LABEL>() };
    let count = unsafe { *GetSidSubAuthorityCount(label.Label.Sid) };
    ensure!(count > 0, "missing integrity subauthority");
    let integrity = unsafe { *GetSidSubAuthority(label.Label.Sid, u32::from(count - 1)) };
    Ok(
        json!({"user_sid_alias": user_alias, "ordinary_groups": token_groups(token.0, TokenGroups, aliases)?, "restricting_sids": token_groups(token.0, TokenRestrictedSids, aliases)?, "integrity_rid": integrity}),
    )
}

fn object_snapshot(path: &Path, aliases: &mut Aliases) -> Result<Value> {
    let mut owner = std::ptr::null_mut();
    let mut dacl = std::ptr::null_mut();
    let mut descriptor = Descriptor(std::ptr::null_mut());
    ensure!(
        unsafe {
            GetNamedSecurityInfoW(
                crate::to_wide(path).as_ptr(),
                SE_FILE_OBJECT,
                OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION,
                &mut owner,
                std::ptr::null_mut(),
                &mut dacl,
                std::ptr::null_mut(),
                &mut descriptor.0,
            )
        } == ERROR_SUCCESS,
        "read fixture DACL failed"
    );
    let mut control = 0;
    let mut revision = 0;
    ensure!(
        unsafe { GetSecurityDescriptorControl(descriptor.0, &mut control, &mut revision) } != 0,
        "read descriptor control failed"
    );
    let mut aces = Vec::new();
    if !dacl.is_null() {
        let count = unsafe { (*dacl).AceCount };
        ensure!(count <= 1024, "DACL ACE count bound");
        for i in 0..count {
            let mut ptr = std::ptr::null_mut();
            ensure!(
                unsafe { GetAce(dacl, u32::from(i), &mut ptr) } != 0,
                "read DACL ACE failed"
            );
            let header = unsafe { &*ptr.cast::<ACE_HEADER>() };
            if matches!(header.AceType, 0 | 1) {
                ensure!(
                    usize::from(header.AceSize) >= size_of::<ACCESS_ALLOWED_ACE>(),
                    "short allow/deny ACE"
                );
                let ace = unsafe { &*ptr.cast::<ACCESS_ALLOWED_ACE>() };
                let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
                aces.push(json!({"kind": if header.AceType == 0 {"allow"} else {"deny"}, "flags": header.AceFlags, "mask": ace.Mask, "sid_alias": unsafe { aliases.name(sid)? }}));
            } else {
                aces.push(json!({"kind": "unsupported_not_interpreted", "type": header.AceType, "flags": header.AceFlags, "size": header.AceSize}));
            }
        }
    }
    Ok(
        json!({"owner_sid_alias": unsafe { aliases.name(owner)? }, "descriptor_control": control, "null_dacl": dacl.is_null(), "aces": aces}),
    )
}

fn direct_cmd_child(parent: u32, expected: &Path) -> Result<Option<(u32, Handle)>> {
    let raw = unsafe {
        CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, /*th32processid*/ 0)
    };
    ensure!(raw != INVALID_HANDLE_VALUE, "process snapshot failed");
    let snapshot = Handle(raw);
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..unsafe { std::mem::zeroed() }
    };
    let mut more = unsafe { Process32FirstW(snapshot.0, &mut entry) };
    let mut candidates = Vec::new();
    let mut count = 0;
    while more != 0 {
        count += 1;
        ensure!(count <= 16_384, "process enumeration bound");
        let end = entry
            .szExeFile
            .iter()
            .position(|v| *v == 0)
            .unwrap_or(entry.szExeFile.len());
        let name = String::from_utf16_lossy(&entry.szExeFile[..end]);
        if entry.th32ParentProcessID == parent && name.eq_ignore_ascii_case("cmd.exe") {
            let raw = unsafe {
                OpenProcess(
                    PROCESS_QUERY_LIMITED_INFORMATION,
                    /*binherithandle*/ 0,
                    entry.th32ProcessID,
                )
            };
            ensure!(raw != 0, "open direct cmd child failed");
            let process = Handle(raw);
            let mut image = vec![0_u16; 32_768];
            let mut size = image.len() as u32;
            ensure!(
                unsafe {
                    QueryFullProcessImageNameW(
                        process.0,
                        /*dwflags*/ 0,
                        image.as_mut_ptr(),
                        &mut size,
                    )
                } != 0,
                "verify child executable failed"
            );
            let image = String::from_utf16(&image[..size as usize])?;
            ensure!(
                image.eq_ignore_ascii_case(&expected.to_string_lossy()),
                "unexpected cmd child executable"
            );
            candidates.push((entry.th32ProcessID, process));
        }
        more = unsafe { Process32NextW(snapshot.0, &mut entry) };
    }
    ensure!(
        unsafe { GetLastError() } == ERROR_NO_MORE_FILES,
        "incomplete process enumeration"
    );
    ensure!(candidates.len() <= 1, "ambiguous direct cmd children");
    Ok(candidates.pop())
}

// Close the snapshot-to-open PID reuse window while retaining the queried handle.
fn verify_live_parent(pid: u32, parent: u32, process: HANDLE) -> Result<()> {
    ensure!(
        unsafe { GetProcessId(process) } == pid,
        "opened child PID differs"
    );
    let raw = unsafe {
        CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, /*th32processid*/ 0)
    };
    ensure!(
        raw != INVALID_HANDLE_VALUE,
        "child identity snapshot failed"
    );
    let snapshot = Handle(raw);
    let mut entry = PROCESSENTRY32W {
        dwSize: size_of::<PROCESSENTRY32W>() as u32,
        ..unsafe { std::mem::zeroed() }
    };
    let mut more = unsafe { Process32FirstW(snapshot.0, &mut entry) };
    let mut count = 0;
    while more != 0 {
        count += 1;
        ensure!(count <= 16_384, "child identity enumeration bound");
        if entry.th32ProcessID == pid {
            ensure!(
                entry.th32ParentProcessID == parent,
                "opened child parent differs"
            );
            return Ok(());
        }
        more = unsafe { Process32NextW(snapshot.0, &mut entry) };
    }
    anyhow::bail!("opened child is no longer in the process snapshot")
}

/// The caller releases the stdin barrier even if this read-only probe fails.
pub(super) fn observe(paths: &[(&str, &Path)]) -> Result<Value> {
    let start = Instant::now();
    let budget = Duration::from_secs(2);
    let parent = std::process::id();
    let expected = Path::new("C:\\Windows\\System32\\cmd.exe");
    let (pid, child) = loop {
        if let Some(child) = direct_cmd_child(parent, expected)? {
            break child;
        }
        ensure!(start.elapsed() < budget, "child diagnostic deadline");
        std::thread::sleep(Duration::from_millis(20));
    };
    verify_live_parent(pid, parent, child.0)?;
    let mut aliases = Aliases::default();
    let base_token = token_snapshot(unsafe { GetCurrentProcess() }, &mut aliases)?;
    let child_token = token_snapshot(child.0, &mut aliases)?;
    let mut objects = Vec::new();
    for (role, path) in paths {
        ensure!(start.elapsed() < budget, "fixture diagnostic deadline");
        objects.push(json!({"role": role, "security": object_snapshot(path, &mut aliases)?}));
    }
    Ok(
        json!({"schema": "hepta.windows-legacy-delete-child.v1", "source": "actual_legacy_cmd_child_before_delete", "stdin_barrier": true, "parent_pid": parent, "child_pid": pid, "parent_and_executable_verified": true, "base_token": base_token, "child_token": child_token, "objects": objects, "sid_alias_scope": "this_test_only_no_raw_SIDs", "production_policy_modified": false, "sandbox_qualified": false}),
    )
}
