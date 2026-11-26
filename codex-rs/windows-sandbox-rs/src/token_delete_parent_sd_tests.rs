//! Three memory-only checks with the original factory impersonation token.
//! No descriptor in this module is installed on a securable object.

use super::access_check;
use super::facts::Descriptor;
use super::facts::MAX_BYTES;
use super::facts::MAX_ENTRIES;
use super::facts::TokenFacts;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::io::Write;
use std::mem::offset_of;
use windows_sys::Win32::Foundation::ERROR_INSUFFICIENT_BUFFER;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::ACCESS_DENIED_ACE;
use windows_sys::Win32::Security::ACE_HEADER;
use windows_sys::Win32::Security::ACL;
use windows_sys::Win32::Security::ACL_REVISION;
use windows_sys::Win32::Security::ACL_REVISION_DS;
use windows_sys::Win32::Security::AddAccessDeniedAceEx;
use windows_sys::Win32::Security::AddAce;
use windows_sys::Win32::Security::InitializeAcl;
use windows_sys::Win32::Security::IsValidAcl;
use windows_sys::Win32::Security::IsValidSecurityDescriptor;
use windows_sys::Win32::Security::IsValidSid;
use windows_sys::Win32::Security::MakeAbsoluteSD;
use windows_sys::Win32::Security::MakeSelfRelativeSD;
use windows_sys::Win32::Security::SE_DACL_DEFAULTED;
use windows_sys::Win32::Security::SE_DACL_PRESENT;
use windows_sys::Win32::Security::SE_SELF_RELATIVE;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR;
use windows_sys::Win32::Security::SECURITY_DESCRIPTOR_RELATIVE;
use windows_sys::Win32::Security::SetSecurityDescriptorDacl;
use windows_sys::Win32::Security::TokenImpersonation;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::System::SystemServices::ACCESS_DENIED_ACE_TYPE;

const PREFIX: &str = "HEPTA_PARENT_DELETE_CHILD ";
const LOG_BYTES: usize = 4096;

struct Aligned {
    words: Vec<usize>,
    length: usize,
}

impl Aligned {
    fn new(length: usize) -> Result<Self> {
        ensure!(length <= MAX_BYTES, "memory_buffer_length");
        Ok(Self {
            words: vec![0; length.div_ceil(size_of::<usize>())],
            length,
        })
    }

    fn copy(bytes: &[u8]) -> Result<Self> {
        ensure!(!bytes.is_empty(), "memory_copy_empty");
        let mut value = Self::new(bytes.len())?;
        unsafe {
            std::ptr::copy_nonoverlapping(bytes.as_ptr(), value.output().cast(), bytes.len());
        }
        Ok(value)
    }

    fn input(&self) -> *mut c_void {
        // Win32 uses a mutable pointer type for these documented input parameters.
        if self.length == 0 {
            std::ptr::null_mut()
        } else {
            self.words.as_ptr().cast_mut().cast()
        }
    }

    fn output(&mut self) -> *mut c_void {
        if self.length == 0 {
            std::ptr::null_mut()
        } else {
            self.words.as_mut_ptr().cast()
        }
    }

    fn bytes(&self) -> &[u8] {
        unsafe { std::slice::from_raw_parts(self.words.as_ptr().cast(), self.length) }
    }
}

fn api(success: i32, stage: &'static str) -> Result<()> {
    ensure!(success != 0, "{stage}: Win32 {}", unsafe { GetLastError() });
    Ok(())
}

fn size_query(success: i32, stage: &'static str) -> Result<()> {
    let error = (success == 0).then(|| unsafe { GetLastError() });
    ensure!(
        success == 0 && error == Some(ERROR_INSUFFICIENT_BUFFER),
        "{stage}: success={success}, Win32 {error:?}"
    );
    Ok(())
}

fn header<T: Copy>(bytes: &[u8]) -> Result<T> {
    // Every caller selects an integer-only SDK header; no reference is formed.
    ensure!(size_of::<T>() <= bytes.len(), "memory_header_extent");
    Ok(unsafe { bytes.as_ptr().cast::<T>().read_unaligned() })
}

fn component(bytes: &[u8], offset: u32, length: usize) -> Result<&[u8]> {
    let start = offset as usize;
    ensure!(
        start >= size_of::<SECURITY_DESCRIPTOR_RELATIVE>() && start.is_multiple_of(/*rhs*/ 4),
        "memory_component_offset"
    );
    bytes
        .get(
            start
                ..start
                    .checked_add(length)
                    .ok_or_else(|| anyhow!("memory_component_size"))?,
        )
        .ok_or_else(|| anyhow!("memory_component_extent"))
}

fn sid_component(bytes: &[u8], offset: u32) -> Result<&[u8]> {
    let sid = component(bytes, offset, /*length*/ 8)?;
    component(bytes, offset, 8 + usize::from(sid[1]) * 4)
}

fn acl_component(bytes: &[u8], offset: u32) -> Result<&[u8]> {
    let acl = header::<ACL>(component(bytes, offset, size_of::<ACL>())?)?;
    ensure!(
        usize::from(acl.AclSize) >= size_of::<ACL>(),
        "memory_acl_size"
    );
    component(bytes, offset, usize::from(acl.AclSize))
}

struct Parts<'a> {
    header: SECURITY_DESCRIPTOR_RELATIVE,
    owner: &'a [u8],
    group: &'a [u8],
    sacl: Option<&'a [u8]>,
    dacl: &'a [u8],
    aces: Vec<&'a [u8]>,
    ace_end: usize,
}

impl<'a> Parts<'a> {
    fn read(bytes: &'a [u8]) -> Result<Self> {
        let sd_header = header::<SECURITY_DESCRIPTOR_RELATIVE>(bytes)?;
        ensure!(
            sd_header.Control & (SE_SELF_RELATIVE | SE_DACL_PRESENT)
                == (SE_SELF_RELATIVE | SE_DACL_PRESENT),
            "memory_sd_control"
        );
        let dacl = acl_component(bytes, sd_header.Dacl)?;
        let acl = header::<ACL>(dacl)?;
        ensure!(usize::from(acl.AceCount) <= MAX_ENTRIES, "memory_ace_count");
        let mut aces = Vec::new();
        let mut cursor = size_of::<ACL>();
        for _ in 0..acl.AceCount {
            let ace = header::<ACE_HEADER>(
                dacl.get(cursor..)
                    .ok_or_else(|| anyhow!("memory_ace_offset"))?,
            )?;
            let length = usize::from(ace.AceSize);
            ensure!(
                length >= size_of::<ACE_HEADER>() && length.is_multiple_of(/*rhs*/ 4),
                "memory_ace_size"
            );
            let end = cursor
                .checked_add(length)
                .ok_or_else(|| anyhow!("memory_ace_size"))?;
            aces.push(
                dacl.get(cursor..end)
                    .ok_or_else(|| anyhow!("memory_ace_extent"))?,
            );
            cursor = end;
        }
        Ok(Self {
            header: sd_header,
            owner: sid_component(bytes, sd_header.Owner)?,
            group: sid_component(bytes, sd_header.Group)?,
            sacl: if sd_header.Sacl == 0 {
                None
            } else {
                Some(acl_component(bytes, sd_header.Sacl)?)
            },
            dacl,
            aces,
            ace_end: cursor,
        })
    }
}

fn with_leading_deny(original: &Aligned, sid: &[u8]) -> Result<Aligned> {
    let parts = Parts::read(original.bytes())?;
    let old_acl = header::<ACL>(parts.dacl)?;
    ensure!(parts.aces.len() < MAX_ENTRIES, "memory_added_ace_limit");
    ensure!(
        sid.len() >= 8 && sid.len() == 8 + usize::from(sid[1]) * 4,
        "memory_sid_extent"
    );
    let revision = u32::from(old_acl.AclRevision);
    ensure!(
        matches!(revision, ACL_REVISION | ACL_REVISION_DS),
        "memory_acl_revision"
    );
    let mut sid_memory = Aligned::copy(sid)?;
    ensure!(
        unsafe { IsValidSid(sid_memory.input()) } != 0,
        "memory_sid_invalid"
    );
    let added_length = offset_of!(ACCESS_DENIED_ACE, SidStart) + sid.len();
    let acl_length = parts
        .dacl
        .len()
        .checked_add(added_length)
        .ok_or_else(|| anyhow!("memory_acl_size"))?;
    ensure!(acl_length <= u16::MAX as usize, "memory_acl_limit");
    let mut new_acl = Aligned::new(acl_length)?;
    api(
        unsafe { InitializeAcl(new_acl.output().cast(), acl_length as u32, revision) },
        "InitializeAcl",
    )?;
    api(
        unsafe {
            AddAccessDeniedAceEx(
                new_acl.output().cast(),
                revision,
                /*aceflags*/ 0,
                FILE_DELETE_CHILD,
                sid_memory.output(),
            )
        },
        "AddAccessDeniedAceEx",
    )?;
    if !parts.aces.is_empty() {
        // Append the complete original ACE sequence after the one new deny.
        let old_aces = &parts.dacl[size_of::<ACL>()..parts.ace_end];
        api(
            unsafe {
                AddAce(
                    new_acl.output().cast(),
                    revision,
                    u32::MAX,
                    old_aces.as_ptr().cast(),
                    old_aces.len() as u32,
                )
            },
            "AddAce",
        )?;
    }
    ensure!(
        unsafe { IsValidAcl(new_acl.input().cast()) } != 0,
        "memory_acl_invalid"
    );

    let (mut sd_size, mut dacl_size, mut sacl_size, mut owner_size, mut group_size) =
        (0, 0, 0, 0, 0);
    size_query(
        unsafe {
            MakeAbsoluteSD(
                original.input(),
                std::ptr::null_mut(),
                &mut sd_size,
                std::ptr::null_mut(),
                &mut dacl_size,
                std::ptr::null_mut(),
                &mut sacl_size,
                std::ptr::null_mut(),
                &mut owner_size,
                std::ptr::null_mut(),
                &mut group_size,
            )
        },
        "MakeAbsoluteSD.size",
    )?;
    ensure!(
        sd_size as usize == size_of::<SECURITY_DESCRIPTOR>(),
        "memory_absolute_header_size"
    );
    let capacities = [sd_size, dacl_size, sacl_size, owner_size, group_size];
    let mut storage = capacities
        .into_iter()
        .map(|size| Aligned::new(size as usize))
        .collect::<Result<Vec<_>>>()?;
    let [absolute, dacl, sacl, owner, group] = storage.as_mut_slice() else {
        return Err(anyhow!("memory_absolute_buffers"));
    };
    api(
        unsafe {
            MakeAbsoluteSD(
                original.input(),
                absolute.output(),
                &mut sd_size,
                dacl.output().cast(),
                &mut dacl_size,
                sacl.output().cast(),
                &mut sacl_size,
                owner.output(),
                &mut owner_size,
                group.output(),
                &mut group_size,
            )
        },
        "MakeAbsoluteSD.copy",
    )?;
    ensure!(
        [sd_size, dacl_size, sacl_size, owner_size, group_size]
            .iter()
            .zip(capacities)
            .all(|(size, cap)| *size <= cap),
        "memory_absolute_returned_size"
    );
    api(
        unsafe {
            SetSecurityDescriptorDacl(
                absolute.output(),
                /*bdaclpresent*/ 1,
                new_acl.input().cast(),
                i32::from(parts.header.Control & SE_DACL_DEFAULTED != 0),
            )
        },
        "SetSecurityDescriptorDacl.memory_only",
    )?;
    let mut length = 0;
    size_query(
        unsafe { MakeSelfRelativeSD(absolute.input(), std::ptr::null_mut(), &mut length) },
        "MakeSelfRelativeSD.size",
    )?;
    ensure!(
        length as usize >= size_of::<SECURITY_DESCRIPTOR_RELATIVE>(),
        "memory_relative_required_size"
    );
    let mut copy = Aligned::new(length as usize)?;
    api(
        unsafe { MakeSelfRelativeSD(absolute.input(), copy.output(), &mut length) },
        "MakeSelfRelativeSD.copy",
    )?;
    ensure!(
        length as usize >= size_of::<SECURITY_DESCRIPTOR_RELATIVE>()
            && length as usize <= copy.length,
        "memory_relative_returned_size"
    );
    copy.length = length as usize;
    ensure!(
        unsafe { IsValidSecurityDescriptor(copy.input()) } != 0,
        "memory_copy_invalid"
    );
    let copied = Parts::read(copy.bytes())?;
    ensure!(
        (
            copied.header.Revision,
            copied.header.Sbz1,
            copied.header.Control
        ) == (
            parts.header.Revision,
            parts.header.Sbz1,
            parts.header.Control
        ) && copied.owner == parts.owner
            && copied.group == parts.group
            && copied.sacl == parts.sacl,
        "memory_non_dacl_components_changed"
    );
    let copied_acl = header::<ACL>(copied.dacl)?;
    ensure!(
        (copied_acl.AclRevision, copied_acl.Sbz1, copied_acl.Sbz2)
            == (old_acl.AclRevision, old_acl.Sbz1, old_acl.Sbz2)
            && copied.aces.len() == parts.aces.len() + 1
            && copied.aces[1..] == parts.aces[..],
        "memory_original_aces_changed"
    );
    let added = copied.aces[0];
    let deny = header::<ACCESS_DENIED_ACE>(added)?;
    ensure!(
        u32::from(deny.Header.AceType) == ACCESS_DENIED_ACE_TYPE
            && deny.Header.AceFlags == 0
            && usize::from(deny.Header.AceSize) == added_length
            && deny.Mask == FILE_DELETE_CHILD
            && &added[offset_of!(ACCESS_DENIED_ACE, SidStart)..] == sid,
        "memory_leading_deny_mismatch"
    );
    Ok(copy)
}

pub(super) fn observe(parent: &Descriptor, token: HANDLE, expected_caps: &[Vec<u8>]) {
    let mut rows = Vec::new();
    let result = (|| -> Result<Value> {
        ensure!(parent.memory_unchanged(), "source_memory_changed_before");
        let before = TokenFacts::capture(token)?;
        let actual: Vec<_> = before
            .restricting
            .iter()
            .map(|(sid, _)| sid.clone())
            .collect();
        ensure!(
            before.token_type == TokenImpersonation && actual.as_slice() == expected_caps,
            "actual_factory_token_mismatch"
        );
        ensure!(
            expected_caps.len() == 2 && expected_caps[0] < expected_caps[1],
            "expected_capability_set"
        );
        let capability = &expected_caps[0];
        ensure!(
            before.user.0 != *capability && before.groups.iter().all(|(sid, _)| sid != capability),
            "capability_is_not_restricting_only"
        );
        let baseline = Aligned::copy(&parent.original)?;
        ensure!(
            unsafe { IsValidSecurityDescriptor(baseline.input()) } != 0,
            "memory_baseline_invalid"
        );
        let capability_deny = with_leading_deny(&baseline, capability)?;
        let user_deny = with_leading_deny(&baseline, &before.user.0)?;
        let copies = [baseline, capability_deny, user_deny];
        let snapshots: Vec<_> = copies.iter().map(|copy| copy.bytes().to_vec()).collect();
        for (variant, copy) in [
            "original_copy",
            "workspace_capability_deny",
            "actual_user_deny",
        ]
        .into_iter()
        .zip(&copies)
        {
            let result = access_check(copy.input(), token, FILE_DELETE_CHILD)?;
            rows.push(json!({"variant": variant, "result": result}));
        }
        let after = TokenFacts::capture(token)?;
        let token_same = before == after;
        let copies_same = copies
            .iter()
            .zip(&snapshots)
            .all(|(copy, snapshot)| copy.bytes() == snapshot.as_slice());
        let source_same = parent.memory_unchanged();
        let original_copy_exact = copies[0].bytes() == parent.original.as_slice();
        let controls_match = rows[0]["result"]["allowed"] == true
            && rows[0]["result"]["granted"] == FILE_DELETE_CHILD
            && rows[2]["result"]["allowed"] == false
            && rows[2]["result"]["granted"] == 0;
        let access_results_consistent = rows.iter().all(|row| {
            let result = &row["result"];
            result["api_success"] == true
                && ((result["allowed"] == true && result["granted"] == FILE_DELETE_CHILD)
                    || (result["allowed"] == false && result["granted"] == 0))
        });
        let complete = access_results_consistent
            && token_same
            && copies_same
            && source_same
            && original_copy_exact
            && controls_match;
        Ok(
            json!({"status": if complete { "observed" } else { "unknown" },
            "captured_token_facts_equal": token_same, "descriptor_copies_unchanged": copies_same,
            "source_memory_unchanged": source_same, "original_copy_byte_equal": original_copy_exact,
            "positive_and_identity_controls_match": controls_match,
            "access_results_consistent": access_results_consistent,
            "non_dacl_components_and_original_aces_preserved": true,
            "selected_capability_index": 0, "selected_capability_is_restricting_only": true,
            "selected_restricting_attributes": before.restricting[0].1,
            "restricting_count": before.restricting.len(), "parent_sd_bytes": parent.original.len()}),
        )
    })();
    let summary = match result {
        Ok(value) => value,
        Err(error) => {
            json!({"status": "unknown", "error": error.to_string().chars().take(/*n*/ 256).collect::<String>()})
        }
    };
    let record = json!({"kind": "parent_delete_child_memory", "phase": "before_original_outside_actions",
        "requested": FILE_DELETE_CHILD, "descriptor_source": "pre_action_memory", "rows": rows, "summary": summary});
    let message = serde_json::to_string(&record).ok().filter(|text| PREFIX.len() + text.len() < LOG_BYTES)
        .unwrap_or_else(|| "{\"kind\":\"parent_delete_child_memory\",\"summary\":{\"status\":\"unknown\",\"error\":\"serialization_or_log_limit\"}}".to_owned());
    let _ = writeln!(std::io::stderr().lock(), "{PREFIX}{message}");
}
