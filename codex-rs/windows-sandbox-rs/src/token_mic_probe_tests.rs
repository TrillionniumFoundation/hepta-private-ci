//! Isolated mechanism experiment; no production token or original test changes.

use super::*;
use anyhow::Context;
use std::path::Path;
use windows_sys::Win32::Security::ACCESS_ALLOWED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::Authorization::ConvertStringSecurityDescriptorToSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::GetAce;
use windows_sys::Win32::Security::GetSecurityDescriptorDacl;
use windows_sys::Win32::Security::GetSecurityDescriptorSacl;
use windows_sys::Win32::Security::GetSidIdentifierAuthority;
use windows_sys::Win32::Security::GetSidSubAuthority;
use windows_sys::Win32::Security::GetSidSubAuthorityCount;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::LABEL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::PROTECTED_DACL_SECURITY_INFORMATION;
use windows_sys::Win32::Security::SYSTEM_MANDATORY_LABEL_ACE;
use windows_sys::Win32::Security::TOKEN_MANDATORY_LABEL;
use windows_sys::Win32::Security::TOKEN_MANDATORY_POLICY;
use windows_sys::Win32::Security::TokenIntegrityLevel;
use windows_sys::Win32::Security::TokenMandatoryPolicy;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::System::SystemServices::ACCESS_ALLOWED_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::ACCESS_DENIED_ACE_TYPE;
use windows_sys::Win32::System::SystemServices::SE_GROUP_INTEGRITY;
use windows_sys::Win32::System::SystemServices::SYSTEM_MANDATORY_LABEL_ACE_TYPE;

const LOW: u32 = 0x1000;
const MEDIUM: u32 = 0x2000;
const NO_WRITE_UP: u32 = 1;

struct Descriptor(*mut c_void);

impl Drop for Descriptor {
    fn drop(&mut self) {
        // SAFETY: every Descriptor is an owned LocalAlloc result from a Windows
        // security-descriptor API and is released exactly once.
        unsafe { LocalFree(self.0 as HLOCAL) };
    }
}

fn descriptor(sddl: &str) -> Result<Descriptor> {
    let mut pointer = std::ptr::null_mut();
    // SAFETY: the string is terminated, output is writable, and ownership is
    // transferred immediately after the API reports success.
    if unsafe {
        ConvertStringSecurityDescriptorToSecurityDescriptorW(
            to_wide(sddl).as_ptr(),
            SDDL_REVISION_1,
            &mut pointer,
            std::ptr::null_mut(),
        )
    } == 0
    {
        anyhow::bail!("MIC_SETUP descriptor os={}", unsafe { GetLastError() });
    }
    Ok(Descriptor(pointer))
}

#[derive(Clone, Copy)]
enum SecurityPart {
    Dacl,
    MandatoryLabel,
}

fn set_fixture_security(path: &Path, sddl: &str, part: SecurityPart) -> Result<()> {
    let label = matches!(part, SecurityPart::MandatoryLabel);
    let descriptor = descriptor(sddl)?;
    let mut acl = std::ptr::null_mut();
    let mut present = 0;
    let mut defaulted = 0;
    // SAFETY: the descriptor remains owned throughout extraction and setting.
    let extracted = unsafe {
        if label {
            GetSecurityDescriptorSacl(descriptor.0, &mut present, &mut acl, &mut defaulted)
        } else {
            GetSecurityDescriptorDacl(descriptor.0, &mut present, &mut acl, &mut defaulted)
        }
    };
    anyhow::ensure!(
        extracted != 0 && present != 0 && !acl.is_null(),
        "MIC_SETUP missing_acl"
    );
    let mut name = to_wide(path);
    // SAFETY: this helper is used only on newly created, owned fixture entries.
    // It is not an authorization primitive for an adversarial mutable pathname.
    let status = unsafe {
        SetNamedSecurityInfoW(
            name.as_mut_ptr(),
            SE_FILE_OBJECT,
            if label {
                LABEL_SECURITY_INFORMATION
            } else {
                DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION
            },
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            if label { std::ptr::null_mut() } else { acl },
            if label { acl } else { std::ptr::null_mut() },
        )
    };
    anyhow::ensure!(
        status == ERROR_SUCCESS,
        "MIC_SETUP set_security os={status}"
    );
    Ok(())
}

unsafe fn integrity_rid(sid: *mut c_void) -> Result<u32> {
    // SAFETY: callers pass a SID in a live, successfully returned Windows token
    // or security-descriptor allocation. No untrusted serialized SID is read.
    unsafe {
        anyhow::ensure!(IsValidSid(sid) != 0, "MIC_SETUP invalid_integrity_sid");
        anyhow::ensure!(
            *GetSidSubAuthorityCount(sid) == 1,
            "MIC_SETUP integrity_sid_count"
        );
        anyhow::ensure!(
            (*GetSidIdentifierAuthority(sid)).Value == [0, 0, 0, 0, 0, 16],
            "MIC_SETUP integrity_authority"
        );
        Ok(*GetSidSubAuthority(sid, /*nsubauthority*/ 0))
    }
}

fn token_state(token: HANDLE) -> Result<(u32, u32)> {
    let mut needed = 0;
    // SAFETY: the owned token is live and this first call only queries size.
    unsafe {
        GetTokenInformation(
            token,
            TokenIntegrityLevel,
            std::ptr::null_mut(),
            /*tokeninformationlength*/ 0,
            &mut needed,
        )
    };
    anyhow::ensure!(
        (std::mem::size_of::<TOKEN_MANDATORY_LABEL>() as u32..=65536).contains(&needed),
        "MIC_SETUP token_label_size"
    );
    let mut words = vec![0_usize; (needed as usize).div_ceil(std::mem::size_of::<usize>())];
    // SAFETY: usize storage provides alignment and at least the requested bytes.
    if unsafe {
        GetTokenInformation(
            token,
            TokenIntegrityLevel,
            words.as_mut_ptr().cast(),
            needed,
            &mut needed,
        )
    } == 0
    {
        anyhow::bail!("MIC_SETUP token_label os={}", unsafe { GetLastError() });
    }
    // SAFETY: a successful query populated an aligned TOKEN_MANDATORY_LABEL and
    // its SID; storage remains live while the SID is examined.
    let label = unsafe { std::ptr::read(words.as_ptr().cast::<TOKEN_MANDATORY_LABEL>()) };
    anyhow::ensure!(
        label.Label.Attributes & SE_GROUP_INTEGRITY as u32 != 0,
        "MIC_SETUP label_attribute"
    );
    let rid = unsafe { integrity_rid(label.Label.Sid)? };
    let mut policy = TOKEN_MANDATORY_POLICY { Policy: 0 };
    let mut length = 0;
    // SAFETY: the correctly sized output and token stay live for the call.
    if unsafe {
        GetTokenInformation(
            token,
            TokenMandatoryPolicy,
            (&mut policy as *mut TOKEN_MANDATORY_POLICY).cast(),
            std::mem::size_of_val(&policy) as u32,
            &mut length,
        )
    } == 0
    {
        anyhow::bail!("MIC_SETUP token_policy os={}", unsafe { GetLastError() });
    }
    anyhow::ensure!(
        length as usize == std::mem::size_of_val(&policy) && policy.Policy & !3 == 0,
        "MIC_SETUP policy_shape"
    );
    Ok((rid, policy.Policy))
}

fn lower_owned_token(token: HANDLE) -> Result<()> {
    let low = LocalSid::from_string("S-1-16-4096")?;
    let (_, old_policy) = token_state(token)?;
    // Keep the label and its SID in one aligned allocation with an exact length.
    let sid_size = unsafe { GetLengthSid(low.as_ptr()) } as usize;
    let header_size = std::mem::size_of::<TOKEN_MANDATORY_LABEL>();
    let length = header_size + sid_size;
    let mut words = vec![0_usize; length.div_ceil(std::mem::size_of::<usize>())];
    let start = words.as_mut_ptr().cast::<u8>();
    // SAFETY: both allocations are live, the destination has the exact SID size,
    // and the header alignment is supplied by usize storage.
    unsafe {
        let sid = start.add(header_size).cast();
        anyhow::ensure!(
            CopySid(sid_size as u32, sid, low.as_ptr()) != 0,
            "MIC_SETUP copy_label"
        );
        std::ptr::write(
            start.cast::<TOKEN_MANDATORY_LABEL>(),
            TOKEN_MANDATORY_LABEL {
                Label: SID_AND_ATTRIBUTES {
                    Sid: sid,
                    Attributes: SE_GROUP_INTEGRITY as u32,
                },
            },
        );
        if SetTokenInformation(token, TokenIntegrityLevel, start.cast(), length as u32) == 0 {
            anyhow::bail!("MIC_SETUP lower_token os={}", GetLastError());
        }
        let mut policy = TOKEN_MANDATORY_POLICY {
            Policy: old_policy | NO_WRITE_UP,
        };
        if SetTokenInformation(
            token,
            TokenMandatoryPolicy,
            (&mut policy as *mut TOKEN_MANDATORY_POLICY).cast(),
            std::mem::size_of_val(&policy) as u32,
        ) == 0
        {
            anyhow::bail!("MIC_SETUP enforce_policy os={}", GetLastError());
        }
    }
    let state = token_state(token)?;
    anyhow::ensure!(
        state == (LOW, old_policy | NO_WRITE_UP),
        "MIC_SETUP token_readback"
    );
    Ok(())
}

fn audit_label(case: u8, object: usize, path: &Path, expected: u32) -> Result<()> {
    let mut descriptor = std::ptr::null_mut();
    let mut sacl = std::ptr::null_mut();
    // SAFETY: path belongs to the owned fixture. The returned descriptor owns
    // every ACE inspected below and is retained until inspection completes.
    let status = unsafe {
        GetNamedSecurityInfoW(
            to_wide(path).as_ptr(),
            SE_FILE_OBJECT,
            LABEL_SECURITY_INFORMATION,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut sacl,
            &mut descriptor,
        )
    };
    anyhow::ensure!(status == ERROR_SUCCESS, "MIC_SETUP read_label os={status}");
    let _owner = Descriptor(descriptor);
    anyhow::ensure!(!sacl.is_null(), "MIC_SETUP missing_sacl");
    let mut count = 0;
    // SAFETY: successful Windows security-descriptor parsing supplied this ACL.
    for index in 0..unsafe { (*sacl).AceCount } {
        let mut pointer = std::ptr::null_mut();
        anyhow::ensure!(
            unsafe { GetAce(sacl, index as u32, &mut pointer) } != 0,
            "MIC_SETUP label_ace"
        );
        let header = unsafe { &*pointer.cast::<ACE_HEADER>() };
        if u32::from(header.AceType) != SYSTEM_MANDATORY_LABEL_ACE_TYPE {
            continue;
        }
        let ace = unsafe { &*pointer.cast::<SYSTEM_MANDATORY_LABEL_ACE>() };
        let rid = unsafe { integrity_rid(std::ptr::addr_of!(ace.SidStart).cast_mut().cast())? };
        anyhow::ensure!(
            rid == expected && ace.Mask == NO_WRITE_UP && header.AceFlags & 0x08 == 0,
            "MIC_SETUP object_label_readback"
        );
        println!(
            "MIC_LABEL case={case} object={object} rid={rid} policy={}",
            ace.Mask
        );
        count += 1;
    }
    anyhow::ensure!(count == 1, "MIC_SETUP label_count");
    Ok(())
}

fn audit_dacl(case: u8, object: usize, path: &Path, known: &[&LocalSid]) -> Result<(u32, u32)> {
    // SAFETY: this reads the owned fixture's DACL and retains its allocation.
    let (dacl, descriptor) = unsafe { fetch_dacl_handle(path)? };
    let _owner = Descriptor(descriptor);
    anyhow::ensure!(!dacl.is_null(), "MIC_SETUP missing_dacl");
    let count = unsafe { (*dacl).AceCount };
    anyhow::ensure!((1..=32).contains(&count), "MIC_SETUP dacl_count");
    let mut everyone_allow = 0;
    let mut everyone_deny = 0;
    for index in 0..count {
        let mut pointer = std::ptr::null_mut();
        anyhow::ensure!(
            unsafe { GetAce(dacl, index as u32, &mut pointer) } != 0,
            "MIC_SETUP dacl_ace"
        );
        let header = unsafe { &*pointer.cast::<ACE_HEADER>() };
        anyhow::ensure!(
            matches!(
                u32::from(header.AceType),
                ACCESS_ALLOWED_ACE_TYPE | ACCESS_DENIED_ACE_TYPE
            ),
            "MIC_SETUP dacl_type"
        );
        // ALLOWED and DENIED ACEs have the same Mask and SidStart layout.
        let ace = unsafe { &*pointer.cast::<ACCESS_ALLOWED_ACE>() };
        let sid = std::ptr::addr_of!(ace.SidStart).cast_mut().cast();
        let identity = known
            .iter()
            .position(|known| unsafe { EqualSid(sid, known.as_ptr()) } != 0)
            .context("MIC_SETUP unknown_dacl_sid")?;
        if identity == 0 && header.AceFlags & 0x08 == 0 {
            if u32::from(header.AceType) == ACCESS_ALLOWED_ACE_TYPE {
                everyone_allow |= ace.Mask;
            } else {
                everyone_deny |= ace.Mask;
            }
        }
        println!(
            "MIC_DACL case={case} object={object} ace={index} type={} sid={identity} mask={} flags={}",
            header.AceType, ace.Mask, header.AceFlags
        );
    }
    Ok((everyone_allow, everyone_deny))
}

#[derive(Clone, Copy, Debug)]
struct Operation {
    success: bool,
    denied: bool,
    os: Option<i32>,
}

fn operation(result: std::io::Result<()>) -> Operation {
    match result {
        Ok(()) => Operation {
            success: true,
            denied: false,
            os: None,
        },
        Err(error) => Operation {
            success: false,
            denied: error.kind() == std::io::ErrorKind::PermissionDenied,
            os: error.raw_os_error(),
        },
    }
}

#[derive(Debug)]
struct Observation {
    outside_read: bool,
    outside: [Operation; 4],
    inside: [[Operation; 3]; 2],
    protected_git: Operation,
    outside_postconditions: bool,
    inside_postconditions: bool,
    protected_git_retained: bool,
}

impl Observation {
    fn original_oracle(&self) -> bool {
        self.outside_read
            && self.outside.iter().all(|op| op.denied)
            && self.inside.iter().flatten().all(|op| op.success)
            && self.protected_git.denied
            && self.outside_postconditions
            && self.inside_postconditions
            && self.protected_git_retained
    }
}

fn observe(case: u8, root: &Path) -> Result<Observation> {
    let everyone = LocalSid::from_string("S-1-1-0")?;
    let cap_a = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let cap_b = LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let other_cap = LocalSid::from_string("S-1-5-21-121-232-343-454")?;
    set_fixture_security(root, "D:P(A;OICI;FA;;;WD)", SecurityPart::Dacl)?;
    let allowed = [root.join("workspace"), root.join("temp")];
    let outside = root.join("outside");
    for (path, cap) in allowed
        .iter()
        .zip([&cap_a, &cap_b])
        .chain(std::iter::once((&outside, &other_cap)))
    {
        std::fs::create_dir(path)?;
        // SAFETY: directory and SID belong solely to this fresh fixture.
        unsafe { ensure_allow_write_aces(path, &[cap.as_ptr()])? };
    }
    let git = allowed[0].join(".git");
    std::fs::create_dir(&git)?;
    unsafe { add_deny_write_ace(&git, cap_a.as_ptr())? };
    if case == 4 {
        // No direct object DELETE grant can match Everyone here. The parent
        // deliberately retains its broad FILE_DELETE_CHILD grant.
        set_fixture_security(&git, "D:P(D;;SD;;;WD)(A;;FA;;;WD)", SecurityPart::Dacl)?;
        unsafe { add_deny_write_ace(&git, cap_a.as_ptr())? };
    }
    for path in &allowed {
        std::fs::write(path.join("delete.txt"), "inside")?;
        std::fs::create_dir(path.join("delete-dir"))?;
    }
    std::fs::write(outside.join("keep.txt"), "outside")?;
    std::fs::create_dir(outside.join("keep-dir"))?;
    let mut objects = vec![(root.to_owned(), MEDIUM), (git.clone(), MEDIUM)];
    for path in &allowed {
        let level = if case >= 2 { LOW } else { MEDIUM };
        objects.extend([
            (path.clone(), level),
            (path.join("delete.txt"), level),
            (path.join("delete-dir"), level),
        ]);
    }
    let outside_level = if case == 3 { LOW } else { MEDIUM };
    objects.extend([
        (outside.clone(), outside_level),
        (outside.join("keep.txt"), outside_level),
        (outside.join("keep-dir"), outside_level),
    ]);
    // Explicitly set every measured object. No inherited default label is assumed.
    for (path, level) in &objects {
        set_fixture_security(
            path,
            if *level == LOW {
                "S:(ML;;NW;;;LW)"
            } else {
                "S:(ML;;NW;;;ME)"
            },
            SecurityPart::MandatoryLabel,
        )?;
    }
    for (index, (path, level)) in objects.iter().enumerate() {
        audit_label(case, index, path, *level)?;
        let (everyone_allow, everyone_deny) =
            audit_dacl(case, index, path, &[&everyone, &cap_a, &cap_b, &other_cap])?;
        if path == &allowed[0] {
            anyhow::ensure!(
                everyone_allow & FILE_DELETE_CHILD != 0,
                "MIC_SETUP parent_delete_child_missing"
            );
        }
        if case == 4 && path == &git {
            anyhow::ensure!(
                everyone_deny & DELETE != 0,
                "MIC_SETUP object_delete_deny_missing"
            );
        }
    }
    let base = OwnedToken(unsafe { get_current_token_for_restriction()? });
    let base_state = token_state(base.0)?;
    anyhow::ensure!(base_state.0 >= MEDIUM, "MIC_SETUP base_below_medium");
    let token = OwnedToken(unsafe {
        create_workspace_write_token_with_caps_from(base.0, &[cap_a.as_ptr(), cap_b.as_ptr()])?
    });
    let before = token_state(token.0)?;
    if case != 0 {
        lower_owned_token(token.0)?;
    }
    let after = token_state(token.0)?;
    println!(
        "MIC_TOKEN case={case} base_rid={} base_policy={} before_rid={} before_policy={} after_rid={} after_policy={}",
        base_state.0, base_state.1, before.0, before.1, after.0, after.1
    );
    let (inside, outside_read, refused, protected_git) = {
        let _impersonation = unsafe { Impersonation::enter(token.0)? };
        let inside = allowed.each_ref().map(|path| {
            [
                operation(std::fs::write(path.join("created.txt"), "allowed")),
                operation(std::fs::remove_file(path.join("delete.txt"))),
                operation(std::fs::remove_dir(path.join("delete-dir"))),
            ]
        });
        let outside_read =
            std::fs::read_to_string(outside.join("keep.txt")).is_ok_and(|value| value == "outside");
        let refused = [
            operation(std::fs::write(outside.join("keep.txt"), "overwritten")),
            operation(std::fs::write(outside.join("created.txt"), "outside")),
            operation(std::fs::remove_file(outside.join("keep.txt"))),
            operation(std::fs::remove_dir(outside.join("keep-dir"))),
        ];
        let protected_git = operation(std::fs::remove_dir(&git));
        (inside, outside_read, refused, protected_git)
    };
    let result = Observation {
        outside_read,
        outside: refused,
        inside,
        protected_git,
        outside_postconditions: std::fs::read_to_string(outside.join("keep.txt"))
            .is_ok_and(|value| value == "outside")
            && !outside.join("created.txt").exists()
            && outside.join("keep-dir").is_dir(),
        inside_postconditions: allowed.iter().all(|path| {
            std::fs::read_to_string(path.join("created.txt")).is_ok_and(|value| value == "allowed")
                && !path.join("delete.txt").exists()
                && !path.join("delete-dir").exists()
        }),
        protected_git_retained: git.is_dir(),
    };
    println!(
        "MIC_RESULT case={case} outside_read={} outside={:?} inside={:?} git={:?} outside_post={} inside_post={} git_retained={} original_oracle={}",
        result.outside_read,
        result.outside.map(|op| (op.success, op.denied, op.os)),
        result
            .inside
            .map(|row| row.map(|op| (op.success, op.denied, op.os))),
        (
            result.protected_git.success,
            result.protected_git.denied,
            result.protected_git.os
        ),
        result.outside_postconditions,
        result.inside_postconditions,
        result.protected_git_retained,
        result.original_oracle()
    );
    Ok(result)
}

#[test]
fn mic_labels_preserve_original_outside_and_protected_child_oracles() -> Result<()> {
    let mut observations = Vec::new();
    for case in 0..=4 {
        let fixture = tempfile::tempdir()?;
        let result = observe(case, fixture.path());
        // All impersonation guards and token handles have left observe before
        // cleanup. The original process token is never changed.
        let cleanup = fixture.close();
        println!(
            "MIC_CLEANUP case={case} success={} os={:?}",
            cleanup.is_ok(),
            cleanup
                .as_ref()
                .err()
                .and_then(std::io::Error::raw_os_error)
        );
        cleanup?;
        observations.push(result?);
    }
    // Record every mechanism scenario before checking its conclusion. Baseline
    // and low-token-only are controls, not qualified sandbox configurations.
    anyhow::ensure!(
        observations[0].outside_read
            && observations[0].inside.iter().flatten().all(|op| op.success),
        "MIC_CONTROL baseline_operations"
    );
    anyhow::ensure!(
        observations[1].outside_read && observations[1].inside.iter().all(|row| row[0].denied),
        "MIC_CONTROL low_without_prepared_roots"
    );
    for (case, observation) in observations.iter().enumerate().skip(2) {
        anyhow::ensure!(
            observation.original_oracle(),
            "MIC_HYPOTHESIS original_oracle_failed case={case}"
        );
    }
    Ok(())
}
