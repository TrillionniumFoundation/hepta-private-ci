//! Bounded observations around the original production-token negative test.
//! Descriptor checks reuse pre-action memory, not a reopened deleted object.

use anyhow::Result;
use anyhow::ensure;
use serde_json::Value;
use serde_json::json;
use std::ffi::c_void;
use std::io::Write;
use std::mem::offset_of;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::FromRawHandle;
use std::os::windows::io::OwnedHandle;
use std::path::Path;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Security::AccessCheck;
use windows_sys::Win32::Security::GENERIC_MAPPING;
use windows_sys::Win32::Security::GetLengthSid;
use windows_sys::Win32::Security::LUID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::PRIVILEGE_SET;
use windows_sys::Win32::Security::TOKEN_QUERY;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ADD_FILE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_EXECUTE;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_DATA;
use windows_sys::Win32::Storage::FileSystem::FILE_WRITE_DATA;
use windows_sys::Win32::System::SystemServices::SE_GROUP_USE_FOR_DENY_ONLY;
use windows_sys::Win32::System::Threading::GetCurrentThread;
use windows_sys::Win32::System::Threading::OpenThreadToken;

#[path = "token_delete_product_facts_tests.rs"]
mod facts;
#[path = "token_delete_parent_sd_tests.rs"]
mod parent_sd;
use facts::Descriptor;
use facts::MAX_BYTES;
use facts::MAX_ENTRIES;
use facts::TokenFacts;

const LOG_BYTES: usize = 16 * 1024;

fn access_check(descriptor: *mut c_void, token: HANDLE, requested: u32) -> Result<Value> {
    let mapping = GENERIC_MAPPING {
        GenericRead: FILE_GENERIC_READ,
        GenericWrite: FILE_GENERIC_WRITE,
        GenericExecute: FILE_GENERIC_EXECUTE,
        GenericAll: FILE_ALL_ACCESS,
    };
    let mut privileges = [0usize; 1024];
    let mut length = size_of_val(&privileges) as u32;
    let (mut granted, mut allowed) = (0, 0);
    let success = unsafe {
        AccessCheck(
            descriptor,
            token,
            requested,
            &mapping,
            privileges.as_mut_ptr().cast(),
            &mut length,
            &mut granted,
            &mut allowed,
        )
    };
    let error = (success == 0 || allowed == 0).then(|| unsafe { GetLastError() });
    if success == 0 {
        return Ok(
            json!({"api_success": false, "allowed": null, "granted": null, "win32_error": error}),
        );
    }
    ensure!(
        length as usize <= size_of_val(&privileges)
            && length as usize >= offset_of!(PRIVILEGE_SET, Privilege),
        "AccessCheck privilege size out of bounds"
    );
    let count = unsafe { privileges.as_ptr().cast::<u32>().read() } as usize;
    ensure!(
        count <= MAX_ENTRIES
            && offset_of!(PRIVILEGE_SET, Privilege) + count * size_of::<LUID_AND_ATTRIBUTES>()
                <= length as usize,
        "AccessCheck privilege count out of bounds"
    );
    Ok(
        json!({"api_success": true, "allowed": allowed != 0, "granted": granted,
        "win32_error": error, "privilege_count": count}),
    )
}

pub(super) struct Observer {
    parent: Descriptor,
    target: Descriptor,
    before: Option<TokenFacts>,
    expected_caps: Vec<Vec<u8>>,
    world: Vec<u8>,
    remaining_log_bytes: usize,
}

impl Observer {
    pub(super) fn capture(
        parent: &Path,
        target: &Path,
        capabilities: &[&super::LocalSid],
    ) -> Option<Self> {
        let result = (|| -> Result<Self> {
            let mut expected_caps = Vec::new();
            for capability in capabilities {
                let pointer = capability.as_ptr();
                // LocalSid owns a previously validated SID for this entire call.
                let length = unsafe { GetLengthSid(pointer) } as usize;
                ensure!(
                    length > 0 && length <= MAX_BYTES,
                    "expected SID length out of bounds"
                );
                expected_caps.push(
                    unsafe { std::slice::from_raw_parts(pointer.cast::<u8>(), length) }.to_vec(),
                );
            }
            expected_caps.sort();
            Ok(Self {
                parent: Descriptor::capture(parent)?,
                target: Descriptor::capture(target)?,
                before: None,
                expected_caps,
                world: unsafe { super::world_sid()? },
                remaining_log_bytes: LOG_BYTES,
            })
        })();
        match result {
            Ok(observer) => Some(observer),
            Err(error) => {
                let message: String = error.to_string().chars().take(256).collect();
                let _ = writeln!(
                    std::io::stderr().lock(),
                    "HEPTA_PRODUCTION_DELETE_UNKNOWN capture={message}"
                );
                None
            }
        }
    }

    fn emit(&mut self, value: Value) {
        let Ok(bytes) = serde_json::to_vec(&value) else {
            return;
        };
        let size = bytes.len() + 32;
        if size > self.remaining_log_bytes {
            const TRUNCATED: &str = "HEPTA_PRODUCTION_DELETE_UNKNOWN log_budget_exhausted";
            if self.remaining_log_bytes > TRUNCATED.len() {
                let _ = writeln!(std::io::stderr().lock(), "{TRUNCATED}");
            }
            self.remaining_log_bytes = 0;
            return;
        }
        self.remaining_log_bytes -= size;
        let _ = writeln!(
            std::io::stderr().lock(),
            "HEPTA_PRODUCTION_DELETE {}",
            String::from_utf8_lossy(&bytes)
        );
    }

    pub(super) fn observe(&mut self, phase: &str) {
        let result = (|| -> Result<TokenFacts> {
            let mut handle = 0;
            ensure!(
                unsafe {
                    OpenThreadToken(
                        GetCurrentThread(),
                        TOKEN_QUERY,
                        /*openasself*/ 1,
                        &mut handle,
                    )
                } != 0,
                "OpenThreadToken: {}",
                std::io::Error::last_os_error()
            );
            let token = unsafe { OwnedHandle::from_raw_handle(handle as _) };
            let facts = TokenFacts::capture(token.as_raw_handle() as _)?;
            let actual_caps: Vec<_> = facts
                .restricting
                .iter()
                .map(|(sid, _)| sid.clone())
                .collect();
            let integrity_rid = facts
                .integrity
                .0
                .get(8..)
                .and_then(|subauthorities| subauthorities.chunks_exact(4).last())
                .and_then(|rid| <[u8; 4]>::try_from(rid).ok())
                .map(u32::from_le_bytes);
            self.emit(json!({"kind": "token", "phase": phase,
                "groups": facts.groups.len(), "deny_only_groups": facts.groups.iter().filter(|(_, attrs)| attrs & SE_GROUP_USE_FOR_DENY_ONLY as u32 != 0).count(),
                "world_group_attributes": facts.groups.iter().filter(|(sid, _)| *sid == self.world).map(|(_, attrs)| *attrs).take(8).collect::<Vec<_>>(),
                "logon_group_attributes": facts.groups.iter().filter(|(_, attrs)| attrs & super::SE_GROUP_LOGON_ID == super::SE_GROUP_LOGON_ID).map(|(_, attrs)| *attrs).take(8).collect::<Vec<_>>(),
                "user_attributes": facts.user.1, "restricting_count": facts.restricting.len(),
                "exact_expected_capabilities": actual_caps == self.expected_caps,
                "target_owner_is_user": self.target.owner == facts.user.0,
                "parent_owner_is_user": self.parent.owner == facts.user.0,
                "target_owner_is_token_default_owner": self.target.owner == facts.owner,
                "privilege_count": facts.privileges.len(), "privileges_first_eight": facts.privileges.iter().take(8).collect::<Vec<_>>(),
                "privileges_truncated": facts.privileges.len() > 8,
                "integrity_rid": integrity_rid, "integrity_attributes": facts.integrity.1,
                "mandatory_policy": facts.mandatory_policy,
                "token_type": facts.token_type, "impersonation_level": facts.impersonation_level,
                "same_semantic_token_as_before": self.before.as_ref().map(|before| before == &facts),
                "sd_memory_unchanged": self.parent.memory_unchanged() && self.target.memory_unchanged()}));
            for (object, requested) in [
                ("target", DELETE),
                ("parent", FILE_DELETE_CHILD),
                ("target", DELETE | FILE_WRITE_DATA),
                ("parent", FILE_DELETE_CHILD | FILE_ADD_FILE),
                ("target", FILE_WRITE_DATA),
                ("target", FILE_READ_DATA),
            ] {
                let descriptor = if object == "parent" {
                    &self.parent
                } else {
                    &self.target
                };
                let row = access_check(descriptor.pointer, token.as_raw_handle() as _, requested)?;
                self.emit(json!({"kind": "access", "phase": phase, "object": object, "requested": requested,
                    "descriptor_source": "pre_action_memory", "result": row}));
            }
            if phase == "before" {
                parent_sd::observe(
                    &self.parent,
                    token.as_raw_handle() as _,
                    &self.expected_caps,
                );
            }
            Ok(facts)
        })();
        match result {
            Ok(facts) if phase == "before" => self.before = Some(facts),
            Ok(_) => {}
            Err(error) => self.emit(json!({"kind": "unknown", "phase": phase, "error": error.to_string().chars().take(256).collect::<String>()})),
        }
    }

    pub(super) fn finish(&mut self, parent: &Path, target: &Path) {
        let result = (|| -> Result<Value> {
            let parent_after = Descriptor::capture(parent)?;
            let exists = target.try_exists()?;
            let target_same = if exists {
                Some(Descriptor::capture(target)?.original == self.target.original)
            } else {
                None
            };
            Ok(
                json!({"kind": "fresh_post_impersonation_readback", "parent_sd_same": parent_after.original == self.parent.original,
                "target_exists": exists, "target_sd_same_if_present": target_same,
                "missing_target_does_not_refresh_pre_action_sd": !exists}),
            )
        })();
        match result {
            Ok(value) => self.emit(value),
            Err(error) => self.emit(json!({"kind": "unknown", "phase": "readback", "error": error.to_string().chars().take(256).collect::<String>()})),
        }
    }
}
