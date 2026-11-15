//! A CLR-independent observation of the unchanged broker boundary fixture.
use anyhow::Context;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_windows_sandbox::LocalSid;
use codex_windows_sandbox::ResolvedWindowsSandboxPermissions;
use codex_windows_sandbox::SandboxSetupRequest;
use codex_windows_sandbox::SetupRootOverrides;
use codex_windows_sandbox::ensure_allow_mask_aces;
use codex_windows_sandbox::ensure_allow_write_aces;
use codex_windows_sandbox::get_current_token_for_restriction;
use codex_windows_sandbox::run_elevated_setup;
use codex_windows_sandbox::run_windows_sandbox_capture;
use serde_json::json;
use std::collections::HashMap;
use std::ffi::c_void;
use std::mem::size_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::TOKEN_GROUPS;
use windows_sys::Win32::Security::TokenLogonSid;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;

const MASKS: [u32; 13] = [
    0x2, 0x4, 0x10, 0x100, 0x40, 0x10000, 0x40000, 0x80000, 0x3, 0x100100, 0x130089, 0x50000,
    0x1A0089,
];

struct LogonSid {
    words: Vec<usize>,
    offset: usize,
}

impl LogonSid {
    fn read() -> Result<Self> {
        let token =
            unsafe { OwnedHandle::from_raw_handle(get_current_token_for_restriction()? as _) };
        let mut required = 0;
        unsafe {
            GetTokenInformation(
                token.as_raw_handle() as HANDLE,
                TokenLogonSid,
                std::ptr::null_mut(),
                0,
                &mut required,
            )
        };
        anyhow::ensure!(
            (size_of::<TOKEN_GROUPS>()..=65536).contains(&(required as usize)),
            "unexpected logon SID buffer size"
        );
        let mut words = vec![0_usize; (required as usize).div_ceil(size_of::<usize>())];
        let capacity = words.len() * size_of::<usize>();
        anyhow::ensure!(
            unsafe {
                GetTokenInformation(
                    token.as_raw_handle() as HANDLE,
                    TokenLogonSid,
                    words.as_mut_ptr().cast(),
                    capacity as u32,
                    &mut required,
                )
            } != 0,
            "query launcher logon SID: {}",
            std::io::Error::last_os_error()
        );
        anyhow::ensure!(
            (size_of::<TOKEN_GROUPS>()..=capacity).contains(&(required as usize)),
            "invalid returned logon SID length"
        );
        let groups = unsafe { &*words.as_ptr().cast::<TOKEN_GROUPS>() };
        anyhow::ensure!(
            groups.GroupCount == 1,
            "expected exactly one launcher logon SID"
        );
        let offset = (groups.Groups[0].Sid as usize)
            .checked_sub(words.as_ptr() as usize)
            .context("logon SID precedes buffer")?;
        anyhow::ensure!(
            offset >= size_of::<TOKEN_GROUPS>()
                && offset
                    .checked_add(8)
                    .is_some_and(|end| end <= required as usize),
            "logon SID header is outside buffer"
        );
        let bytes =
            unsafe { std::slice::from_raw_parts(words.as_ptr().cast::<u8>(), required as usize) };
        let count = bytes[offset + 1] as usize;
        anyhow::ensure!(
            bytes[offset] == 1
                && count <= 15
                && offset
                    .checked_add(8 + count * 4)
                    .is_some_and(|end| end <= bytes.len()),
            "invalid launcher logon SID"
        );
        Ok(Self { words, offset })
    }

    fn as_ptr(&self) -> *mut c_void {
        unsafe {
            self.words
                .as_ptr()
                .cast::<u8>()
                .add(self.offset)
                .cast_mut()
                .cast()
        }
    }
}

fn numbers(stdout: &str, name: &str) -> Result<Vec<u32>> {
    stdout
        .lines()
        .filter_map(|line| {
            line.strip_prefix(name)
                .and_then(|tail| tail.strip_prefix("=0x"))
        })
        .map(|value| {
            u32::from_str_radix(value, 16).with_context(|| format!("invalid {name} observation"))
        })
        .collect()
}

pub(super) fn run(probe: &Path) -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let logon = LogonSid::read()?;
    // Exactly the original owner's deliberately broad ambient rights, confined
    // to this disposable fixture. No system or unrelated path ACL is touched.
    unsafe {
        ensure_allow_mask_aces(
            fixture.path(),
            &[everyone.as_ptr(), logon.as_ptr()],
            FILE_ALL_ACCESS,
        )?
    };
    let allowed = [
        fixture.path().join("workspace"),
        fixture.path().join("temp"),
    ];
    let caps = [
        LocalSid::from_string("S-1-5-21-101-202-303-404")?,
        LocalSid::from_string("S-1-5-21-111-222-333-444")?,
    ];
    for (root, cap) in allowed.iter().zip(&caps) {
        std::fs::create_dir(root)?;
        unsafe { ensure_allow_write_aces(root, &[cap.as_ptr()])? };
        std::fs::write(root.join("delete.txt"), "inside")?;
        std::fs::create_dir(root.join("delete-dir"))?;
    }
    let outside = fixture.path().join("outside");
    std::fs::create_dir(&outside)?;
    let other_cap = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    unsafe { ensure_allow_write_aces(&outside, &[other_cap.as_ptr()])? };
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let child = allowed[0].join("native-file-boundary-probe.exe");
    std::fs::copy(probe, &child)?;
    // Credentials are not children of the deliberately world-writable fixture.
    let home = tempfile::tempdir()?;
    let roots = [AbsolutePathBuf::from_absolute_path(&allowed[0])?];
    let extra = [AbsolutePathBuf::from_absolute_path(&allowed[1])?];
    let profile = PermissionProfile::workspace_write_with(
        &extra,
        NetworkSandboxPolicy::Restricted,
        true,
        true,
    );
    let mut environment = HashMap::from([
        ("SystemRoot".to_owned(), std::env::var("SystemRoot")?),
        ("TEMP".to_owned(), allowed[1].display().to_string()),
        ("TMP".to_owned(), allowed[1].display().to_string()),
        ("BOUNDARY_DIAGNOSTIC".to_owned(), "1".to_owned()),
        (
            "BOUNDARY_WORKSPACE".to_owned(),
            allowed[0].display().to_string(),
        ),
        ("BOUNDARY_TEMP".to_owned(), allowed[1].display().to_string()),
        ("BOUNDARY_OUTSIDE".to_owned(), outside.display().to_string()),
    ]);
    let permissions =
        ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
            &profile, &roots,
        )?;
    run_elevated_setup(
        SandboxSetupRequest {
            permissions: &permissions,
            command_cwd: &allowed[0],
            env_map: &environment,
            codex_home: home.path(),
            proxy_enforced: false,
        },
        SetupRootOverrides::default(),
    )?;
    // Preserve the owner test's ordering: aliases appear after grants. Their
    // spelling inside the workspace must not authorize the outside target.
    let alias = allowed[0].join("outside-alias");
    let hardlink = allowed[0].join("outside-hardlink.txt");
    std::os::windows::fs::symlink_dir(&outside, &alias)?;
    std::fs::hard_link(outside.join("keep.txt"), &hardlink)?;
    environment.insert("BOUNDARY_ALIAS".to_owned(), alias.display().to_string());
    environment.insert(
        "BOUNDARY_HARDLINK".to_owned(),
        hardlink.display().to_string(),
    );
    let output = run_windows_sandbox_capture(
        &profile,
        &roots,
        home.path(),
        vec![child.display().to_string()],
        &allowed[0],
        environment,
        Some(5_000),
        /*cancellation*/ None,
        /*use_private_desktop*/ true,
    )?;
    anyhow::ensure!(
        output.stdout.len() <= 16 * 1024 && output.stderr.len() <= 16 * 1024,
        "file diagnostic output exceeded limit"
    );
    let stdout = String::from_utf8(output.stdout)?;
    let indices = numbers(&stdout, "file_open_index")?;
    let masks = numbers(&stdout, "file_open_mask")?;
    let opens = numbers(&stdout, "file_open_error")?;
    let complete = stdout
        .lines()
        .filter(|line| *line == "file_probe_complete=1")
        .count()
        == 1
        && stdout
            .lines()
            .filter(|line| *line == "file_probe_entry=1")
            .count()
            == 1
        && indices == (0..65).collect::<Vec<_>>()
        && masks == MASKS.repeat(5)
        && opens.len() == 65
        && output.exit_code == 0
        && !output.timed_out;
    let allowed_ops = [
        "allowed_create_error",
        "allowed_delete_file_error",
        "allowed_delete_directory_error",
    ]
    .map(|key| numbers(&stdout, key))
    .into_iter()
    .collect::<Result<Vec<_>>>()?;
    let refused_ops = [
        "outside_overwrite_error",
        "outside_create_error",
        "outside_delete_file_error",
        "outside_delete_directory_error",
    ]
    .map(|key| numbers(&stdout, key))
    .into_iter()
    .collect::<Result<Vec<_>>>()?;
    let maximum = numbers(&stdout, "maximum_write_error")?;
    let read_error = numbers(&stdout, "outside_read_error")?;
    let read_exact = numbers(&stdout, "outside_read_exact")?;
    let allowed_state: Vec<_> = allowed
        .iter()
        .map(|root| {
            json!({
                "created": std::fs::read_to_string(root.join("created.txt")).ok(),
                "delete_file_exists": root.join("delete.txt").exists(),
                "delete_directory_exists": root.join("delete-dir").exists(),
            })
        })
        .collect();
    let outside_state = json!({
        "keep": std::fs::read_to_string(outside.join("keep.txt")).ok(),
        "created_exists": outside.join("created.txt").exists(),
        "keep_directory_exists": outside.join("keep-dir").is_dir(),
    });
    let policy_passed = complete && opens == vec![5; 65] && maximum == [5]
        && allowed_ops.iter().all(|values| values == &[0, 0])
        && refused_ops.iter().all(|values| values == &[5])
        && read_error == [0] && read_exact == [1]
        && allowed_state.iter().all(|state| state == &json!({"created":"allowed", "delete_file_exists":false, "delete_directory_exists":false}))
        && outside_state == json!({"keep":"outside", "created_exists":false, "keep_directory_exists":true});
    println!(
        "{}",
        json!({
            "mode":"files", "supplements_original_owner_test":true, "uses_actual_file_operations":true,
            "complete":complete, "policy_passed":policy_passed,
            "result":{"exit_code":output.exit_code, "timed_out":output.timed_out, "stdout":stdout, "stderr":String::from_utf8_lossy(&output.stderr)},
            "open_masks":masks, "open_errors":opens, "maximum_write_error":maximum,
            "allowed_operations":allowed_ops, "refused_operations":refused_ops,
            "allowed_state":allowed_state, "outside_state":outside_state,
        })
    );
    anyhow::ensure!(
        policy_passed,
        "CRT-free broker fixture did not satisfy the unchanged owner boundary expectations"
    );
    Ok(())
}
