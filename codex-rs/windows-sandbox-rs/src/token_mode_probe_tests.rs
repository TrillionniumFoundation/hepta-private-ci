//! Owned-fixture comparison of the current write-restricted token and a fully
//! restricted token. This is diagnostic output, not a replacement sandbox policy.

use super::Impersonation;
use super::OwnedToken;
use super::fixture_access_check;
use super::token_has_restricting_sid;
use super::trace_fixture_dacl;
use crate::acl::ensure_allow_mask_aces;
use crate::acl::ensure_allow_write_aces;
use crate::token::DISABLE_MAX_PRIVILEGE;
use crate::token::LUA_TOKEN;
use crate::token::LocalSid;
use crate::token::WRITE_RESTRICTED;
use crate::token::enable_single_privilege;
use crate::token::get_logon_sid_bytes;
use crate::token::set_default_dacl;
use crate::token::world_sid;
use anyhow::Result;
use anyhow::anyhow;
use serde::Serialize;
use std::path::Path;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Security::CreateRestrictedToken;
use windows_sys::Win32::Security::DuplicateToken;
use windows_sys::Win32::Security::GetTokenInformation;
use windows_sys::Win32::Security::SID_AND_ATTRIBUTES;
use windows_sys::Win32::Security::SecurityImpersonation;
use windows_sys::Win32::Security::TokenImpersonationLevel;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_ALL_ACCESS;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_READ;

fn operation<T: Serialize>(name: &str, result: std::io::Result<T>) -> serde_json::Value {
    match result {
        Ok(value) => serde_json::json!({
            "name": name,
            "success": true,
            "value": value,
            "error": null,
        }),
        Err(error) => serde_json::json!({
            "name": name,
            "success": false,
            "value": null,
            "error": {
                "kind": format!("{:?}", error.kind()),
                "raw_os_error": error.raw_os_error(),
                "message": error.to_string(),
            },
        }),
    }
}

fn observe_root(path: &Path) -> [serde_json::Value; 5] {
    [
        operation("read_existing", std::fs::read(path.join("existing.txt"))),
        operation(
            "write_existing",
            std::fs::write(path.join("existing.txt"), "overwritten"),
        ),
        operation(
            "create",
            std::fs::write(path.join("created.txt"), "created"),
        ),
        operation("remove_file", std::fs::remove_file(path.join("delete.txt"))),
        operation(
            "remove_directory",
            std::fs::remove_dir(path.join("delete-dir")),
        ),
    ]
}

pub(super) fn trace_full_restriction_comparison(
    base: &OwnedToken,
    current: &OwnedToken,
    capabilities: [&LocalSid; 2],
    outside_capability: &LocalSid,
) {
    // Construct only the diagnostic counterpart from the same original base,
    // rather than filtering the already write-restricted token a second time.
    // Production construction, policy flags, and the original assertions stay
    // unchanged. The same default DACL and traversal privilege are applied.
    let full = (|| -> Result<OwnedToken> {
        let entries = capabilities.map(|sid| SID_AND_ATTRIBUTES {
            Sid: sid.as_ptr(),
            Attributes: 0,
        });
        let mut raw = 0;
        // SAFETY: base, the two validated SIDs, and the output handle all remain
        // live for the call. A successful handle is immediately RAII-owned.
        let ok = unsafe {
            CreateRestrictedToken(
                base.0,
                DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
                /*disablesidcount*/ 0,
                std::ptr::null(),
                /*deleteprivilegecount*/ 0,
                std::ptr::null(),
                entries.len() as u32,
                entries.as_ptr(),
                &mut raw,
            )
        };
        if ok == 0 {
            return Err(anyhow!(
                "diagnostic CreateRestrictedToken failed: {}",
                unsafe { GetLastError() }
            ));
        }
        let token = OwnedToken(raw);
        // SAFETY: the base/token handles and all SID buffers stay owned until
        // the existing constructor helpers finish copying the default DACL.
        unsafe {
            let mut logon = get_logon_sid_bytes(base.0)?;
            let mut everyone = world_sid()?;
            let dacl_sids = [
                logon.as_mut_ptr().cast(),
                everyone.as_mut_ptr().cast(),
                capabilities[0].as_ptr(),
                capabilities[1].as_ptr(),
            ];
            set_default_dacl(token.0, &dacl_sids)?;
            enable_single_privilege(token.0, "SeChangeNotifyPrivilege")?;
        }
        Ok(token)
    })();
    if let Err(error) = &full {
        eprintln!("TOKEN_MODE probe full-token unavailable: {error:#}");
    }
    for (mode, flags, token) in [
        (
            "current_write_restricted",
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN | WRITE_RESTRICTED,
            Some(current),
        ),
        (
            "full_restriction_comparison",
            DISABLE_MAX_PRIVILEGE | LUA_TOKEN,
            full.as_ref().ok(),
        ),
    ] {
        let Some(token) = token else {
            continue;
        };
        let fixture = match tempfile::tempdir() {
            Ok(fixture) => fixture,
            Err(error) => {
                eprintln!("TOKEN_MODE probe fixture unavailable {mode}: {error}");
                continue;
            }
        };
        let observed = (|| -> Result<serde_json::Value> {
            let mut logon = unsafe { get_logon_sid_bytes(base.0)? };
            let mut everyone = unsafe { world_sid()? };
            // SAFETY: this is a newly owned tempdir. No outside/user directory
            // ACL is changed, and all SID allocations outlive each call.
            unsafe {
                ensure_allow_mask_aces(
                    fixture.path(),
                    &[logon.as_mut_ptr().cast(), everyone.as_mut_ptr().cast()],
                    FILE_ALL_ACCESS,
                )?;
            }
            let roots = [
                (
                    "allowed_a",
                    fixture.path().join("workspace"),
                    capabilities[0],
                ),
                ("allowed_b", fixture.path().join("temp"), capabilities[1]),
                (
                    "outside",
                    fixture.path().join("outside"),
                    outside_capability,
                ),
            ];
            for (_, path, capability) in &roots {
                std::fs::create_dir(path)?;
                // SAFETY: only owned fixture directories receive grants.
                unsafe { ensure_allow_write_aces(path, &[capability.as_ptr()])? };
                std::fs::write(path.join("existing.txt"), "original")?;
                std::fs::write(path.join("delete.txt"), "delete fixture")?;
                std::fs::create_dir(path.join("delete-dir"))?;
            }
            for (name, path, _) in &roots {
                trace_fixture_dacl(&format!("TOKEN_MODE probe {mode} {name}"), path);
                trace_fixture_dacl(
                    &format!("TOKEN_MODE probe {mode} {name} existing"),
                    &path.join("existing.txt"),
                );
            }
            let mut raw_duplicate = 0;
            // SAFETY: token remains owned for duplication and observation. The
            // duplicate is used only for AccessCheck, not for filesystem I/O.
            let duplicate =
                if unsafe { DuplicateToken(token.0, SecurityImpersonation, &mut raw_duplicate) }
                    == 0
                {
                    Err(anyhow!("diagnostic DuplicateToken failed: {}", unsafe {
                        GetLastError()
                    }))
                } else {
                    Ok(OwnedToken(raw_duplicate))
                };
            let duplicate_level =
                duplicate
                    .as_ref()
                    .map_err(|error| error.to_string())
                    .map(|duplicate| {
                        let mut level = 0;
                        let mut returned = 0;
                        // SAFETY: the owned duplicate and bounded output buffers
                        // remain live throughout this information query.
                        let ok = unsafe {
                            GetTokenInformation(
                                duplicate.0,
                                TokenImpersonationLevel,
                                (&mut level as *mut i32).cast(),
                                std::mem::size_of::<i32>() as u32,
                                &mut returned,
                            )
                        };
                        let error = if ok == 0 {
                            Some(unsafe { GetLastError() })
                        } else {
                            None
                        };
                        serde_json::json!({
                            "api_success": ok != 0,
                            "api_error": error,
                            "actual_level": (ok != 0).then_some(level),
                            "returned_bytes": returned,
                        })
                    });
            let identities = [
                ("capability_a", capabilities[0].as_ptr()),
                ("capability_b", capabilities[1].as_ptr()),
                ("outside_capability", outside_capability.as_ptr()),
                ("logon", logon.as_mut_ptr().cast()),
                ("everyone", everyone.as_mut_ptr().cast()),
            ]
            .map(|(name, sid)| {
                serde_json::json!({
                    "name": name,
                    // SAFETY: all handles and SID buffers remain live.
                    "token_restricting_sid": unsafe {
                        token_has_restricting_sid(token.0, sid)
                    }.map_err(|error| error.to_string()),
                    "duplicate_restricting_sid": duplicate.as_ref().map_err(|error| error.to_string())
                        .and_then(|duplicate| unsafe {
                            token_has_restricting_sid(duplicate.0, sid)
                        }.map_err(|error| error.to_string())),
                })
            });
            let outside = &roots[2].1;
            let access_checks = [
                (
                    "outside_parent_delete_child",
                    outside.clone(),
                    FILE_DELETE_CHILD,
                ),
                (
                    "outside_read",
                    outside.join("existing.txt"),
                    FILE_GENERIC_READ,
                ),
                ("outside_file_delete", outside.join("delete.txt"), DELETE),
                (
                    "outside_directory_delete",
                    outside.join("delete-dir"),
                    DELETE,
                ),
            ]
            .map(|(name, path, requested)| {
                serde_json::json!({
                    "name": name,
                    "result": duplicate.as_ref().map_err(|error| error.to_string())
                        .and_then(|duplicate| fixture_access_check(&path, duplicate, requested)
                            .map_err(|error| error.to_string())),
                })
            });
            let operations = {
                // SAFETY: each token stays live throughout its own observation.
                // This scope always reverts before owned-fixture cleanup.
                let _impersonation = unsafe { Impersonation::enter(token.0)? };
                roots.iter().map(|(name, path, _)| {
                    serde_json::json!({"root": name, "operations": observe_root(path)})
                }).collect::<Vec<_>>()
            };
            let after = roots
                .iter()
                .map(|(name, path, _)| {
                    serde_json::json!({
                        "root": name,
                        "observations": [
                            operation("existing_bytes", std::fs::read(path.join("existing.txt"))),
                            operation("created_exists", path.join("created.txt").try_exists()),
                            operation("delete_file_exists", path.join("delete.txt").try_exists()),
                            operation("delete_directory_exists", path.join("delete-dir").try_exists()),
                        ],
                    })
                })
                .collect::<Vec<_>>();
            Ok(serde_json::json!({
                "constructor_flags": flags,
                "restricting_identity_policy": "capabilities_only",
                "requested_access_check_impersonation_level": SecurityImpersonation,
                "duplicate_level": duplicate_level,
                "identities": identities,
                "access_checks": access_checks,
                "operations": operations,
                "unrestricted_observations_after_revert": after,
            }))
        })();
        // Cleanup is attempted and recorded even when setup or observation fails.
        // Neither an observation error nor a counterexample changes test outcome.
        let cleanup = fixture.close().map_err(|error| error.to_string());
        eprintln!(
            "TOKEN_MODE probe result {}",
            serde_json::json!({
                "mode": mode,
                "observation": observed.map_err(|error| format!("{error:#}")),
                "cleanup": cleanup,
            })
        );
    }
}
